"""Real bounded owner composition with database and policy boundaries substituted."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.host_queries import (
    ProgrammeHostRosterEntry,
    ProgrammeHostRosterSnapshot,
    ProgrammeHostStateProjection,
)
from maru.programme.queries import (
    ProgrammeItemProjection,
    ProgrammeTimetableItemProjection,
)
from maru.scheduling import change_notice_selection as selection
from maru.scheduling.command_support import (
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.planning_queries import PlanningOccurrence, SchedulingReadRequest
from tests.unit.test_scheduling_release_workspace_queries import (
    queryset,
)
from tests.unit.test_scheduling_release_workspace_queries import (
    release_query_world as release_query_world,  # noqa: PLC0414
)


@pytest.fixture
def choices(monkeypatch):
    request = SchedulingReadRequest(uuid4(), uuid4(), uuid4(), uuid4())
    occurrence = PlanningOccurrence(uuid4(), uuid4(), 2, uuid4(), "active", None, None)
    item = ProgrammeTimetableItemProjection(
        ProgrammeItemProjection(occurrence.item_id, "core", "organizer", "active", 3),
        "Opening <ceremony>",
        2,
    )
    host = ProgrammeHostRosterEntry(
        ProgrammeHostStateProjection(uuid4(), "host", "confirmed", 4, 1),
        uuid4(),
        person_current=True,
        display_label="Synthetic host <one>",
    )
    sources = Mock(return_value=(uuid4(), 2, (occurrence,)))
    items = Mock(return_value=(item,))
    roster = Mock(return_value=ProgrammeHostRosterSnapshot(3, (host,)))
    monkeypatch.setattr(selection, "_sources", sources)
    monkeypatch.setattr(selection, "list_programme_timetable_items", items)
    monkeypatch.setattr(selection, "load_programme_host_roster", roster)
    return SimpleNamespace(
        request=request,
        occurrence=occurrence,
        item=item,
        host=host,
        sources=sources,
        items=items,
        roster=roster,
    )


def test_current_label_selection_never_loads_roster_until_deliberate_choice(choices):
    result = selection.load_notice_host_selection(choices.request)
    assert result.occurrences[0].label == "Opening <ceremony> · occurrence 1 · active"
    assert result.occurrences[0].working_version == 2
    assert result.hosts == ()
    choices.roster.assert_not_called()
    assert choices.items.call_args.kwargs == {
        "actor_id": choices.request.actor_id,
        "organization_id": choices.request.organization_id,
        "edition_id": choices.request.edition_id,
        "correlation_id": choices.request.correlation_id,
    }


def test_only_selected_item_current_confirmed_relationships_are_choices(choices):
    excluded = [
        replace(choices.host, person_current=False),
        replace(
            choices.host,
            relationship=replace(choices.host.relationship, state="invited"),
        ),
        replace(
            choices.host, relationship=replace(choices.host.relationship, state="ended")
        ),
    ]
    choices.roster.return_value = ProgrammeHostRosterSnapshot(
        3, (choices.host, *excluded)
    )
    result = selection.load_notice_host_selection(
        choices.request,
        occurrence_id=choices.occurrence.id,
    )
    assert len(result.hosts) == 1
    assert result.hosts[0].host_id == choices.host.relationship.host_id
    assert result.hosts[0].account_id == choices.host.account_id
    assert result.hosts[0].label == "Synthetic host <one> · host"
    assert choices.roster.call_args.args[0].item_id == choices.occurrence.item_id
    assert choices.roster.call_args.args[0].actor_id == choices.request.actor_id


def test_foreign_or_removed_occurrence_cannot_discover_a_roster(choices):
    with pytest.raises(SchedulingVersionConflictError):
        selection.load_notice_host_selection(choices.request, occurrence_id=uuid4())
    choices.roster.assert_not_called()


def test_missing_item_is_unavailable_not_a_partial_label_list(choices):
    choices.items.return_value = ()
    with pytest.raises(SchedulingUnavailableError):
        selection.load_notice_host_selection(choices.request)


def test_moved_item_cannot_compose_old_label_with_fresh_roster(choices):
    choices.roster.return_value = replace(choices.roster.return_value, item_version=4)
    with pytest.raises(SchedulingVersionConflictError):
        selection.load_notice_host_selection(
            choices.request, occurrence_id=choices.occurrence.id
        )


@pytest.mark.parametrize("boundary", ["items", "roster"])
def test_independent_owner_denial_never_returns_partial_selection(choices, boundary):
    getattr(choices, boundary).side_effect = ProgrammeAuthorizationDeniedError
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        selection.load_notice_host_selection(
            choices.request, occurrence_id=choices.occurrence.id
        )


def test_source_failure_precedes_any_private_programme_discovery(choices):
    choices.sources.side_effect = SchedulingUnavailableError
    with pytest.raises(SchedulingUnavailableError):
        selection.load_notice_host_selection(choices.request)
    choices.items.assert_not_called()
    choices.roster.assert_not_called()


def install_sources(world, monkeypatch):
    occurrence = selection.SchedulingOccurrence(
        id=uuid4(),
        organization_id=world.request.organization_id,
        edition_id=world.request.edition_id,
        programme_item_id=uuid4(),
        aggregate_version=2,
    )
    revision = selection.SchedulingOccurrenceRevision(
        id=uuid4(),
        organization_id=world.request.organization_id,
        edition_id=world.request.edition_id,
        occurrence=occurrence,
        sequence=2,
        lifecycle="active",
        group_key=None,
        group_sequence=None,
    )
    rows = [revision]
    current = [occurrence]
    revision_query = queryset(rows)
    occurrence_query = queryset(current)
    monkeypatch.setattr(
        selection.SchedulingOccurrenceRevision, "objects", revision_query
    )
    monkeypatch.setattr(selection.SchedulingOccurrence, "objects", occurrence_query)
    pointer = Mock(return_value=SimpleNamespace(active_release_id=uuid4(), version=2))
    monkeypatch.setattr(selection, "load_release_pointer", pointer)
    return SimpleNamespace(
        rows=rows,
        current=current,
        revision_query=revision_query,
        occurrence_query=occurrence_query,
        pointer=pointer,
    )


def test_source_query_scopes_audits_and_requests_only_identity_fields(
    release_query_world, monkeypatch
):
    world = release_query_world
    source = install_sources(world, monkeypatch)
    result = selection._sources(world.request)
    assert result[0] == source.pointer.return_value.active_release_id
    assert result[2][0].item_id == source.current[0].programme_item_id
    kwargs = source.revision_query.filter.call_args.kwargs
    assert kwargs["organization_id"] == world.request.organization_id
    assert kwargs["edition_id"] == world.request.edition_id
    assert kwargs["occurrence__organization_id"] == world.request.organization_id
    assert kwargs["occurrence__edition_id"] == world.request.edition_id
    assert world.authorize.call_args.args[2] == frozenset(
        {"occurrences", "release_manifest"}
    )
    assert world.authorize.call_args.kwargs["lock"] is True
    assert world.audit.call_args.args[2] == "notice_source_choices"


@pytest.mark.parametrize("version", [0, 3])
def test_absence_or_latest_withdrawal_needs_no_old_geometry(
    release_query_world, monkeypatch, version
):
    world = release_query_world
    source = install_sources(world, monkeypatch)
    source.pointer.return_value = SimpleNamespace(
        active_release_id=None, version=version
    )
    release_id = uuid4()
    query = world.managers[selection.SchedulingReleaseWithdrawal]
    query.values_list.return_value.first.return_value = release_id
    result = selection._sources(world.request)
    assert result[0] == (release_id if version else None)
    if version:
        assert query.filter.call_args.kwargs == {
            "organization_id": world.request.organization_id,
            "edition_id": world.request.edition_id,
            "pointer_version": version,
        }
    else:
        query.values_list.assert_not_called()


def test_missing_withdrawal_fails_closed(release_query_world, monkeypatch):
    world = release_query_world
    source = install_sources(world, monkeypatch)
    source.pointer.return_value = SimpleNamespace(active_release_id=None, version=3)
    world.managers[
        selection.SchedulingReleaseWithdrawal
    ].values_list.return_value.first.return_value = None
    with pytest.raises(SchedulingUnavailableError):
        selection._sources(world.request)


@pytest.mark.parametrize("overflow", [False, True])
def test_missing_revision_or_overflow_never_returns_partial_sources(
    release_query_world, monkeypatch, overflow
):
    source = install_sources(release_query_world, monkeypatch)
    if overflow:
        monkeypatch.setattr(selection, "MAX_OCCURRENCES", 0)
    else:
        source.rows.clear()
    with pytest.raises(
        SchedulingLimitError if overflow else SchedulingUnavailableError
    ):
        selection._sources(release_query_world.request)


def test_work_selection_needs_deliberate_occurrence_but_never_host_authority(
    choices, monkeypatch
):
    work = Mock(return_value=())
    monkeypatch.setattr(selection, "list_programme_work_notice_choices", work)
    assert selection.load_notice_work_selection(choices.request).commitments == ()
    work.assert_not_called()
    with pytest.raises(SchedulingVersionConflictError):
        selection.load_notice_work_selection(choices.request, occurrence_id=uuid4())
    work.assert_not_called()
    result = selection.load_notice_work_selection(
        choices.request, occurrence_id=choices.occurrence.id
    )
    assert result.occurrences[0].label.startswith("Opening <ceremony>")
    assert work.call_args.args[0] == selection.ProgrammeWorkNoticeRequest(
        choices.request.actor_id,
        choices.request.organization_id,
        choices.request.edition_id,
        choices.request.correlation_id,
        choices.occurrence.id,
    )
    choices.roster.assert_not_called()


@pytest.mark.parametrize("boundary", ["sources", "items"])
def test_source_bounds_have_distinct_recovery_semantics(choices, boundary):
    getattr(choices, boundary).side_effect = (
        SchedulingLimitError
        if boundary == "sources"
        else selection.ProgrammeTimetableInventoryLimitError
    )
    with pytest.raises(selection.NoticeSourceSelectionLimitError):
        selection.load_notice_source_selection(choices.request)
    choices.roster.assert_not_called()
