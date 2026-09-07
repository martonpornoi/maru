"""Venue-owned physical reservations from live, exact Scheduling command proof."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_resource,
)
from maru.events.adoption import profile_allows_adapter
from maru.events.queries import edition_adoption_profile_reference
from maru.scheduling.reservation_sources import resolve_scheduling_reservation_source

from .adoption import VENUES_SCHEDULING_RESERVATION_ADAPTER
from .bindings import edition_space_binding_id
from .inputs import canonical_digest, normalized_source_channel
from .models import (
    EditionSpaceSelection,
    VenueBooking,
    VenueBookingHistory,
    VenueBookingOccupancy,
    VenueCommandReceipt,
    VenueSchedulingBinding,
)
from .physical_locks import _lock_physical_scope
from .services import (
    SPACE_MANAGE_CAPABILITY,
    VenueAuthorizationDeniedError,
    VenueBookingEnvelope,
    VenueCommandResult,
    VenueResourceUnavailableError,
    VenueStateConflictError,
    VenueVersionConflictError,
    _append_booking_history_ids,
    _append_evidence_ids,
    _booking_envelope,
    _require_available_capacity,
    _write_booking_occupancy,
)
from .writer_boundary import venue_writer

if TYPE_CHECKING:
    from datetime import datetime

    from maru.scheduling.reservation_sources import SchedulingReservationSource


def _require_adapter(organization_id: UUID, edition_id: UUID) -> None:
    profile = edition_adoption_profile_reference(
        organization_id=organization_id, edition_id=edition_id
    )
    if profile is None or not profile_allows_adapter(
        profile.code, profile.version, VENUES_SCHEDULING_RESERVATION_ADAPTER
    ):
        raise VenueResourceUnavailableError


def _authorize(actor_id: UUID, space: EditionSpaceSelection) -> PolicyDecision:
    decision = decide_verified_principal_exact_resource(
        principal_id=actor_id,
        organization_id=space.organization_id,
        edition_id=space.edition_id,
        department_id=space.responsible_department_id,
        resource_binding_id=edition_space_binding_id(space.id),
        capability_code=SPACE_MANAGE_CAPABILITY,
    )
    if not isinstance(decision, PolicyDecision) or not decision.allowed:
        raise VenueAuthorizationDeniedError
    return decision


def _spaces(source: SchedulingReservationSource) -> tuple[EditionSpaceSelection, ...]:
    ids = {source.space_selection_id}
    if source.previous_booking_id is not None:
        previous_space = (
            VenueBooking.objects.filter(
                id=source.previous_booking_id,
                organization_id=source.organization_id,
                edition_id=source.edition_id,
            )
            .values_list("space_selection_id", flat=True)
            .first()
        )
        if previous_space is None:
            raise VenueResourceUnavailableError
        ids.add(previous_space)
    spaces = tuple(
        EditionSpaceSelection.objects.filter(
            id__in=ids,
            organization_id=source.organization_id,
            edition_id=source.edition_id,
        ).order_by("id")
    )
    if len(spaces) != len(ids):
        raise VenueResourceUnavailableError
    for space in spaces:
        _authorize(source.actor_id, space)
    _lock_physical_scope(
        actor_id=source.actor_id,
        organization_id=source.organization_id,
        edition_id=source.edition_id,
        selection_ids=tuple(sorted(ids)),
    )
    for space in spaces:
        space.refresh_from_db()
        _authorize(source.actor_id, space)
    return spaces


def _current_booking(source: SchedulingReservationSource) -> VenueBooking | None:
    active = tuple(
        VenueSchedulingBinding.objects.filter(
            organization_id=source.organization_id,
            edition_id=source.edition_id,
            occurrence_id=source.occurrence_id,
            booking__lifecycle="active",
        ).values_list("booking_id", flat=True)[:2]
    )
    expected = (
        () if source.previous_booking_id is None else (source.previous_booking_id,)
    )
    if active != expected:
        raise VenueVersionConflictError
    if not active:
        return None
    booking = VenueBooking.objects.select_for_update(of=("self",)).get(
        id=active[0],
        organization_id=source.organization_id,
        edition_id=source.edition_id,
    )
    if booking.aggregate_version != source.expected_booking_version:
        raise VenueVersionConflictError
    if (
        source.operation == "reservation_cancel"
        and not VenueSchedulingBinding.objects.filter(
            booking=booking, placement_id=source.placement_id
        ).exists()
    ):
        raise VenueVersionConflictError
    return booking


def _evidence(
    source: SchedulingReservationSource,
    booking: VenueBooking,
    *,
    decision: PolicyDecision,
    action: str,
    operation: str,
    receipt_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    occurred_at: datetime,
) -> VenueCommandReceipt:
    return _append_evidence_ids(
        actor_id=source.actor_id,
        organization_id=source.organization_id,
        edition_id=source.edition_id,
        operation=operation,
        idempotency_key=source.intent_id,
        request_digest=canonical_digest(
            {"source": asdict(source), "operation": operation}
        ),
        result_object_id=booking.id,
        resulting_version=booking.aggregate_version,
        correlation_id=correlation_id,
        request_id=correlation_id,
        source_channel=source_channel,
        capability_code=SPACE_MANAGE_CAPABILITY,
        decision=decision,
        changed_fields=("lifecycle", "physical_occupancy"),
        aggregate_type="venues.booking",
        aggregate_id=booking.id,
        action=action,
        occurred_at=occurred_at,
        receipt_id=receipt_id,
    )


def _cancel(
    source: SchedulingReservationSource,
    booking: VenueBooking,
    *,
    decision: PolicyDecision,
    receipt_id: UUID,
    correlation_id: UUID,
    source_channel: str,
    occurred_at: datetime,
) -> VenueCommandReceipt:
    old_lifecycle = booking.lifecycle
    VenueBookingOccupancy.objects.filter(booking=booking, active=True).update(
        active=False
    )
    booking.lifecycle = VenueBooking.Lifecycle.CANCELLED
    booking.last_modified_by_id = source.actor_id
    booking.aggregate_version += 1
    booking.save()
    _append_booking_history_ids(
        booking=booking,
        actor_id=source.actor_id,
        action=VenueBookingHistory.Action.CANCELLED,
        reason=source.reason,
        occurred_at=occurred_at,
        old_envelope=_booking_envelope(booking),
        old_review_state=booking.review_state,
        old_publication_state=booking.publication_state,
        old_lifecycle=old_lifecycle,
    )
    return _evidence(
        source,
        booking,
        decision=decision,
        action="cancelled",
        operation=VenueCommandReceipt.Operation.BOOKING_CANCEL,
        receipt_id=receipt_id,
        correlation_id=correlation_id,
        source_channel=source_channel,
        occurred_at=occurred_at,
    )


def _create(
    source: SchedulingReservationSource, space: EditionSpaceSelection
) -> VenueBooking:
    if (
        space.lifecycle != "active"
        or space.venue_selection.lifecycle != "active"
        or space.venue_selection.property.lifecycle != "active"
        or space.physical_members.filter(source_space__is_active=False).exists()
    ):
        raise VenueStateConflictError
    envelope = VenueBookingEnvelope(**asdict(source.envelope))
    _require_available_capacity(
        space_selection=space,
        envelope=envelope,
        capacity_mode=source.capacity_mode,
        expected_attendance=source.expected_attendance,
    )
    booking = VenueBooking.objects.create(
        id=source.target_booking_id,
        organization_id=source.organization_id,
        edition_id=source.edition_id,
        space_selection=space,
        responsible_department_id=space.responsible_department_id,
        kind=VenueBooking.Kind.PROGRAMME,
        internal_title="Programme reservation",
        capacity_mode=source.capacity_mode,
        expected_attendance=source.expected_attendance,
        created_by_id=source.actor_id,
        last_modified_by_id=source.actor_id,
        **asdict(envelope),
    )
    _write_booking_occupancy(booking=booking)
    return booking


@transaction.atomic
def apply_scheduling_reservation(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    intent_id: UUID,
    correlation_id: UUID,
    source_channel: str,
) -> VenueCommandResult:
    """Apply an independently authorized physical intent in its live parent command.

    Parameters
    ----------
    actor_id : UUID
        Current verified person independently authorized by both owners.
    organization_id : UUID
        Exact common organization.
    edition_id : UUID
        Exact common edition.
    intent_id : UUID
        Scheduling-owned in-progress intent, not caller-supplied placement facts.
    correlation_id : UUID
        Parent command audit correlation.
    source_channel : str
        Bounded trusted parent channel.

    Returns
    -------
    VenueCommandResult
        Exact new or cancelled booking and reciprocal Venue receipt; never approval.

    Raises
    ------
    VenueResourceUnavailableError
        If the exact identifiers or adapter are unavailable.
    VenueStateConflictError
        If the owned intent cannot produce a coherent physical result.
    """
    if any(
        not isinstance(value, UUID)
        for value in (actor_id, organization_id, edition_id, intent_id, correlation_id)
    ):
        raise VenueResourceUnavailableError
    source_channel = normalized_source_channel(source_channel)
    _require_adapter(organization_id, edition_id)
    source = resolve_scheduling_reservation_source(
        actor_id=actor_id,
        organization_id=organization_id,
        edition_id=edition_id,
        intent_id=intent_id,
    )
    spaces = _spaces(source)
    by_id = {space.id: space for space in spaces}
    previous = _current_booking(source)
    occurred_at = timezone.now()
    receipt = None
    with venue_writer():
        if previous is not None:
            receipt = _cancel(
                source,
                previous,
                decision=_authorize(actor_id, by_id[previous.space_selection_id]),
                receipt_id=source.venue_receipt_id
                if source.target_booking_id is None
                else uuid4(),
                correlation_id=correlation_id,
                source_channel=source_channel,
                occurred_at=occurred_at,
            )
        booking = previous
        if source.target_booking_id is not None:
            booking = _create(source, by_id[source.space_selection_id])
            _append_booking_history_ids(
                booking=booking,
                actor_id=actor_id,
                action=VenueBookingHistory.Action.CREATED,
                reason=source.reason,
                occurred_at=occurred_at,
            )
            receipt = _evidence(
                source,
                booking,
                decision=_authorize(actor_id, by_id[booking.space_selection_id]),
                action="created",
                operation=VenueCommandReceipt.Operation.BOOKING_CREATE,
                receipt_id=source.venue_receipt_id,
                correlation_id=correlation_id,
                source_channel=source_channel,
                occurred_at=occurred_at,
            )
            VenueSchedulingBinding.objects.create(
                organization_id=organization_id,
                edition_id=edition_id,
                booking=booking,
                source_intent_id=source.intent_id,
                occurrence_id=source.occurrence_id,
                placement_id=source.placement_id,
                source_actor_id=source.placement_actor_id,
                occurred_at=occurred_at,
            )
        if receipt is None or booking is None:
            raise VenueStateConflictError
        _require_adapter(organization_id, edition_id)
        resolve_scheduling_reservation_source(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            intent_id=intent_id,
        )
        for space in spaces:
            _authorize(actor_id, space)
    return VenueCommandResult(
        booking.id, receipt.id, booking.aggregate_version, replayed=False
    )
