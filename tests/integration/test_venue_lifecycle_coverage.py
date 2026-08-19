"""End-to-end venue catalog, accommodation, and booking lifecycle coverage."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from maru.venues.models import (
    AccommodationNightInventory,
    AccommodationRoomType,
    VenueBooking,
    VenueLayoutVersion,
    VenuePropertyMedia,
    VenueSpace,
    VenueSpaceCombination,
)
from maru.venues.services import (
    VenueBookingEnvelope,
    VenueSpaceCatalogInput,
    VenueVersionConflictError,
    add_venue_layout_version,
    add_venue_property_media,
    approve_venue_booking,
    approve_venue_layout_version,
    approve_venue_property_media,
    cancel_venue_booking,
    create_accommodation_room_type,
    create_venue_space_catalog_path,
    create_venue_space_combination,
    publish_venue_booking,
    reschedule_venue_booking,
    set_accommodation_night_inventory,
    withdraw_venue_booking_publication,
)
from tests.factories import AccountFactory
from tests.integration import test_venues as venue_scenarios

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def test_governed_venue_assets_inventory_and_booking_lifecycle() -> None:
    scope = venue_scenarios._scope()
    selected_space = venue_scenarios._selected_space(scope)
    property_record = selected_space.venue_selection.property
    primary_space = selected_space.source_space
    assert primary_space is not None

    reviewer = AccountFactory()
    venue_scenarios._grant_organization(
        reviewer,
        scope,
        "venues.manage_properties",
    )
    venue_scenarios._grant_organization(
        scope.manager,
        scope,
        "venues.manage_accommodation",
    )

    secondary_catalog = create_venue_space_catalog_path(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        property_id=property_record.id,
        catalog=VenueSpaceCatalogInput(
            site_code="annex-site",
            site_name="Annex site",
            building_code="annex-wing",
            building_name="Annex wing",
            space_code="breakout-room",
            space_name="Breakout room",
            space_kind=VenueSpace.Kind.FUNCTION_ROOM,
            configuration_code="classroom",
            configuration_name="Classroom",
            seated_capacity=40,
            standing_capacity=60,
            table_capacity=24,
            fire_capacity=70,
            public_description="An attendee breakout room.",
            accessibility_features="Step-free route.",
            known_barriers="",
            equipment_facts="Portable projection.",
        ),
        reason="Register the second physical room.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    secondary_space = VenueSpace.objects.get(id=secondary_catalog.object_id)
    combination = create_venue_space_combination(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        property_id=property_record.id,
        code="combined-halls",
        name="Combined halls",
        member_space_ids=(primary_space.id, secondary_space.id),
        reason="Represent the contracted combined-room configuration.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert (
        VenueSpaceCombination.objects.get(id=combination.object_id).members.count() == 2
    )

    media_key = uuid4()
    media_correlation = uuid4()
    media_values = {
        "actor": scope.manager,
        "organization_id": scope.edition.organization_id,
        "property_id": property_record.id,
        "kind": VenuePropertyMedia.Kind.PHOTO,
        "source_reference": "provider://venue/front-elevation",
        "owner_name": "Riverside Hospitality",
        "license_basis": "Provider contract",
        "usage_scope": "Edition venue listing",
        "attribution": "Riverside Hospitality",
        "expires_at": timezone.now() + timedelta(days=365),
        "reason": "Record the licensed property photograph.",
        "idempotency_key": media_key,
        "correlation_id": media_correlation,
        "source_channel": "test",
    }
    media = add_venue_property_media(**media_values)
    assert add_venue_property_media(**media_values).replayed is True
    approved_media = approve_venue_property_media(
        actor=reviewer,
        organization_id=scope.edition.organization_id,
        property_id=property_record.id,
        media_id=media.object_id,
        expected_version=media.resulting_version,
        public_reference="https://media.example.invalid/venue/front.webp",
        reason="Approve the public-safe rendition independently.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert approved_media.resulting_version == 2

    layout = add_venue_layout_version(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        space_id=primary_space.id,
        layout_code="attendee-plan",
        version=1,
        title="Attendee plan",
        visibility=VenueLayoutVersion.Visibility.PUBLIC,
        source_reference="provider://venue/layout-v1",
        checksum_sha256="a" * 64,
        notes="Public circulation paths only.",
        reason="Register the provider layout artifact.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    approved_layout = approve_venue_layout_version(
        actor=reviewer,
        organization_id=scope.edition.organization_id,
        layout_id=layout.object_id,
        expected_version=layout.resulting_version,
        approved_reference="https://media.example.invalid/layouts/attendee-plan.pdf",
        reason="Approve the attendee-safe layout independently.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert approved_layout.resulting_version == 2

    room_type = create_accommodation_room_type(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        property_id=property_record.id,
        code="accessible-twin",
        public_name="Accessible twin",
        description="Twin room in the convention hotel.",
        accessible_features="Step-free access and roll-in shower.",
        minimum_occupants=1,
        maximum_occupants=2,
        provider_reference="provider-room-type-17",
        reason="Register the contracted accommodation type.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    inventory_night = scope.edition.starts_on
    inventory = set_accommodation_night_inventory(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        room_type_id=room_type.object_id,
        night=inventory_night,
        room_capacity=12,
        release_at=timezone.now() + timedelta(days=2),
        provider_reference="allotment-2026-01",
        expected_version=None,
        reason="Record the initial contracted room allotment.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    updated_inventory = set_accommodation_night_inventory(
        actor=scope.manager,
        organization_id=scope.edition.organization_id,
        room_type_id=room_type.object_id,
        night=inventory_night,
        room_capacity=10,
        release_at=timezone.now() + timedelta(days=3),
        provider_reference="allotment-2026-02",
        expected_version=inventory.resulting_version,
        reason="Accept the provider's revised room allotment.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert AccommodationRoomType.objects.filter(id=room_type.object_id).exists()
    assert (
        AccommodationNightInventory.objects.get(
            id=updated_inventory.object_id
        ).room_capacity
        == 10
    )

    schedule_start = venue_scenarios._configure_schedule(scope, selected_space)
    booking = venue_scenarios._create_booking(
        scope,
        selected_space,
        start=schedule_start,
    )
    rescheduled = reschedule_venue_booking(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=selected_space.id,
        booking_id=booking.object_id,
        expected_version=booking.resulting_version,
        kind=VenueBooking.Kind.PANEL,
        external_reference="programme-panel-17",
        internal_title="Revised production title",
        public_title="Revised opening panel",
        public_description="Welcome to the revised opening panel.",
        capacity_mode=VenueBooking.CapacityMode.SEATED,
        expected_attendance=75,
        envelope=VenueBookingEnvelope(
            setup_starts_at=schedule_start + timedelta(hours=3),
            effective_starts_at=schedule_start + timedelta(hours=4),
            effective_ends_at=schedule_start + timedelta(hours=5),
            teardown_ends_at=schedule_start + timedelta(hours=6),
        ),
        public_layout_id=layout.object_id,
        reason="Move the panel after the programme revision.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    approved = approve_venue_booking(
        actor=scope.approver,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=selected_space.id,
        booking_id=booking.object_id,
        expected_version=rescheduled.resulting_version,
        reason="Approve the revised operational envelope.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    publish_key = uuid4()
    publish_correlation = uuid4()
    publish_values = {
        "actor": scope.publisher,
        "organization_id": scope.edition.organization_id,
        "edition_id": scope.edition.id,
        "space_selection_id": selected_space.id,
        "booking_id": booking.object_id,
        "expected_version": approved.resulting_version,
        "reason": "Publish the independently approved attendee item.",
        "idempotency_key": publish_key,
        "correlation_id": publish_correlation,
        "source_channel": "test",
    }
    published = publish_venue_booking(**publish_values)
    assert publish_venue_booking(**publish_values).replayed is True
    withdrawn = withdraw_venue_booking_publication(
        actor=scope.publisher,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=selected_space.id,
        booking_id=booking.object_id,
        expected_version=published.resulting_version,
        reason="Withdraw the item after the programme cancellation.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    cancelled = cancel_venue_booking(
        actor=scope.scheduler,
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        space_selection_id=selected_space.id,
        booking_id=booking.object_id,
        expected_version=withdrawn.resulting_version,
        reason="Release the physical room after withdrawal.",
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        source_channel="test",
    )
    assert VenueBooking.objects.get(id=booking.object_id).lifecycle == "cancelled"
    with pytest.raises(VenueVersionConflictError):
        cancel_venue_booking(
            actor=scope.scheduler,
            organization_id=scope.edition.organization_id,
            edition_id=scope.edition.id,
            space_selection_id=selected_space.id,
            booking_id=booking.object_id,
            expected_version=withdrawn.resulting_version,
            reason="Reject a stale cancellation retry under a new key.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    assert cancelled.resulting_version > booking.resulting_version
