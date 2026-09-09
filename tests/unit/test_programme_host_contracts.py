"""Static host authority, closed dormancy and reserved privacy-exit contracts."""

from importlib import import_module
from types import SimpleNamespace

import pytest
from django.db import migrations

from maru.authorization.catalog import CAPABILITIES, ScopeLevel
from maru.programme.authorization import PROGRAMME_HOST_SELF_CAPABILITIES
from maru.programme.commands import ProgrammeLimitConflictError
from maru.programme.host_commands import _require_host_history_room
from maru.scheduling.authorization import SCHEDULING_CAPABILITIES


def test_host_capabilities_add_only_exact_edition_manager_authority():
    previous = import_module(
        "maru.authorization.migrations.0025_programme_conversion_capability"
    )
    current = import_module(
        "maru.authorization.migrations.0026_programme_host_capabilities"
    )
    assert (
        *previous.EDITION_CAPABILITIES,
        *current.HOST_CAPABILITIES,
    ) == current.EDITION_CAPABILITIES
    assert current.ORGANIZATION_CAPABILITIES == previous.ORGANIZATION_CAPABILITIES
    assert current.DEPARTMENT_CAPABILITIES == previous.DEPARTMENT_CAPABILITIES
    assert current.RESOURCE_CAPABILITIES == previous.RESOURCE_CAPABILITIES
    assert {
        *current.ORGANIZATION_CAPABILITIES,
        *current.EDITION_CAPABILITIES,
        *current.DEPARTMENT_CAPABILITIES,
        *current.RESOURCE_CAPABILITIES,
    } == {
        code for code, capability in CAPABILITIES.items() if capability.persistable
    } - {
        "programme.manage_staffing",
        "programme.view_staffing",
        *SCHEDULING_CAPABILITIES,
        "programme.view_scheduling_dependencies",
        "venues.view_scheduling_dependencies",
    }
    for code in current.HOST_CAPABILITIES:
        assert CAPABILITIES[code].maximum_scope == ScopeLevel.EDITION
        assert CAPABILITIES[code].persistable
    for code in PROGRAMME_HOST_SELF_CAPABILITIES:
        assert not CAPABILITIES[code].persistable
        assert not CAPABILITIES[code].delegable
    assert isinstance(current.Migration.operations[0], migrations.RunSQL)
    fence = current.Migration.operations[1]
    assert isinstance(fence, migrations.RunPython)
    assert fence.reverse_code is current.refuse_used_host_capability_downgrade


@pytest.mark.parametrize(
    ("version", "closing", "allowed"),
    [
        (999, False, True),
        (1000, False, False),
        (1000, True, True),
        (1001, True, True),
        (1002, True, False),
        (1001, False, False),
    ],
)
def test_history_budget_reserves_two_exits_without_reopening_editing(
    version, closing, allowed
):
    host = SimpleNamespace(version=version)
    if allowed:
        _require_host_history_room(host, closing=closing)
    else:
        with pytest.raises(ProgrammeLimitConflictError):
            _require_host_history_room(host, closing=closing)


def test_new_relationship_needs_no_history_reservation():
    _require_host_history_room(None, closing=False)
