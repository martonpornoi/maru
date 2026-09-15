"""Real moderation forms and HTTP disclosure/retry contracts without databases."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import resolve

from maru.applications import programme_moderation_queries as queries
from maru.applications import programme_moderation_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_commands import (
    ProgrammeReviewResult,
    apply_programme_review_command,
)
from maru.applications.programme_review_queries import ProgrammeReviewDetail
from maru.applications.programme_review_rules import ProgrammeReviewConflictError
from tests.unit.test_application_programme_review_inputs import review_policy
from tests.unit.test_application_programme_review_management_views import (
    context as manager_context,
)
from tests.unit.test_application_programme_review_setup_views import hidden, shell, soup

pytestmark = pytest.mark.usefixtures(shell.__name__)


def context(**changes):
    first = review_policy().stages[0]
    return replace(
        queries.ModerationCase(
            replace(manager_context().case, stage=1, stage_code="later"),
            (first, replace(first, code="later"), replace(first, code="final")),
            writable=True,
        ),
        **changes,
    )


@pytest.fixture
def page(monkeypatch):
    source = Mock(return_value=context())
    queue = Mock(
        return_value=queries.ReviewManagerPage((context().case,), UUID(int=20))
    )
    authorize = Mock()
    detail = create_autospec(views.get_programme_review_detail)
    detail.return_value = ProgrammeReviewDetail(UUID(int=20), 5, None, None, None, None)
    evidence = Mock(
        return_value=queries.ModerationEvidence(
            ProgrammeReviewDetail(
                UUID(int=20),
                5,
                None,
                None,
                json.dumps(
                    [
                        {
                            "version": 3,
                            "stage": 0,
                            "action": "scored",
                            "actor_id": str(UUID(int=40)),
                            "assignment_id": str(UUID(int=30)),
                            "payload": {"scores": {"fit": 4}},
                            "reason": "Private independent reason",
                        },
                        {
                            "version": 4,
                            "stage": 0,
                            "action": "moderated",
                            "actor_id": str(UUID(int=41)),
                            "payload": {"evidence_version": 3},
                            "reason": "Earlier moderation",
                        },
                    ]
                ),
                4,
            ),
            1,
            2,
            ready=False,
        )
    )
    command = create_autospec(apply_programme_review_command)
    command.return_value = ProgrammeReviewResult(
        UUID(int=70), UUID(int=30), UUID(int=20), 6, replayed=False
    )
    for name, value in (
        ("get_programme_moderation_case", source),
        ("list_programme_moderation_cases", queue),
        ("get_programme_moderation_evidence", evidence),
    ):
        monkeypatch.setattr(queries, name, value)
    monkeypatch.setattr(views, "authorize_programme_review_scope", authorize)
    monkeypatch.setattr(views, "get_programme_review_detail", detail)
    monkeypatch.setattr(views, "apply_programme_review_command", command)
    return SimpleNamespace(
        source=source,
        queue=queue,
        authorize=authorize,
        detail=detail,
        evidence=evidence,
        command=command,
    )


def request(method="get", values=None, *, task="overview", queue=False, csrf=True):
    req = getattr(RequestFactory(), method)("/", data=values or {})
    req.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=True)
    req._dont_enforce_csrf_checks = csrf
    return views.programme_moderation(
        req,
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        None if queue else UUID(int=20),
        task,
    )


def proof(task="moderate"):
    values = {
        "action": task,
        "expected_version": "5",
        "retry_key": str(UUID(int=60)),
        "reason": "My exact independent rationale",
        "confirm": "on",
    }
    if task == "reopen":
        values["stage"] = "0"
    return values


def test_independent_discovery_and_overview_do_not_read_private_evidence(page):
    response = request(queue=True, values={"after": str(UUID(int=19))})
    html = soup(response)
    assert response.status_code == 200
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert html.find("a", string="Next page of moderation cases")
    assert page.queue.call_args.kwargs["after_id"] == UUID(int=19)
    html = soup(request())
    assert html.find("a", string="Inspect evidence and record moderation")
    assert html.find("a", string="Reopen a configured stage")
    page.evidence.assert_not_called()
    page.detail.assert_not_called()


@pytest.mark.parametrize("task", ["moderate", "advance", "reopen"])
def test_exact_action_and_old_receipt_need_no_private_metadata_or_content(page, task):
    page.source.side_effect = Denied
    page.detail.side_effect = Denied
    page.evidence.side_effect = Denied
    page.command.return_value = replace(page.command.return_value, replayed=True)
    response = request("post", proof(task), task=task)
    assert response.status_code == 200
    assert "original receipt was recovered" in soup(response).get_text()
    assert not soup(response).find("form", {"data-call-command": True})
    kwargs = page.command.call_args.kwargs
    assert kwargs["command"].action == views._ACTIONS[task]
    assert kwargs["command"].target_id == UUID(int=20)
    assert kwargs["command"].stage == (0 if task == "reopen" else None)
    assert kwargs["expected_version"] == 5
    assert kwargs["retry_key"] == UUID(int=60)
    assert kwargs["reason"] == proof(task)["reason"]
    assert kwargs["source_channel"] == "programme-moderation"
    page.source.assert_not_called()
    page.evidence.assert_not_called()
    page.detail.assert_not_called()


def test_moderation_form_shows_exact_protected_evidence_without_new_identity_lookup(
    page,
):
    response = request(task="moderate")
    html = soup(response)
    assert response.status_code == 200
    assert "Private independent reason" in html.get_text()
    assert "Valid independent scores: 1 of 2 required" in html.get_text()
    assert hidden(response)["expected_version"] == "5"
    assert (
        html.find("a", string="Next page of this evidence version")["href"]
        == "?after=4&version=5"
    )
    assert (
        str(UUID(int=40))
        in html.find("summary", string="Attribution references").parent.get_text()
    )
    assert page.evidence.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_evidence"}
    )
    page.detail.assert_not_called()


def test_snapshot_mismatch_returns_no_history_and_no_silently_refreshed_form(page):
    response = request(task="moderate", values={"after": "3", "version": "4"})
    assert response.status_code == 409
    html = soup(response)
    assert "Evidence changed" in html.get_text()
    assert "Private independent reason" not in html.get_text()
    assert not html.find("form", {"data-call-command": True})
    assert html.find(attrs={"role": "alert", "autofocus": True})


def test_snapshot_cursor_is_retained_when_paginating(page):
    response = request(task="evidence", values={"after": "3", "version": "5"})
    assert response.status_code == 200
    assert page.evidence.call_args.kwargs["after_version"] == 3
    assert not soup(response).find("form", {"data-call-command": True})


def test_reopen_has_no_default_and_only_labelled_current_or_earlier_choices(page):
    response = request(task="reopen")
    options = soup(response).find("select", {"name": "stage"}).find_all("option")
    assert [(row["value"], row.get_text()) for row in options] == [
        ("", "Choose a stage deliberately"),
        ("0", "1. content"),
        ("1", "2. later"),
    ]
    page.command.assert_not_called()


@pytest.mark.parametrize("task", ["moderate", "advance", "reopen"])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProgrammeReviewConflictError, 409),
        (DatabaseError, 503),
        (ValidationError("Invalid owner intent"), 400),
    ],
)
def test_failed_intent_retains_original_proof_and_reason_after_case_moves(
    page, task, error, status
):
    page.command.side_effect = error
    page.source.return_value = context(
        case=replace(context().case, version=20, stage=0, stage_code="content")
    )
    values = proof(task)
    if task == "reopen":
        values["stage"] = "1"
    response = request("post", values, task=task)
    assert response.status_code == status
    assert hidden(response)["expected_version"] == "5"
    assert hidden(response)["retry_key"] == str(UUID(int=60))
    html = soup(response)
    # HTML consumes the one leading textarea newline emitted by Django's widget.
    assert (
        html.find("textarea", {"name": "reason"}).get_text().removeprefix("\n")
        == values["reason"]
    )
    assert html.find("input", {"name": "confirm"}).has_attr("checked")
    if task == "reopen":
        assert html.find("option", {"value": "1"}).has_attr("selected")
    page.evidence.assert_not_called()


@pytest.mark.parametrize("state", ["accepted", "rejected", "revision_requested"])
@pytest.mark.parametrize("task", ["moderate", "advance", "reopen"])
def test_final_cases_never_offer_fresh_actions(page, state, task):
    page.source.return_value = context(case=replace(context().case, state=state))
    response = request(task=task)
    assert response.status_code == 200
    assert not soup(response).find("form", {"data-call-command": True})
    assert "final case cannot be reopened" in soup(response).get_text()


def test_readonly_stale_and_waitlisted_states_have_truthful_actions(page):
    for changes in (
        {"writable": False},
        {"case": replace(context().case, current_revision=False)},
    ):
        page.source.return_value = context(**changes)
        assert not soup(request()).find("a", string="Reopen a configured stage")
    page.source.return_value = context(case=replace(context().case, state="waitlisted"))
    html = soup(request())
    assert html.find("a", string="Reopen a configured stage")
    assert not html.find("a", string="Inspect evidence and record moderation")


@pytest.mark.parametrize(
    "values",
    [
        {"confirm": ""},
        {"reason": ""},
        {"extra": "forged"},
        {"expected_version": "05"},
        {"expected_version": "+5"},
        {"retry_key": "not-uuid"},
        {"stage": "0"},
    ],
)
def test_invalid_moderation_forms_never_invoke_owner(page, values):
    assert request("post", proof() | values, task="moderate").status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize("value", ["", "8", "-1", "00", "1.0", "+1", " 1", "\u0661"])
def test_reopen_stage_uses_closed_strict_integer_without_choice_rebasing(page, value):
    assert (
        request("post", proof("reopen") | {"stage": value}, task="reopen").status_code
        == 400
    )
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"after": "3"},
        {"version": "05"},
        {"version": "0"},
        {"after": "6", "version": "5"},
        {"unknown": "x"},
        {"version": ["5", "6"]},
    ],
)
def test_closed_snapshot_transport_precedes_private_queries(page, values):
    assert request(task="evidence", values=values).status_code == 400
    page.source.assert_not_called()
    page.evidence.assert_not_called()


def test_csrf_duplicate_post_and_route_action_fail_before_writer(page):
    assert request("post", proof(), task="moderate", csrf=False).status_code == 403
    assert (
        request(
            "post", proof() | {"reason": ["one", "two"]}, task="moderate"
        ).status_code
        == 400
    )
    assert request("post", proof(), task="reopen").status_code == 400
    assert request("post", proof(), queue=True).status_code == 400
    page.command.assert_not_called()


def test_current_admission_and_render_revalidation_still_guard_receipts(page):
    page.authorize.side_effect = [None, None, Denied]
    assert request("post", proof(), task="moderate").status_code == 404
    assert page.command.call_count == 1
    page.source.assert_not_called()


def test_revoked_metadata_discards_bound_request_and_private_content(page):
    page.command.side_effect = ProgrammeReviewConflictError
    page.source.side_effect = Denied
    response = request("post", proof(), task="moderate")
    assert response.status_code == 404
    assert proof()["reason"] not in response.content.decode()


def test_protected_evidence_revocation_during_render_releases_no_cached_history(page):
    page.evidence.side_effect = [
        page.evidence.return_value,
        page.evidence.return_value,
        Denied,
    ]
    response = request(task="evidence")
    assert response.status_code == 404
    assert "Private independent reason" not in response.content.decode()


def test_answers_are_escaped_and_protected_references_do_not_become_links(page):
    page.detail.return_value = replace(
        page.detail.return_value,
        answers_json=json.dumps(
            [
                {
                    "label": "Abstract",
                    "classification": "C2",
                    "type": "short_text",
                    "value": "<script>attack</script>",
                },
                {
                    "label": "Upload",
                    "classification": "C2",
                    "type": "safe_file",
                    "value": "https://unsafe.invalid/file",
                },
            ]
        ),
    )
    html = soup(request(task="answers"))
    assert not html.find("script", string="attack")
    assert not html.find("a", href="https://unsafe.invalid/file")
    assert "dedicated safe viewer remains tracked" in html.get_text()
    assert page.detail.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_answers"}
    )


def test_reserved_moderation_routes_do_not_mount_in_production():
    root = (
        f"/admin/applications/programme-review/{UUID(int=2)}/"
        f"{UUID(int=3)}/{UUID(int=4)}/moderation/"
    )
    assert (
        resolve(root, urlconf="maru.applications.programme_review_setup_urls").func
        is views.programme_moderation
    )
    assert resolve(root).func is not views.programme_moderation
