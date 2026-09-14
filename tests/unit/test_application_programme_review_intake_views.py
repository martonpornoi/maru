"""Database-forbidden real HTTP/form/HTML contracts for exact case opening."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_review_intake_queries as queries
from maru.applications import programme_review_intake_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_commands import (
    ProgrammeReviewResult,
    apply_programme_review_command,
)
from maru.applications.programme_review_rules import ProgrammeReviewConflictError
from tests.unit.test_application_programme_review_setup_views import (
    context,
    hidden,
    shell,
    soup,
)
from tests.unit.test_application_programme_review_setup_views import page as _setup_page

pytestmark = pytest.mark.usefixtures(shell.__name__)


def selection(**changes):
    return replace(
        queries.ReviewIntakeSelection(
            queries.ReviewIntakeSeal(
                UUID(int=40), UUID(int=41), 3, datetime(2026, 9, 1, tzinfo=UTC)
            ),
            eligible=True,
            opened=False,
            writable=True,
        ),
        **changes,
    )


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(
        views, "can_manage_programme_review_cases", Mock(return_value=False)
    )
    setup_page = _setup_page.__wrapped__(monkeypatch)
    selected = Mock(return_value=selection())
    seals = Mock(
        return_value=queries.ReviewIntakePage((selection().seal,), UUID(int=40))
    )
    command = create_autospec(apply_programme_review_command)
    command.return_value = ProgrammeReviewResult(
        UUID(int=50), UUID(int=51), UUID(int=51), 1, replayed=False
    )
    monkeypatch.setattr(queries, "get_programme_review_intake_seal", selected)
    monkeypatch.setattr(queries, "list_programme_review_intake_seals", seals)
    monkeypatch.setattr(views, "apply_programme_review_command", command)
    return SimpleNamespace(
        selected=selected, seals=seals, command=command, setup=setup_page
    )


def request(method="get", values=None, *, detail=True, csrf=True, url="/"):
    req = getattr(RequestFactory(), method)(url, data=values or {})
    req.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=True)
    req._dont_enforce_csrf_checks = csrf
    return views.programme_review_intake(
        req,
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        UUID(int=20),
        3,
        UUID(int=40) if detail else None,
    )


def proof():
    return {
        "retry_key": str(UUID(int=60)),
        "expected_version": "0",
        "reason": "Open the explicitly selected seal.",
        "confirm": "on",
    }


def test_source_chooser_is_labelled_paged_audited_and_content_free(page):
    response = request(detail=False)
    assert response.status_code == 200
    html = soup(response)
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert not html.find("a", string="Manage review cases and named reviewers")
    assert html.find("script", string="attack") is None
    assert html.find("a", string="Submitted revision 3")["href"].endswith(
        f"/policies/3/cases/{UUID(int=40)}/"
    )
    assert html.find("a", string="Next page of submitted revisions")["href"].endswith(
        f"?after={UUID(int=40)}"
    )
    assert "2026-09-01T00:00:00+00:00" in html.get_text()
    assert page.seals.call_count == 3
    scope = page.seals.call_args.kwargs["request"]
    assert scope.requested_fields == frozenset({"review_setup"})
    assert scope.actor_id == UUID(int=1)
    page.command.assert_not_called()


def test_explicit_selection_confirms_only_canonical_exact_source_and_policy(page):
    first = request()
    assert first.status_code == 200
    assert hidden(first)["expected_version"] == "0"
    assert not soup(first).find("input", {"name": "confirm"}).has_attr("checked")
    response = request("post", proof())
    assert response.status_code == 200
    html = soup(response)
    assert "Case opening confirmed" in html.get_text()
    assert not html.find("form", {"data-call-command": True})
    kwargs = page.command.call_args.kwargs
    assert kwargs["command"] == views.ProgrammeReviewCommandInput(
        views.ProgrammeReviewAction.CASE_OPENED,
        UUID(int=41),
        policy_id=UUID(int=30),
        reference_id=UUID(int=40),
    )
    assert kwargs["expected_version"] == 0
    assert kwargs["retry_key"] == UUID(int=60)
    assert kwargs["reason"] == proof()["reason"]
    assert kwargs["department_id"] == UUID(int=4)
    assert kwargs["source_channel"] == "programme-review-intake"


def test_case_receipt_links_to_independently_admitted_manager_and_rechecks(
    page, monkeypatch
):
    admission = Mock(return_value=True)
    monkeypatch.setattr(views, "can_manage_programme_review_cases", admission)
    response = request("post", proof())
    assert response.status_code == 200
    assert (
        soup(response)
        .find("a", string="Inspect this case and assign reviewers")["href"]
        .endswith(f"/cases/{UUID(int=51)}/")
    )
    admission.side_effect = [True, False]
    response = request()
    assert response.status_code == 404
    assert b"Synthetic" not in response.content


@pytest.mark.parametrize(
    "change", [{"opened": True}, {"eligible": False}, {"writable": False}]
)
def test_original_post_reaches_canonical_replay_after_source_or_planning_changes(
    page, change
):
    page.selected.return_value = selection(**change)
    page.command.return_value = replace(page.command.return_value, replayed=True)
    response = request("post", proof())
    assert response.status_code == 200
    assert "original receipt was recovered" in soup(response).get_text()
    page.command.assert_called_once()


@pytest.mark.parametrize(
    ("error", "status"), [(ProgrammeReviewConflictError, 409), (DatabaseError, 503)]
)
def test_conflict_and_dependency_failure_preserve_original_intent_and_focus(
    page, error, status
):
    page.command.side_effect = error
    page.selected.return_value = selection(eligible=False, opened=True)
    response = request("post", proof())
    assert response.status_code == status
    html = soup(response)
    assert hidden(response)["retry_key"] == proof()["retry_key"]
    assert hidden(response)["expected_version"] == "0"
    assert (
        html.find("textarea", {"name": "reason"}).get_text().lstrip("\n")
        == proof()["reason"]
    )
    assert html.find("input", {"name": "confirm"}).has_attr("checked")
    assert html.find(attrs={"role": "alert"}).has_attr("autofocus")
    assert html.find("form", {"data-call-command": True})["data-call-pending"] == "true"


@pytest.mark.parametrize("value", ["1", "-1", "00", "+0", "0.0", " 0", ""])
def test_creation_version_is_canonical_zero_only(page, value):
    response = request("post", proof() | {"expected_version": value})
    assert response.status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "change", [{"confirm": ""}, {"reason": ""}, {"retry_key": "unknown"}]
)
def test_confirmation_reason_and_valid_original_retry_are_required(page, change):
    assert request("post", proof() | change).status_code == 400
    page.command.assert_not_called()


def test_empty_and_readonly_sources_do_not_offer_fresh_mutation(page):
    page.seals.return_value = queries.ReviewIntakePage((), None)
    assert "No currently eligible" in soup(request(detail=False)).get_text()
    page.setup.source.return_value = replace(context(), writable=False)
    page.selected.return_value = selection(writable=False)
    response = request()
    assert "Planning is closed" in soup(response).get_text()
    assert not soup(response).find("form", {"data-call-command": True})
    page.command.assert_not_called()


@pytest.mark.parametrize("target", ["source", "policy", "selected", "seals"])
def test_query_denials_and_render_races_never_release_private_context(page, target):
    owner = page.setup if target in {"source", "policy"} else page
    query = getattr(owner, target)
    original = query.return_value
    query.side_effect = Denied
    response = request(detail=target != "seals")
    assert response.status_code == 404
    assert b"Synthetic" not in response.content
    query.side_effect = [original, original, Denied]
    response = request(detail=target != "seals")
    assert response.status_code == 404
    assert b"Synthetic" not in response.content


def test_entry_denial_precedes_all_source_loading(page):
    page.setup.authorize.side_effect = Denied
    assert request().status_code == 404
    page.setup.source.assert_not_called()
    page.selected.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"after": "bad"},
        {"after": str(UUID(int=0))},
        {"after": [str(UUID(int=1)), str(UUID(int=2))]},
        {"actor_id": str(UUID(int=9))},
    ],
)
def test_query_transport_is_closed_before_source_load(page, values):
    assert request(values=values, detail=False).status_code == 400
    page.seals.assert_not_called()


def test_exclusive_cursor_is_forwarded_without_scope_or_policy_change(page):
    assert request(values={"after": str(UUID(int=39))}, detail=False).status_code == 200
    assert page.seals.call_args.kwargs["after_id"] == UUID(int=39)
    assert page.setup.policy.call_args.kwargs["version"] == 3


@pytest.mark.parametrize(
    "change",
    [
        {"policy_id": str(UUID(int=99))},
        {"confirm": ["on", "on"]},
        {"reason": "x" * 12001},
    ],
)
def test_post_cannot_override_url_scope_or_duplicate_controls(page, change):
    assert request("post", proof() | change).status_code == 400
    page.command.assert_not_called()


def test_csrf_files_unsafe_methods_and_inventory_posts_are_rejected(page):
    assert request("post", proof(), csrf=False).status_code == 403
    assert request("put", proof()).status_code == 405
    assert request("post", proof(), detail=False).status_code == 400
    assert (
        request(
            "post", proof() | {"upload": SimpleUploadedFile("x.txt", b"x")}
        ).status_code
        == 400
    )
    page.command.assert_not_called()


def test_reserved_routes_remain_unmounted_in_production_and_headers_are_private(page):
    path = (
        f"/admin/applications/programme-review/{UUID(int=2)}/{UUID(int=3)}/"
        f"{UUID(int=4)}/{UUID(int=20)}/policies/3/cases/{UUID(int=40)}/"
    )
    assert (
        resolve(path, urlconf="maru.applications.programme_review_setup_urls").url_name
        == "programme-review-open"
    )
    try:
        production = resolve(path)
    except Resolver404:
        pass
    else:
        assert production.func != views.programme_review_intake
        assert production.url_name != "programme-review-open"
    response = request()
    assert "no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
