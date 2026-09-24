"""Exact scoped stop observation without authority, labels or profile widening."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from maru.events import programme_stop_queries as queries


@pytest.fixture
def world(monkeypatch):
    query = MagicMock()
    query.order_by.return_value = query
    query.values_list.return_value = query
    query.first.return_value = ("programme_operations", 1, "draft", 7)
    scope_filter = MagicMock(return_value=query)
    monkeypatch.setattr(queries.EventEdition.objects, "filter", scope_filter)
    profile = MagicMock(return_value=object())
    monkeypatch.setattr(queries, "adoption_profile", profile)
    return query, scope_filter, profile


def observe(**changes):
    return queries.resolve_programme_stop_reference(
        **{"organization_id": UUID(int=1), "edition_id": UUID(int=2), **changes}
    )


def test_minimal_reference_pins_the_complete_tenant_chain(world):
    query, scope_filter, profile = world
    assert observe() == queries.ProgrammeStopReference(
        applies=True, is_stopped=False, version=7
    )
    scope_filter.assert_called_once_with(
        id=UUID(int=2), organization_id=UUID(int=1), series__organization_id=UUID(int=1)
    )
    query.values_list.assert_called_once_with(
        "adoption_profile_code",
        "adoption_profile_version",
        "lifecycle",
        "aggregate_version",
    )
    profile.assert_called_once_with("programme_operations", 1)


@pytest.mark.parametrize(
    "lifecycle",
    ["draft", "preparing", "ready", "live", "closing", "archived", "cancelled"],
)
def test_exact_programme_terminal_states_do_not_depend_on_capabilities(
    world, lifecycle
):
    world[0].first.return_value = ("programme_operations", 1, lifecycle, 7)
    assert observe().is_stopped == (lifecycle in {"archived", "cancelled"})


@pytest.mark.parametrize("code", ["full_convention", "workforce_only"])
@pytest.mark.parametrize(
    "lifecycle", ["draft", "live", "closing", "archived", "cancelled"]
)
def test_other_profiles_keep_their_own_lifecycle_rules(world, code, lifecycle):
    world[0].first.return_value = (code, 1, lifecycle, 7)
    assert observe() == queries.ProgrammeStopReference(
        applies=False, is_stopped=False, version=7
    )


@pytest.mark.parametrize("field", ["organization_id", "edition_id"])
@pytest.mark.parametrize("value", [None, False, 1, UUID(int=0), str(UUID(int=1))])
def test_invalid_scope_never_reaches_the_database(world, field, value):
    assert observe(**{field: value}) is None
    world[1].assert_not_called()


def test_absent_or_foreign_scope_has_no_profile_lookup(world):
    world[0].first.return_value = None
    assert observe() is None
    world[2].assert_not_called()


def test_unregistered_profile_is_unavailable_not_merely_non_stopped(world):
    world[2].return_value = None
    assert observe() is None


@pytest.mark.parametrize(
    "row",
    [
        ("programme_operations", 2, "live", 7),
        ("programme_operations", 1, "unknown", 7),
        ("programme_operations", 1, "live", 0),
        ("programme_operations", 1, "live", True),
    ],
)
def test_unknown_programme_version_or_source_state_fails_closed(world, row):
    world[0].first.return_value = row
    assert observe() is None


def test_current_version_is_returned_not_cached(world):
    first = observe()
    world[0].first.return_value = ("programme_operations", 1, "archived", 8)
    second = observe()
    assert first.version == 7
    assert not first.is_stopped
    assert second.version == 8
    assert second.is_stopped
    assert world[1].call_count == 2
