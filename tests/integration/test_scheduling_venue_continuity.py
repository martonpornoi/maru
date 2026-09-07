"""Independent Venue decisions cannot silently change Programme intent."""

from dataclasses import replace
from uuid import uuid4

import pytest

from maru.authorization.models import ScopedResourceBinding
from maru.identity.models import Account
from maru.scheduling.occurrence_commands import retire_scheduling_occurrence
from maru.venues.models import (
    VenueBooking,
    VenueBookingOccupancy,
    VenueSchedulingBinding,
)
from maru.venues.services import (
    VenueBookingEnvelope,
    VenueIndependentApprovalError,
    VenueStateConflictError,
    approve_venue_booking,
    cancel_venue_booking,
    publish_venue_booking,
    reschedule_venue_booking,
)
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration.test_scheduling_placements import next_request, place
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_reservations import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_reservations import reserve

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def grant(actor, world, capability="venues.manage_space_schedule"):
    binding = ScopedResourceBinding.objects.get(
        resource_kind="venue.edition_space",
        resource_id=world.placement.space_selection_id,
    )
    CapabilityGrantFactory(
        organization_id=world.request.organization_id,
        edition_id=world.request.edition_id,
        department_id=binding.department_id,
        resource_binding=binding,
        principal=actor,
        capability_code=capability,
    )


def command(booking, actor):
    return {
        "actor": actor,
        "organization_id": booking.organization_id,
        "edition_id": booking.edition_id,
        "space_selection_id": booking.space_selection_id,
        "booking_id": booking.id,
        "expected_version": booking.aggregate_version,
        "reason": "Independent synthetic Venue decision",
        "idempotency_key": uuid4(),
        "correlation_id": uuid4(),
        "source_channel": "test",
    }


@pytest.mark.parametrize("author_state", ["active", "inactive", "unverified"])
def test_placement_author_cannot_approve_even_when_another_person_reserved(
    world, admitted, author_state
):
    placed = place(world)
    reserver = AccountFactory()
    grant(reserver, world)
    placement_author = Account.objects.get(id=world.request.actor_id)
    verified_at = placement_author.email_verified_at
    if author_state == "inactive":
        Account.objects.filter(id=placement_author.id).update(is_active=False)
    elif author_state == "unverified":
        Account.objects.filter(id=placement_author.id).update(email_verified_at=None)
    reserve(
        world, placed=placed, request=replace(next_request(world), actor_id=reserver.id)
    )
    booking = VenueBooking.objects.get()
    assert VenueSchedulingBinding.objects.get(booking=booking).source_actor_id == (
        placement_author.id
    )
    # Historical authorship remains an approval exclusion after account recovery.
    Account.objects.filter(id=placement_author.id).update(
        is_active=True, email_verified_at=verified_at
    )
    placement_author.refresh_from_db()
    with pytest.raises(VenueIndependentApprovalError):
        approve_venue_booking(**command(booking, placement_author))
    approver = AccountFactory()
    grant(approver, world)
    result = approve_venue_booking(**command(booking, approver))
    booking.refresh_from_db()
    assert result.resulting_version == booking.aggregate_version == 2
    assert booking.approved_by_id == approver.id
    assert booking.review_state == "approved"
    assert booking.publication_state == "unpublished"
    assert set(
        VenueBookingOccupancy.objects.filter(active=True).values_list(
            "booking_version", flat=True
        )
    ) == {1}


def test_generic_reschedule_cannot_rewrite_a_linked_placement(world, admitted):
    reserve(world)
    booking = VenueBooking.objects.get()
    actor = Account.objects.get(id=world.request.actor_id)
    with pytest.raises(VenueStateConflictError):
        reschedule_venue_booking(
            **command(booking, actor),
            kind=booking.kind,
            external_reference="",
            internal_title="Attempted generic rewrite",
            public_title="",
            public_description="",
            capacity_mode=booking.capacity_mode,
            expected_attendance=booking.expected_attendance,
            envelope=VenueBookingEnvelope(
                booking.setup_starts_at,
                booking.effective_starts_at,
                booking.effective_ends_at,
                booking.teardown_ends_at,
            ),
            public_layout_id=None,
        )
    booking.refresh_from_db()
    assert booking.internal_title == "Programme reservation"
    assert booking.aggregate_version == 1


def test_generic_publication_is_denied_after_independent_venue_approval(
    world, admitted
):
    reserve(world)
    booking = VenueBooking.objects.get()
    approver = AccountFactory()
    grant(approver, world)
    approve_venue_booking(**command(booking, approver))
    booking.refresh_from_db()
    publisher = AccountFactory()
    grant(publisher, world, "venues.publish_space_schedule")
    with pytest.raises(VenueStateConflictError):
        publish_venue_booking(**command(booking, publisher))
    booking.refresh_from_db()
    assert booking.publication_state == "unpublished"


def test_generic_cancel_releases_hold_and_allows_explicit_occurrence_retirement(
    world, admitted
):
    reserve(world)
    booking = VenueBooking.objects.get()
    actor = Account.objects.get(id=world.request.actor_id)
    kwargs = {
        "occurrence_id": world.occurrence.object_id,
        "expected_version": world.occurrence.version,
        "authorizer": world.policy,
    }
    with pytest.raises(VenueStateConflictError):
        retire_scheduling_occurrence(next_request(world), **kwargs)
    cancel_venue_booking(**command(booking, actor))
    retired = retire_scheduling_occurrence(next_request(world), **kwargs)
    assert retired.version == world.occurrence.version + 1
    assert VenueSchedulingBinding.objects.count() == 1
    assert not VenueBookingOccupancy.objects.filter(active=True).exists()
