"""Closed staffing authority, dormant containment and exact migration contracts."""

from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.db import migrations

from maru.authorization.catalog import CAPABILITIES, ScopeLevel
from maru.programme.authorization import PROGRAMME_CAPABILITY_CODES
from maru.programme.commands import ProgrammeLimitConflictError
from maru.programme.events import programme_item_changed_payload
from maru.programme.readiness import (
    _STAFFING_INTEGRITY_CONTRACT,
    PROGRAMME_INTEGRITY_CONTRACT,
    _staffing_migration_contract_is_current,
)
from maru.programme.staffing_commands import _locked_requirement
from maru.programme.staffing_inputs import (
    MAX_STAFFING_REQUIREMENT_REVISIONS,
    MAX_STAFFING_REQUIREMENTS_PER_ITEM,
)
from tests.unit.test_programme_staffing_inputs import change


def test_staffing_capabilities_are_exact_additive_and_independently_ceilinged():
    current = import_module(
        "maru.authorization.migrations.0028_programme_staffing_capabilities"
    )
    previous = import_module(
        "maru.authorization.migrations.0027_scheduling_capabilities"
    )
    assert current.STAFFING_CAPABILITIES == (
        "programme.manage_staffing",
        "programme.view_staffing",
    )
    assert (
        *previous.EDITION_CAPABILITIES,
        *current.STAFFING_CAPABILITIES,
    ) == current.EDITION_CAPABILITIES
    for field in (
        "ORGANIZATION_CAPABILITIES",
        "DEPARTMENT_CAPABILITIES",
        "RESOURCE_CAPABILITIES",
    ):
        assert getattr(current, field) == getattr(previous, field)
    assert {code for code, value in CAPABILITIES.items() if value.persistable} == {
        *current.ORGANIZATION_CAPABILITIES,
        *current.EDITION_CAPABILITIES,
        *current.DEPARTMENT_CAPABILITIES,
        *current.RESOURCE_CAPABILITIES,
    }
    for code in current.STAFFING_CAPABILITIES:
        assert code in PROGRAMME_CAPABILITY_CODES
        assert CAPABILITIES[code].maximum_scope == ScopeLevel.EDITION
    assert CAPABILITIES["programme.view_staffing"].field_ceiling == frozenset(
        {"staffing_requirements", "staffing_history", "placement_decisions"}
    )
    assert CAPABILITIES["programme.manage_staffing"].obligations == frozenset(
        {"reason", "audit"}
    )


def test_staffing_migrations_keep_exact_integrity_and_reserved_retirement_room():
    assert _staffing_migration_contract_is_current()
    assert PROGRAMME_INTEGRITY_CONTRACT.terminal_migration == (
        "programme",
        "0015_placement_decision_downgrade_fence",
    )
    assert _STAFFING_INTEGRITY_CONTRACT.terminal_migration == (
        "programme",
        "0012_staffing_downgrade_fence",
    )
    assert MAX_STAFFING_REQUIREMENTS_PER_ITEM == 128
    assert MAX_STAFFING_REQUIREMENT_REVISIONS == 1000
    fence = import_module("maru.programme.migrations.0012_staffing_downgrade_fence")
    operation = fence.Migration.operations[0]
    assert isinstance(operation, migrations.RunPython)
    assert operation.code is migrations.RunPython.noop
    assert operation.reverse_code is fence.refuse_used_staffing_downgrade


@pytest.mark.parametrize(
    "action", ["create_staffing", "revise_staffing", "retire_staffing"]
)
def test_staffing_events_are_content_free_and_have_their_own_layer(action):
    assert programme_item_changed_payload(
        action=action,
        item_kind="organizer_core",
        provenance="organizer_core",
        lifecycle="active",
    ) == {
        "action": action,
        "layer": "staffing",
        "item_kind": "organizer_core",
        "provenance": "organizer_core",
        "lifecycle": "active",
        "concern": "none",
    }


def test_revision_budget_reserves_retirement_without_permitting_revival(monkeypatch):
    intent = replace(
        change(), requirement_id=change().item_id, expected_requirement_version=1000
    )
    scope = SimpleNamespace(
        organization_id=change().item_id, edition_id=change().item_id
    )
    requirement = SimpleNamespace(version=1000, lifecycle="active")
    query = MagicMock()
    query.select_for_update.return_value.filter.return_value.first.return_value = (
        requirement
    )
    monkeypatch.setattr(
        "maru.programme.staffing_commands.ProgrammeStaffingRequirement.objects.filter",
        lambda **_: query,
    )
    with pytest.raises(ProgrammeLimitConflictError):
        _locked_requirement(scope, intent)
    assert (
        _locked_requirement(scope, replace(intent, retire=True, expectation=None))
        is requirement
    )
    requirement.version = 1001
    with pytest.raises(ProgrammeLimitConflictError):
        _locked_requirement(
            scope,
            replace(
                intent, expected_requirement_version=1001, retire=True, expectation=None
            ),
        )


@pytest.mark.parametrize("retained", [128, 129])
def test_retained_requirement_bound_never_silently_drops_history(monkeypatch, retained):
    query = MagicMock()
    query.count.return_value = retained
    monkeypatch.setattr(
        "maru.programme.staffing_commands.ProgrammeStaffingRequirement.objects.filter",
        lambda **_: query,
    )
    scope = SimpleNamespace(
        organization_id=change().item_id, edition_id=change().item_id
    )
    with pytest.raises(ProgrammeLimitConflictError):
        _locked_requirement(scope, change())
