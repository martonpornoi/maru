"""Own-presence comparison, minimization and stale-source composition without SQL."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.programme.timetable_queries import PersonalHostPurpose
from maru.scheduling import personal_release_impact as impact
from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_HOST_SELF,
    SchedulingAuthorizationDeniedError,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.personal_release_references import PersonalHostPresence
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_artifacts import ReleaseArtifactSelection
from maru.scheduling.release_queries import ProgrammeReleaseManifest
from maru.scheduling.release_queries import ProgrammeReleaseState as State
from maru.scheduling.time_rules import SchedulingEnvelope


@pytest.fixture
def world(monkeypatch):
    request = SchedulingReadRequest(*(UUID(int=n) for n in range(1, 5)))
    host = PersonalHostPurpose(
        UUID(int=5),
        UUID(int=6),
        "host",
        "confirmed",
        3,
        2,
        "Own invitation",
        "Own briefing",
    )
    start = datetime(2026, 9, 20, 10, tzinfo=UTC)
    end = start + timedelta(hours=1)
    presence = PersonalHostPresence(
        host.host_id,
        UUID(int=7),
        UUID(int=8),
        UUID(int=9),
        UUID(int=10),
        start - timedelta(hours=1),
        end + timedelta(hours=1),
        start,
        end,
        SchedulingEnvelope(start, start, end, end),
    )
    selection = ReleaseArtifactSelection(
        presence.occurrence_id, presence.placement_id, UUID(int=11)
    )
    current = ProgrammeReleaseManifest(
        State.AVAILABLE, 2, UUID(int=12), is_active=True, selections=(selection,)
    )
    previous = replace(current, release_id=UUID(int=13), is_active=False)
    release = SimpleNamespace(
        id=current.release_id,
        previous_release_id=previous.release_id,
        pointer_version=2,
    )
    manager = Mock()
    manager.filter.return_value.only.return_value.first.return_value = release
    monkeypatch.setattr(impact.SchedulingRelease, "objects", manager)
    purposes = Mock(return_value=(host,))
    monkeypatch.setattr(impact, "load_personal_host_purposes", purposes)
    manifest = Mock(side_effect=[current, previous, previous, current])
    monkeypatch.setattr(impact, "_manifest", manifest)
    presences = Mock(return_value=(presence,))
    monkeypatch.setattr(impact, "_presences", presences)
    return SimpleNamespace(
        request=request,
        host=host,
        presence=presence,
        selection=selection,
        current=current,
        previous=previous,
        release=release,
        manager=manager,
        purposes=purposes,
        manifest=manifest,
        presences=presences,
    )


def compare(world, *, before=None, after=None, previous=None, current=None):
    return impact._compare(
        {world.host.host_id: world.host},
        (world.presence,) if before is None else before,
        (world.presence,) if after is None else after,
        world.previous if previous is None else previous,
        world.current if current is None else current,
    )


def test_exact_self_authority_not_history_and_loader_runs_only_after_admission(
    world, monkeypatch
):
    reader = Mock(return_value=object())
    loader = Mock()
    monkeypatch.setattr(impact, "_read", reader)
    monkeypatch.setattr(impact, "_load", loader)
    result = impact.load_personal_host_release_impact(**asdict(world.request))
    assert result is reader.return_value
    loader.assert_not_called()
    options = reader.call_args.kwargs
    assert options["capability"] == VIEW_HOST_SELF
    assert options["fields"] == frozenset({"own_host_schedule"})
    assert options["authorizer"] is DEFAULT_SCHEDULING_AUTHORIZER
    assert options["purpose"] == "personal_host_release_impact"
    options["loader"](object())
    loader.assert_called_once_with(world.request)


def test_scheduling_denial_prevents_owner_or_release_lookup(world, monkeypatch):
    monkeypatch.setattr(
        impact, "_read", Mock(side_effect=SchedulingAuthorizationDeniedError)
    )
    with pytest.raises(SchedulingAuthorizationDeniedError):
        impact.load_personal_host_release_impact(**asdict(world.request))
    world.purposes.assert_not_called()
    world.manifest.assert_not_called()


@pytest.mark.parametrize(
    "error", [ProgrammeAuthorizationDeniedError, ProgrammeQueryUnavailableError]
)
def test_independent_owner_failure_is_not_an_empty_audience(world, error):
    world.purposes.side_effect = error
    with pytest.raises(error):
        impact._load(world.request)
    world.manifest.assert_not_called()
    world.manager.filter.assert_not_called()


@pytest.mark.parametrize("state", [None, "invited", "declined", "removed"])
def test_no_confirmed_purpose_learns_no_release_existence(world, state):
    world.purposes.return_value = (
        () if state is None else (replace(world.host, state=state),)
    )
    result = impact._load(world.request)
    assert all(value is None for value in asdict(result).values())
    assert world.purposes.call_count == 2
    world.manifest.assert_not_called()
    world.presences.assert_not_called()
    world.manager.filter.assert_not_called()


def test_retained_predecessor_exact_scope_and_minimized_unchanged_result(world):
    result = impact._load(world.request)
    assert result.state is State.AVAILABLE
    assert result.previous_state is State.AVAILABLE
    assert result.release_id == world.current.release_id
    assert result.previous_release_id == world.previous.release_id
    assert result.pointer_version == 2
    (change,) = result.changes
    assert change.kind == "unchanged"
    assert change.changed_fields == ()
    assert change.host_version == world.host.version
    assert change.invitation_sequence == world.host.invitation_sequence
    assert change.before == change.after == world.presence
    assert "Own invitation" not in repr(result)
    assert "Own briefing" not in repr(result)
    assert world.manager.filter.call_args.kwargs == {
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
        "id": world.current.release_id,
    }
    assert [call.kwargs["release_id"] for call in world.manifest.call_args_list] == [
        None,
        world.previous.release_id,
        world.previous.release_id,
        None,
    ]
    for call in world.manifest.call_args_list:
        assert call.kwargs["organization_id"] == world.request.organization_id
        assert call.kwargs["edition_id"] == world.request.edition_id
    for call in world.presences.call_args_list:
        assert call.args[0] == world.request
        assert call.args[2] == {world.host.host_id: world.host}
    assert world.purposes.call_args.kwargs == asdict(world.request)


def test_first_publication_is_actual_own_addition(world):
    world.release.previous_release_id = None
    world.manifest.side_effect = [world.current, world.current]
    result = impact._load(world.request)
    assert result.previous_state is State.ABSENT
    assert result.previous_release_id is None
    assert result.changes[0].kind == "added"
    assert result.changes[0].before is None
    world.presences.assert_called_once()


@pytest.mark.parametrize("state", [State.ABSENT, State.WITHDRAWN, State.INVALIDATED])
def test_suppressed_current_state_never_loads_predecessor_or_geometry(world, state):
    current = replace(
        world.current,
        state=state,
        selections=(),
        release_id=world.current.release_id if state is State.INVALIDATED else None,
    )
    world.manifest.side_effect = [current, current]
    result = impact._load(world.request)
    assert result.state is state
    assert result.previous_state is None
    assert result.previous_release_id is None
    assert result.changes is None
    world.manager.filter.assert_not_called()
    world.presences.assert_not_called()


@pytest.mark.parametrize("state", [State.WITHDRAWN, State.INVALIDATED])
def test_suppressed_predecessor_is_not_fabricated_mass_addition(world, state):
    previous = replace(world.previous, state=state, selections=())
    world.manifest.side_effect = [world.current, previous, previous, world.current]
    result = impact._load(world.request)
    assert result.previous_state is state
    assert result.changes is None
    world.presences.assert_not_called()


@pytest.mark.parametrize("source", ["person", "previous", "current", "mixed_version"])
def test_moving_purpose_or_native_evidence_withholds_every_result(world, source):
    if source == "person":
        world.purposes.side_effect = [
            (world.host,),
            (replace(world.host, state="removed"),),
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


@pytest.mark.parametrize("fault", ["missing", "version", "inactive", "no_identity"])
def test_current_publication_must_match_pointer_before_own_geometry(world, fault):
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
    world.presences.assert_not_called()


@pytest.mark.parametrize("side", ["before", "after"])
def test_own_presence_membership_is_not_whole_occurrence_membership(world, side):
    (change,) = compare(world, **{side: ()})
    assert change.kind == ("added" if side == "before" else "removed")
    assert change.changed_fields == ()
    assert getattr(change, side) is None
    assert world.previous.selections == world.current.selections


@pytest.mark.parametrize(
    "field",
    [
        "placement_id",
        "space_id",
        "day_id",
        "day_starts_at",
        "day_ends_at",
        "starts_at",
        "ends_at",
    ],
)
def test_exact_own_and_day_fields_are_classified_independently(world, field):
    old = getattr(world.presence, field)
    new = UUID(int=100) if isinstance(old, UUID) else old + timedelta(minutes=5)
    (change,) = compare(world, after=(replace(world.presence, **{field: new}),))
    assert change.kind == "changed"
    assert change.changed_fields == (field,)


@pytest.mark.parametrize(
    "field",
    ["setup_starts_at", "effective_starts_at", "effective_ends_at", "teardown_ends_at"],
)
def test_phase_change_does_not_silently_change_required_own_presence(world, field):
    envelope = replace(
        world.presence.envelope,
        **{field: getattr(world.presence.envelope, field) + timedelta(minutes=5)},
    )
    (change,) = compare(world, after=(replace(world.presence, envelope=envelope),))
    assert change.changed_fields == (field,)
    assert change.before.starts_at == change.after.starts_at
    assert change.before.ends_at == change.after.ends_at


def test_copy_reference_change_is_separate_from_presence_or_text_disclosure(world):
    current = replace(
        world.current,
        selections=(replace(world.selection, public_rendition_id=UUID(int=90)),),
    )
    (change,) = compare(world, current=current)
    assert change.kind == "changed"
    assert change.changed_fields == ("public_rendition_id",)
    assert change.before == change.after
    assert "public_rendition_id" not in asdict(change)


@pytest.mark.parametrize(
    "fault", ["duplicate", "foreign_host", "missing_selection", "oversized"]
)
def test_incomplete_or_oversized_own_sources_fail_closed(world, fault, monkeypatch):
    before = (world.presence,)
    previous = world.previous
    if fault == "duplicate":
        before *= 2
    elif fault == "foreign_host":
        before = (replace(world.presence, host_id=UUID(int=50)),)
    elif fault == "missing_selection":
        previous = replace(previous, selections=())
    else:
        monkeypatch.setattr(impact, "MAX_OCCURRENCES", 0)
    with pytest.raises(SchedulingUnavailableError):
        compare(world, before=before, previous=previous)


def test_empty_available_own_presence_is_not_suppression(world):
    world.presences.return_value = ()
    result = impact._load(world.request)
    assert result.state is result.previous_state is State.AVAILABLE
    assert result.changes == ()


def test_complete_disjoint_maximum_union_is_not_truncated(world):
    before = tuple(
        replace(world.presence, occurrence_id=UUID(int=100 + n))
        for n in range(impact.MAX_OCCURRENCES)
    )
    after = tuple(
        replace(world.presence, occurrence_id=UUID(int=3000 + n))
        for n in range(impact.MAX_OCCURRENCES)
    )
    previous = replace(
        world.previous,
        selections=tuple(
            replace(world.selection, occurrence_id=row.occurrence_id) for row in before
        ),
    )
    current = replace(
        world.current,
        selections=tuple(
            replace(world.selection, occurrence_id=row.occurrence_id) for row in after
        ),
    )
    result = compare(
        world, before=before, after=after, previous=previous, current=current
    )
    assert len(result) == 2 * impact.MAX_OCCURRENCES
    assert [row.occurrence_id for row in result] == sorted(
        row.occurrence_id for row in result
    )
    assert sum(row.kind == "added" for row in result) == impact.MAX_OCCURRENCES
    assert sum(row.kind == "removed" for row in result) == impact.MAX_OCCURRENCES
