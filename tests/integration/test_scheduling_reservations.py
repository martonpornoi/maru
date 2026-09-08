"""Real reciprocal reservations, independent physical authority and atomic failure."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from threading import Barrier

import pytest
from django.db import DatabaseError, close_old_connections, transaction

from maru.authorization.policy import PolicyDecision
from maru.scheduling import command_support, reservation_sources
from maru.scheduling.candidate_commands import archive_scheduling_candidate
from maru.scheduling.catalogs import SchedulingOperation
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.day_commands import retire_scheduling_service_day
from maru.scheduling.models import SchedulingCommandReceipt, SchedulingReservationIntent
from maru.scheduling.planning_record_actions import submit_planning_record
from maru.scheduling.reservation_commands import (
    SchedulingReservationInput,
    change_scheduling_reservation,
)
from maru.venues import scheduling_reservations as adapter
from maru.venues.models import (
    VenueBooking,
    VenueBookingHistory,
    VenueBookingOccupancy,
    VenueSchedulingBinding,
)
from maru.venues.services import (
    VenueAuthorizationDeniedError,
    VenueCapacityConflictError,
    VenueResourceUnavailableError,
    VenueVersionConflictError,
)
from tests.integration.test_scheduling_candidates import read_request, record_form
from tests.integration.test_scheduling_placements import (
    member,
    moved,
    next_request,
    place,
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def admitted(world, monkeypatch):
    admit_reservations(world, monkeypatch)


def admit_reservations(world, monkeypatch):
    monkeypatch.setattr(
        reservation_sources, "profile_allows_adapter", lambda *_args: True
    )
    monkeypatch.setattr(adapter, "profile_allows_adapter", lambda *_args: True)
    monkeypatch.setattr(
        adapter,
        "resolve_scheduling_reservation_source",
        partial(
            reservation_sources.resolve_scheduling_reservation_source,
            authorizer=world.policy,
        ),
    )


def intent(world, placed, previous=None):
    return SchedulingReservationInput(
        world.candidate.object_id,
        placed.version,
        member(placed).placement_id,
        previous.id if previous else None,
        previous.aggregate_version if previous else 0,
    )


def reserve(
    world,
    *,
    placed=None,
    previous=None,
    request=None,
    operation=SchedulingOperation.RESERVATION_REPLACE,
):
    placed = placed or place(world)
    result = change_scheduling_reservation(
        request or next_request(world),
        reservation=intent(world, placed, previous),
        operation=operation,
        authorizer=world.policy,
    )
    return result, SchedulingReservationIntent.objects.get(id=result.object_id)


def test_current_profiles_do_not_activate_physical_reservation(world):
    placed = place(world)
    with pytest.raises(VenueResourceUnavailableError):
        reserve(world, placed=placed)
    assert not SchedulingReservationIntent.objects.exists()
    assert not VenueBooking.objects.exists()


def reservation_form(world, placed, *, previous=None, cancel=False):
    return record_form(
        SchedulingOperation.RESERVATION_CANCEL
        if cancel
        else SchedulingOperation.RESERVATION_REPLACE,
        candidate_id=world.candidate.object_id,
        candidate_version=placed.version,
        placement_id=member(placed).placement_id,
        previous_booking_id=previous.id if previous else "",
        expected_booking_version=previous.aggregate_version if previous else 0,
        confirm="confirmed",
    )


def test_native_physical_replace_unplace_and_historical_cancel_are_independent(
    world, admitted
):
    placed = place(world)
    scope = read_request(world)
    first = submit_planning_record(
        scope, reservation_form(world, placed), authorizer=world.policy
    )
    old = VenueBooking.objects.get(
        id=SchedulingReservationIntent.objects.get(id=first.object_id).target_booking_id
    )
    changed = place(world, intent=moved(world), version=placed.version)
    old.refresh_from_db()
    assert old.lifecycle == "active"
    assert old.aggregate_version == 1
    second_form = reservation_form(world, changed, previous=old)
    second = submit_planning_record(scope, second_form, authorizer=world.policy)
    current = VenueBooking.objects.get(
        id=SchedulingReservationIntent.objects.get(
            id=second.object_id
        ).target_booking_id
    )
    old.refresh_from_db()
    assert old.lifecycle == "cancelled"
    replay = submit_planning_record(scope, second_form, authorizer=world.policy)
    assert replay.replayed
    assert replay.receipt_id == second.receipt_id
    assert VenueBooking.objects.count() == 2
    submit_planning_record(
        scope,
        record_form(
            SchedulingOperation.PLACEMENT_REMOVE,
            candidate_id=changed.object_id,
            occurrence_id=world.occurrence.object_id,
            expected_version=changed.version,
            confirm="confirmed",
        ),
        authorizer=world.policy,
    )
    current.refresh_from_db()
    assert current.lifecycle == "active"
    assert current.aggregate_version == 1
    cancelled = submit_planning_record(
        scope,
        reservation_form(world, changed, previous=current, cancel=True),
        authorizer=world.policy,
    )
    current.refresh_from_db()
    assert current.lifecycle == "cancelled"
    assert (
        SchedulingReservationIntent.objects.get(
            id=cancelled.object_id
        ).target_booking_id
        is None
    )
    assert not VenueBookingOccupancy.objects.filter(active=True).exists()
    assert VenueSchedulingBinding.objects.count() == 2


def test_native_failed_physical_replacement_retains_old_hold_and_entered_intent(
    world, admitted
):
    placed = place(world)
    _, reserved = reserve(world, placed=placed)
    old = VenueBooking.objects.get(id=reserved.target_booking_id)
    impossible = place(
        world,
        intent=replace(moved(world), expected_attendance=9_000),
        version=placed.version,
    )
    form = reservation_form(world, impossible, previous=old)
    original = dict(form.data)
    before = SchedulingCommandReceipt.objects.count()
    with pytest.raises(VenueCapacityConflictError):
        submit_planning_record(read_request(world), form, authorizer=world.policy)
    old.refresh_from_db()
    assert old.lifecycle == "active"
    assert old.aggregate_version == 1
    assert VenueBooking.objects.count() == VenueSchedulingBinding.objects.count() == 1
    assert SchedulingCommandReceipt.objects.count() == before
    assert dict(form.data) == original


def test_both_owners_receive_exact_evidence_without_copying_private_layers(
    world, admitted
):
    placed = place(world)
    request = replace(
        next_request(world), reason="Explicitly Venue-visible physical hold"
    )
    result, source = reserve(world, placed=placed, request=request)
    booking = VenueBooking.objects.get(id=source.target_booking_id)
    binding = VenueSchedulingBinding.objects.get(booking=booking)
    assert booking.internal_title == "Programme reservation"
    assert (
        booking.public_title
        == booking.public_description
        == booking.external_reference
        == ""
    )
    assert booking.review_state == "draft"
    assert booking.publication_state == "unpublished"
    assert binding.placement_id == member(placed).placement_id
    assert binding.occurrence_id == world.occurrence.object_id
    assert binding.source_actor_id == world.request.actor_id
    assert source.command_receipt_id == result.receipt_id
    assert source.venue_receipt.result_object_id == booking.id
    assert source.venue_receipt.operation == "booking.create"
    assert VenueBookingHistory.objects.get(booking=booking).reason == request.reason
    assert (
        VenueBookingOccupancy.objects.filter(booking=booking, active=True).count() == 2
    )
    replay, same = reserve(world, placed=placed, request=request)
    assert replay.replayed
    assert same.id == source.id
    assert VenueBooking.objects.count() == 1


def test_source_proof_cannot_be_reused_outside_its_parent_command(world, admitted):
    _, source = reserve(world)
    with transaction.atomic(), pytest.raises(SchedulingUnavailableError):
        reservation_sources.resolve_scheduling_reservation_source(
            actor_id=world.request.actor_id,
            organization_id=world.request.organization_id,
            edition_id=world.request.edition_id,
            intent_id=source.id,
            authorizer=world.policy,
        )


def test_replacement_keeps_cancelled_history_and_only_one_active_hold(world, admitted):
    placed = place(world)
    _, first = reserve(world, placed=placed)
    old = VenueBooking.objects.get(id=first.target_booking_id)
    changed = place(world, intent=moved(world), version=placed.version)
    _, second = reserve(world, placed=changed, previous=old)
    old.refresh_from_db()
    assert old.lifecycle == "cancelled"
    assert old.aggregate_version == 2
    assert second.target_booking_id != old.id
    assert VenueSchedulingBinding.objects.count() == 2
    assert VenueBooking.objects.filter(lifecycle="active").count() == 1
    assert not VenueBookingOccupancy.objects.filter(booking=old, active=True).exists()
    assert VenueBookingHistory.objects.filter(booking=old).count() == 2


def test_failed_replacement_restores_old_occupancy_and_both_owner_histories(
    world, admitted
):
    placed = place(world)
    _, first = reserve(world, placed=placed)
    old = VenueBooking.objects.get(id=first.target_booking_id)
    impossible = place(
        world,
        intent=replace(moved(world), expected_attendance=9_000),
        version=placed.version,
    )
    before = SchedulingCommandReceipt.objects.count()
    with pytest.raises(VenueCapacityConflictError):
        reserve(world, placed=impossible, previous=old)
    old.refresh_from_db()
    assert old.lifecycle == "active"
    assert old.aggregate_version == 1
    assert VenueBooking.objects.count() == VenueSchedulingBinding.objects.count() == 1
    assert VenueBookingHistory.objects.filter(booking=old).count() == 1
    assert VenueBookingOccupancy.objects.filter(booking=old, active=True).count() == 2
    assert SchedulingReservationIntent.objects.count() == 1
    assert SchedulingCommandReceipt.objects.count() == before


def test_cancel_retains_source_and_binding_but_releases_physical_occupancy(
    world, admitted
):
    placed = place(world)
    _, first = reserve(world, placed=placed)
    old = VenueBooking.objects.get(id=first.target_booking_id)
    _, cancelled = reserve(
        world,
        placed=placed,
        previous=old,
        operation=SchedulingOperation.RESERVATION_CANCEL,
    )
    old.refresh_from_db()
    assert old.lifecycle == "cancelled"
    assert cancelled.target_booking_id is None
    assert cancelled.venue_receipt.result_object_id == old.id
    assert cancelled.venue_receipt.operation == "booking.cancel"
    assert VenueSchedulingBinding.objects.count() == 1
    assert not VenueBookingOccupancy.objects.filter(active=True).exists()


def test_independent_venue_policy_denial_rolls_back_scheduling_intent(
    world, admitted, monkeypatch
):
    placed = place(world)
    monkeypatch.setattr(
        adapter,
        "decide_verified_principal_exact_resource",
        lambda **_kwargs: PolicyDecision(
            allowed=False,
            reason_code="synthetic_venue_denial",
            fields=frozenset(),
            obligations=frozenset(),
        ),
    )
    with pytest.raises(VenueAuthorizationDeniedError):
        reserve(world, placed=placed)
    assert not SchedulingReservationIntent.objects.exists()
    assert not VenueBooking.objects.exists()


def test_parent_evidence_failure_rolls_back_a_completed_venue_adapter(
    world, admitted, monkeypatch
):
    placed = place(world)

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic parent evidence failure")

    monkeypatch.setattr(command_support, "publish_domain_event", fail)
    with pytest.raises(RuntimeError, match="synthetic parent"):
        reserve(world, placed=placed)
    assert not SchedulingReservationIntent.objects.exists()
    assert not VenueBooking.objects.exists()
    assert not VenueBookingHistory.objects.exists()
    assert not VenueBookingOccupancy.objects.exists()
    assert not VenueSchedulingBinding.objects.exists()


def test_concurrent_initial_reservations_have_one_winner(world, admitted):
    placed = place(world)
    selected = intent(world, placed)
    barrier = Barrier(2)

    def attempt():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                change_scheduling_reservation(
                    next_request(world),
                    reservation=selected,
                    operation=SchedulingOperation.RESERVATION_REPLACE,
                    authorizer=world.policy,
                )
            except VenueVersionConflictError:
                return "stale"
            else:
                return "reserved"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == [
            "reserved",
            "stale",
        ]
    assert (
        VenueBooking.objects.count() == SchedulingReservationIntent.objects.count() == 1
    )


def test_historical_cancel_remains_possible_after_candidate_archive_and_day_retirement(
    world, admitted
):
    placed = place(world)
    _, source = reserve(world, placed=placed)
    booking = VenueBooking.objects.get(id=source.target_booking_id)
    archive_scheduling_candidate(
        next_request(world),
        candidate_id=world.candidate.object_id,
        expected_version=placed.version,
        authorizer=world.policy,
    )
    retire_scheduling_service_day(
        next_request(world),
        day_id=world.day.object_id,
        expected_version=world.day.version,
        authorizer=world.policy,
    )
    reserve(
        world,
        placed=placed,
        previous=booking,
        operation=SchedulingOperation.RESERVATION_CANCEL,
    )
    booking.refresh_from_db()
    assert booking.lifecycle == "cancelled"
    assert VenueSchedulingBinding.objects.count() == 1
    assert not VenueBookingOccupancy.objects.filter(active=True).exists()


@pytest.mark.parametrize("bypass_application_freshness", [False, True])
def test_retired_day_cannot_acquire_a_new_physical_hold(
    world, admitted, monkeypatch, bypass_application_freshness
):
    placed = place(world)
    retire_scheduling_service_day(
        next_request(world),
        day_id=world.day.object_id,
        expected_version=world.day.version,
        authorizer=world.policy,
    )
    if bypass_application_freshness:
        monkeypatch.setattr(
            reservation_sources,
            "_require_current_physical_intent",
            lambda _source: None,
        )
    error = (
        DatabaseError if bypass_application_freshness else SchedulingUnavailableError
    )
    with pytest.raises(error):
        reserve(world, placed=placed)
    assert not SchedulingReservationIntent.objects.exists()
    assert not VenueBooking.objects.exists()
    assert not VenueBookingOccupancy.objects.exists()
