"""Real own-review forms and disclosure/retry boundaries without databases."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_reviewer_queries as queries
from maru.applications import programme_reviewer_views as views
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
    return replace(
        queries.ReviewerWork(
            replace(manager_context().case, stage=0, stage_code="content"),
            UUID(int=30),
            "pending",
            0,
            review_policy().stages[0],
            writable=True,
            has_scored=False,
        ),
        **changes,
    )


@pytest.fixture
def page(monkeypatch):
    source = Mock(return_value=context())
    queue = Mock(return_value=queries.ReviewerWorkPage((context(),), UUID(int=30)))
    authorize = Mock()
    detail = create_autospec(views.get_programme_review_detail)
    detail.return_value = ProgrammeReviewDetail(UUID(int=20), 5, None, None, None, None)
    command = create_autospec(apply_programme_review_command)
    command.return_value = ProgrammeReviewResult(
        UUID(int=70), UUID(int=30), UUID(int=20), 6, replayed=False
    )
    monkeypatch.setattr(queries, "get_programme_reviewer_work", source)
    monkeypatch.setattr(queries, "list_programme_reviewer_work", queue)
    monkeypatch.setattr(views, "authorize_programme_review_scope", authorize)
    monkeypatch.setattr(views, "get_programme_review_detail", detail)
    monkeypatch.setattr(views, "apply_programme_review_command", command)
    return SimpleNamespace(
        source=source, queue=queue, authorize=authorize, detail=detail, command=command
    )


def request(method="get", values=None, *, task="overview", queue=False, csrf=True):
    req = getattr(RequestFactory(), method)("/", data=values or {})
    req.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=True)
    req._dont_enforce_csrf_checks = csrf
    return views.programme_reviewer_work(
        req,
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        None if queue else UUID(int=20),
        None if queue else UUID(int=30),
        task,
    )


def proof(task="clear"):
    values = {
        "action": task,
        "expected_version": "5",
        "retry_key": str(UUID(int=60)),
        "reason": "My deliberate private rationale.",
        "confirm": "on",
    }
    if task == "score":
        values |= {
            f"score_{row.code}": str(row.minimum) for row in context().rubric.criteria
        }
    if task == "discuss":
        values["text"] = "Separate peer discussion."
    return values


def test_own_discovery_and_pending_context_expose_no_answers_or_peer_roster(page):
    response = request(queue=True, values={"after": str(UUID(int=29))})
    html = soup(response)
    assert response.status_code == 200
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert not html.find("script", string="attack")
    assert page.queue.call_args.kwargs["after_id"] == UUID(int=29)
    assert html.find("a", string="Next page of my assignments")
    html = soup(request())
    assert html.find("a", string="Declare no conflict of interest")
    assert not html.find("a", string="Read permitted answers")
    assert not html.find("a", string="Submit a complete independent rubric")
    assert "Declare your own conflict status" in html.get_text()
    page.detail.assert_not_called()
    page.command.assert_not_called()


@pytest.mark.parametrize("task", ["clear", "recuse", "score", "discuss"])
def test_exact_action_uses_original_assignment_version_retry_and_separate_text(
    page, task
):
    response = request("post", proof(task), task=task)
    assert response.status_code == 200
    assert "Review action confirmed" in soup(response).get_text()
    assert not soup(response).find("form", {"data-call-command": True})
    kwargs = page.command.call_args.kwargs
    assert kwargs["command"].action == views._ACTIONS[task]
    assert kwargs["command"].reference_id == UUID(int=30)
    assert kwargs["command"].target_id == UUID(int=20)
    assert kwargs["expected_version"] == 5
    assert kwargs["retry_key"] == UUID(int=60)
    assert kwargs["reason"] == proof(task)["reason"]
    assert kwargs["command"].text == proof(task).get("text", "")
    assert kwargs["source_channel"] == "programme-reviewer-work"
    page.detail.assert_not_called()


@pytest.mark.parametrize("state", ["removed", "recused", "active", "pending"])
@pytest.mark.parametrize("task", ["clear", "recuse", "score", "discuss"])
def test_old_request_reaches_receipt_after_stage_source_planning_and_assignment_changes(
    page, state, task
):
    page.source.return_value = context(
        state=state,
        writable=False,
        case=replace(
            context().case,
            stage=1,
            stage_code="later",
            version=30,
            state="accepted",
            current_revision=False,
        ),
    )
    page.detail.side_effect = Denied
    page.command.return_value = replace(page.command.return_value, replayed=True)
    response = request("post", proof(task), task=task)
    assert response.status_code == 200
    assert "original receipt was recovered" in soup(response).get_text()
    assert page.command.call_args.kwargs["expected_version"] == 5
    if task == "score":
        assert page.command.call_args.kwargs["command"].scores == tuple(
            (row.code, row.minimum) for row in context().rubric.criteria
        )
    page.detail.assert_not_called()


@pytest.mark.parametrize("task", ["answers", "context", "evidence"])
def test_pending_or_historical_assignment_cannot_reach_content_owner(page, task):
    assert request(task=task).status_code == 404
    page.source.return_value = context(state="active", stage=1)
    assert request(task=task).status_code == 404
    page.detail.assert_not_called()


def test_active_content_field_ceiling_is_independent_and_revalidated(page):
    page.source.return_value = context(state="active")
    page.detail.return_value = replace(
        page.detail.return_value,
        answers_json=json.dumps(
            [
                {
                    "label": "Title <script>attack</script>",
                    "type": "short_text",
                    "classification": "C2",
                    "value": "Answer <script>secret</script>",
                }
            ]
        ),
    )
    response = request(task="answers")
    html = soup(response)
    assert response.status_code == 200
    assert "Answer <script>secret</script>" in html.get_text()
    assert not html.find("script", string="secret")
    assert page.detail.call_count == 3
    assert page.detail.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_answers"}
    )
    page.detail.side_effect = Denied
    response = request(task="answers")
    assert response.status_code == 404
    assert b"Answer" not in response.content


def test_independent_field_nav_does_not_imply_answer_or_evidence_grants(page):
    page.source.return_value = context(state="active")

    def authorize(**kwargs):
        if kwargs["requested_fields"] != frozenset({"review_context"}):
            raise Denied

    page.authorize.side_effect = authorize
    html = soup(request())
    assert html.find("a", string="Read permitted context")
    assert not html.find("a", string="Read permitted answers")
    assert not html.find("a", string="Read permitted evidence")


@pytest.mark.parametrize("changed", ["source", "detail"])
def test_render_time_revocation_discards_private_content(page, monkeypatch, changed):
    page.source.return_value = context(state="active")
    page.detail.return_value = replace(
        page.detail.return_value,
        answers_json=json.dumps(
            [
                {
                    "label": "Secret label",
                    "type": "short_text",
                    "classification": "C3",
                    "value": "Secret answer",
                }
            ]
        ),
    )
    original = views.render_to_string

    def render(*args, **kwargs):
        result = original(*args, **kwargs)
        getattr(page, changed).side_effect = Denied
        return result

    monkeypatch.setattr(views, "render_to_string", render)
    response = request(task="answers")
    assert response.status_code == 404
    assert b"Secret" not in response.content


def test_evidence_page_uses_only_filtered_owner_projection_and_exclusive_cursor(page):
    page.source.return_value = context(state="active", has_scored=True)
    page.detail.return_value = replace(
        page.detail.return_value,
        evidence_json=json.dumps(
            [
                {
                    "version": 4,
                    "action": "scored",
                    "payload": {"scores": {"quality": 4}},
                    "reason": "My rationale",
                },
                {
                    "version": 5,
                    "action": "discussed",
                    "payload": {"text": "Permitted peer discussion"},
                },
            ]
        ),
        next_evidence_version=5,
    )
    response = request(task="evidence", values={"after": "3"})
    assert response.status_code == 200
    html = soup(response)
    assert "My rationale" in html.get_text()
    assert "Permitted peer discussion" in html.get_text()
    assert html.find("a", string="Next page of permitted history")["href"] == "?after=5"
    assert page.detail.call_args.kwargs["after_version"] == 3
    assert page.detail.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_evidence"}
    )


@pytest.mark.parametrize(
    ("has_scored", "enabled", "offered"),
    [(False, True, False), (True, False, False), (True, True, True)],
)
def test_fresh_discussion_requires_both_policy_and_own_score(
    page, has_scored, enabled, offered
):
    page.source.return_value = context(
        state="active",
        has_scored=has_scored,
        rubric=replace(context().rubric, discussion=enabled),
    )
    assert bool(soup(request()).find("a", string="Add peer discussion")) == offered
    assert (
        bool(soup(request(task="discuss")).find("form", {"data-call-command": True}))
        == offered
    )


def test_fresh_score_has_no_defaults_and_late_recusal_remains_distinct(page):
    page.source.return_value = context(state="active")
    html = soup(request(task="score"))
    visible = [
        field.get("name")
        for field in html.select(
            "form[data-call-command] input:not([type=hidden]), "
            "form[data-call-command] textarea"
        )
    ]
    assert visible == [
        *(f"score_{row.code}" for row in context().rubric.criteria),
        "reason",
        "confirm",
    ]
    for row in context().rubric.criteria:
        field = html.find("input", {"name": f"score_{row.code}"})
        assert not field.get("value")
        assert field["min"] == str(row.minimum)
        assert field["max"] == str(row.maximum)
    assert not html.find("input", {"name": "confirm"}).has_attr("checked")
    page.source.return_value = context(
        case=replace(context().case, stage=1, state="accepted")
    )
    assert soup(request()).find("a", string="Recuse myself with a reason")
    assert not soup(request()).find("a", string="Declare no conflict of interest")


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValidationError("Rejected input"), 400),
        (ProgrammeReviewConflictError(), 409),
        (DatabaseError(), 503),
    ],
)
def test_failure_retains_complete_original_form_without_rebasing(page, error, status):
    page.command.side_effect = error
    page.source.return_value = context(case=replace(context().case, version=17))
    response = request("post", proof("score"), task="score")
    assert response.status_code == status
    assert hidden(response)["expected_version"] == "5"
    assert hidden(response)["retry_key"] == str(UUID(int=60))
    html = soup(response)
    assert (
        html.find("textarea", {"name": "reason"}).get_text().strip()
        == proof()["reason"]
    )
    assert html.find("input", {"name": "confirm"}).has_attr("checked")
    assert html.find("div", {"role": "alert", "tabindex": "-1"})
    for row in context().rubric.criteria:
        assert html.find("input", {"name": f"score_{row.code}"})["value"] == str(
            row.minimum
        )


@pytest.mark.parametrize(
    "value", ["", "-1", "10001", "1.0", "1e0", "true", " 1 ", "01", "\u0661"]
)
def test_incomplete_or_noncanonical_scores_never_reach_owner(page, value):
    criterion = context().rubric.criteria[0]
    response = request(
        "post", proof("score") | {f"score_{criterion.code}": value}, task="score"
    )
    assert response.status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown": "x"},
        {"reason": ""},
        {"confirm": ""},
        {"action": "decide"},
        {"expected_version": "0"},
        {"retry_key": "bad"},
        {"score_peer": "5"},
        {"reason": ["first", "second"]},
        {"reason": "x" * 12001},
    ],
)
def test_closed_post_rejects_unknown_missing_duplicate_and_overflow(page, changes):
    assert request("post", proof() | changes, task="clear").status_code == 400
    page.command.assert_not_called()


def test_real_csrf_protection_and_production_route_containment(page):
    assert request("post", proof(), task="clear", csrf=False).status_code == 403
    page.command.assert_not_called()
    route = (
        f"/admin/applications/programme-review/{UUID(int=2)}/{UUID(int=3)}/"
        f"{UUID(int=4)}/mine/{UUID(int=20)}/{UUID(int=30)}/score/"
    )
    assert (
        resolve(route, urlconf="maru.applications.programme_review_setup_urls").kwargs[
            "task"
        ]
        == "score"
    )
    try:
        production = resolve(route, urlconf="maru.urls")
    except Resolver404:
        pass
    else:
        assert production.func != views.programme_reviewer_work
        assert production.url_name != "programme-review-own-score"


@pytest.mark.parametrize(
    "value", ["0", "-1", "01", "1.0", "\u0661", "9223372036854775808", ["1", "2"]]
)
def test_evidence_cursor_is_closed_bounded_and_canonical(page, value):
    assert request(task="evidence", values={"after": value}).status_code == 400
    page.detail.assert_not_called()


def test_denied_and_unavailable_metadata_never_load_content_or_write(page):
    for error, status in ((Denied(), 404), (DatabaseError(), 503)):
        page.source.side_effect = error
        assert request("post", proof(), task="clear").status_code == status
    page.command.assert_not_called()
    page.detail.assert_not_called()


@pytest.mark.parametrize("kind", ["safe_file", "person_reference", "domain_reference"])
def test_files_and_references_never_become_unsafe_links_or_identity_lookup(kind):
    assert "no download or person lookup" in views._answer_text(
        {"type": kind, "value": "private-reference"}
    )
    assert "private-reference" not in views._answer_text(
        {"type": kind, "value": "private-reference"}
    )
