"""Native adapters authorize before parsing and preserve exact owner command intent."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import planning_staffing_actions as actions
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.planning_staffing_forms import PlanningStaffingBindingForm
from tests.unit.test_scheduling_staffing_forms import (
    binding_payload,
    requirement_form,
    requirement_payload,
)


@pytest.fixture
def dispatcher(monkeypatch):
    scope = SchedulingReadRequest(uuid4(), uuid4(), uuid4(), uuid4())
    names = (
        "authorize_scheduling_scope",
        "authorize_programme_scope",
        "authorize_programme_staffing_adapter",
        "change_programme_staffing_requirement",
        "preview_programme_staffing_binding",
        "apply_programme_staffing_binding",
    )
    mocks = {name: Mock(name=name) for name in names}
    for name, value in mocks.items():
        monkeypatch.setattr(actions, name, value)
    return SimpleNamespace(
        scope=scope, actor=SimpleNamespace(id=scope.actor_id), mocks=mocks
    )


def test_requirement_dispatch_uses_trusted_scope_and_original_versions(dispatcher):
    world = dispatcher
    payload = requirement_payload(expected_item_version=7)
    form = requirement_form(payload)
    item, occurrence = uuid4(), uuid4()
    result = actions.submit_planning_staffing_requirement(
        world.scope,
        form,
        item_id=item,
        occurrence_id=occurrence,
        requirement_id=None,
    )
    command = world.mocks["change_programme_staffing_requirement"]
    assert result is command.return_value
    sent = command.call_args.kwargs
    assert sent["actor_id"] == world.scope.actor_id
    assert sent["organization_id"] == world.scope.organization_id
    assert sent["edition_id"] == world.scope.edition_id
    assert sent["correlation_id"] == world.scope.correlation_id
    assert sent["idempotency_key"] == UUID(payload["retry_key"])
    assert sent["change"].item_id == item
    assert sent["change"].occurrence_id == occurrence
    assert sent["change"].expected_item_version == 7
    assert world.mocks["authorize_programme_scope"].call_count == 2
    world.mocks["apply_programme_staffing_binding"].assert_not_called()


def test_requirement_denial_precedes_private_form_validation(dispatcher):
    world = dispatcher
    world.mocks[
        "authorize_programme_scope"
    ].side_effect = ProgrammeAuthorizationDeniedError
    form = Mock()
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        actions.submit_planning_staffing_requirement(
            world.scope,
            form,
            item_id=uuid4(),
            occurrence_id=uuid4(),
            requirement_id=None,
        )
    form.change.assert_not_called()
    world.mocks["change_programme_staffing_requirement"].assert_not_called()


def test_requirement_selection_cannot_be_retargeted_by_hidden_input(dispatcher):
    world = dispatcher
    form = requirement_form(requirement_payload())
    assert (
        actions.submit_planning_staffing_requirement(
            world.scope,
            form,
            item_id=uuid4(),
            occurrence_id=uuid4(),
            requirement_id=uuid4(),
        )
        is None
    )
    assert form.non_field_errors()
    world.mocks["change_programme_staffing_requirement"].assert_not_called()


def selected(payload):
    return {
        name: UUID(payload[name])
        for name in ("requirement_id", "occurrence_id", "candidate_id")
    }


@pytest.mark.parametrize("apply", [False, True])
def test_binding_preview_and_apply_dispatch_only_the_explicit_owner_operation(
    dispatcher, apply
):
    world = dispatcher
    payload = binding_payload(
        action="staffing_apply" if apply else "staffing_preview",
        preview_digest="b" * 64 if apply else "",
        confirm="on" if apply else "",
    )
    form = PlanningStaffingBindingForm(payload)
    item = uuid4()
    result = actions.submit_planning_staffing_binding(
        world.actor,
        world.scope,
        form,
        item_id=item,
        **selected(payload),
    )
    chosen = (
        "apply_programme_staffing_binding"
        if apply
        else "preview_programme_staffing_binding"
    )
    other = (
        "preview_programme_staffing_binding"
        if apply
        else "apply_programme_staffing_binding"
    )
    command = world.mocks[chosen]
    assert result is command.return_value
    world.mocks[other].assert_not_called()
    sent = command.call_args.kwargs
    assert sent["change"].source.requirement_id == UUID(payload["requirement_id"])
    assert sent["change"].source.candidate_revision_id == UUID(
        payload["candidate_revision_id"]
    )
    request = command.call_args.args[1 if apply else 0]
    assert request.item_id == item
    assert request.actor_id == world.scope.actor_id
    assert request.correlation_id == world.scope.correlation_id
    if apply:
        assert command.call_args.args[0] is world.actor
        assert sent["preview_digest"] == payload["preview_digest"]
        assert sent["retry_key"] == UUID(payload["retry_key"])


@pytest.mark.parametrize("field", ["requirement_id", "occurrence_id", "candidate_id"])
def test_binding_source_cannot_differ_from_visible_selected_task(dispatcher, field):
    world = dispatcher
    payload = binding_payload()
    form = PlanningStaffingBindingForm(payload)
    assert (
        actions.submit_planning_staffing_binding(
            world.actor,
            world.scope,
            form,
            item_id=uuid4(),
            **{**selected(payload), field: uuid4()},
        )
        is None
    )
    assert form.non_field_errors()
    world.mocks["preview_programme_staffing_binding"].assert_not_called()
    world.mocks["apply_programme_staffing_binding"].assert_not_called()


def test_missing_confirmation_never_reaches_a_binding_command(dispatcher):
    world = dispatcher
    payload = binding_payload(action="staffing_apply", preview_digest="a" * 64)
    form = PlanningStaffingBindingForm(payload)
    assert (
        actions.submit_planning_staffing_binding(
            world.actor,
            world.scope,
            form,
            item_id=uuid4(),
            **selected(payload),
        )
        is None
    )
    assert "confirm" in form.errors
    world.mocks["apply_programme_staffing_binding"].assert_not_called()
