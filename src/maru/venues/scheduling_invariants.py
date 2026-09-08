"""Identifier-only owner invariant for already-authorized occurrence retirement."""

from uuid import UUID

from django.db import connection

from maru.events.scheduling_queries import resolve_scheduling_edition_reference

from .models import VenueSchedulingBinding
from .services import VenueResourceUnavailableError, VenueStateConflictError


def require_no_active_scheduling_reservation(
    *, organization_id: UUID, edition_id: UUID, occurrence_id: UUID
) -> None:
    """Fence retirement while an exact occurrence still owns physical occupancy.

    This owner invariant is not a user-facing query or authority grant. The
    calling Scheduling command must authorize retirement and retain its edition
    mutex. No booking identity, timing, title or review decision is disclosed.

    Parameters
    ----------
    organization_id : UUID
        Expected common organization.
    edition_id : UUID
        Exact edition already authorized for the parent mutation.
    occurrence_id : UUID
        Stable owned occurrence being retired.

    Raises
    ------
    VenueResourceUnavailableError
        If the exact transaction or owner scope is unavailable.
    VenueStateConflictError
        If an active physical hold must first be deliberately cancelled.
    """
    if (
        not connection.in_atomic_block
        or any(
            not isinstance(value, UUID)
            for value in (organization_id, edition_id, occurrence_id)
        )
        or resolve_scheduling_edition_reference(
            organization_id=organization_id, edition_id=edition_id, lock=True
        )
        is None
    ):
        raise VenueResourceUnavailableError
    if VenueSchedulingBinding.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        occurrence_id=occurrence_id,
        booking__lifecycle="active",
    ).exists():
        raise VenueStateConflictError
