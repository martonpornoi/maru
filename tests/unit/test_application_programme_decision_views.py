"""Exact personal receipt HTTP contracts with real templates and typed commands."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec, patch
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_decision_views as views
from maru.applications import programme_review_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_authorization import ACKNOWLEDGE_SELF
from maru.applications.programme_review_commands import apply_programme_review_command


def message():
    return queries.ProgrammeDecisionMessage(
        UUID(int=20),
        UUID(int=30),
        12,
        10,
        datetime(2026, 9, 1, tzinfo=UTC),
        "accepted",
        "Exact recipient text.\n<script>private attack</script>",
        acknowledgement_required=True,
        own_acknowledged=False,
        own_acknowledged_at=None,
        source=queries.ProgrammeDecisionSource(
            UUID(int=40),
            "Synthetic call <script>unsafe</script>",
            2,
            UUID(int=50),
            datetime(2026, 8, 30, tzinfo=UTC),
            UUID(int=60),
            3,
            datetime(2026, 8, 31, tzinfo=UTC),
        ),
    )


def data(**overrides):
    return {
        "retry_key": str(UUID(int=90)),
        "expected_version": "12",
        "confirm": "on",
    } | overrides


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access",
            return_value={"workspace_available": False},
        ),
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        yield


@pytest.fixture
def page(monkeypatch):
    detail = Mock(return_value=message())
    history = Mock(
        return_value=queries.ProgrammeDecisionPage((message(),), UUID(int=20))
    )
    authorize = Mock(
        return_value=SimpleNamespace(accepts_private_planning_writes=False)
    )
    command = create_autospec(apply_programme_review_command)
    proposal = Mock(
        return_value=SimpleNamespace(
            relationship="collaborator",
            proposal_id=UUID(int=50),
            call_id=UUID(int=40),
        )
    )
    monkeypatch.setattr(queries, "get_self_programme_decision", detail)
    monkeypatch.setattr(queries, "list_self_programme_decisions", history)
    monkeypatch.setattr(views, "authorize_programme_review_scope", authorize)
    monkeypatch.setattr(views, "apply_programme_review_command", command)
    monkeypatch.setattr(views, "authorize_programme_proposal_scope", proposal)
    return SimpleNamespace(
        detail=detail,
        history=history,
        authorize=authorize,
        command=command,
        proposal=proposal,
    )


def request(method="get", values=None, *, detail=True, csrf=True, url="/", user=True):
    request = getattr(RequestFactory(), method)(url, data=values or {})
    request.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=user)
    request._dont_enforce_csrf_checks = csrf
    return views.programme_decisions(
        request, UUID(int=2), UUID(int=3), UUID(int=20) if detail else None
    )


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def test_history_has_bounded_labelled_navigation_without_message_content(page):
    response = request(detail=False)
    assert response.status_code == 200
    html = soup(response)
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert "Accepted" in html.get_text()
    assert "Exact recipient text" not in html.get_text()
    assert html.find("a", string="Next page of decisions")["href"].endswith(
        f"?after={UUID(int=20)}"
    )
    assert page.history.call_count == 3
    for invocation in page.history.call_args_list:
        scope = invocation.kwargs["request"]
        assert (scope.actor_id, scope.organization_id, scope.edition_id) == (
            UUID(int=1),
            UUID(int=2),
            UUID(int=3),
        )
        assert scope.department_id is None
        assert scope.requested_fields == frozenset(
            {"decision_message", "own_acknowledgement"}
        )
    page.command.assert_not_called()


def test_empty_history_is_truthful(page):
    page.history.return_value = queries.ProgrammeDecisionPage((), None)
    html = soup(request(detail=False))
    assert "No addressed decisions" in html.get_text()
    assert html.find("a", string="Next page of decisions") is None


def test_exact_detail_escapes_message_and_never_acknowledges_on_get(page):
    response = request()
    html = soup(response)
    assert response.status_code == 200
    assert html.select_one(".decision-message script") is None
    assert "<script>private attack</script>" in html.get_text()
    assert html.select_one(".decision-message br") is not None
    assert html.find("input", {"name": "expected_version"})["value"] == "12"
    assert html.find("input", {"name": "confirm"}).get("checked") is None
    assert "not agreement" in html.get_text()
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert page.detail.call_count == 3
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"acknowledgement_required": False},
        {
            "own_acknowledged": True,
            "own_acknowledged_at": datetime(2026, 9, 2, tzinfo=UTC),
        },
    ],
)
def test_not_requested_or_already_received_has_no_fresh_form(page, change):
    page.detail.return_value = replace(message(), **change)
    assert soup(request()).find("form", {"data-call-command": True}) is None


def test_read_does_not_require_write_or_open_planning(page):
    def authorize(**kwargs):
        if kwargs["capability_code"] == ACKNOWLEDGE_SELF:
            raise Denied
        return SimpleNamespace(accepts_private_planning_writes=False)

    page.authorize.side_effect = authorize
    response = request()
    assert response.status_code == 200
    assert "read-only" in soup(response).get_text()
    assert soup(response).find("form", {"data-call-command": True}) is None
    assert request("post", data()).status_code == 404
    page.command.assert_not_called()


def test_confirmed_receipt_uses_exact_owner_signature_without_newer_proof(page):
    response = request("post", data(expected_version="7"))
    assert response.status_code == 302
    assert response["Location"].endswith(f"/decisions/{UUID(int=20)}/")
    page.command.assert_called_once()
    values = page.command.call_args.kwargs
    assert values["actor_id"] == UUID(int=1)
    assert values["organization_id"] == UUID(int=2)
    assert values["edition_id"] == UUID(int=3)
    assert values["department_id"] is None
    assert values["expected_version"] == 7
    assert values["retry_key"] == UUID(int=90)
    assert values["reason"] == ""
    assert values["command"].action == "acknowledged"
    assert values["command"].target_id == UUID(int=30)
    assert values["command"].reference_id == UUID(int=20)


def test_exact_uncertain_retry_reaches_writer_even_after_receipt_recorded(page):
    page.detail.return_value = replace(message(), own_acknowledged=True)
    assert request("post", data(expected_version="7")).status_code == 302
    assert page.command.call_args.kwargs["expected_version"] == 7


@pytest.mark.parametrize(
    "error",
    [
        views.ProgrammeReviewConflictError,
        views.ApplicationsProgrammeIdempotencyConflictError,
    ],
)
def test_stale_receipt_keeps_original_evidence_and_reads_new_authorized_cursor(
    page, error
):
    page.command.side_effect = error
    page.detail.side_effect = [message(), *([replace(message(), case_version=13)] * 3)]
    response = request("post", data(expected_version="7"))
    html = soup(response)
    assert response.status_code == 409
    assert html.find("input", {"name": "expected_version"})["value"] == "7"
    assert html.find("input", {"name": "retry_key"})["value"] == str(UUID(int=90))
    assert html.find("input", {"name": "confirm"}).has_attr("checked")
    assert html.find(attrs={"role": "alert"}).has_attr("autofocus")
    assert html.find("form", {"data-call-command": True})["data-call-pending"] == "true"


@pytest.mark.parametrize(
    "changes",
    [
        {"confirm": ""},
        {"retry_key": "invalid"},
        {"expected_version": "0"},
        {"expected_version": "+12"},
        {"expected_version": " 12"},
        {"expected_version": "1.0"},
        {"expected_version": str(2**63)},
    ],
)
def test_original_form_evidence_is_strict_and_confirmation_required(page, changes):
    assert request("post", data(**changes)).status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "field",
    [
        "actor_id",
        "department_id",
        "case_id",
        "decision_id",
        "outcome",
        "reason",
        "action",
        "message",
    ],
)
def test_unknown_post_fields_cannot_change_subject_scope_or_content(page, field):
    assert request("post", data(**{field: "overridden"})).status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "field", ["confirm", "retry_key", "expected_version", "csrfmiddlewaretoken"]
)
def test_duplicate_scalar_fields_are_rejected(page, field):
    values = QueryDict(mutable=True)
    values.update(data())
    values.setlist(field, ["first", "second"])
    req = RequestFactory().post("/", data={})
    req.POST = values
    req.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=True)
    req._dont_enforce_csrf_checks = True
    assert (
        views.programme_decisions(
            req, UUID(int=2), UUID(int=3), UUID(int=20)
        ).status_code
        == 400
    )
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "/?after=invalid",
        "/?after=",
        "/?after=" + str(UUID(int=0)),
        "/?after=a&after=b",
        "/?page=2",
    ],
)
def test_malformed_history_cursor_is_bounded(page, url):
    assert request(detail=False, url=url).status_code == 400
    page.history.assert_not_called()


def test_valid_history_cursor_is_forwarded_exactly(page):
    assert request(detail=False, url=f"/?after={UUID(int=40)}").status_code == 200
    assert page.history.call_args.kwargs["after_id"] == UUID(int=40)


@pytest.mark.parametrize("detail", [False, True])
def test_late_disclosure_denial_discards_every_prepared_message(page, detail):
    selected = page.detail if detail else page.history
    selected.side_effect = [selected.return_value, selected.return_value, Denied()]
    response = request(detail=detail)
    assert response.status_code == 404
    assert b"Exact recipient text" not in response.content
    assert b"accepted" not in response.content


def test_late_receipt_or_page_change_refuses_stale_render(page):
    page.detail.side_effect = [
        message(),
        message(),
        replace(message(), case_version=13),
    ]
    assert request().status_code == 404
    page.history.side_effect = [
        page.history.return_value,
        queries.ProgrammeDecisionPage((), None),
    ]
    assert request(detail=False).status_code == 404


def test_read_authority_precedes_private_projection(page):
    page.authorize.side_effect = Denied
    assert request("post", data()).status_code == 404
    page.detail.assert_not_called()
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        DatabaseError,
        views.ProgrammeReviewUnavailableError,
        views.ApplicationsProgrammeWriteScopeUnavailableError,
    ],
)
def test_unavailable_dependencies_never_claim_receipt_success(page, error):
    page.command.side_effect = error
    response = request("post", data())
    assert response.status_code == 503
    assert b"Exact recipient text" not in response.content


def test_owner_validation_retains_form_and_never_redirects(page):
    page.command.side_effect = ValidationError("Synthetic invalid receipt.")
    response = request("post", data())
    assert response.status_code == 400
    assert "Synthetic invalid receipt" in soup(response).get_text()


def test_method_csrf_and_history_mutation_fences(page):
    assert request("post", data(), csrf=False).status_code == 403
    assert request("put").status_code == 405
    assert request("post", data(), detail=False).status_code == 400
    assert request("post", data(), url="/?after=ignored").status_code == 400
    assert request("post", data(confirm="x" * 201)).status_code == 400
    page.command.assert_not_called()


def test_dormant_routes_are_explicit_and_absent_from_production(page):
    root = f"/my/applications/programme/{UUID(int=2)}/{UUID(int=3)}/decisions/"
    assert (
        resolve(root, urlconf="maru.applications.programme_proposal_urls").func
        == views.programme_decisions
    )
    assert resolve(
        root + f"{UUID(int=20)}/", urlconf="maru.applications.programme_proposal_urls"
    ).kwargs["decision_id"] == UUID(int=20)
    with pytest.raises(Resolver404):
        resolve(root)


@pytest.mark.parametrize(
    ("outcome", "label"),
    [
        ("waitlisted", "Wait-listed"),
        ("rejected", "Rejected"),
        ("revision_requested", "Revision requested"),
    ],
)
def test_each_historical_outcome_has_a_human_label(page, outcome, label):
    page.detail.return_value = replace(message(), outcome=outcome)
    assert soup(request()).find("h2", id="decision-message").get_text() == label


def test_uploads_never_enter_the_receipt_command(page):
    values = data() | {"file": SimpleUploadedFile("synthetic.txt", b"not a receipt")}
    assert request("post", values).status_code == 400
    page.command.assert_not_called()


def test_anonymous_and_missing_person_are_denied_before_projection(page):
    assert request(user=False).status_code == 302
    req = RequestFactory().get("/")
    req.user = SimpleNamespace(pk=None, is_authenticated=True)
    assert views.programme_decisions(req, UUID(int=2), UUID(int=3)).status_code == 404
    page.history.assert_not_called()


def test_invalid_owner_outcome_is_unavailable_not_fabricated(page):
    page.detail.return_value = replace(message(), outcome=None)
    assert request().status_code == 503


def test_retained_labels_are_escaped_and_references_are_progressive(page):
    for detail in (False, True):
        html = soup(request(detail=detail))
        context = html.select_one(".decision-source")
        assert "Synthetic call <script>unsafe</script>" in context.get_text()
        assert context.find("script") is None
        assert "Call version 2" in context.get_text()
        assert "Proposal created 2026-08-30" in context.get_text()
        assert "Seal 3" in context.get_text()
        assert str(UUID(int=60)) in context.find("details").get_text()
        assert str(UUID(int=50)) in context.find("details").get_text()


def test_history_never_discovers_current_proposals(page):
    request(detail=False)
    page.proposal.assert_not_called()


@pytest.mark.parametrize("relationship", ["lead", "collaborator", "invited"])
def test_source_navigation_requires_complete_independent_destination_ceiling(
    page, relationship
):
    page.proposal.return_value.relationship = relationship
    response = request()
    html = soup(response)
    assert html.find("a", string="Open my current proposal overview")["href"] == (
        f"/my/applications/programme/{UUID(int=2)}/{UUID(int=3)}/{UUID(int=50)}/"
    )
    assert page.proposal.call_count == 4
    for index, invocation in enumerate(page.proposal.call_args_list):
        values = invocation.kwargs
        assert values["actor_id"] == UUID(int=1)
        assert values["organization_id"] == UUID(int=2)
        assert values["edition_id"] == UUID(int=3)
        assert values["proposal_id"] == UUID(int=50)
        assert values["capability_code"] == "applications.view_programme_proposal_self"
        expected = {"proposal_summary", "selection", "own_invitation"}
        if index % 2 == 1 and relationship != "invited":
            expected.add("contributor_profiles")
        assert values["requested_fields"] == frozenset(expected)


@pytest.mark.parametrize(
    "error",
    [Denied, DatabaseError, views.ApplicationsProgrammeWriteScopeUnavailableError],
)
@pytest.mark.parametrize("failure_call", [0, 1, 2, 3])
def test_missing_revoked_or_unavailable_source_link_never_erases_retained_message(
    page, error, failure_call
):
    page.proposal.side_effect = [page.proposal.return_value] * failure_call + [error()]
    response = request()
    html = soup(response)
    assert response.status_code == 200
    assert "Exact recipient text" in html.get_text()
    assert "Synthetic call" in html.get_text()
    assert html.find("a", string="Open my current proposal overview") is None
    assert html.find("input", {"name": "expected_version"})["value"] == "12"
    assert page.detail.call_count == 3
    page.command.assert_not_called()


@pytest.mark.parametrize("field", ["proposal_id", "call_id", "relationship"])
def test_moved_or_wrong_destination_admission_never_creates_a_link(page, field):
    changed = SimpleNamespace(
        **(
            vars(page.proposal.return_value)
            | {
                field: "lead" if field == "relationship" else UUID(int=999),
            }
        )
    )
    page.proposal.side_effect = [page.proposal.return_value, changed]
    assert soup(request()).find("a", string="Open my current proposal overview") is None


def test_missing_source_is_truthful_without_current_lookup_or_lost_receipt(page):
    page.detail.return_value = replace(message(), source=None)
    html = soup(request())
    assert "Original proposal context is unavailable" in html.get_text()
    assert "Exact recipient text" in html.get_text()
    assert html.find("input", {"name": "confirm"}) is not None
    page.proposal.assert_not_called()


def test_optional_navigation_never_precedes_or_blocks_receipt_writer(page):
    page.proposal.side_effect = AssertionError("No navigation needed for redirect")
    assert request("post", data()).status_code == 302
    page.command.assert_called_once()
    page.proposal.assert_not_called()


def test_message_revocation_during_link_free_rerender_still_discards_content(page):
    page.proposal.side_effect = [page.proposal.return_value] * 2 + [Denied()]
    page.detail.side_effect = [message()] * 2 + [Denied()]
    response = request()
    assert response.status_code == 404
    assert b"Exact recipient text" not in response.content


def test_changed_retained_context_during_render_is_not_disclosed(page):
    changed = replace(message(), source=replace(message().source, revision_sequence=4))
    page.detail.side_effect = [message(), message(), changed]
    assert request().status_code == 404


def test_unknown_current_relationship_cannot_offer_proposal_navigation(page):
    page.proposal.return_value.relationship = "removed"
    assert soup(request()).find("a", string="Open my current proposal overview") is None


def test_message_authority_is_checked_after_final_navigation_admission(page):
    count = 0

    def navigation(**_values):
        nonlocal count
        count += 1
        if count == 4:
            page.detail.side_effect = Denied
        return page.proposal.return_value

    page.proposal.side_effect = navigation
    response = request()
    assert response.status_code == 404
    assert b"Exact recipient text" not in response.content
