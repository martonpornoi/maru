"""Reciprocal physical evidence survives bypasses of application validation."""

from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction

from maru.venues import scheduling_reservations as adapter
from maru.venues import services
from maru.venues.models import (
    VenueBooking,
    VenueBookingOccupancy,
    VenueSchedulingBinding,
)
from tests.integration.test_scheduling_placements import place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_reservations import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_reservations import reserve

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_binding_cannot_be_changed_deleted_or_truncated(world, admitted):
    reserve(world)
    link = VenueSchedulingBinding.objects.get()
    for sql in (
        "UPDATE venues_venueschedulingbinding "
        "SET occurred_at = occurred_at WHERE id = %s",
        "DELETE FROM venues_venueschedulingbinding WHERE id = %s",
    ):
        with (
            pytest.raises(DatabaseError, match="immutable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(sql, [link.id])
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        with (
            pytest.raises(DatabaseError, match="cannot be truncated"),
            transaction.atomic(),
        ):
            cursor.execute("TRUNCATE venues_venueschedulingbinding")
    assert VenueSchedulingBinding.objects.filter(id=link.id).exists()


def test_linked_booking_cannot_be_rewritten_or_self_approved_with_raw_sql(
    world, admitted
):
    reserve(world)
    booking = VenueBooking.objects.get()
    assignments = (
        "internal_title = 'Changed private content'",
        "effective_ends_at = effective_ends_at + interval '5 minutes'",
        "publication_state = 'published', review_state = 'approved'",
        "review_state = 'approved', approved_by_id = created_by_id, "
        "approved_at = CURRENT_TIMESTAMP",
        "lifecycle = 'cancelled'",
    )
    for assignment in assignments:
        sql = (
            "UPDATE venues_venuebooking "
            "SET aggregate_version = aggregate_version + 1, "
            + assignment
            + " WHERE id = %s"
        )
        with (
            pytest.raises(DatabaseError),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(sql, [booking.id])
    booking.refresh_from_db()
    assert booking.aggregate_version == 1
    assert booking.review_state == "draft"
    assert booking.lifecycle == "active"
    assert (
        VenueBookingOccupancy.objects.filter(booking=booking, active=True).count() == 2
    )


def test_linked_occupancy_cannot_be_silently_released(world, admitted):
    reserve(world)
    booking = VenueBooking.objects.get()
    with (
        pytest.raises(DatabaseError, match="complete physical reservation"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE venues_venuebookingoccupancy "
            "SET active = FALSE WHERE booking_id = %s",
            [booking.id],
        )
    assert VenueBookingOccupancy.objects.filter(active=True).count() == 2


def test_omitting_reciprocal_binding_cannot_commit_a_physical_hold(
    world, admitted, monkeypatch
):
    placed = place(world)
    monkeypatch.setattr(
        VenueSchedulingBinding.objects, "create", lambda **_kwargs: None
    )
    with pytest.raises(DatabaseError, match="exact new Venue binding"):
        reserve(world, placed=placed)
    assert not VenueBooking.objects.exists()
    assert not VenueBookingOccupancy.objects.exists()


def test_omitting_venue_effects_rolls_back_both_owners(world, admitted, monkeypatch):
    placed = place(world)
    monkeypatch.setattr(
        services, "publish_domain_event", lambda *_args, **_kwargs: None
    )
    with pytest.raises(DatabaseError, match="history and effects"):
        reserve(world, placed=placed)
    assert not VenueBooking.objects.exists()
    assert not VenueSchedulingBinding.objects.exists()


def test_cross_occurrence_binding_regression_fails_closed(world, admitted, monkeypatch):
    placed = place(world)
    original = VenueSchedulingBinding.objects.create

    def wrong_occurrence(**kwargs):
        kwargs["occurrence_id"] = uuid4()
        return original(**kwargs)

    monkeypatch.setattr(
        adapter.VenueSchedulingBinding.objects, "create", wrong_occurrence
    )
    with pytest.raises(DatabaseError, match="exact newly reserved placement"):
        reserve(world, placed=placed)
    assert not VenueBooking.objects.exists()


def test_nested_parent_transaction_keeps_reciprocal_evidence_valid(world, admitted):
    with transaction.atomic():
        placed = place(world)
        with transaction.atomic():
            reserve(world, placed=placed)
    assert VenueBooking.objects.count() == VenueSchedulingBinding.objects.count() == 1
