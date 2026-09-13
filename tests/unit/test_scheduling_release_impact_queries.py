"""Published-transition scope, geometry and freshness contracts without a database."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.scheduling import release_impact_queries as queries
from maru.scheduling.authorization import (
    VIEW_HISTORY,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_queries import HISTORY_FIELDS, SchedulingReadRequest
from maru.scheduling.release_artifacts import ReleaseArtifactSelection
from maru.scheduling.release_queries import (
    RELEASE_MANIFEST_FIELDS,
    ProgrammeReleaseManifest,
)
from maru.scheduling.release_queries import (
    ProgrammeReleaseState as State,
)
from maru.scheduling.time_rules import SchedulingEnvelope


@pytest.fixture
def impact_world(monkeypatch):
    real_geometry = queries._geometry
    request = SchedulingReadRequest(*(UUID(int=n) for n in range(1, 5)))
    selected = ReleaseArtifactSelection(*(UUID(int=n) for n in range(10, 13)))
    release = SimpleNamespace(
        id=UUID(int=20), previous_release_id=None, pointer_version=1
    )
    manager = Mock()
    manager.filter.return_value.only.return_value.first.return_value = release
    monkeypatch.setattr(queries.SchedulingRelease, "objects", manager)
    after = ProgrammeReleaseManifest(
        State.AVAILABLE, 1, release.id, is_active=True, selections=(selected,)
    )
    manifest = Mock(return_value=after)
    monkeypatch.setattr(queries, "_manifest", manifest)
    start = datetime(2026, 9, 20, 10, tzinfo=UTC)
    envelope = SchedulingEnvelope(
        start, start, start + timedelta(hours=1), start + timedelta(hours=1)
    )
    geometry = queries.ReleasedChangeGeometry(
        selected.placement_id, UUID(int=30), UUID(int=31), envelope
    )
    geometry_loader = Mock(return_value={selected.occurrence_id: geometry})
    monkeypatch.setattr(queries, "_geometry", geometry_loader)
    return SimpleNamespace(
        request=request,
        selected=selected,
        release=release,
        manager=manager,
        after=after,
        manifest=manifest,
        geometry=geometry,
        geometry_loader=geometry_loader,
        real_geometry=real_geometry,
    )


def test_first_publication_has_real_additions_without_inventing_prior_release(
    impact_world,
):
    world = impact_world
    result = queries._load(world.request, world.release.id)
    assert result.previous_release_id is None
    assert result.before_state is State.ABSENT
    assert result.is_active
    assert result.changes[0].selection.kind == "added"
    assert result.changes[0].before is None
    assert result.changes[0].after == world.geometry
    assert world.manifest.call_count == 2
    assert world.manager.filter.call_args.kwargs == {
        "id": world.release.id,
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
    }
    assert set(asdict(result)) == {
        "release_id",
        "previous_release_id",
        "release_version",
        "observed_pointer_version",
        "is_active",
        "before_state",
        "after_state",
        "changes",
    }


@pytest.mark.parametrize("state", [State.WITHDRAWN, State.INVALIDATED])
@pytest.mark.parametrize("side", ["before", "after"])
def test_governing_suppression_is_not_an_empty_success_or_mass_removal(
    impact_world, state, side
):
    world = impact_world
    world.release.previous_release_id = UUID(int=21)
    before = replace(
        world.after, release_id=world.release.previous_release_id, is_active=False
    )
    after = world.after
    if side == "before":
        before = replace(before, state=state, selections=())
    else:
        after = replace(after, state=state, selections=())
    world.manifest.side_effect = [before, after, before, after]
    result = queries._load(world.request, world.release.id)
    assert result.changes is None
    world.geometry_loader.assert_not_called()


def test_predecessor_is_the_retained_transition_and_all_queries_keep_exact_scope(
    impact_world,
):
    world = impact_world
    world.release.previous_release_id = UUID(int=21)
    world.release.pointer_version = 2
    before = replace(
        world.after,
        release_id=world.release.previous_release_id,
        pointer_version=8,
        is_active=False,
    )
    after = replace(world.after, pointer_version=8, is_active=False)
    world.manifest.side_effect = [before, after, before, after]
    result = queries._load(world.request, world.release.id)
    assert result.release_version == 2
    assert result.observed_pointer_version == 8
    assert not result.is_active
    assert result.changes[0].selection.kind == "unchanged"
    assert [call.kwargs["release_id"] for call in world.manifest.call_args_list] == [
        world.release.previous_release_id,
        world.release.id,
        world.release.previous_release_id,
        world.release.id,
    ]
    for call in world.manifest.call_args_list:
        assert call.kwargs["organization_id"] == world.request.organization_id
        assert call.kwargs["edition_id"] == world.request.edition_id


def test_changed_governing_state_during_composition_releases_nothing(impact_world):
    world = impact_world
    world.manifest.side_effect = [
        world.after,
        replace(world.after, state=State.INVALIDATED, selections=()),
    ]
    with pytest.raises(SchedulingUnavailableError):
        queries._load(world.request, world.release.id)


def test_mixed_pointer_snapshots_are_rejected_before_geometry(impact_world):
    world = impact_world
    world.release.previous_release_id = UUID(int=21)
    world.manifest.side_effect = [replace(world.after, pointer_version=2), world.after]
    with pytest.raises(SchedulingUnavailableError):
        queries._load(world.request, world.release.id)
    world.geometry_loader.assert_not_called()


def test_missing_or_foreign_release_is_generic_unavailable(impact_world):
    world = impact_world
    world.manager.filter.return_value.only.return_value.first.return_value = None
    with pytest.raises(SchedulingUnavailableError):
        queries._load(world.request, world.release.id)
    world.manifest.assert_not_called()


def test_public_query_requires_both_history_fields_before_loading(
    monkeypatch, impact_world
):
    read = Mock(return_value=object())
    loader = Mock()
    monkeypatch.setattr(queries, "_read", read)
    monkeypatch.setattr(queries, "_load", loader)
    policy = object()
    result = queries.load_programme_release_impact(
        impact_world.request, release_id=impact_world.release.id, authorizer=policy
    )
    assert result is read.return_value
    assert read.call_args.kwargs["fields"] == HISTORY_FIELDS | RELEASE_MANIFEST_FIELDS
    assert read.call_args.kwargs["capability"] == VIEW_HISTORY
    assert read.call_args.kwargs["purpose"] == "release_impact"
    assert read.call_args.kwargs["authorizer"] is policy
    loader.assert_not_called()
    read.call_args.kwargs["loader"](object())
    loader.assert_called_once_with(impact_world.request, impact_world.release.id)


def test_denial_precedes_untrusted_release_validation_and_lookup(
    monkeypatch, impact_world
):
    read = Mock(side_effect=SchedulingAuthorizationDeniedError)
    monkeypatch.setattr(queries, "_read", read)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.load_programme_release_impact(
            impact_world.request, release_id="invalid"
        )
    impact_world.manager.filter.assert_not_called()


@pytest.mark.parametrize("field", ["day_id", "space_id"])
def test_actual_day_and_room_changes_have_exact_closed_field_names(impact_world, field):
    before = impact_world.geometry
    after = replace(before, **{field: UUID(int=50)})
    assert queries._changed_geometry(before, after) == (field,)


@pytest.mark.parametrize(
    "field",
    ["setup_starts_at", "effective_starts_at", "effective_ends_at", "teardown_ends_at"],
)
def test_each_phase_is_compared_independently(impact_world, field):
    before = impact_world.geometry
    after = replace(
        before,
        envelope=replace(
            before.envelope,
            **{field: getattr(before.envelope, field) + timedelta(minutes=5)},
        ),
    )
    assert queries._changed_geometry(before, after) == (field,)


def test_revision_only_change_does_not_invent_a_time_room_or_shift_change(impact_world):
    before = impact_world.geometry
    after = replace(before, placement_id=UUID(int=99))
    assert queries._changed_geometry(before, after) == ()
    assert queries._changed_geometry(None, after) == ()
    assert queries._changed_geometry(before, None) == ()


@pytest.mark.parametrize(
    "case", ["valid", "missing", "foreign", "duplicate", "phase_order"]
)
def test_geometry_requires_complete_exact_membership_and_valid_phases(
    monkeypatch, impact_world, case
):
    world = impact_world
    geometry = world.geometry
    envelope = geometry.envelope
    row = (
        geometry.placement_id,
        world.selected.occurrence_id,
        geometry.day_id,
        geometry.space_id,
        envelope.setup_starts_at - timedelta(hours=1),
        envelope.teardown_ends_at + timedelta(hours=1),
        envelope.setup_starts_at,
        envelope.effective_starts_at,
        envelope.effective_ends_at,
        envelope.teardown_ends_at,
    )
    rows = [row]
    if case == "missing":
        rows = []
    elif case == "foreign":
        rows = [(row[0], UUID(int=99), *row[2:])]
    elif case == "duplicate":
        rows *= 2
    elif case == "phase_order":
        rows = [(*row[:8], row[7], row[9])]
    manager = Mock()
    manager.filter.return_value.order_by.return_value.values_list.return_value = rows
    monkeypatch.setattr(queries.SchedulingPlacementRevision, "objects", manager)
    if case == "valid":
        assert world.real_geometry(world.request, world.after) == {
            world.selected.occurrence_id: geometry
        }
    else:
        with pytest.raises(SchedulingUnavailableError):
            world.real_geometry(world.request, world.after)
    filters = manager.filter.call_args.kwargs
    assert filters["organization_id"] == world.request.organization_id
    assert filters["edition_id"] == world.request.edition_id
    assert (
        filters["occurrence_revision__occurrence__edition_id"]
        == world.request.edition_id
    )
    assert filters["id__in"] == {world.selected.placement_id: world.selected}
