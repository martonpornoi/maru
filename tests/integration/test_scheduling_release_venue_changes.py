"""Native Venue changes retain exact physical release consequences."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction

from maru.scheduling.models import (
    SchedulingReleaseDependencyChange,
    SchedulingReleaseDependencyKey,
)
from maru.scheduling.writer_boundary import scheduling_writer
from maru.venues.models import (
    EditionVenueSelection,
    VenueBooking,
    VenueBookingOccupancy,
    VenueProperty,
    VenueSpace,
)
from maru.venues.services import (
    VenueAvailabilityInterval,
    approve_venue_booking,
    cancel_venue_booking,
    publish_venue_booking,
    set_edition_space_availability,
    update_venue_property,
    withdraw_venue_booking_publication,
)
from tests.integration.test_venues import (
    _configure_schedule,
    _create_booking,
    _scope,
    _selected_space,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def world():
    scope = _scope()
    space = _selected_space(scope)
    start = _configure_schedule(scope, space)
    return scope, space, start


def _track(world, kind, source_id):
    scope = world[0]
    with transaction.atomic(), scheduling_writer():
        return SchedulingReleaseDependencyKey.objects.create(
            kind=kind,
            source_id=source_id,
            organization_id=scope.edition.organization_id,
            edition_id=None
            if kind in {"venue_property", "venue_member"}
            else scope.edition.id,
        )


def _property_change(world, **changes):
    scope, space, _ = world
    record = VenueProperty.objects.get(pk=space.venue_selection.property_id)
    return update_venue_property(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        property_id=record.id,
        expected_version=record.aggregate_version,
        changes=changes,
        reason="Synthetic property change",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"location_name": "Synthetic new location"},
        {"postal_address": "Synthetic new address"},
        {"country_code": "AT"},
        {"lifecycle": "retired"},
    ],
)
def test_property_operational_change_records_native_generation(world, changes):
    key = _track(world, "venue_property", world[1].venue_selection.property_id)
    result = _property_change(world, **changes)
    key.refresh_from_db()
    change = SchedulingReleaseDependencyChange.objects.get()
    assert key.generation == change.generation == 2
    assert change.source_audit.target_id == result.object_id
    assert change.source_audit.operation == "venues.catalog.add"
    assert change.edition_id is None


@pytest.mark.parametrize("field", ["internal_notes", "contact_name", "public_name"])
def test_property_private_or_label_change_does_not_invalidate_physical_source(
    world, field
):
    key = _track(world, "venue_property", world[1].venue_selection.property_id)
    _property_change(world, **{field: "Synthetic changed text"})
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_skipped_native_venue_join_cannot_commit_source_change(world):
    key = _track(world, "venue_property", world[1].venue_selection.property_id)
    with (
        patch("maru.venues.services.record_venues_release_change"),
        pytest.raises(IntegrityError, match="exact native release invalidation"),
    ):
        _property_change(world, location_name="Synthetic rejected change")
    key.refresh_from_db()
    assert key.generation == 1
    assert VenueProperty.objects.get(pk=key.source_id).location_name == "Budapest"
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_raw_tracked_member_change_without_native_command_is_rejected(world):
    key = _track(world, "venue_member", world[1].source_space_id)
    with (
        pytest.raises(IntegrityError, match="exact native release invalidation"),
        transaction.atomic(),
    ):
        VenueSpace.objects.filter(pk=key.source_id).update(is_active=False)
    assert VenueSpace.objects.get(pk=key.source_id).is_active
    assert not SchedulingReleaseDependencyChange.objects.exists()


def _change_availability(world):
    scope, space, start = world
    space.refresh_from_db()
    set_edition_space_availability(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        expected_version=space.aggregate_version,
        intervals=(
            VenueAvailabilityInterval(
                starts_at=start,
                ends_at=start + timedelta(hours=11),
                opening_restriction="Synthetic availability adjustment",
            ),
        ),
        reason="Synthetic availability change",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_selection_availability_change_records_exact_source(world):
    key = _track(world, "venue_selection", world[1].id)
    _change_availability(world)
    key.refresh_from_db()
    assert key.generation == 2
    assert (
        SchedulingReleaseDependencyChange.objects.get().source_audit.operation
        == "venues.availability.set"
    )


def _booking_action(world, booking, command, actor):
    scope, space, _ = world
    booking.refresh_from_db()
    return command(
        actor=actor,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=space.id,
        booking_id=booking.id,
        expected_version=booking.aggregate_version,
        reason="Synthetic native booking change",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )


def test_booking_approval_and_cancellation_both_record_native_generations(world):
    scope, space, start = world
    created = _create_booking(scope, space, start=start)
    booking = VenueBooking.objects.get(pk=created.object_id)
    key = _track(world, "venue_booking", booking.id)
    _booking_action(world, booking, approve_venue_booking, scope.approver)
    _booking_action(world, booking, cancel_venue_booking, scope.scheduler)
    key.refresh_from_db()
    assert key.generation == 3
    assert set(
        SchedulingReleaseDependencyChange.objects.values_list(
            "source_audit__operation",
            flat=True,
        )
    ) == {"venues.booking.approve", "venues.booking.cancel"}


def test_venue_public_projection_does_not_cancel_programme_physical_evidence(world):
    scope, space, start = world
    created = _create_booking(scope, space, start=start)
    booking = VenueBooking.objects.get(pk=created.object_id)
    _booking_action(world, booking, approve_venue_booking, scope.approver)
    key = _track(world, "venue_booking", booking.id)
    _booking_action(world, booking, publish_venue_booking, scope.publisher)
    _booking_action(world, booking, withdraw_venue_booking_publication, scope.publisher)
    key.refresh_from_db()
    booking.refresh_from_db()
    assert key.generation == 1
    assert booking.review_state == "approved"
    assert booking.lifecycle == "active"
    assert not SchedulingReleaseDependencyChange.objects.exists()


def test_multiple_native_source_versions_in_outer_transaction_are_attributed_exactly(
    world,
):
    key = _track(world, "venue_property", world[1].venue_selection.property_id)
    with transaction.atomic():
        _property_change(world, location_name="Synthetic first move")
        _property_change(world, location_name="Synthetic second move")
    key.refresh_from_db()
    assert key.generation == 3
    assert SchedulingReleaseDependencyChange.objects.count() == 2


def test_raw_selected_venue_retirement_cannot_invalidate_tracked_space_silently(world):
    key = _track(world, "venue_selection", world[1].id)
    with (
        pytest.raises(IntegrityError, match="tracked selected venue"),
        transaction.atomic(),
    ):
        EditionVenueSelection.objects.filter(pk=world[1].venue_selection_id).update(
            lifecycle="retired"
        )
    key.refresh_from_db()
    assert key.generation == 1
    assert (
        EditionVenueSelection.objects.get(pk=world[1].venue_selection_id).lifecycle
        == "active"
    )


def test_raw_physical_membership_cannot_expand_a_tracked_selection(world):
    _track(world, "venue_selection", world[1].id)
    with (
        pytest.raises(IntegrityError, match="tracked physical membership"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO public.venues_editionspacemember "
            "(id, created_at, updated_at, organization_id, edition_id, "
            "space_selection_id, source_space_id) "
            "SELECT gen_random_uuid(), clock_timestamp(), clock_timestamp(), "
            "organization_id, edition_id, space_selection_id, source_space_id "
            "FROM public.venues_editionspacemember WHERE space_selection_id = %s",
            [world[1].id],
        )


def test_raw_current_availability_append_cannot_change_a_sealed_source(world):
    _track(world, "venue_selection", world[1].id)
    with (
        pytest.raises(IntegrityError, match="sealed physical source version"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO public.venues_editionspaceavailabilitywindow "
            "(id, created_at, updated_at, organization_id, edition_id, "
            "space_selection_id, availability_version, starts_at, ends_at, "
            "opening_restriction) "
            "SELECT gen_random_uuid(), clock_timestamp(), clock_timestamp(), "
            "organization_id, edition_id, space_selection_id, availability_version, "
            "starts_at + interval '1 minute', ends_at, opening_restriction "
            "FROM public.venues_editionspaceavailabilitywindow "
            "WHERE space_selection_id = %s",
            [world[1].id],
        )


def test_raw_occupancy_deactivation_cannot_silently_free_a_release_reservation(world):
    scope, space, start = world
    created = _create_booking(scope, space, start=start)
    _track(world, "venue_booking", created.object_id)
    with (
        pytest.raises(IntegrityError, match="sealed physical source version"),
        transaction.atomic(),
    ):
        VenueBookingOccupancy.objects.filter(booking_id=created.object_id).update(
            active=False
        )
    assert (
        VenueBookingOccupancy.objects.filter(
            booking_id=created.object_id, active=True
        ).count()
        == 2
    )


def test_same_transaction_raw_append_after_native_receipt_is_also_rejected(world):
    _track(world, "venue_selection", world[1].id)
    with transaction.atomic():
        _change_availability(world)
        # The outer transaction still contains its fresh native Audit witness,
        # but the recorded source version is sealed and cannot gain more rows.
        with (
            pytest.raises(IntegrityError, match="sealed physical source version"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO public.venues_editionspaceavailabilitywindow "
                "(id, created_at, updated_at, organization_id, edition_id, "
                "space_selection_id, availability_version, starts_at, ends_at, "
                "opening_restriction) "
                "SELECT gen_random_uuid(), clock_timestamp(), clock_timestamp(), "
                "organization_id, edition_id, space_selection_id, "
                "availability_version, "
                "starts_at + interval '1 minute', ends_at, opening_restriction "
                "FROM public.venues_editionspaceavailabilitywindow "
                "WHERE space_selection_id = %s "
                "ORDER BY availability_version DESC LIMIT 1",
                [world[1].id],
            )


@pytest.mark.parametrize("kind", ["venue_property", "venue_selection", "venue_booking"])
def test_first_capture_after_completed_native_change_in_same_transaction_is_current(
    world, kind
):
    with transaction.atomic():
        if kind == "venue_property":
            _property_change(world, location_name="Synthetic pre-capture move")
            source = world[1].venue_selection.property_id
        elif kind == "venue_selection":
            _change_availability(world)
            source = world[1].id
        else:
            scope, space, start = world
            created = _create_booking(scope, space, start=start)
            booking = VenueBooking.objects.get(pk=created.object_id)
            _booking_action(world, booking, approve_venue_booking, scope.approver)
            source = booking.id
        key = _track(world, kind, source)
    key.refresh_from_db()
    assert key.generation == 1
    assert not SchedulingReleaseDependencyChange.objects.filter(dependency=key).exists()


def test_later_change_after_first_capture_in_same_transaction_still_invalidates(world):
    with transaction.atomic():
        _property_change(world, location_name="Synthetic captured move")
        key = _track(world, "venue_property", world[1].venue_selection.property_id)
        _property_change(world, location_name="Synthetic later move")
    key.refresh_from_db()
    assert key.generation == 2
    assert SchedulingReleaseDependencyChange.objects.filter(dependency=key).count() == 1


def test_first_tracking_rejects_unsealed_source_version(world):
    property_id = world[1].venue_selection.property_id

    def attempt_unsealed_tracking():
        with transaction.atomic():
            record = VenueProperty.objects.get(pk=property_id)
            VenueProperty.objects.filter(pk=property_id).update(
                aggregate_version=record.aggregate_version + 1
            )
            _track(world, "venue_property", property_id)

    with pytest.raises(IntegrityError, match="sealed native source version"):
        attempt_unsealed_tracking()


@pytest.mark.parametrize("change", ["same_version_operational", "regress_version"])
def test_tracked_source_cannot_reuse_or_regress_its_initial_version(world, change):
    key = _track(world, "venue_property", world[1].venue_selection.property_id)
    record = VenueProperty.objects.get(pk=key.source_id)
    changes = (
        {"location_name": "Synthetic raw change"}
        if change == "same_version_operational"
        else {"aggregate_version": record.aggregate_version - 1}
    )
    with (
        pytest.raises(IntegrityError, match="one new native version"),
        transaction.atomic(),
    ):
        VenueProperty.objects.filter(pk=key.source_id).update(**changes)
    key.refresh_from_db()
    assert key.generation == 1
