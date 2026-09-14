"""Real reviewer forms, safe rendering and exact-intent recovery without databases."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_review_management_queries as queries
from maru.applications import programme_review_management_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_commands import (
    ProgrammeReviewResult,
    apply_programme_review_command,
)
from maru.applications.programme_review_rules import ProgrammeReviewConflictError
from tests.unit.test_application_programme_review_setup_queries import (
    request as scope_request,
)
from tests.unit.test_application_programme_review_setup_views import hidden, shell, soup

pytestmark = pytest.mark.usefixtures(shell.__name__)


def context():
    return queries.ReviewManagerContext(
        queries.ReviewManagerCase(
            UUID(int=20),
            UUID(int=21),
            "Synthetic call <script>attack</script>",
            UUID(int=22),
            3,
            datetime(2026, 9, 1, tzinfo=UTC),
            2,
            5,
            1,
            "quality",
            "open",
            current_revision=True,
        ),
        tuple(
            queries.ReviewManagerAssignment(
                UUID(int=30 + index),
                UUID(int=40 + index),
                f"Synthetic reviewer {index}",
                0 if index else 1,
                "eligibility" if index else "quality",
                state,
            )
            for index, state in enumerate(("pending", "active", "removed", "recused"))
        ),
        writable=True,
    )


def selection():
    return views.selections.ProgrammeReviewerSelection(
        UUID(int=50),
        "Selected reviewer <script>attack</script>",
        person_current=True,
        expected_version=5,
        retry_key=UUID(int=60),
        token="signed-original-person",
    )


@pytest.fixture
def page(monkeypatch):
    source = Mock(return_value=context())
    cases = Mock(
        return_value=queries.ReviewManagerPage((context().case,), UUID(int=20))
    )
    authorize = Mock()
    command = create_autospec(apply_programme_review_command)
    command.return_value = ProgrammeReviewResult(
        UUID(int=70), UUID(int=30), UUID(int=20), 6, replayed=False
    )
    preview = Mock(return_value=selection())
    retained = Mock(return_value=selection())
    monkeypatch.setattr(queries, "get_programme_review_management", source)
    monkeypatch.setattr(queries, "list_programme_review_management_cases", cases)
    monkeypatch.setattr(views, "authorize_programme_review_scope", authorize)
    monkeypatch.setattr(views, "apply_programme_review_command", command)
    monkeypatch.setattr(
        views.selections, "prepare_programme_reviewer_selection", preview
    )
    monkeypatch.setattr(views.selections, "read_programme_reviewer_selection", retained)
    return SimpleNamespace(
        source=source,
        cases=cases,
        authorize=authorize,
        command=command,
        preview=preview,
        retained=retained,
    )


def request(
    method="get",
    values=None,
    *,
    task="overview",
    case=True,
    assignment=None,
    csrf=True,
    actor=None,
):
    req = getattr(RequestFactory(), method)("/", data=values or {})
    req.user = SimpleNamespace(
        pk=UUID(int=1) if actor is None else actor, is_authenticated=True
    )
    req._dont_enforce_csrf_checks = csrf
    return views.programme_review_management(
        req,
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        UUID(int=20) if case else None,
        task,
        assignment
        if assignment is not None
        else UUID(int=30)
        if task == "remove"
        else None,
    )


def proof(action="assign"):
    values = {"action": action, "expected_version": "5", "retry_key": str(UUID(int=60))}
    if action == "preview":
        return values | {"email": "reviewer@maru.invalid"}
    values |= {"reason": "Deliberate exact reviewer change.", "confirm": "on"}
    return values | ({"selection": selection().token} if action == "assign" else {})


def test_queue_and_roster_have_scoped_labels_complete_retained_states_and_no_content(
    page,
):
    response = request(case=False, values={"after": str(UUID(int=19))})
    html = soup(response)
    assert response.status_code == 200
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert not html.find("script", string="attack")
    assert html.find("a", string="Next page of review cases")["href"].endswith(
        f"?after={UUID(int=20)}"
    )
    assert page.cases.call_args.kwargs["after_id"] == UUID(int=19)
    assert page.cases.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_context"}
    )
    html = soup(request())
    for state in ("pending", "active", "removed", "recused"):
        assert state in html.get_text()
    assert (
        len(
            html.find_all(
                "a", string=lambda text: text and text.startswith("Review removal")
            )
        )
        == 2
    )
    page.command.assert_not_called()


def test_preview_only_then_explicit_original_person_confirmation(page):
    response = request("post", proof("preview"), task="assign")
    assert response.status_code == 200
    html = soup(response)
    assert "Selected reviewer" in html.get_text()
    assert not html.find("script", string="attack")
    assert not html.find("input", {"name": "email"})
    assert not html.find("input", {"name": "confirm"}).has_attr("checked")
    assert hidden(response)["selection"] == selection().token
    assert hidden(response)["expected_version"] == "5"
    assert hidden(response)["retry_key"] == str(UUID(int=60))
    assert html.find("form", {"data-call-command": True})["data-call-pending"] == "true"
    page.command.assert_not_called()
    page.preview.reset_mock()
    response = request("post", proof(), task="assign")
    assert response.status_code == 200
    assert "Reviewer change confirmed" in soup(response).get_text()
    assert not soup(response).find("form", {"data-call-command": True})
    page.preview.assert_not_called()
    kwargs = page.command.call_args.kwargs
    assert kwargs["command"].action == views.ProgrammeReviewAction.REVIEWER_ASSIGNED
    assert kwargs["command"].reference_id == UUID(int=50)
    assert kwargs["expected_version"] == 5
    assert kwargs["retry_key"] == UUID(int=60)
    assert kwargs["reason"] == proof()["reason"]
    assert kwargs["department_id"] == UUID(int=4)
    assert kwargs["source_channel"] == "programme-review-management"


@pytest.mark.parametrize(
    "change",
    [
        {"writable": False},
        {"case": replace(context().case, state="decided", stage=2, version=20)},
        {"case": replace(context().case, current_revision=False)},
    ],
)
def test_original_assignment_reaches_replay_after_lifecycle_or_person_changes(
    page, change
):
    page.source.return_value = replace(context(), **change)
    page.retained.return_value = replace(
        selection(), display_label="Unavailable person", person_current=False
    )
    page.command.return_value = replace(page.command.return_value, replayed=True)
    response = request("post", proof(), task="assign")
    assert response.status_code == 200
    assert "original receipt was recovered" in soup(response).get_text()
    assert page.command.call_args.kwargs["command"].reference_id == UUID(int=50)
    page.preview.assert_not_called()


def test_late_removal_preserves_prior_stage_and_renders_refreshed_relationship(page):
    old = replace(context(), case=replace(context().case, state="accepted"))
    page.source.return_value = old
    assert soup(request(task="remove", assignment=UUID(int=31))).find(
        "form", {"data-call-command": True}
    )
    new = replace(
        old,
        assignments=(
            replace(old.assignments[0], state="removed", display_label="Fresh label"),
            *old.assignments[1:],
        ),
    )
    page.source.side_effect = [old, new, new, new]
    response = request("post", proof("remove"), task="remove")
    assert response.status_code == 200
    assert "Fresh label" in soup(response).get_text()
    assert "Synthetic reviewer 0" not in soup(response).get_text()
    assert (
        page.command.call_args.kwargs["command"].action
        == views.ProgrammeReviewAction.REVIEWER_REMOVED
    )
    assert page.command.call_args.kwargs["command"].reference_id == UUID(int=30)
    page.retained.assert_not_called()


@pytest.mark.parametrize("action", ["assign", "remove"])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProgrammeReviewConflictError, 409),
        (DatabaseError, 503),
        (ValidationError("Invalid current change"), 400),
    ],
)
def test_failed_commands_retain_original_proof_reason_confirmation_and_focus(
    page, action, error, status
):
    page.command.side_effect = error
    response = request("post", proof(action), task=action)
    assert response.status_code == status
    html = soup(response)
    assert hidden(response)["retry_key"] == proof(action)["retry_key"]
    assert hidden(response)["expected_version"] == "5"
    if action == "assign":
        assert hidden(response)["selection"] == selection().token
    assert (
        html.find("textarea", {"name": "reason"}).get_text().lstrip("\n")
        == proof(action)["reason"]
    )
    assert html.find("input", {"name": "confirm"}).has_attr("checked")
    assert html.find(attrs={"role": "alert"}).has_attr("autofocus")
    assert html.find("form", {"data-call-command": True})["data-call-pending"] == "true"


@pytest.mark.parametrize(
    "change",
    [
        {"confirm": ""},
        {"reason": ""},
        {"retry_key": "bad"},
        {"expected_version": "05"},
        {"expected_version": "0"},
    ],
)
def test_real_forms_require_confirmation_reason_and_strict_original_intent(
    page, change
):
    assert request("post", proof() | change, task="assign").status_code == 400
    page.command.assert_not_called()


def test_unusable_preview_is_single_nondisclosing_validation_result(page):
    page.preview.return_value = None
    response = request("post", proof("preview"), task="assign")
    assert response.status_code == 400
    assert "This address cannot be selected" in soup(response).get_text()
    assert (
        soup(response).find("input", {"name": "email"})["value"]
        == "reviewer@maru.invalid"
    )
    assert not soup(response).find("input", {"name": "selection"})
    page.command.assert_not_called()


def test_readonly_empty_and_retained_unavailable_states_offer_no_fresh_form(page):
    page.cases.return_value = queries.ReviewManagerPage((), None)
    assert "No review cases are available" in soup(request(case=False)).get_text()
    page.source.return_value = replace(context(), writable=False, assignments=())
    html = soup(request(task="assign"))
    assert "Planning is closed" in html.get_text()
    assert not html.find("form", {"data-call-command": True})
    assert request(task="remove").status_code == 404


def test_setup_navigation_is_independent_and_revocation_discards_page(page):
    def authorize(**kwargs):
        if kwargs["requested_fields"] == frozenset({"review_setup"}):
            raise Denied

    page.authorize.side_effect = authorize
    html = soup(request())
    assert not html.find("a", string="Review policy setup")
    assert html.find("a", string="Select a named reviewer")
    page.authorize.side_effect = [None, None, None, Denied]
    response = request()
    assert response.status_code == 404
    assert b"Synthetic" not in response.content


def test_navigation_helper_uses_only_manager_context_ceiling_and_propagates_outage(
    page,
):
    assert views.can_manage_programme_review_cases(scope_request())
    assert page.authorize.call_args.kwargs["requested_fields"] == frozenset(
        {"review_context"}
    )
    assert page.authorize.call_args.kwargs["capability_code"] == views.MANAGE_REVIEW
    page.authorize.side_effect = Denied
    assert not views.can_manage_programme_review_cases(scope_request())
    page.authorize.side_effect = DatabaseError
    with pytest.raises(DatabaseError):
        views.can_manage_programme_review_cases(scope_request())


@pytest.mark.parametrize("target", ["source", "cases", "retained"])
def test_scope_object_audit_and_render_races_never_disclose_cached_names(page, target):
    query = getattr(page, target)
    original = query.return_value
    query.side_effect = [original, original, Denied]
    response = (
        request("post", proof(), task="assign")
        if target == "retained"
        else request(case=target != "cases")
    )
    assert response.status_code == 404
    assert b"Synthetic" not in response.content
    assert b"Selected reviewer" not in response.content


def test_early_denial_and_persistent_dependency_failure_are_generic(page):
    page.authorize.side_effect = Denied
    assert request().status_code == 404
    page.source.assert_not_called()
    page.authorize.side_effect = None
    page.source.side_effect = DatabaseError
    response = request()
    assert response.status_code == 503
    assert b"Synthetic" not in response.content
    assert request(actor=1).status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        {"account_id": str(UUID(int=99))},
        {"confirm": ["on", "on"]},
        {"reason": "x" * 12001},
        {"action": "remove"},
        {"email": "different@maru.invalid"},
    ],
)
def test_closed_post_rejects_overrides_duplicated_controls_and_action_substitution(
    page, change
):
    assert request("post", proof() | change, task="assign").status_code == 400
    page.command.assert_not_called()
    page.source.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"after": "bad"},
        {"after": str(UUID(int=0))},
        {"after": [str(UUID(int=1))] * 2},
        {"department": "other"},
    ],
)
def test_cursor_is_closed_and_canonical_before_case_loading(page, values):
    assert request(values=values, case=False).status_code == 400
    page.cases.assert_not_called()


def test_csrf_files_methods_and_inconsistent_route_shapes_are_rejected(page):
    assert request("post", proof(), task="assign", csrf=False).status_code == 403
    assert request("put", proof()).status_code == 405
    assert request("post", proof(), task="overview").status_code == 400
    assert (
        request(
            "post",
            proof() | {"upload": SimpleUploadedFile("x.txt", b"x")},
            task="assign",
        ).status_code
        == 400
    )
    assert request(task="assign", case=False).status_code == 400
    assert request(task="unknown").status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    ("suffix", "name"),
    [
        ("", "programme-review-cases"),
        (f"{UUID(int=20)}/", "programme-review-case"),
        (f"{UUID(int=20)}/assign/", "programme-review-assign"),
        (
            f"{UUID(int=20)}/assignments/{UUID(int=30)}/remove/",
            "programme-review-remove",
        ),
    ],
)
def test_reserved_routes_remain_unmounted_and_response_headers_private(
    page, suffix, name
):
    path = (
        f"/admin/applications/programme-review/{UUID(int=2)}/{UUID(int=3)}/"
        f"{UUID(int=4)}/cases/{suffix}"
    )
    assert (
        resolve(path, urlconf="maru.applications.programme_review_setup_urls").url_name
        == name
    )
    try:
        production = resolve(path)
    except Resolver404:
        pass
    else:
        assert production.func != views.programme_review_management
        assert production.url_name != name
    response = request()
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
