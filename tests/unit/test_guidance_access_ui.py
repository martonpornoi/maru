"""Guides access pages preserve purpose authority and actual second-person decisions."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory
from django.utils import timezone

from maru.authorization import guidance_readiness, provenance_readiness
from maru.authorization.guidance_access_queries import (
    GuidanceAccessAssignment,
    GuidanceAccessPerson,
    GuidanceAccessRequestPage,
    GuidanceAccessRequestView,
    GuidanceAccessWorkspace,
)
from maru.authorization.guidance_catalog import GUIDANCE_ROLE_RECIPES
from maru.events.knowledge_workspace_queries import KnowledgeWorkspaceReference
from maru.identity.models import Account
from maru.knowledge import access_views as views
from maru.knowledge.access_forms import GuidanceAccessRequestForm
from maru.knowledge.errors import GuidanceDeniedError


@pytest.fixture
def access_page(monkeypatch):
    first = GuidanceAccessPerson(UUID(int=21), "Synthetic Fox")
    second = GuidanceAccessPerson(UUID(int=22), "Synthetic Lynx")
    reader = GuidanceAccessPerson(UUID(int=23), "Synthetic Reader")
    scope = KnowledgeWorkspaceReference(
        UUID(int=1),
        UUID(int=2),
        "Synthetic organizers",
        "Synthetic convention",
        "Synthetic 2027",
        "Europe/Budapest",
        "announcements_guidance",
        1,
    )
    assignment = GuidanceAccessAssignment(
        UUID(int=4),
        reader,
        "guidance-reader",
        "Read approved Guidance",
        None,
        current=True,
        revoked=False,
    )
    workspace = GuidanceAccessWorkspace(
        scope, (GUIDANCE_ROLE_RECIPES["guidance-reader"],), (second,), (assignment,)
    )
    proposal = GuidanceAccessRequestView(
        UUID(int=5),
        "a" * 64,
        scope.organization_id,
        scope.edition_id,
        scope.edition_name,
        first,
        second,
        reader,
        "guidance-reader",
        "Read approved Guidance",
        ("knowledge.view_current",),
        "Read synthetic FAQs",
        None,
        datetime(2027, 1, 1, tzinfo=UTC),
        "waiting",
        can_answer=True,
        own_answer=None,
        assignment_id=None,
    )
    workspace_query, request_query = (
        Mock(return_value=workspace),
        Mock(return_value=proposal),
    )
    monkeypatch.setattr(views, "load_guidance_access_workspace", workspace_query)
    monkeypatch.setattr(views, "load_guidance_access_request", request_query)
    monkeypatch.setattr(
        views,
        "list_my_guidance_access_requests_page",
        Mock(return_value=GuidanceAccessRequestPage((proposal,), None)),
    )
    monkeypatch.setattr(
        views, "authorize_guidance_scope", Mock(side_effect=GuidanceDeniedError)
    )
    monkeypatch.setattr(views.admin.site, "each_context", lambda _request: {})
    render = Mock(return_value="COMPLETE AUTHORIZED ACCESS PAGE")
    monkeypatch.setattr(views, "render_to_string", render)
    commands = {}
    for name in (
        "request_guidance_access",
        "respond_to_guidance_access",
        "revoke_guidance_access",
    ):
        commands[name] = Mock(
            return_value=SimpleNamespace(request_id=proposal.request_id)
        )
        monkeypatch.setattr(views.commands, name, commands[name])
    return SimpleNamespace(
        workspace=workspace,
        proposal=proposal,
        assignment=assignment,
        workspace_query=workspace_query,
        request_query=request_query,
        commands=commands,
        render=render,
    )


def request_data(**changes):
    data = {
        "recipient_email": "synthetic-reader@example.invalid",
        "recipe_code": "guidance-reader",
        "approver_id": str(UUID(int=22)),
        "reason": "Read synthetic FAQs",
        "expires_at": "",
        "confirmed": "on",
        "idempotency_key": str(UUID(int=6)),
    }
    data.update(changes)
    return data


def call(access_page, action="workspace", data=None, query="", *, csrf=False):
    request = (
        RequestFactory().get("/admin/guidance-access/" + query)
        if data is None
        else RequestFactory().post("/admin/guidance-access/" + query, data=data)
    )
    request.user = Account(
        id=UUID(int=21), email="synthetic-fox@example.invalid", is_active=True
    )
    request._dont_enforce_csrf_checks = not csrf
    request.session = {}
    request._messages = FallbackStorage(request)
    access_page.actor = request.user
    return views.guidance_access_workspace(
        request,
        access_page.workspace.scope.organization_id,
        access_page.workspace.scope.edition_id,
        action=action,
        request_id=access_page.proposal.request_id,
        assignment_id=access_page.assignment.assignment_id,
    )


def test_access_choices_never_offer_controller_or_an_implicit_approval(access_page):
    form = GuidanceAccessRequestForm(workspace=access_page.workspace)
    assert form["recipe_code"].value() is None
    assert form["approver_id"].value() is None
    assert "guidance-access-controller" not in dict(form.fields["recipe_code"].choices)
    attempted = GuidanceAccessRequestForm(
        request_data(recipe_code="guidance-access-controller"),
        workspace=access_page.workspace,
    )
    assert not attempted.is_valid()


def test_access_end_time_uses_explicit_event_timezone(access_page):
    with timezone.override("Europe/Budapest"):
        form = GuidanceAccessRequestForm(
            request_data(expires_at="2027-06-18T12:00"), workspace=access_page.workspace
        )
        assert form.is_valid(), form.errors
        end = form.cleaned_data["expires_at"]
    assert end.astimezone(UTC).hour == 10


def test_access_admission_precedes_email_parsing_and_command(access_page):
    access_page.workspace_query.side_effect = PermissionDenied
    response = call(access_page, "new", request_data(), query="?unowned=1")
    assert response.status_code == 404
    access_page.commands["request_guidance_access"].assert_not_called()
    access_page.render.assert_not_called()


def test_content_reading_is_not_required_for_independent_access_management(access_page):
    response = call(access_page)
    assert response.status_code == 200
    assert access_page.render.call_args.args[1]["content_url"] == ""


def test_access_request_passes_actual_actor_exact_scope_and_named_approver(access_page):
    response = call(access_page, "new", request_data())
    assert response.status_code == 302
    sent = access_page.commands["request_guidance_access"].call_args.kwargs
    assert sent["actor"] is access_page.actor
    assert sent["organization_id"] == access_page.workspace.scope.organization_id
    assert sent["edition_id"] == access_page.workspace.scope.edition_id
    assert sent["approver_id"] == UUID(int=22)
    assert sent["recipe_code"] == "guidance-reader"
    access_page.commands["respond_to_guidance_access"].assert_not_called()


def test_access_retry_keeps_original_approver_and_request_key(access_page):
    access_page.workspace_query.return_value = replace(
        access_page.workspace, approvers=()
    )
    access_page.commands["request_guidance_access"].side_effect = ValidationError(
        "The original responsibilities changed."
    )
    response = call(access_page, "new", request_data())
    assert response.status_code == 409
    sent = access_page.commands["request_guidance_access"].call_args.kwargs
    assert sent["idempotency_key"] == UUID(int=6)
    assert sent["approver_id"] == UUID(int=22)


def test_answer_replay_retains_original_digest_and_does_not_preempt_owner(access_page):
    access_page.request_query.return_value = replace(
        access_page.proposal, state="accepted", can_answer=False, own_answer=True
    )
    response = call(
        access_page,
        "answer",
        {"expected_digest": "b" * 64, "decision": "accept", "confirmed": "on"},
    )
    assert response.status_code == 302
    assert (
        access_page.commands["respond_to_guidance_access"].call_args.kwargs[
            "expected_digest"
        ]
        == "b" * 64
    )


def test_revoke_locator_cannot_remove_an_assignment_from_another_event(access_page):
    access_page.workspace_query.return_value = replace(
        access_page.workspace, assignments=()
    )
    response = call(
        access_page, "revoke", {"reason": "Synthetic removal", "confirmed": "on"}
    )
    assert response.status_code == 404
    access_page.commands["revoke_guidance_access"].assert_not_called()


def test_get_and_missing_csrf_cannot_grant_or_remove_access(access_page):
    assert call(access_page, "revoke").status_code == 200
    assert call(access_page, "new", request_data(), csrf=True).status_code == 403
    for command in access_page.commands.values():
        command.assert_not_called()


def test_final_access_change_releases_no_previously_rendered_labels(access_page):
    access_page.workspace_query.side_effect = [
        access_page.workspace,
        replace(access_page.workspace, approvers=()),
    ]
    response = call(access_page)
    assert response.status_code == 409
    assert b"COMPLETE AUTHORIZED ACCESS PAGE" not in response.content


@pytest.mark.parametrize("failure_at", [1, 2])
def test_history_integrity_loss_returns_unavailable_without_rendered_labels(
    access_page, monkeypatch, failure_at
):
    native = Mock(side_effect=[True] * (failure_at - 1) + [False])
    monkeypatch.setattr(
        guidance_readiness, "guidance_authority_database_integrity_is_ready", native
    )
    monkeypatch.setattr(
        provenance_readiness,
        "authority_provenance_runtime_contract_is_ready",
        lambda: True,
    )

    def history(**_values):
        guidance_readiness.require_guidance_authority_integrity()
        return GuidanceAccessRequestPage((access_page.proposal,), None)

    monkeypatch.setattr(views, "list_my_guidance_access_requests_page", history)
    response = call(access_page, "tasks")
    assert response.status_code == 503
    assert b"COMPLETE AUTHORIZED ACCESS PAGE" not in response.content
    assert b"protection" not in response.content
    assert native.call_count == failure_at


def test_access_history_preserves_cursor_and_empty_continuation(
    access_page, monkeypatch
):
    query = Mock(return_value=GuidanceAccessRequestPage((), "signed-next"))
    monkeypatch.setattr(views, "list_my_guidance_access_requests_page", query)
    response = call(access_page, "tasks", query="?cursor=original-token")
    assert response.status_code == 200
    assert query.call_count == 2
    assert all(
        item.kwargs["cursor"] == "original-token" for item in query.call_args_list
    )
    context = access_page.render.call_args.args[1]
    assert context["task_rows"] == ()
    assert context["next_url"].endswith("?cursor=signed-next")
