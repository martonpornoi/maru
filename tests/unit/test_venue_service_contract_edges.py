"""Pure and adapter-edge coverage for Venues command invariants."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from maru.authorization.policy import PolicyDecision
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.venues import services
from maru.venues.models import (
    EditionSpaceSelection,
    VenueBooking,
    VenueCommandReceipt,
    VenueLayoutVersion,
    VenueProperty,
)
from maru.venues.services import (
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueAvailabilityInterval,
    VenueBookingEnvelope,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueCapacityProfile,
    VenuePropertyProfile,
    VenueResourceUnavailableError,
    VenueRetryConflictError,
)


def _actor(*, active: bool = True, identified: bool = True) -> Account:
    return Account(id=uuid4() if identified else None, is_active=active)


def _decision(*, allowed: bool) -> PolicyDecision:
    return PolicyDecision(
        allowed=allowed,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="synthetic_venue_decision",
    )


def _envelope(*, offset_hours: int = 0) -> VenueBookingEnvelope:
    start = datetime(2031, 8, 10, 9, tzinfo=UTC) + timedelta(hours=offset_hours)
    return VenueBookingEnvelope(
        setup_starts_at=start,
        effective_starts_at=start + timedelta(hours=1),
        effective_ends_at=start + timedelta(hours=2),
        teardown_ends_at=start + timedelta(hours=3),
    )


def _space_selection(**overrides: object) -> EditionSpaceSelection:
    values: dict[str, object] = {
        "id": uuid4(),
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "seated_capacity": 100,
        "standing_capacity": 150,
        "table_capacity": 60,
        "fire_capacity": 120,
        "current_availability_version": 1,
    }
    values.update(overrides)
    return EditionSpaceSelection(**values)


def test_command_identifiers_and_versions_are_strictly_typed() -> None:
    identifier = uuid4()
    assert services._require_uuid(identifier, field="id") == identifier
    assert services._require_expected_version(1) == 1
    assert services._validate_command_ids(
        idempotency_key=identifier,
        correlation_id=identifier,
    ) == (identifier, identifier)

    with pytest.raises(ValidationError):
        services._require_uuid(str(identifier), field="id")  # type: ignore[arg-type]
    for invalid in (True, 0, -1, "1"):
        with pytest.raises(ValidationError):
            services._require_expected_version(invalid)  # type: ignore[arg-type]


def test_property_profile_normalizes_multiline_and_public_values() -> None:
    values = services._normalize_profile(
        VenuePropertyProfile(
            kind=VenueProperty.Kind.MIXED,
            legal_name="  Synthetic   Venue Limited ",
            public_name=" Synthetic Venue ",
            public_description="Line one and line two",
            internal_notes="Restricted notes",
            location_name=" Budapest ",
            postal_address="1 Synthetic Street, Budapest",
            country_code="hu",
            website_url="https://example.invalid",
        )
    )
    assert values["legal_name"] == "Synthetic Venue Limited"
    assert values["country_code"] == "HU"
    assert values["public_description"] == "Line one and line two"

    with pytest.raises(ValidationError):
        services._normalize_profile(
            VenuePropertyProfile(
                kind="future_kind",
                legal_name="Synthetic",
                public_name="Synthetic",
                location_name="Budapest",
                postal_address="Address",
                country_code="HU",
            )
        )


def test_actor_and_policy_decision_fail_closed() -> None:
    for actor in (_actor(active=False), _actor(identified=False)):
        with pytest.raises(VenueAuthorizationDeniedError):
            services._require_actor(actor)

    actor = _actor()
    at = datetime(2031, 8, 1, tzinfo=UTC)
    target = MagicMock()
    with patch.object(
        services, "decide", return_value=_decision(allowed=True)
    ) as decide:
        result = services._require_decision(
            actor=actor,
            capability_code="venues.manage_properties",
            target=target,
            at=at,
        )
    assert result.allowed
    decide.assert_called_once_with(
        principal=actor,
        capability_code="venues.manage_properties",
        resource=target,
        at=at,
    )

    with (
        patch.object(services, "decide", return_value=_decision(allowed=False)),
        pytest.raises(VenueAuthorizationDeniedError),
    ):
        services._require_decision(
            actor=actor,
            capability_code="venues.manage_properties",
            target=target,
            at=at,
        )


def test_receipt_lookup_distinguishes_absence_replay_and_changed_intent() -> None:
    actor = _actor()
    key = uuid4()
    organization_id = uuid4()
    query = MagicMock()
    with patch.object(
        VenueCommandReceipt.objects,
        "select_for_update",
        return_value=query,
    ):
        query.filter.return_value.first.return_value = None
        assert (
            services._existing_receipt(
                actor=actor,
                operation="property_created",
                idempotency_key=key,
                organization_id=organization_id,
                request_digest="a" * 64,
            )
            is None
        )

        receipt = VenueCommandReceipt(
            id=uuid4(),
            organization_id=organization_id,
            result_object_id=uuid4(),
            request_digest="a" * 64,
            resulting_version=3,
        )
        query.filter.return_value.first.return_value = receipt
        assert (
            services._existing_receipt(
                actor=actor,
                operation="property_created",
                idempotency_key=key,
                organization_id=organization_id,
                request_digest="a" * 64,
            )
            is receipt
        )

        with pytest.raises(VenueRetryConflictError):
            services._existing_receipt(
                actor=actor,
                operation="property_created",
                idempotency_key=key,
                organization_id=uuid4(),
                request_digest="a" * 64,
            )
        with pytest.raises(VenueRetryConflictError):
            services._existing_receipt(
                actor=actor,
                operation="property_created",
                idempotency_key=key,
                organization_id=organization_id,
                request_digest="b" * 64,
            )


def test_result_helpers_preserve_replay_and_receipt_identity() -> None:
    receipt = VenueCommandReceipt(
        id=uuid4(),
        result_object_id=uuid4(),
        resulting_version=4,
    )
    replay = services._replayed_result(receipt)
    assert replay.object_id == receipt.result_object_id
    assert replay.receipt_id == receipt.id
    assert replay.resulting_version == 4
    assert replay.replayed is True

    object_id = uuid4()
    fresh = services._result(
        object_id=object_id,
        receipt=receipt,
        resulting_version=5,
    )
    assert fresh.object_id == object_id
    assert fresh.receipt_id == receipt.id
    assert fresh.resulting_version == 5
    assert fresh.replayed is False
    assert len(services._request_key_hash(uuid4())) == 64


def test_capacity_profile_requires_nonnegative_integer_capacities() -> None:
    normalized = services._normalized_capacity(
        VenueCapacityProfile(
            configuration_name="  Theatre   mode ",
            seated_capacity=100,
            standing_capacity=150,
            table_capacity=60,
            fire_capacity=180,
        )
    )
    assert normalized.configuration_name == "Theatre mode"

    for values in (
        (True, 1, 1, 1),
        (-1, 1, 1, 1),
        (1, 1, 1, 0),
    ):
        with pytest.raises(ValidationError):
            services._normalized_capacity(
                VenueCapacityProfile(
                    configuration_name="Mode",
                    seated_capacity=values[0],
                    standing_capacity=values[1],
                    table_capacity=values[2],
                    fire_capacity=values[3],
                )
            )


def test_availability_normalization_sorts_and_rejects_invalid_windows() -> None:
    first = VenueAvailabilityInterval(
        starts_at=datetime(2031, 8, 10, 9, tzinfo=UTC),
        ends_at=datetime(2031, 8, 10, 10, tzinfo=UTC),
        opening_restriction="  Staff   only ",
    )
    second = VenueAvailabilityInterval(
        starts_at=datetime(2031, 8, 10, 11, tzinfo=UTC),
        ends_at=datetime(2031, 8, 10, 12, tzinfo=UTC),
    )
    normalized = services._normalized_availability((second, first))
    assert normalized[0].starts_at == first.starts_at
    assert normalized[0].opening_restriction == "Staff   only"

    with pytest.raises(ValidationError):
        services._normalized_availability(())
    with pytest.raises(ValidationError):
        services._normalized_availability((first,) * 257)
    with pytest.raises(ValidationError):
        services._normalized_availability(
            (
                VenueAvailabilityInterval(
                    starts_at=datetime(2031, 8, 10, 9, tzinfo=UTC).replace(tzinfo=None),
                    ends_at=datetime(2031, 8, 10, 10, tzinfo=UTC).replace(tzinfo=None),
                ),
            )
        )
    with pytest.raises(ValidationError):
        services._normalized_availability(
            (
                VenueAvailabilityInterval(
                    starts_at=first.ends_at,
                    ends_at=first.starts_at,
                ),
            )
        )
    with pytest.raises(ValidationError):
        services._normalized_availability(
            (
                first,
                VenueAvailabilityInterval(
                    starts_at=first.starts_at + timedelta(minutes=30),
                    ends_at=first.ends_at + timedelta(minutes=30),
                ),
            )
        )


def test_booking_normalizers_close_types_order_and_catalog_choices() -> None:
    envelope = _envelope()
    assert services._normalized_booking_envelope(envelope) is envelope
    values = services._normalized_booking_values(
        kind=VenueBooking.Kind.PANEL,
        external_reference="  programme-1 ",
        internal_title="  Opening   panel ",
        public_title=" Opening panel ",
        public_description="Welcome to the convention",
        capacity_mode=VenueBooking.CapacityMode.SEATED,
        expected_attendance=80,
    )
    assert values["internal_title"] == "Opening panel"
    assert values["public_description"] == "Welcome to the convention"

    naive = VenueBookingEnvelope(
        setup_starts_at=datetime(2031, 8, 10, 9, tzinfo=UTC).replace(tzinfo=None),
        effective_starts_at=envelope.effective_starts_at,
        effective_ends_at=envelope.effective_ends_at,
        teardown_ends_at=envelope.teardown_ends_at,
    )
    with pytest.raises(ValidationError):
        services._normalized_booking_envelope(naive)
    unordered = VenueBookingEnvelope(
        setup_starts_at=envelope.effective_ends_at,
        effective_starts_at=envelope.effective_starts_at,
        effective_ends_at=envelope.effective_ends_at,
        teardown_ends_at=envelope.teardown_ends_at,
    )
    with pytest.raises(ValidationError):
        services._normalized_booking_envelope(unordered)

    invalid_values = (
        {
            "kind": "future",
            "capacity_mode": VenueBooking.CapacityMode.SEATED,
            "attendance": 1,
        },
        {"kind": VenueBooking.Kind.PANEL, "capacity_mode": "future", "attendance": 1},
        {
            "kind": VenueBooking.Kind.PANEL,
            "capacity_mode": VenueBooking.CapacityMode.SEATED,
            "attendance": True,
        },
        {
            "kind": VenueBooking.Kind.PANEL,
            "capacity_mode": VenueBooking.CapacityMode.SEATED,
            "attendance": 0,
        },
    )
    for invalid in invalid_values:
        with pytest.raises(ValidationError):
            services._normalized_booking_values(
                kind=str(invalid["kind"]),
                external_reference="",
                internal_title="Title",
                public_title="",
                public_description="",
                capacity_mode=str(invalid["capacity_mode"]),
                expected_attendance=invalid["attendance"],  # type: ignore[arg-type]
            )


def test_capacity_limit_uses_mode_and_fire_ceiling() -> None:
    space = _space_selection()
    assert (
        services._capacity_limit(
            space_selection=space,
            capacity_mode=VenueBooking.CapacityMode.SEATED,
        )
        == 100
    )
    assert (
        services._capacity_limit(
            space_selection=space,
            capacity_mode=VenueBooking.CapacityMode.STANDING,
        )
        == 120
    )
    assert (
        services._capacity_limit(
            space_selection=space,
            capacity_mode=VenueBooking.CapacityMode.TABLE,
        )
        == 60
    )
    with pytest.raises(VenueCapacityConflictError):
        services._capacity_limit(
            space_selection=_space_selection(table_capacity=0),
            capacity_mode=VenueBooking.CapacityMode.TABLE,
        )


def test_available_capacity_requires_version_containment_and_capacity() -> None:
    space = _space_selection()
    envelope = _envelope()
    with patch.object(
        services.EditionSpaceAvailabilityWindow.objects,
        "filter",
    ) as filter_rows:
        filter_rows.return_value.exists.return_value = True
        services._require_available_capacity(
            space_selection=space,
            envelope=envelope,
            capacity_mode=VenueBooking.CapacityMode.SEATED,
            expected_attendance=100,
        )
        filter_rows.return_value.exists.return_value = False
        with pytest.raises(VenueAvailabilityConflictError):
            services._require_available_capacity(
                space_selection=space,
                envelope=envelope,
                capacity_mode=VenueBooking.CapacityMode.SEATED,
                expected_attendance=80,
            )

    with pytest.raises(VenueCapacityConflictError):
        services._require_available_capacity(
            space_selection=space,
            envelope=envelope,
            capacity_mode=VenueBooking.CapacityMode.SEATED,
            expected_attendance=101,
        )
    with pytest.raises(VenueAvailabilityConflictError):
        services._require_available_capacity(
            space_selection=_space_selection(current_availability_version=0),
            envelope=envelope,
            capacity_mode=VenueBooking.CapacityMode.SEATED,
            expected_attendance=80,
        )


def test_public_layout_validation_is_optional_closed_and_approved() -> None:
    space = _space_selection()
    assert (
        services._validate_public_layout(
            organization_id=space.organization_id,
            space_selection=space,
            public_layout_id=None,
        )
        is None
    )
    member_query = MagicMock()
    layout_query = MagicMock()
    layout = VenueLayoutVersion(id=uuid4())
    with (
        patch.object(
            services.EditionSpaceMember.objects,
            "filter",
            return_value=member_query,
        ),
        patch.object(
            services.VenueLayoutVersion.objects,
            "filter",
            return_value=layout_query,
        ),
    ):
        member_query.values_list.return_value = (uuid4(),)
        layout_query.exclude.return_value.first.return_value = layout
        assert (
            services._validate_public_layout(
                organization_id=space.organization_id,
                space_selection=space,
                public_layout_id=layout.id,
            )
            is layout
        )
        layout_query.exclude.return_value.first.return_value = None
        with pytest.raises(VenueResourceUnavailableError):
            services._validate_public_layout(
                organization_id=space.organization_id,
                space_selection=space,
                public_layout_id=uuid4(),
            )


def _booking() -> VenueBooking:
    organization = Organization(id=uuid4())
    edition = EventEdition(id=uuid4(), organization=organization)
    space = EditionSpaceSelection(
        id=uuid4(),
        organization=organization,
        edition=edition,
    )
    envelope = _envelope()
    return VenueBooking(
        id=uuid4(),
        organization=organization,
        edition=edition,
        space_selection=space,
        aggregate_version=2,
        setup_starts_at=envelope.setup_starts_at,
        effective_starts_at=envelope.effective_starts_at,
        effective_ends_at=envelope.effective_ends_at,
        teardown_ends_at=envelope.teardown_ends_at,
        review_state=VenueBooking.ReviewState.APPROVED,
        publication_state=VenueBooking.PublicationState.UNPUBLISHED,
        lifecycle=VenueBooking.Lifecycle.ACTIVE,
    )


def test_booking_history_projects_old_and_new_state_without_private_adapter_logic() -> (
    None
):
    booking = _booking()
    old = _envelope(offset_hours=-4)
    with (
        patch.object(services, "venue_writer", return_value=nullcontext()),
        patch.object(services.VenueBookingHistory.objects, "create") as create,
    ):
        services._append_booking_history(
            booking=booking,
            actor=_actor(),
            action="rescheduled",
            reason="Move the booking.",
            occurred_at=datetime(2031, 8, 1, tzinfo=UTC),
            old_envelope=old,
            old_review_state=VenueBooking.ReviewState.DRAFT,
            old_publication_state=VenueBooking.PublicationState.PUBLISHED,
            old_lifecycle=VenueBooking.Lifecycle.ACTIVE,
        )
    values = create.call_args.kwargs
    assert values["old_setup_starts_at"] == old.setup_starts_at
    assert values["new_setup_starts_at"] == booking.setup_starts_at
    assert values["to_review_state"] == VenueBooking.ReviewState.APPROVED

    with (
        patch.object(services, "venue_writer", return_value=nullcontext()),
        patch.object(services.VenueBookingHistory.objects, "create") as create,
    ):
        services._append_booking_history(
            booking=booking,
            actor=_actor(),
            action="created",
            reason="Create the booking.",
            occurred_at=datetime(2031, 8, 1, tzinfo=UTC),
        )
    assert create.call_args.kwargs["old_setup_starts_at"] is None


def test_booking_occupancy_requires_members_and_translates_exclusion_conflict() -> None:
    booking = _booking()
    members = MagicMock()
    with patch.object(
        services.EditionSpaceMember.objects,
        "filter",
        return_value=members,
    ):
        members.order_by.return_value.values_list.return_value = ()
        with pytest.raises(services.VenueStateConflictError):
            services._write_booking_occupancy(booking=booking)

        members.order_by.return_value.values_list.return_value = (uuid4(), uuid4())
        with (
            patch.object(services.transaction, "atomic", return_value=nullcontext()),
            patch.object(services, "venue_writer", return_value=nullcontext()),
            patch.object(
                services.VenueBookingOccupancy.objects,
                "bulk_create",
            ) as bulk_create,
        ):
            services._write_booking_occupancy(booking=booking)
            assert len(bulk_create.call_args.args[0]) == 4
            bulk_create.side_effect = IntegrityError("synthetic overlap")
            with pytest.raises(VenueBookingOverlapError):
                services._write_booking_occupancy(booking=booking)


def test_booking_envelope_reads_persisted_operational_times() -> None:
    booking = _booking()
    envelope = services._booking_envelope(booking)
    assert envelope.setup_starts_at == booking.setup_starts_at
    assert envelope.teardown_ends_at == booking.teardown_ends_at
