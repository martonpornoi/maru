"""Native setup decisions preserve actual actors, exact previews and safe handoffs."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import QueryDict
from django.test import RequestFactory

from maru.events import guidance_activation_views as views
from maru.events import guidance_setup_views as setup_views
from maru.events.guidance_activation_forms import GuidanceActivationProposalForm
from maru.events.guidance_activation_queries import (
    GuidanceActivationRequestView,
    GuidanceActivationStart,
    GuidanceOperatorChoice,
)
from maru.events.guidance_setup_queries import GuidanceSetupChoices
from maru.identity.models import Account
from maru.knowledge.errors import GuidanceDeniedError
from tests.unit.test_guidance_setup_forms import setup_data


@pytest.fixture
def activation(monkeypatch):
    first = GuidanceOperatorChoice(UUID(int=21), "Synthetic Fox")
    second = GuidanceOperatorChoice(UUID(int=22), "Synthetic Lynx")
    start = GuidanceActivationStart(
        UUID(int=1),
        "synthetic",
        "Synthetic organizers",
        UUID(int=2),
        "Synthetic 2027",
        3,
        UUID(int=4),
        "active",
        foundation_ready=True,
        can_propose=True,
        guidance_ready=False,
        source_profile_code="announcements_only",
        target_profile_code="announcements_guidance",
        purpose="initial",
        operators=(first, second),
    )
    proposal = GuidanceActivationRequestView(
        UUID(int=5),
        1,
        "a" * 64,
        start.organization_id,
        start.organization_slug,
        start.organization_name,
        start.edition_id,
        start.edition_name,
        first,
        second,
        start.source_profile_code,
        start.target_profile_code,
        "initial",
        "Prepare synthetic FAQs",
        datetime(2027, 1, 1, tzinfo=UTC),
        "waiting",
        None,
        0,
        can_answer=True,
        can_apply=False,
    )
    start_query = Mock(return_value=start)
    detail_query = Mock(return_value=proposal)
    task_query = Mock(return_value=(proposal,))
    monkeypatch.setattr(views, "load_guidance_activation_start", start_query)
    monkeypatch.setattr(views, "load_guidance_activation_request", detail_query)
    monkeypatch.setattr(views, "list_my_guidance_activation_requests", task_query)
    commands = {}
    for name in (
        "propose_guidance_activation",
        "respond_to_guidance_activation",
        "apply_guidance_activation",
    ):
        commands[name] = Mock(
            return_value=SimpleNamespace(request_id=proposal.request_id)
        )
        monkeypatch.setattr(views.commands, name, commands[name])
    monkeypatch.setattr(views.admin.site, "each_context", lambda _request: {})
    monkeypatch.setattr(
        views, "authorize_guidance_scope", Mock(side_effect=GuidanceDeniedError)
    )
    render = Mock(return_value="COMPLETE AUTHORIZED PAGE")
    monkeypatch.setattr(views, "render_to_string", render)
    return SimpleNamespace(
        start=start,
        proposal=proposal,
        start_query=start_query,
        detail_query=detail_query,
        task_query=task_query,
        commands=commands,
        render=render,
    )


def activation_call(activation, action="detail", data=None, query="", *, csrf=False):
    path = "/admin/guidance-setup/"
    request = (
        RequestFactory().get(path + query)
        if data is None
        else RequestFactory().post(path + query, data=data)
    )
    request.user = Account(
        id=UUID(int=21), email="synthetic-fox@example.invalid", is_active=True
    )
    request._dont_enforce_csrf_checks = not csrf
    activation.actor = request.user
    return views.guidance_activation_workspace(
        request,
        action=action,
        organization_id=activation.start.organization_id,
        edition_id=activation.start.edition_id,
        request_id=activation.proposal.request_id,
    )


def proposal_data(**changes):
    data = {
        "operator_a_id": str(UUID(int=21)),
        "operator_b_id": str(UUID(int=22)),
        "expected_edition_version": "3",
        "idempotency_key": str(UUID(int=6)),
        "reason": "Prepare synthetic FAQs",
        "confirmed": "on",
    }
    data.update(changes)
    return data


def test_proposal_has_no_default_people_and_rejects_self_approval_pair(activation):
    blank = GuidanceActivationProposalForm(operators=activation.start.operators)
    assert blank["operator_a_id"].value() is None
    assert blank["operator_b_id"].value() is None
    form = GuidanceActivationProposalForm(
        proposal_data(operator_b_id=str(UUID(int=21))),
        operators=activation.start.operators,
    )
    assert not form.is_valid()
    assert "operator_b_id" in form.errors


def test_original_lost_choice_can_reach_owner_retry_without_invented_label(activation):
    form = GuidanceActivationProposalForm(proposal_data(), operators=())
    assert form.is_valid(), form.errors
    assert form.operator_ids() == (UUID(int=21), UUID(int=22))
    assert "Previously selected person (no longer available)" in str(form)
    assert "Synthetic Fox" not in str(form)


def test_activation_scope_denial_precedes_transport_labels_and_commands(activation):
    activation.start_query.side_effect = PermissionDenied
    response = activation_call(activation, "start", query="?unowned=1")
    assert response.status_code == 404
    activation.render.assert_not_called()
    for command in activation.commands.values():
        command.assert_not_called()


def test_inactive_foundation_shows_handoff_without_content_or_proposal_form(activation):
    activation.start_query.return_value = replace(
        activation.start,
        foundation_ready=False,
        can_propose=False,
        representation_state="draft",
        operators=(),
    )
    response = activation_call(activation, "start")
    assert response.status_code == 200
    context = activation.render.call_args.args[1]
    assert context["form"] is None
    assert "representation" in context["representation_url"]
    assert context["baseline_hide_admin_scoped_navigation"] is True
    assert "guidance_scope" not in context


def test_proposal_keeps_original_actor_scope_and_preview_version(activation):
    activation.start_query.return_value = replace(activation.start, edition_version=4)
    activation.commands["propose_guidance_activation"].side_effect = ValidationError(
        "The event changed. Review a fresh request."
    )
    response = activation_call(activation, "start", proposal_data())
    assert response.status_code == 409
    sent = activation.commands["propose_guidance_activation"].call_args.kwargs
    assert sent["actor"] is activation.actor
    assert sent["organization_id"] == activation.start.organization_id
    assert sent["expected_edition_version"] == 3
    assert sent["idempotency_key"] == UUID(int=6)
    assert (
        activation.render.call_args.args[1]["form"]["expected_edition_version"].value()
        == "3"
    )
    assert activation.render.call_args.args[1]["submit_label"] == "Request this setup"


def test_setup_decision_uses_request_language_without_changing_responsibilities(
    activation,
):
    assert activation_call(activation, "detail").status_code == 200
    assert activation.render.call_args.args[1]["title"] == "Guides setup request"
    assert activation_call(activation, "answer").status_code == 200
    form = activation.render.call_args.args[1]["form"]
    assert form.fields["confirmed"].label == (
        "I have read the event, people and responsibilities in this request."
    )
    assert form.fields["decision"].choices[0] == (
        "accept",
        "Accept my responsibilities and approve the other person's assignment",
    )


def test_exact_own_answer_retry_reaches_owner_even_after_button_disappears(activation):
    activation.detail_query.return_value = replace(
        activation.proposal,
        can_answer=False,
        own_answer=True,
        state="accepted",
        accepted_count=2,
    )
    response = activation_call(
        activation,
        "answer",
        {"decision": "accept", "confirmed": "on", "expected_version": "1"},
    )
    assert response.status_code == 302
    sent = activation.commands["respond_to_guidance_activation"].call_args.kwargs
    assert sent["actor"] is activation.actor
    assert sent["accept"] is True
    assert sent["expected_version"] == 1


def test_submitted_alternate_actor_is_not_silently_discarded(activation):
    response = activation_call(
        activation,
        "answer",
        {
            "decision": "accept",
            "confirmed": "on",
            "expected_version": "1",
            "actor_id": str(UUID(int=22)),
        },
    )
    assert response.status_code == 400
    activation.commands["respond_to_guidance_activation"].assert_not_called()


def test_activation_requires_csrf_and_get_never_records_a_decision(activation):
    assert activation_call(activation, "answer").status_code == 200
    response = activation_call(
        activation,
        "answer",
        {"decision": "accept", "confirmed": "on", "expected_version": "1"},
        csrf=True,
    )
    assert response.status_code == 403
    for command in activation.commands.values():
        command.assert_not_called()


def test_changed_decision_projection_is_not_released(activation):
    activation.detail_query.side_effect = [
        activation.proposal,
        replace(activation.proposal, can_answer=False),
    ]
    response = activation_call(activation)
    assert response.status_code == 409
    assert b"COMPLETE AUTHORIZED PAGE" not in response.content


def test_platform_completion_has_no_content_link_without_independent_admission(
    activation,
):
    activation.detail_query.return_value = replace(
        activation.proposal, state="applied", can_answer=False
    )
    assert activation_call(activation).status_code == 200
    assert activation.render.call_args.args[1]["content_url"] == ""


def test_completion_content_link_rechecks_exact_actor_and_event(
    activation, monkeypatch
):
    admission = Mock()
    monkeypatch.setattr(views, "authorize_guidance_scope", admission)
    assert activation_call(activation).status_code == 200
    for call in admission.call_args_list:
        request = call.args[0]
        assert request.actor_id == activation.actor.id
        assert request.organization_id == activation.start.organization_id
        assert request.edition_id == activation.start.edition_id
    assert len(admission.call_args_list) == 2
    assert activation.render.call_args.args[1]["content_url"]


def test_new_foundation_handoff_preserves_the_exact_event(activation, monkeypatch):
    monkeypatch.setattr(setup_views, "require_guidance_setup_actor", Mock())
    monkeypatch.setattr(
        setup_views,
        "load_guidance_setup_choices",
        Mock(return_value=GuidanceSetupChoices()),
    )
    command = Mock(
        return_value=SimpleNamespace(
            organization_id=activation.start.organization_id,
            edition_id=activation.start.edition_id,
        )
    )
    monkeypatch.setattr(setup_views, "set_up_guidance_adoption", command)
    data = setup_data()
    assert isinstance(data, QueryDict)
    request = RequestFactory().post(
        "/admin/platform/setup/guidance/new/",
        data=data.urlencode(),
        content_type="application/x-www-form-urlencoded",
    )
    request.user = Account(
        id=UUID(int=20), email="synthetic-platform@example.invalid", is_active=True
    )
    request._dont_enforce_csrf_checks = True
    response = setup_views.guidance_setup_workspace(request, mode="new_foundation")
    assert response.status_code == 302
    assert (
        f"/activate/{activation.start.organization_id}/{activation.start.edition_id}/"
        in response["Location"]
    )
    assert command.call_args.kwargs["details"].language_codes == ("en", "hu")
