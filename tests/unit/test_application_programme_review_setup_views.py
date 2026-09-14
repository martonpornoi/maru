"""Real review setup forms/templates with database-forbidden owner boundaries."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec, patch
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.applications import programme_review_setup_queries as queries
from maru.applications import programme_review_setup_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_commands import apply_programme_review_command
from maru.applications.programme_review_rules import ProgrammeReviewConflictError
from tests.unit.test_application_programme_review_inputs import review_policy
from tests.unit.test_application_programme_review_setup_forms import proof, stage_data


def context():
    return queries.ReviewSetupContext(
        queries.ReviewSetupCall(
            UUID(int=20),
            "Synthetic call <script>attack</script>",
            "programme",
            "active",
            1,
        ),
        (
            queries.ReviewSetupQuestion(
                "session-title", "Session title", "short_text", "C2"
            ),
        ),
        4,
        writable=True,
    )


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
    monkeypatch.setattr(
        views, "can_manage_programme_review_cases", Mock(return_value=False)
    )
    source = Mock(return_value=context())
    calls = Mock(
        return_value=queries.ReviewSetupCallPage((context().call,), UUID(int=20))
    )
    policy = Mock(
        return_value=queries.ReviewSetupPolicy(
            UUID(int=30),
            UUID(int=20),
            3,
            datetime(2026, 9, 1, tzinfo=UTC),
            "Deliberate policy reason",
            review_policy(),
        )
    )
    authorize = Mock()
    command = create_autospec(apply_programme_review_command)
    command.return_value = SimpleNamespace(version=5)
    monkeypatch.setattr(queries, "get_programme_review_setup", source)
    monkeypatch.setattr(queries, "list_programme_review_setup_calls", calls)
    monkeypatch.setattr(queries, "get_programme_review_setup_policy", policy)
    monkeypatch.setattr(views, "authorize_programme_review_scope", authorize)
    monkeypatch.setattr(views, "apply_programme_review_command", command)
    return SimpleNamespace(
        source=source, calls=calls, policy=policy, authorize=authorize, command=command
    )


def request(method="get", values=None, *, call=True, version=None, csrf=True, url="/"):
    req = getattr(RequestFactory(), method)(url, data=values or {})
    req.user = SimpleNamespace(pk=UUID(int=1), is_authenticated=True)
    req._dont_enforce_csrf_checks = csrf
    return views.programme_review_setup(
        req,
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        UUID(int=20) if call else None,
        version,
    )


def soup(response):
    return BeautifulSoup(response.content, "html.parser")


def hidden(response):
    return {
        field["name"]: field.get("value", "")
        for field in soup(response).select('form input[type="hidden"]')
        if field["name"] != "csrfmiddlewaretoken"
    }


def test_case_manager_navigation_is_separate_and_revocation_discards_setup(
    page, monkeypatch
):
    admission = Mock(return_value=True)
    monkeypatch.setattr(views, "can_manage_programme_review_cases", admission)
    assert soup(request(call=False)).find(
        "a", string="Manage review cases and named reviewers"
    )
    admission.side_effect = [True, False]
    response = request(call=False)
    assert response.status_code == 404
    assert b"Synthetic" not in response.content


def test_call_discovery_is_labelled_bounded_and_independently_authorized(page):
    response = request(call=False)
    assert response.status_code == 200
    html = soup(response)
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert not html.find("a", string="Manage review cases and named reviewers")
    assert html.find("script", string="attack") is None
    assert html.find("a", string="Next page of calls")["href"].endswith(
        f"?after={UUID(int=20)}"
    )
    assert page.calls.call_count == 3
    scope = page.calls.call_args.kwargs["request"]
    assert (
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        scope.department_id,
    ) == tuple(UUID(int=index) for index in range(1, 5))
    assert scope.requested_fields == frozenset({"review_setup"})
    page.command.assert_not_called()


def test_entire_explicit_composer_journey_writes_only_at_confirmed_save(page):
    response = request()
    assert response.status_code == 200
    values = hidden(response)
    original = values.copy()
    response = request("post", values | {"action": "add-stage"})
    assert response.status_code == 200
    assert len(soup(response).find_all("fieldset")) >= 16
    assert len(soup(response).select("form details[open]")) == 1
    stage = stage_data() | hidden(response) | {"action": "keep-stage"}
    response = request("post", stage)
    assert response.status_code == 200
    values = hidden(response)
    assert json.loads(values["proposed"])["stages"][0]["code"] == "content"
    response = request("post", values | {"action": "templates"})
    values = hidden(response)
    for item in review_policy().templates:
        values[f"{item.outcome}_text"] = item.text
        values[f"{item.outcome}_receipt"] = "yes"
    response = request("post", values | {"action": "keep-templates"})
    assert response.status_code == 200
    response = request("post", hidden(response) | {"action": "confirm"})
    assert response.status_code == 200
    assert "Session title" in soup(response).get_text()
    page.command.assert_not_called()
    values = hidden(response)
    assert values["retry_key"] == original["retry_key"]
    assert values["expected_version"] == "4"
    response = request(
        "post",
        values
        | {"action": "save", "confirm": "on", "reason": "Independent review policy"},
    )
    assert response.status_code == 302
    assert response["Location"].endswith(f"{UUID(int=20)}/policies/5/")
    page.command.assert_called_once()
    arguments = page.command.call_args.kwargs
    assert arguments["command"].target_id == UUID(int=20)
    assert arguments["command"].policy.stages[0].discussion is False
    assert arguments["expected_version"] == 4
    assert str(arguments["retry_key"]) == original["retry_key"]
    assert arguments["department_id"] == UUID(int=4)


def test_stale_save_preserves_input_and_requires_deliberate_refresh(page):
    values = proof(action="save", reason="Original reason", confirm="on")
    page.command.side_effect = ProgrammeReviewConflictError
    response = request("post", values)
    assert response.status_code == 409
    assert soup(response).find(attrs={"role": "alert"}) is not None
    retained = hidden(response)
    assert retained["proposed"] == values["proposed"]
    assert retained["retry_key"] == values["retry_key"]
    assert retained["expected_version"] == "4"
    page.source.return_value = replace(context(), policy_version=9)
    response = request(
        "post",
        retained | {"action": "back", "reason": "Original reason", "confirm": "on"},
    )
    assert response.status_code == 200
    retained = hidden(response)
    assert retained["expected_version"] == "4"
    response = request("post", retained | {"action": "refresh"})
    refreshed = hidden(response)
    assert refreshed["expected_version"] == "9"
    assert refreshed["retry_key"] != retained["retry_key"]
    assert json.loads(refreshed["proposed"]) == json.loads(retained["proposed"])
    page.command.assert_called_once()


def test_partial_optional_criterion_is_open_with_linked_recoverable_error(page):
    response = request(
        "post", stage_data(action="keep-stage", criterion_5_label="Partial criterion")
    )
    assert response.status_code == 400
    html = soup(response)
    partial = html.find("input", attrs={"name": "criterion_5_label"})
    assert partial["value"] == "Partial criterion"
    assert partial.find_parent("details").has_attr("open")
    assert html.find(attrs={"role": "alert"}) is not None
    page.command.assert_not_called()


def test_stage_reordering_editing_and_removal_preserve_original_intent(page):
    values = proof()
    proposed = json.loads(values["proposed"])
    proposed["stages"].append(proposed["stages"][0] | {"code": "delivery"})
    values["proposed"] = json.dumps(proposed)
    response = request("post", values | {"action": "up:1"})
    retained = hidden(response)
    assert json.loads(retained["proposed"])["stages"][0]["code"] == "delivery"
    assert retained["retry_key"] == values["retry_key"]
    response = request("post", retained | {"action": "edit:0"})
    assert soup(response).find("input", attrs={"name": "code"})["value"] == "delivery"
    response = request("post", retained | {"action": "remove:1"})
    assert len(json.loads(hidden(response)["proposed"])["stages"]) == 1
    page.command.assert_not_called()


@pytest.mark.parametrize("status", ["draft", "unknown"])
def test_unfrozen_or_unknown_call_cannot_compose_or_save(page, status):
    page.source.return_value = replace(
        context(), call=replace(context().call, status=status)
    )
    assert soup(request()).find("form", attrs={"data-call-command": True}) is None
    assert (
        request("post", proof(action="save", reason="Reason", confirm="on")).status_code
        == 404
    )
    page.command.assert_not_called()


def test_planning_closed_history_is_read_only_but_same_intent_reaches_canonical_replay(
    page,
):
    page.source.return_value = replace(context(), writable=False)
    assert soup(request()).find("form", attrs={"data-call-command": True}) is None
    assert request("post", proof(action="add-stage")).status_code == 404
    page.command.assert_not_called()
    assert (
        request("post", proof(action="save", reason="Reason", confirm="on")).status_code
        == 302
    )
    page.command.assert_called_once()


def test_policy_history_exposes_reason_and_explicit_neighbors_without_write(page):
    response = request(version=3)
    html = soup(response)
    assert response.status_code == 200
    assert "Deliberate policy reason" in html.get_text()
    assert html.find("a", string="Previous policy version")["href"].endswith(
        "/policies/2/"
    )
    assert html.find("a", string="Next policy version")["href"].endswith("/policies/4/")
    assert html.find("form", attrs={"data-call-command": True}) is None
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        proof(action="save", reason="Reason", confirm="on", organization_id="foreign"),
        proof(action="keep-stage", stage_index="8"),
        proof(action="unknown"),
        proof(action="edit:8"),
        proof(action="down:0"),
        proof(
            action="add-stage", upload=SimpleUploadedFile("fixture.txt", b"synthetic")
        ),
    ],
)
def test_malformed_or_extra_transport_never_writes(page, values):
    assert request("post", values).status_code == 400
    page.command.assert_not_called()


def test_csrf_and_method_guards_are_real(page):
    assert (
        request(
            "post", proof(action="save", reason="Reason", confirm="on"), csrf=False
        ).status_code
        == 403
    )
    assert request("put").status_code == 405
    page.command.assert_not_called()


@pytest.mark.parametrize("target", ["source", "calls", "policy"])
def test_late_render_revocation_discards_prepared_configuration(page, target):
    mock = getattr(page, target)
    mock.side_effect = [mock.return_value, mock.return_value, Denied()]
    response = request(
        call=target != "calls", version=3 if target == "policy" else None
    )
    assert response.status_code == 404
    assert b"Synthetic call" not in response.content


def test_dependency_failure_and_empty_discovery_are_truthful(page):
    page.calls.return_value = queries.ReviewSetupCallPage((), None)
    assert "No calls" in soup(request(call=False)).get_text()
    page.source.side_effect = DatabaseError
    response = request()
    assert response.status_code == 503
    assert b"Synthetic call" not in response.content


def test_review_setup_routes_remain_absent_from_production():
    url = (
        f"/admin/applications/programme-review/{UUID(int=2)}/"
        f"{UUID(int=3)}/{UUID(int=4)}/"
    )
    assert (
        resolve(url, urlconf="maru.applications.programme_review_setup_urls").url_name
        == "programme-review-setup"
    )
    try:
        match = resolve(url)
    except Resolver404:
        return
    assert match.func is not views.programme_review_setup
