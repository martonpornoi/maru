"""Binding intents are explicit, bounded and closed before persistence."""

from dataclasses import replace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.effects.adoption import NON_EDITION_EFFECT_ROUTES
from maru.effects.handlers import (
    ACKNOWLEDGED_DORMANT_EVENTS,
    ACKNOWLEDGED_INTERNAL_EVENTS,
    built_in_handler_registry,
)
from maru.effects.registry import validate_event_payload
from maru.events.adoption import ADOPTION_PROFILES
from maru.programme.staffing_inputs import ProgrammeStaffingSource
from maru.workforce.models import ProgrammeShiftBinding, ProgrammeShiftBindingRevision
from maru.workforce.programme_impact import ProgrammeStaffingAction as Action
from maru.workforce.programme_staffing_inputs import ProgrammeStaffingBindingChange
from maru.workforce.programme_staffing_writer import (
    programme_staffing_writer,
    require_programme_staffing_writer,
)


def change(action=Action.CREATE):
    return ProgrammeStaffingBindingChange(
        action,
        ProgrammeStaffingSource(
            uuid4(), uuid4(), 1, uuid4(), 1, uuid4(), uuid4(), uuid4()
        ),
        binding_id=uuid4() if action in {Action.RECONCILE, Action.SUCCESSOR} else None,
        expected_binding_version=1
        if action in {Action.RECONCILE, Action.SUCCESSOR}
        else 0,
        demand_id=None if action == Action.CREATE else uuid4(),
        expected_demand_version=0 if action == Action.CREATE else 1,
    )


@pytest.mark.parametrize("action", list(Action))
def test_closed_actions_keep_exact_caller_selection(action):
    selected = change(action)
    assert selected.validated() is selected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", "create"),
        ("action", True),
        ("source", None),
        ("binding_id", "bad"),
        ("expected_binding_version", True),
        ("expected_binding_version", -1),
        ("expected_binding_version", 2**63 - 1),
        ("demand_id", "bad"),
        ("expected_demand_version", True),
        ("expected_demand_version", -1),
        ("expected_demand_version", 2**63 - 1),
    ],
)
def test_malformed_intent_never_becomes_an_implicit_choice(field, value):
    with pytest.raises(ValidationError):
        replace(change(), **{field: value}).validated()


@pytest.mark.parametrize("action", list(Action))
def test_identity_version_pairs_cannot_be_dropped_or_fabricated(action):
    selected = change(action)
    for values in (
        {"binding_id": uuid4(), "expected_binding_version": 0},
        {"binding_id": None, "expected_binding_version": 1},
        {"demand_id": uuid4(), "expected_demand_version": 0},
        {"demand_id": None, "expected_demand_version": 1},
    ):
        with pytest.raises(ValidationError):
            replace(selected, **values).validated()


@pytest.mark.parametrize("action", [Action.RECONCILE, Action.SUCCESSOR])
def test_binding_budget_rejects_an_unbounded_additional_revision(action):
    assert replace(change(action), expected_binding_version=999).validated()
    with pytest.raises(ValidationError):
        replace(change(action), expected_binding_version=1000).validated()


@pytest.mark.parametrize(
    "model", [ProgrammeShiftBinding, ProgrammeShiftBindingRevision]
)
def test_models_reject_accidental_orm_writes_before_database_access(model):
    with pytest.raises(ValidationError, match="governed owner command"):
        model().save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        model().delete()


def test_nested_writer_restores_its_boundary_after_failure():
    with programme_staffing_writer():
        require_programme_staffing_writer()
        with pytest.raises(RuntimeError), programme_staffing_writer():
            raise RuntimeError("synthetic failure")
        require_programme_staffing_writer()
    with pytest.raises(ValidationError):
        require_programme_staffing_writer()


@pytest.mark.parametrize("action", list(Action))
def test_binding_events_are_content_free(action):
    validate_event_payload(
        event_name="workforce.programme_staffing.changed.v1",
        schema_version=1,
        payload={"action": action.value},
    )
    with pytest.raises(ValidationError):
        validate_event_payload(
            event_name="workforce.programme_staffing.changed.v1",
            schema_version=1,
            payload={"action": action.value, "briefing": "private"},
        )


def test_staffing_event_declaration_does_not_activate_any_delivery_route():
    event_name = "workforce.programme_staffing.changed.v1"
    assert event_name in ACKNOWLEDGED_DORMANT_EVENTS
    assert event_name not in ACKNOWLEDGED_INTERNAL_EVENTS
    handlers = built_in_handler_registry()
    assert all(
        handlers.resolve(event_name=event_name, destination=destination) is None
        for destination in ("internal", "notifications")
    )
    assert all(name != event_name for name, _destination in NON_EDITION_EFFECT_ROUTES)
    assert all(
        route.event_name != event_name
        for profile in ADOPTION_PROFILES.values()
        for route in profile.effect_routes
    )
