"""Exact operator transition membership and source failure without PostgreSQL."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.scheduling import operator_release_impact as impact
from maru.scheduling import operator_release_references as references
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_scope import OperatorReadRequest, OperatorScopeKind
from maru.scheduling.release_artifacts import ReleaseArtifactSelection
from maru.scheduling.release_queries import ProgrammeReleaseManifest
from maru.scheduling.release_queries import ProgrammeReleaseState as State
from maru.venues.operator_queries import OperatorRoomLink
from maru.workforce.operator_links import OperatorWorkLink
from tests.unit.test_programme_operator_rendering import (
    sheet as sheet,  # noqa: PLC0414
)


@pytest.fixture
def world(monkeypatch, sheet):
    request = OperatorReadRequest(
        UUID(int=50),
        sheet.organization_id,
        sheet.edition_id,
        UUID(int=51),
        sheet.kind,
        sheet.target_id,
    )
    row = sheet.reference.occurrences[0]
    current = ProgrammeReleaseManifest(
        State.AVAILABLE,
        2,
        sheet.reference.release_id,
        is_active=True,
        selections=(
            ReleaseArtifactSelection(
                row.occurrence_id, row.placement_id, row.public_rendition_id
            ),
        ),
    )
    previous = replace(current, release_id=UUID(int=52), is_active=False)
    release = SimpleNamespace(
        id=current.release_id,
        previous_release_id=previous.release_id,
        pointer_version=2,
    )
    guard = Mock(side_effect=lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(impact, "operator_read", guard)
    rooms = Mock(return_value=(OperatorRoomLink(row.space_id, 3),))
    staffing = Mock(return_value=False)
    work = Mock(
        return_value=(
            OperatorWorkLink(
                row.occurrence_id, UUID(int=53), 2, UUID(int=54), 3, current=True
            ),
        )
    )
    manifest = Mock(side_effect=[current, previous, previous, current])
    geometry = Mock(return_value=(row,))
    for name, mock in (
        ("load_operator_room_links", rooms),
        ("operator_staffing_adopted", staffing),
        ("load_operator_department_work_links", work),
        ("_manifest", manifest),
        ("_geometry", geometry),
    ):
        monkeypatch.setattr(impact, name, mock)
    manager = Mock()
    manager.filter.return_value.only.return_value.first.return_value = release
    monkeypatch.setattr(impact.SchedulingRelease, "objects", manager)
    return SimpleNamespace(
        request=request,
        row=row,
        current=current,
        previous=previous,
        release=release,
        guard=guard,
        rooms=rooms,
        staffing=staffing,
        work=work,
        manifest=manifest,
        geometry=geometry,
        manager=manager,
    )


def test_fresh_exact_scope_owner_versions_and_each_side_geometry(world):
    result = impact.load_operator_release_impact(world.request)
    assert result.kind == world.request.kind
    assert result.target_id == world.request.target_id
    assert result.release_id == world.current.release_id
    assert result.previous_release_id == world.previous.release_id
    assert result.pointer_version == 2
    assert result.room_links == world.rooms.return_value
    assert not result.staffing_adopted
    assert result.work_links == ()
    assert result.changes[0].kind == "unchanged"
    world.work.assert_not_called()
    assert world.guard.call_args.kwargs == {
        "capability": "scheduling.view_operator_output",
        "fields": frozenset({"released_geometry"}),
    }
    assert world.geometry.call_count == 2
    assert world.geometry.call_args_list[0].args == (
        world.request,
        world.previous,
        {world.row.space_id},
        set(),
    )
    assert world.geometry.call_args_list[1].args == (
        world.request,
        world.current,
        {world.row.space_id},
        set(),
    )
    assert world.rooms.call_count == world.staffing.call_count == 2
    for call in world.manifest.call_args_list:
        assert call.kwargs["organization_id"] == world.request.organization_id
        assert call.kwargs["edition_id"] == world.request.edition_id
    assert world.manager.filter.call_args.kwargs == {
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
        "id": world.current.release_id,
    }


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
def test_only_adopted_department_purpose_uses_independent_work_links(world, kind):
    world.staffing.return_value = True
    request = replace(world.request, kind=kind)
    result = impact.load_operator_release_impact(request)
    assert result.staffing_adopted
    if kind is OperatorScopeKind.DEPARTMENT:
        assert world.work.call_count == 2
        assert result.work_links == world.work.return_value
        assert world.geometry.call_args.args[3] == {world.row.occurrence_id}
    else:
        assert result.work_links == ()
        world.work.assert_not_called()


@pytest.mark.parametrize("source", ["guard", "rooms", "work"])
def test_independent_denial_precedes_release_lookup_even_with_empty_scope(
    world, source
):
    world.staffing.return_value = True
    getattr(world, source).side_effect = SchedulingAuthorizationDeniedError
    with pytest.raises(SchedulingAuthorizationDeniedError):
        impact.load_operator_release_impact(
            replace(world.request, kind=OperatorScopeKind.DEPARTMENT)
        )
    world.manifest.assert_not_called()
    world.geometry.assert_not_called()


@pytest.mark.parametrize("source", ["rooms", "staffing", "work", "previous", "current"])
def test_changed_owner_or_native_evidence_withholds_comparison(world, source):
    world.staffing.return_value = True
    if source == "rooms":
        world.rooms.side_effect = [world.rooms.return_value, ()]
    elif source == "staffing":
        world.staffing.side_effect = [True, False]
    elif source == "work":
        world.work.side_effect = [world.work.return_value, ()]
    elif source == "previous":
        world.manifest.side_effect = [
            world.current,
            world.previous,
            replace(world.previous, state=State.INVALIDATED),
        ]
    else:
        world.manifest.side_effect = [
            world.current,
            world.previous,
            world.previous,
            replace(world.current, pointer_version=3),
        ]
    with pytest.raises(SchedulingUnavailableError):
        impact.load_operator_release_impact(
            replace(world.request, kind=OperatorScopeKind.DEPARTMENT)
        )


@pytest.mark.parametrize("state", [State.ABSENT, State.INVALIDATED, State.WITHDRAWN])
def test_current_suppression_never_loads_history_or_geometry(world, state):
    current = replace(world.current, state=state, selections=())
    world.manifest.side_effect = [current, current]
    result = impact.load_operator_release_impact(world.request)
    assert result.state is state
    assert result.changes is result.previous_state is result.previous_release_id is None
    world.manager.filter.assert_not_called()
    world.geometry.assert_not_called()
    assert world.rooms.call_count == 2


@pytest.mark.parametrize("state", [State.INVALIDATED, State.WITHDRAWN])
def test_predecessor_suppression_is_not_a_fabricated_addition(world, state):
    previous = replace(world.previous, state=state, selections=())
    world.manifest.side_effect = [world.current, previous, previous, world.current]
    result = impact.load_operator_release_impact(world.request)
    assert result.previous_state is state
    assert result.changes is None
    world.geometry.assert_not_called()


def test_first_publication_and_available_empty_scope_are_distinct(world):
    world.release.previous_release_id = None
    world.manifest.side_effect = [world.current, world.current]
    world.geometry.return_value = ()
    result = impact.load_operator_release_impact(world.request)
    assert result.previous_state is State.ABSENT
    assert result.changes == ()
    world.geometry.assert_called_once()


@pytest.mark.parametrize(
    "fault", ["missing", "version", "inactive", "no_identity", "mixed"]
)
def test_inconsistent_publication_cannot_reach_geometry(world, fault):
    if fault == "missing":
        world.manager.filter.return_value.only.return_value.first.return_value = None
    elif fault == "version":
        world.release.pointer_version = 1
    elif fault == "inactive":
        world.manifest.side_effect = [replace(world.current, is_active=False)]
    elif fault == "no_identity":
        world.manifest.side_effect = [replace(world.current, release_id=None)]
    else:
        world.manifest.side_effect = [
            world.current,
            replace(world.previous, pointer_version=1),
        ]
    with pytest.raises(SchedulingUnavailableError):
        impact.load_operator_release_impact(world.request)
    world.geometry.assert_not_called()


@pytest.mark.parametrize("side", ["before", "after"])
def test_scope_entry_exit_does_not_reveal_unadmitted_destination(world, side):
    before = () if side == "before" else (world.row,)
    after = () if side == "after" else (world.row,)
    (change,) = impact._compare(before, after)
    assert change.kind == ("added" if side == "before" else "removed")
    assert getattr(change, side) is None
    assert change.changed_fields == ()


@pytest.mark.parametrize(
    "field",
    [
        "placement_id",
        "public_rendition_id",
        "space_id",
        "day_id",
        "day_starts_at",
        "day_ends_at",
    ],
)
def test_reference_room_and_day_changes_remain_independent(world, field):
    old = getattr(world.row, field)
    value = UUID(int=95) if isinstance(old, UUID) else old + timedelta(minutes=5)
    (change,) = impact._compare((world.row,), (replace(world.row, **{field: value}),))
    assert change.changed_fields == (field,)
    assert change.kind == "changed"


@pytest.mark.parametrize(
    "field",
    ["setup_starts_at", "effective_starts_at", "effective_ends_at", "teardown_ends_at"],
)
def test_phase_changes_are_not_inferred_from_references(world, field):
    envelope = replace(
        world.row.envelope,
        **{field: getattr(world.row.envelope, field) + timedelta(minutes=5)},
    )
    (change,) = impact._compare((world.row,), (replace(world.row, envelope=envelope),))
    assert change.changed_fields == (field,)


@pytest.mark.parametrize("fault", ["duplicate", "item", "oversized"])
def test_incomplete_own_geometry_is_not_a_partial_comparison(world, monkeypatch, fault):
    after = (world.row,)
    if fault == "duplicate":
        after *= 2
    elif fault == "item":
        after = (replace(world.row, item_id=UUID(int=95)),)
    else:
        monkeypatch.setattr(impact, "MAX_OCCURRENCES", 0)
    with pytest.raises(SchedulingUnavailableError):
        impact._compare((world.row,), after)


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
@pytest.mark.parametrize("via_work", [False, True])
def test_real_geometry_filter_applies_scope_to_each_side_not_just_the_union(
    world, monkeypatch, kind, via_work
):
    row = world.row
    manager = Mock()
    values = manager.filter.return_value.order_by.return_value.values_list

    def raw(space):
        return (
            row.placement_id,
            row.occurrence_id,
            row.item_id,
            space,
            row.day_id,
            row.day_starts_at,
            row.day_ends_at,
            row.envelope.setup_starts_at,
            row.envelope.effective_starts_at,
            row.envelope.effective_ends_at,
            row.envelope.teardown_ends_at,
        )

    values.side_effect = [[raw(row.space_id)], [raw(UUID(int=95))]]
    monkeypatch.setattr(references.SchedulingPlacementRevision, "objects", manager)
    request = replace(world.request, kind=kind)
    work = (
        {row.occurrence_id}
        if via_work and kind is OperatorScopeKind.DEPARTMENT
        else set()
    )
    before = references._geometry(request, world.previous, {row.space_id}, work)
    after = references._geometry(request, world.current, {row.space_id}, work)
    (change,) = impact._compare(before, after)
    if kind is OperatorScopeKind.EDITION or work:
        assert change.kind == "changed"
        assert change.changed_fields == ("space_id",)
    else:
        assert change.kind == "removed"
        assert change.after is None
        assert "00000000-0000-0000-0000-00000000005f" not in repr(change)
    for call in manager.filter.call_args_list:
        assert call.kwargs["organization_id"] == request.organization_id
        assert call.kwargs["edition_id"] == request.edition_id
        assert (
            call.kwargs["occurrence_revision__occurrence__edition_id"]
            == request.edition_id
        )


def test_complete_disjoint_union_is_deterministic_and_not_truncated(world):
    before = tuple(
        replace(world.row, occurrence_id=UUID(int=100 + n))
        for n in range(impact.MAX_OCCURRENCES)
    )
    after = tuple(
        replace(world.row, occurrence_id=UUID(int=3000 + n))
        for n in range(impact.MAX_OCCURRENCES)
    )
    result = impact._compare(before[::-1], after[::-1])
    assert len(result) == 2 * impact.MAX_OCCURRENCES
    assert [row.occurrence_id for row in result] == sorted(
        row.occurrence_id for row in result
    )
