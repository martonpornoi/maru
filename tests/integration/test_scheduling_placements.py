"""Real Programme/Venue seams and immutable candidate placement independence."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections

import maru.effects.services as effect_services
from maru.authorization.policy import PolicyDecision
from maru.programme import scheduling_queries as programme_source
from maru.programme.host_inputs import ProgrammeHostAvailabilityPeriod
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.scheduling import occurrence_commands, placement_commands
from maru.scheduling.candidate_commands import (
    copy_scheduling_candidate,
    create_scheduling_candidate,
    remove_scheduling_placement,
    restore_scheduling_candidate,
)
from maru.scheduling.command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.day_commands import (
    create_scheduling_service_day,
    revise_scheduling_service_day,
)
from maru.scheduling.inputs import (
    SchedulingCommandRequest,
    SchedulingOccurrenceInput,
    SchedulingPlacementInput,
    SchedulingServiceDayInput,
)
from maru.scheduling.models import (
    SchedulingCandidate,
    SchedulingCandidateMember,
    SchedulingCandidateRevision,
    SchedulingCommandReceipt,
    SchedulingEditionControl,
    SchedulingPlacementHostPresence,
    SchedulingPlacementRevision,
)
from maru.scheduling.occurrence_commands import create_scheduling_occurrence
from maru.scheduling.placement_commands import set_scheduling_placement
from maru.scheduling.time_rules import (
    SchedulingEnvelope,
    SchedulingHostPresence,
    SchedulingWindow,
)
from maru.venues import scheduling_queries as venue_source
from maru.venues.models import VenueBooking
from maru.venues.services import (
    VenueAvailabilityInterval,
    set_edition_space_availability,
)
from tests.factories import AccountFactory
from tests.integration import test_programme_hosts as hosting
from tests.integration import test_venues as venues
from tests.integration.test_programme_commands import (
    _create,
    _TrustedProgrammeAuthorizer,
)
from tests.integration.test_scheduling_days import TrustedSchedulingPolicy

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
START = datetime(2030, 8, 2, 8, tzinfo=UTC)


@dataclass
class PlanningWorld:
    request: object
    policy: object
    day: object
    occurrence: object
    candidate: object
    placement: SchedulingPlacementInput


@pytest.fixture
def world(monkeypatch):
    return planning_world(monkeypatch)


def planning_world(monkeypatch, *, starts_at=START, host_account=None):
    monkeypatch.setattr(
        effect_services, "require_effect_delivery_allowed", lambda **_kwargs: None
    )
    scope = venues._scope(starts_on=starts_at.date())
    space = venues._selected_space(scope)
    venues._grant_space(scope.scheduler, scope, space, "venues.manage_space_schedule")
    set_edition_space_availability(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        expected_version=1,
        intervals=(
            VenueAvailabilityInterval(
                starts_at, starts_at + timedelta(hours=12), "Synthetic restriction"
            ),
        ),
        reason="Synthetic room availability",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    programme_policy = _TrustedProgrammeAuthorizer()
    item, _, _ = _create(
        actor=scope.scheduler, edition=scope.edition, authorizer=programme_policy
    )
    host_world = (
        scope.scheduler,
        host_account or AccountFactory(),
        {
            "organization_id": scope.edition.organization_id,
            "edition_id": scope.edition.id,
            "item_id": item.item_id,
            "authorizer": programme_policy,
            "source_channel": "test",
        },
    )
    host = hosting.share(
        host_world,
        hosting.respond(host_world, hosting.invite(host_world)),
        periods=(
            ProgrammeHostAvailabilityPeriod(starts_at, starts_at + timedelta(hours=2)),
        ),
    )
    monkeypatch.setattr(
        programme_source, "profile_allows_conflict_source", lambda *_args: True
    )
    for module in (occurrence_commands, placement_commands):
        monkeypatch.setattr(
            module,
            "load_programme_scheduling_dependencies",
            partial(
                programme_source.load_programme_scheduling_dependencies,
                authorizer=programme_policy,
            ),
        )
    monkeypatch.setattr(
        venue_source, "profile_allows_conflict_source", lambda *_args: True
    )
    monkeypatch.setattr(
        venue_source,
        "decide_verified_principal_exact_resource",
        lambda **kwargs: PolicyDecision(
            allowed=True,
            fields=kwargs["requested_fields"],
            obligations=frozenset({"audit"}),
            reason_code="sealed_future_profile_harness",
        ),
    )
    policy = TrustedSchedulingPolicy()
    request = SchedulingCommandRequest(
        scope.scheduler.id,
        scope.edition.organization_id,
        scope.edition.id,
        uuid4(),
        uuid4(),
        "Synthetic timetable draft",
        "test",
    )
    day = create_scheduling_service_day(
        request,
        day=SchedulingServiceDayInput(
            "Friday", SchedulingWindow(starts_at, starts_at + timedelta(hours=12)), 5
        ),
        expected_control_version=0,
        authorizer=policy,
    )
    occurrence = create_scheduling_occurrence(
        replace(request, idempotency_key=uuid4()),
        occurrence=SchedulingOccurrenceInput(item.item_id),
        expected_control_version=1,
        authorizer=policy,
    )
    candidate = create_scheduling_candidate(
        replace(request, idempotency_key=uuid4()),
        label="First draft",
        expected_control_version=2,
        authorizer=policy,
    )
    envelope = SchedulingEnvelope(
        starts_at,
        starts_at + timedelta(minutes=15),
        starts_at + timedelta(hours=1),
        starts_at + timedelta(hours=1, minutes=15),
    )
    placement = SchedulingPlacementInput(
        occurrence.object_id,
        1,
        day.object_id,
        1,
        space.id,
        envelope,
        "seated",
        80,
        (
            SchedulingHostPresence(
                host.host_id, envelope.effective_starts_at, envelope.effective_ends_at
            ),
        ),
    )
    return PlanningWorld(request, policy, day, occurrence, candidate, placement)


def next_request(world):
    return replace(world.request, idempotency_key=uuid4(), correlation_id=uuid4())


def place(world, *, intent=None, version=1, request=None):
    return set_scheduling_placement(
        request or next_request(world),
        candidate_id=world.candidate.object_id,
        placement=intent or world.placement,
        expected_version=version,
        authorizer=world.policy,
    )


def candidate_revision(result):
    return SchedulingCandidateRevision.objects.get(
        candidate_id=result.object_id, sequence=result.version
    )


def member(result):
    return SchedulingCandidateMember.objects.get(revision=candidate_revision(result))


def moved(world):
    delta = timedelta(minutes=30)
    base = world.placement.envelope
    return replace(
        world.placement,
        envelope=SchedulingEnvelope(
            base.setup_starts_at + delta,
            base.effective_starts_at + delta,
            base.effective_ends_at + delta,
            base.teardown_ends_at + delta,
        ),
        host_presences=tuple(
            replace(
                host, starts_at=host.starts_at + delta, ends_at=host.ends_at + delta
            )
            for host in world.placement.host_presences
        ),
    )


def test_explicit_placement_has_presence_not_copied_personal_availability(world):
    placed = place(world)
    row = member(placed).placement
    assert row.occurrence_revision.occurrence_id == world.occurrence.object_id
    assert row.host_presence_count == 1
    presence = SchedulingPlacementHostPresence.objects.get(placement=row)
    assert presence.starts_at == START + timedelta(minutes=15)
    assert presence.ends_at == START + timedelta(hours=1)
    assert row.setup_starts_at < presence.starts_at
    assert row.teardown_ends_at > presence.ends_at
    assert not VenueBooking.objects.exists()


def test_copy_move_remove_and_restore_preserve_other_candidate_and_occurrence(world):
    first = place(world)
    first_revision = candidate_revision(first)
    original_placement = member(first).placement_id
    copied = copy_scheduling_candidate(
        next_request(world),
        source_revision_id=first_revision.id,
        label="Alternative",
        expected_control_version=4,
        authorizer=world.policy,
    )
    changed = place(world, intent=moved(world), version=2)
    assert member(changed).placement_id != original_placement
    assert member(copied).placement_id == original_placement
    assert member(changed).occurrence_id == member(copied).occurrence_id
    removed = remove_scheduling_placement(
        next_request(world),
        candidate_id=world.candidate.object_id,
        occurrence_id=world.occurrence.object_id,
        expected_version=3,
        authorizer=world.policy,
    )
    assert candidate_revision(removed).placement_count == 0
    assert member(copied).placement_id == original_placement
    restored = restore_scheduling_candidate(
        next_request(world),
        candidate_id=world.candidate.object_id,
        source_revision_id=first_revision.id,
        expected_version=4,
        authorizer=world.policy,
    )
    assert member(restored).placement_id == original_placement
    assert SchedulingPlacementRevision.objects.count() == 2
    assert not VenueBooking.objects.exists()


def test_exact_retry_does_not_reapply_geometry_or_require_old_candidate_version(world):
    request = next_request(world)
    first = place(world, request=request)
    changed = place(world, intent=moved(world), version=2)
    retried = place(world, request=request)
    assert retried == replace(first, replayed=True)
    assert SchedulingCandidate.objects.get(id=changed.object_id).aggregate_version == 3
    assert SchedulingPlacementRevision.objects.count() == 2


def test_stale_candidate_edit_does_not_leave_an_orphan_placement(world):
    place(world)
    with pytest.raises(SchedulingVersionConflictError):
        place(world, intent=moved(world), version=1)
    assert SchedulingPlacementRevision.objects.count() == 1
    assert (
        SchedulingCommandReceipt.objects.filter(operation="placement_set").count() == 1
    )


def test_stale_day_revision_is_not_silently_substituted(world):
    revise_scheduling_service_day(
        next_request(world),
        day_id=world.day.object_id,
        day=SchedulingServiceDayInput(
            "Revised Friday", SchedulingWindow(START, START + timedelta(hours=11)), 10
        ),
        expected_version=1,
        authorizer=world.policy,
    )
    with pytest.raises(SchedulingUnavailableError):
        place(world)
    assert not SchedulingPlacementRevision.objects.exists()


def test_foreign_or_missing_host_purpose_is_not_accepted_as_a_host(world):
    intent = replace(
        world.placement,
        host_presences=(replace(world.placement.host_presences[0], host_id=uuid4()),),
    )
    with pytest.raises(ProgrammeQueryUnavailableError):
        place(world, intent=intent)
    assert not SchedulingPlacementRevision.objects.exists()


def test_unknown_physical_selection_cannot_be_persisted(world):
    with pytest.raises(venue_source.VenueSchedulingSourceDeniedError):
        place(world, intent=replace(world.placement, space_selection_id=uuid4()))
    assert not SchedulingPlacementRevision.objects.exists()


def test_conflicting_capacity_and_missing_host_selection_remain_unapproved_draft(world):
    result = place(
        world,
        intent=replace(world.placement, expected_attendance=1000, host_presences=()),
    )
    assert member(result).placement.expected_attendance == 1000
    assert member(result).placement.host_presence_count == 0
    assert not VenueBooking.objects.exists()


def test_late_manifest_insertion_failure_rolls_back_placement_and_sources(
    world, monkeypatch
):
    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic manifest failure")

    monkeypatch.setattr(SchedulingCandidateMember.objects, "bulk_create", fail)
    with pytest.raises(RuntimeError, match="manifest failure"):
        place(world)
    assert SchedulingEditionControl.objects.get().aggregate_version == 3
    assert not SchedulingPlacementRevision.objects.exists()
    assert not SchedulingPlacementHostPresence.objects.exists()
    assert SchedulingCandidateRevision.objects.count() == 1


def test_competing_candidate_placements_have_one_exact_version_winner(world):
    barrier = Barrier(2)

    def compete(intent):
        close_old_connections()
        try:
            barrier.wait(timeout=20)
            try:
                place(world, intent=intent)
            except SchedulingVersionConflictError:
                return "stale"
            else:
                return "placed"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(compete, (world.placement, moved(world))))
    assert sorted(outcomes) == ["placed", "stale"]
    assert SchedulingPlacementRevision.objects.count() == 1
    assert SchedulingCandidateMember.objects.count() == 1
