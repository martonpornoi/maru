"""Locked physical source closure for the dormant Programme release compositor."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from maru.events.write_references import lock_edition_ownership

from .models import VenueBooking, VenueSpace
from .physical_locks import _lock_physical_scope
from .scheduling_queries import (
    VenueSchedulingSnapshot,
    VenueSchedulingSourceDeniedError,
    VenueSchedulingSourceUnavailableError,
    load_venue_scheduling_dependencies,
)

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class VenueReleaseSelectionSource:
    """Exact authorized physical identities, without foreign reservations or text.

    Attributes
    ----------
    selection_id
        Exact edition selection from the independently authorized physical source.
    member_properties
        Complete sorted physical-member and owning-property pairs for this selection.
    """

    selection_id: UUID
    member_properties: tuple[tuple[UUID, UUID], ...]


@dataclass(frozen=True, slots=True)
class VenueReleaseSources:
    """Current physical evidence held stable until the compositor transaction ends.

    Attributes
    ----------
    snapshot
        Existing minimized current physical consequences and exact local bindings.
    selections
        Complete selected physical identities suitable for owner dependency capture.
    """

    snapshot: VenueSchedulingSnapshot
    selections: tuple[VenueReleaseSelectionSource, ...]


def lock_venue_release_sources(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    selection_ids: tuple[UUID, ...],
    placement_ids: tuple[UUID, ...],
    correlation_id: UUID,
) -> VenueReleaseSources:
    """Authorize, lock and reread the complete selected physical owner closure.

    Parameters
    ----------
    actor_id : UUID
        Current release principal, already in the compositor's complete person union.
    organization_id : UUID
        Exact authorized organization; foreign tenant sources never become references.
    edition_id : UUID
        Exact requesting edition, not an inferred foreign occupancy owner.
    selection_ids : tuple[UUID, ...]
        Complete bounded selection set resolved by Scheduling from its candidate.
    placement_ids : tuple[UUID, ...]
        Complete candidate placements whose current native bindings are collected.
    correlation_id : UUID
        Trusted trace for mandatory owner-sensitive-read audits.

    Returns
    -------
    VenueReleaseSources
        Locked native identities plus fresh minimized physical evidence, not approval.

    Raises
    ------
    VenueSchedulingSourceUnavailableError
        Without an enclosing READ COMMITTED transaction or a complete stable closure.
    VenueSchedulingSourceDeniedError
        Without current exact-resource physical-dependency authority.

    Notes
    -----
    The compositor must first lock owning parents and its complete person union.
    This owner locks the property/member/selection union before any local booking.
    Foreign busy sources stay pseudonymous; their booking and edition identities
    are never collected or locked. No release key, reservation or approval is written.
    Current profile admission and field policy remain the ordinary source boundary.
    """
    if not connection.in_atomic_block:
        raise VenueSchedulingSourceUnavailableError
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_isolation")
        if cursor.fetchone() != ("read committed",):
            raise VenueSchedulingSourceUnavailableError
    with transaction.atomic():
        if not lock_edition_ownership(
            organization_id=organization_id, edition_id=edition_id
        ):
            raise VenueSchedulingSourceDeniedError
        load_source = partial(
            load_venue_scheduling_dependencies,
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            selection_ids=selection_ids,
            placement_ids=placement_ids,
            correlation_id=correlation_id,
        )
        # Authority and complete source shape precede locking physical resources.
        load_source()
        try:
            _lock_physical_scope(
                actor_id=actor_id,
                organization_id=organization_id,
                edition_id=edition_id,
                selection_ids=selection_ids,
            )
        except ValidationError as error:
            raise VenueSchedulingSourceUnavailableError from error
        snapshot = load_source()
        members = {member for row in snapshot.spaces for member in row.member_ids}
        properties = dict(
            VenueSpace.objects.filter(
                organization_id=organization_id, id__in=members
            ).values_list("id", "property_id")
        )
        booking_ids = tuple(sorted(row.booking_id for row in snapshot.reservations))
        locked_bookings = tuple(
            VenueBooking.objects.select_for_update(of=("self",))
            .filter(
                organization_id=organization_id,
                edition_id=edition_id,
                id__in=booking_ids,
                space_selection_id__in=selection_ids,
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        if properties.keys() != members or locked_bookings != booking_ids:
            raise VenueSchedulingSourceUnavailableError
        # Repeat authority and evidence after every possible wait. Never lock a
        # newly discovered source out of order or return a partial replacement set.
        if load_source() != snapshot:
            raise VenueSchedulingSourceUnavailableError
        return VenueReleaseSources(
            snapshot,
            tuple(
                VenueReleaseSelectionSource(
                    row.selection_id,
                    tuple((member, properties[member]) for member in row.member_ids),
                )
                for row in snapshot.spaces
            ),
        )
