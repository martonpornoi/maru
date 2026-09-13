"""Volunteer change context is independently authorized and never rewrites work."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.scheduling import personal_work_release_impact as impact
from maru.scheduling import release_impact_queries as geometry_queries
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_WORK_SELF,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_artifacts import ReleaseArtifactSelection
from maru.scheduling.release_impact_queries import ReleasedChangeGeometry
from maru.scheduling.release_queries import ProgrammeReleaseManifest
from maru.scheduling.release_queries import ProgrammeReleaseState as State
from maru.scheduling.time_rules import SchedulingEnvelope
from maru.workforce.personal_programme_links import PersonalProgrammeWorkLink
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftUnavailableError,
)


@pytest.fixture
def world(monkeypatch):
    request = SchedulingReadRequest(*(UUID(int=n) for n in range(1, 5)))
    link = PersonalProgrammeWorkLink(
        UUID(int=5),
        3,
        "confirmed",
        UUID(int=6),
        4,
        UUID(int=7),
        UUID(int=8),
        2,
        current=False,
    )
    selection = ReleaseArtifactSelection(link.occurrence_id, UUID(int=9), UUID(int=10))
    foreign = ReleaseArtifactSelection(UUID(int=11), UUID(int=12), UUID(int=13))
    current = ProgrammeReleaseManifest(
        State.AVAILABLE,
        2,
        UUID(int=14),
        is_active=True,
        selections=(selection, foreign),
    )
    previous = replace(current, release_id=UUID(int=15), is_active=False)
    release = SimpleNamespace(
        id=current.release_id,
        previous_release_id=previous.release_id,
        pointer_version=2,
    )
    start = datetime(2030, 8, 2, 10, tzinfo=UTC)
    envelope = SchedulingEnvelope(
        start, start, start + timedelta(hours=1), start + timedelta(hours=1)
    )
    geometry = ReleasedChangeGeometry(
        selection.placement_id, UUID(int=16), UUID(int=17), envelope
    )
    links = Mock(return_value=(link,))
    manifest = Mock(side_effect=[current, previous, previous, current])
    loader = Mock(return_value={link.occurrence_id: geometry})
    for name, mock in (
        ("load_personal_programme_work_links", links),
        ("_manifest", manifest),
        ("_geometry", loader),
    ):
        monkeypatch.setattr(impact, name, mock)
    manager = Mock()
    manager.filter.return_value.only.return_value.first.return_value = release
    monkeypatch.setattr(impact.SchedulingRelease, "objects", manager)
    return SimpleNamespace(
        request=request,
        link=link,
        selection=selection,
        foreign=foreign,
        current=current,
        previous=previous,
        release=release,
        geometry=geometry,
        links=links,
        manifest=manifest,
        loader=loader,
        manager=manager,
    )


def test_fresh_self_reference_scopes_both_sides_and_excludes_unrelated_occurrences(
    world,
):
    result = impact._load(world.request)
    assert result.state is result.previous_state is State.AVAILABLE
    assert result.release_id == world.current.release_id
    assert result.previous_release_id == world.previous.release_id
    assert result.pointer_version == 2
    (change,) = result.changes
    assert change.work == world.link
    assert (
        not change.work.current
    )  # A retained predecessor still justifies own context.
    assert change.kind == "unchanged"
    assert change.before == change.after == world.geometry
    assert change.changed_fields == ()
    assert world.links.call_count == 2
    assert world.links.call_args.kwargs == asdict(world.request)
    for call in world.loader.call_args_list:
        assert call.args[0] == world.request
        assert call.kwargs == {"occurrence_ids": {world.link.occurrence_id}}
    assert [call.kwargs["release_id"] for call in world.manifest.call_args_list] == [
        None,
        world.previous.release_id,
        world.previous.release_id,
        None,
    ]
    assert str(world.foreign.occurrence_id) not in repr(result)


@pytest.mark.parametrize("status", ["claimed", "confirmed"])
def test_operative_work_state_and_versions_survive_a_changed_release(world, status):
    link = replace(world.link, status=status)
    world.links.return_value = (link,)
    current = replace(
        world.current,
        selections=(
            replace(
                world.selection,
                placement_id=UUID(int=80),
                public_rendition_id=UUID(int=81),
            ),
            world.foreign,
        ),
    )
    after = replace(world.geometry, placement_id=UUID(int=80), space_id=UUID(int=82))
    world.manifest.side_effect = [current, world.previous, world.previous, current]
    world.loader.side_effect = [
        {link.occurrence_id: world.geometry},
        {link.occurrence_id: after},
    ]
    (change,) = impact._load(world.request).changes
    assert change.work == link
    assert change.kind == "changed"
    assert change.changed_fields == ("placement_id", "public_rendition_id", "space_id")
    assert change.before.envelope == change.after.envelope


@pytest.mark.parametrize("status", [None, "removed", "completed"])
def test_no_operative_link_means_no_release_existence_discovery(world, status):
    world.links.return_value = (
        () if status is None else (replace(world.link, status=status),)
    )
    result = impact._load(world.request)
    assert all(value is None for value in asdict(result).values())
    world.manifest.assert_not_called()
    world.loader.assert_not_called()


def test_partial_adoption_is_unavailable_before_release_lookup(world):
    world.links.return_value = None
    with pytest.raises(SchedulingUnavailableError):
        impact._load(world.request)
    world.manifest.assert_not_called()


@pytest.mark.parametrize(
    "error", [ShiftAuthorizationDeniedError, ShiftUnavailableError]
)
def test_independent_workforce_failure_is_not_an_empty_recipient_set(world, error):
    world.links.side_effect = error
    with pytest.raises(error):
        impact._load(world.request)
    world.manifest.assert_not_called()


@pytest.mark.parametrize("state", [State.ABSENT, State.WITHDRAWN, State.INVALIDATED])
def test_current_suppression_never_loads_old_release_or_geometry(world, state):
    current = replace(world.current, state=state, selections=())
    world.manifest.side_effect = [current, current]
    result = impact._load(world.request)
    assert result.state is state
    assert result.changes is result.previous_release_id is result.previous_state is None
    world.manager.filter.assert_not_called()
    world.loader.assert_not_called()


@pytest.mark.parametrize("state", [State.WITHDRAWN, State.INVALIDATED])
def test_predecessor_suppression_is_not_a_false_work_addition(world, state):
    previous = replace(world.previous, state=state, selections=())
    world.manifest.side_effect = [world.current, previous, previous, world.current]
    result = impact._load(world.request)
    assert result.previous_state is state
    assert result.changes is None
    world.loader.assert_not_called()


def test_first_publication_is_context_addition_not_new_work(world):
    world.release.previous_release_id = None
    world.manifest.side_effect = [world.current, world.current]
    result = impact._load(world.request)
    assert result.previous_state is State.ABSENT
    assert result.changes[0].kind == "added"
    assert result.changes[0].before is None
    assert result.changes[0].work == world.link


def test_occurrence_removed_from_release_does_not_remove_retained_commitment(world):
    current = replace(world.current, selections=(world.foreign,))
    world.manifest.side_effect = [current, world.previous, world.previous, current]
    world.loader.side_effect = [{world.link.occurrence_id: world.geometry}, {}]
    (change,) = impact._load(world.request).changes
    assert change.kind == "removed"
    assert change.after is None
    assert change.work == world.link
    assert change.work.status == "confirmed"


@pytest.mark.parametrize("source", ["links", "previous", "current", "mixed_version"])
def test_changed_owner_or_native_evidence_withholds_every_result(world, source):
    if source == "links":
        world.links.side_effect = [
            (world.link,),
            (replace(world.link, commitment_version=4),),
        ]
    elif source == "previous":
        world.manifest.side_effect = [
            world.current,
            world.previous,
            replace(world.previous, state=State.INVALIDATED),
        ]
    elif source == "current":
        world.manifest.side_effect = [
            world.current,
            world.previous,
            world.previous,
            replace(world.current, pointer_version=3),
        ]
    else:
        world.manifest.side_effect = [
            world.current,
            replace(world.previous, pointer_version=1),
        ]
    with pytest.raises(SchedulingUnavailableError):
        impact._load(world.request)


def test_real_scheduling_self_policy_not_planner_is_required_before_loader(
    world, monkeypatch
):
    reader = Mock(return_value=object())
    monkeypatch.setattr(impact, "_read", reader)
    result = impact.load_personal_work_release_impact(**asdict(world.request))
    assert result is reader.return_value
    world.links.assert_not_called()
    options = reader.call_args.kwargs
    assert options["capability"] == VIEW_WORK_SELF
    assert options["fields"] == frozenset({"own_work_schedule"})
    assert options["authorizer"] is DEFAULT_SCHEDULING_AUTHORIZER
    assert options["purpose"] == "personal_work_release_impact"
    assert options["loader"](object()).changes[0].work == world.link


@pytest.mark.parametrize("fault", ["missing", "version", "inactive", "no_identity"])
def test_unproven_active_publication_is_unavailable_before_geometry(world, fault):
    if fault == "missing":
        world.manager.filter.return_value.only.return_value.first.return_value = None
    elif fault == "version":
        world.release.pointer_version = 1
    elif fault == "inactive":
        world.manifest.side_effect = [replace(world.current, is_active=False)]
    else:
        world.manifest.side_effect = [replace(world.current, release_id=None)]
    with pytest.raises(SchedulingUnavailableError):
        impact._load(world.request)
    world.loader.assert_not_called()


def test_denied_scheduling_self_policy_never_calls_workforce(world, monkeypatch):
    monkeypatch.setattr(
        impact, "_read", Mock(side_effect=SchedulingAuthorizationDeniedError)
    )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        impact.load_personal_work_release_impact(**asdict(world.request))
    world.links.assert_not_called()


def test_real_geometry_query_selects_only_proven_own_occurrences(world, monkeypatch):
    row = world.geometry
    start, end = row.envelope.setup_starts_at, row.envelope.teardown_ends_at
    manager = Mock()
    manager.filter.return_value.order_by.return_value.values_list.return_value = [
        (
            row.placement_id,
            world.link.occurrence_id,
            row.day_id,
            row.space_id,
            start,
            end,
            start,
            row.envelope.effective_starts_at,
            row.envelope.effective_ends_at,
            end,
        ),
    ]
    monkeypatch.setattr(
        geometry_queries.SchedulingPlacementRevision, "objects", manager
    )
    result = geometry_queries._geometry(
        world.request, world.current, occurrence_ids={world.link.occurrence_id}
    )
    assert result == {world.link.occurrence_id: row}
    assert set(manager.filter.call_args.kwargs["id__in"]) == {row.placement_id}
    assert world.foreign.placement_id not in manager.filter.call_args.kwargs["id__in"]
    assert (
        manager.filter.call_args.kwargs["organization_id"]
        == world.request.organization_id
    )
    assert manager.filter.call_args.kwargs["edition_id"] == world.request.edition_id


def test_no_selected_own_occurrence_queries_no_unrelated_geometry(world, monkeypatch):
    manager = Mock()
    monkeypatch.setattr(
        geometry_queries.SchedulingPlacementRevision, "objects", manager
    )
    assert (
        geometry_queries._geometry(
            world.request, world.current, occurrence_ids={UUID(int=99)}
        )
        == {}
    )
    manager.filter.assert_not_called()
