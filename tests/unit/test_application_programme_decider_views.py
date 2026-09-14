"""Real decision forms and HTTP proof/receipt/disclosure contracts without a DB."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import resolve

from maru.applications import programme_decider_preview as previews
from maru.applications import programme_decider_queries as queries
from maru.applications import programme_decider_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_commands import (
    ProgrammeReviewResult,
    apply_programme_review_command,
)
from maru.applications.programme_review_rules import ProgrammeReviewConflictError
from tests.unit.test_application_programme_decider_preview import (
    evidence,
    intent,
    prepare,
    work,
)
from tests.unit.test_application_programme_review_setup_views import hidden, shell, soup

pytestmark = pytest.mark.usefixtures(shell.__name__)


@pytest.fixture
def page(monkeypatch):
    source, facts = Mock(return_value=work()), Mock(return_value=evidence())
    queue = Mock(return_value=queries.ReviewManagerPage((work().case,), UUID(int=20)))
    messages = Mock(return_value=queries.DecisionMessages(5, (), None))
    authorize, audit = Mock(), Mock()
    detail = create_autospec(views.get_programme_review_detail)
    detail.return_value = work().detail
    command = create_autospec(apply_programme_review_command)
    command.return_value = ProgrammeReviewResult(
        UUID(int=70), UUID(int=30), UUID(int=20), 6, replayed=False
    )
    for module in (queries, previews):
        monkeypatch.setattr(module, "get_programme_decision_work", source)
        monkeypatch.setattr(module, "get_programme_decision_evidence", facts)
    monkeypatch.setattr(queries, "list_programme_decision_cases", queue)
    monkeypatch.setattr(queries, "list_programme_decision_messages", messages)
    monkeypatch.setattr(previews, "_audit", audit)
    monkeypatch.setattr(
        views,
        "prepare_programme_decision_preview",
        previews.prepare_programme_decision_preview.__wrapped__,
    )
    monkeypatch.setattr(views, "authorize_programme_review_scope", authorize)
    monkeypatch.setattr(views, "get_programme_review_detail", detail)
    monkeypatch.setattr(views, "apply_programme_review_command", command)
    return SimpleNamespace(
        source=source,
        facts=facts,
        queue=queue,
        messages=messages,
        authorize=authorize,
        detail=detail,
        command=command,
    )


def request(method="get", values=None, *, task="overview", queue=False, csrf=True):
    req = getattr(RequestFactory(), method)("/", data=values or {})
    req.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=True)
    req._dont_enforce_csrf_checks = csrf
    return views.programme_decider(
        req,
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        None if queue else UUID(int=20),
        task,
    )


def values(**changes):
    return {
        "action": "preview",
        "expected_version": "5",
        "retry_key": str(UUID(int=60)),
        "outcome": intent().outcome,
        "text": intent().text,
        "reason": intent().reason,
    } | changes


def confirmed():
    return values(action="confirm", preview_proof=prepare().proof, confirm="on")


def test_discovery_and_overview_have_labels_without_reading_evidence(page):
    html = soup(request(queue=True, values={"after": str(UUID(int=19))}))
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert html.find("a", string="Next page of decision cases")
    assert page.queue.call_args.kwargs["after_id"] == UUID(int=19)
    assert soup(request()).find("a", string="Inspect evidence and compose a decision")
    page.facts.assert_not_called()
    page.detail.assert_not_called()
    page.messages.assert_not_called()
    page.command.assert_not_called()


def test_blank_deliberate_form_shows_all_stage_facts_with_no_default_outcome(page):
    response = request(task="decide")
    html = soup(response)
    assert response.status_code == 200
    assert "All-stage readiness" in html.get_text()
    assert hidden(response)["expected_version"] == "5"
    assert html.find("select", {"name": "outcome"}).find("option")["value"] == ""
    assert not html.find("input", {"name": "confirm"})
    assert not html.find("button", {"value": "confirm"})
    assert html.find("textarea", {"name": "reason"}).get_text().strip() == ""
    page.command.assert_not_called()


def test_preview_is_exact_separate_and_requires_an_unchecked_confirmation(page):
    response = request("post", values(), task="decide")
    html = soup(response)
    assert response.status_code == 200
    assert "Exact decision preview · Accept" in html.get_text()
    assert "Private rationale — not sent to recipients" in html.get_text()
    assert html.find("input", {"name": "confirm"}).get("checked") is None
    assert hidden(response)["preview_proof"]
    assert html.find("form", {"data-call-command": True})["data-call-pending"] == "true"
    assert html.find("button", {"value": "preview"}).has_attr("formnovalidate")
    assert not html.find("button", {"value": "confirm"}).has_attr("formnovalidate")
    page.command.assert_not_called()


def test_original_receipt_precedes_every_private_read_after_preview(page):
    data = confirmed()
    for name in ("source", "facts", "detail", "messages"):
        getattr(page, name).reset_mock()
        getattr(page, name).side_effect = Denied
    page.command.return_value = replace(page.command.return_value, replayed=True)
    response = request("post", data, task="decide")
    assert response.status_code == 200
    assert "original receipt was recovered" in soup(response).get_text()
    assert not soup(response).find("form", {"data-call-command": True})
    for name in ("source", "facts", "detail", "messages"):
        getattr(page, name).assert_not_called()
    kwargs = page.command.call_args.kwargs
    assert kwargs["expected_version"] == 5
    assert kwargs["retry_key"] == UUID(int=60)
    assert kwargs["reason"] == intent().reason
    assert kwargs["command"].outcome == intent().outcome
    assert kwargs["command"].text == intent().text
    assert kwargs["command"].target_id == UUID(int=20)
    assert kwargs["source_channel"] == "programme-decision-compose"


@pytest.mark.parametrize(
    "change",
    [
        {"text": "Edited text"},
        {"reason": "Edited reason"},
        {"outcome": "rejected"},
        {"expected_version": "6"},
        {"retry_key": str(UUID(int=61))},
        {"confirm": ""},
        {"preview_proof": "invalid"},
    ],
)
def test_missing_or_changed_exact_confirmation_never_calls_writer(page, change):
    response = request("post", confirmed() | change, task="decide")
    assert response.status_code == 400
    assert soup(response).find(attrs={"role": "alert", "autofocus": True})
    page.command.assert_not_called()


def test_explicit_repreview_can_change_text_without_confirming_old_proof(page):
    data = confirmed() | {
        "action": "preview",
        "text": "Changed deliberately",
        "confirm": "",
    }
    response = request("post", data, task="decide")
    assert response.status_code == 200
    assert hidden(response)["preview_proof"] != data["preview_proof"]
    assert "Changed deliberately" in soup(response).get_text()
    assert not soup(response).find("input", {"name": "confirm"}).has_attr("checked")
    page.command.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"), [(ProgrammeReviewConflictError, 409), (DatabaseError, 503)]
)
def test_failed_confirm_preserves_original_proof_text_rationale_and_checkbox(
    page, error, status
):
    data = confirmed()
    page.command.side_effect = error
    page.source.return_value = work(
        case=replace(work().case, version=6, state="accepted")
    )
    response = request("post", data, task="decide")
    html = soup(response)
    assert response.status_code == status
    for key in ("expected_version", "retry_key", "preview_proof"):
        assert hidden(response)[key] == data[key]
    for key in ("text", "reason"):
        assert (
            html.find("textarea", {"name": key}).get_text().removeprefix("\n")
            == data[key]
        )
    assert html.find("input", {"name": "confirm"}).has_attr("checked")
    assert "Original inspected case version 5" in html.get_text()
    assert "Current version 6" in html.get_text()
    assert html.find(attrs={"role": "alert", "autofocus": True})


def test_failed_preview_does_not_refresh_version_or_retry(page):
    page.source.return_value = work(case=replace(work().case, version=6))
    response = request("post", values(), task="decide")
    assert response.status_code == 409
    assert hidden(response)["expected_version"] == "5"
    assert hidden(response)["retry_key"] == str(UUID(int=60))
    page.command.assert_not_called()


@pytest.mark.parametrize("task", ["decide", "evidence", "messages"])
def test_snapshot_movement_releases_no_history_or_fresh_form(page, task):
    response = request(task=task, values={"after": "3", "version": "4"})
    assert response.status_code == 409
    html = soup(response)
    assert "Inspected case version changed" in html.get_text()
    assert not html.find("form", {"data-call-command": True})
    assert "All-stage readiness" not in html.get_text()
    assert "Retained outgoing decisions" not in html.get_text()


@pytest.mark.parametrize(
    "change",
    [
        {"writable": False},
        {"case": replace(work().case, state="accepted")},
        {"case": replace(work().case, current_revision=False)},
        {"case": replace(work().case, stage=0)},
    ],
)
def test_no_fresh_form_for_nonwritable_case(page, change):
    page.source.return_value = work(**change)
    assert not soup(request(task="decide")).find("form", {"data-call-command": True})


def test_any_unready_stage_blocks_fresh_form_and_preview(page):
    page.facts.return_value = evidence(
        stages=(replace(evidence().stages[0], ready=False), evidence().stages[1])
    )
    assert not soup(request(task="decide")).find("form", {"data-call-command": True})
    assert request("post", values(), task="decide").status_code == 409
    page.command.assert_not_called()


def test_retained_messages_are_separate_from_recipient_receipt_state(page):
    message = queries.DecisionMessage(
        UUID(int=80),
        4,
        work().case.sealed_at,
        "waitlisted",
        "Stored <script>recipient</script>",
        acknowledgement_required=True,
    )
    page.messages.return_value = queries.DecisionMessages(5, (message,), 4)
    response = request(task="messages")
    html = soup(response)
    assert response.status_code == 200
    assert "Stored <script>recipient</script>" in html.get_text()
    assert not html.find("script", string="recipient")
    assert (
        html.find("a", string="Next page of retained decisions")["href"]
        == "?after=4&version=5"
    )
    assert page.messages.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_evidence"}
    )
    page.detail.assert_not_called()
    page.facts.assert_not_called()


def test_sensitive_or_render_time_revocation_discards_private_form(page):
    data = confirmed()
    page.command.side_effect = ProgrammeReviewConflictError
    page.source.side_effect = Denied
    response = request("post", data, task="decide")
    assert response.status_code == 404
    assert data["reason"] not in response.content.decode()
    page.source.side_effect = [work(), work(), Denied]
    response = request(task="decide")
    assert response.status_code == 404
    assert "Synthetic call" not in response.content.decode()


def test_each_content_section_has_independent_field_authority(page):
    def authorize(**kwargs):
        if kwargs["requested_fields"] != frozenset({"review_context"}):
            raise Denied

    page.authorize.side_effect = authorize
    html = soup(request())
    assert not html.find("a", string="Inspect evidence and compose a decision")
    assert not html.find("a", string="Read permitted answers")
    page.detail.side_effect = Denied
    assert request(task="answers").status_code == 404


@pytest.mark.parametrize(
    "data",
    [
        {"action": "automatic"},
        {"extra": "unknown"},
        {"text": ["one", "two"]},
        {"text": "x" * 12001},
        {"expected_version": "+5"},
        {"outcome": ""},
    ],
)
def test_closed_post_transport_and_forms_never_call_writer(page, data):
    assert request("post", values() | data, task="decide").status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "data",
    [
        {"after": "3"},
        {"version": "05"},
        {"after": "6", "version": "5"},
        {"version": ["5", "5"]},
        {"extra": "x"},
    ],
)
def test_closed_snapshot_transport_precedes_private_reads(page, data):
    assert request(task="evidence", values=data).status_code == 400
    page.source.assert_not_called()


def test_real_csrf_and_method_boundary(page):
    assert request("post", values(), task="decide", csrf=False).status_code == 403
    assert request("post", values(), task="overview").status_code == 400
    assert request("delete", task="decide").status_code == 405
    page.command.assert_not_called()


def test_exact_dormant_route_preserves_decider_purpose():
    path = (
        f"/admin/applications/programme-review/{UUID(int=2)}/{UUID(int=3)}/"
        f"{UUID(int=4)}/decisions/{UUID(int=20)}/decide/"
    )
    match = resolve(path, urlconf="maru.applications.programme_review_setup_urls")
    assert match.func is views.programme_decider
    assert match.kwargs["task"] == "decide"
