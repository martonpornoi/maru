"""Own released-host wayfinding, never arbitrary room or public-copy discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction

from maru.scheduling.inputs import require_identifier
from maru.scheduling.personal_release_references import (
    load_personal_host_release_reference,
)
from maru.scheduling.release_queries import ProgrammeReleaseState

from .models import EditionSpaceSelection
from .programme_output_queries import ReleasedRoomWayfinding
from .scheduling_queries import VenueSchedulingSourceUnavailableError

if TYPE_CHECKING:
    from uuid import UUID


def load_personal_host_room_wayfinding(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    expected_release_id: UUID,
) -> tuple[ReleasedRoomWayfinding, ...]:
    """Independently prove own approved presence before reading its room labels.

    Parameters
    ----------
    actor_id : UUID
        Trusted authenticated person, never a selectable other host.
    organization_id : UUID
        Exact expected room, venue and personal-purpose owner.
    edition_id : UUID
        Exact edition independently checked by Scheduling and Programme.
    correlation_id : UUID
        Trusted trace for the required personal source audits.
    expected_release_id : UUID
        Optimistic active release identity, not a room-discovery permission.

    Returns
    -------
    tuple[ReleasedRoomWayfinding, ...]
        Complete minimal current labels/versions for own approved presence only.

    Raises
    ------
    VenueSchedulingSourceUnavailableError
        If the active release or complete selected wayfinding cannot be verified.

    Notes
    -----
    The caller supplies no room IDs or reusable manifest. Both owners' real
    self authority and current Programme purpose are checked through Scheduling
    before and after labels. No public adapter, planner grant, other host,
    contact, access instruction or independent Venue publication is inferred.
    Missing, changed, withdrawn or incomplete evidence withholds all labels.
    """
    require_identifier(expected_release_id)
    arguments = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
        "correlation_id": correlation_id,
    }
    try:
        with transaction.atomic():
            reference = load_personal_host_release_reference(**arguments)
            if (
                reference.state is not ProgrammeReleaseState.AVAILABLE
                or reference.release_id != expected_release_id
            ):
                raise VenueSchedulingSourceUnavailableError
            selected = {row.space_id for row in reference.presences}
            rows = tuple(
                EditionSpaceSelection.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    venue_selection__organization_id=organization_id,
                    venue_selection__edition_id=edition_id,
                    id__in=selected,
                )
                .order_by("id")
                .values_list(
                    "id",
                    "aggregate_version",
                    "venue_selection__aggregate_version",
                    "local_name",
                    "venue_selection__local_name",
                )[: len(selected) + 1]
            )
            if (
                len(rows) != len(selected)
                or {row[0] for row in rows} != selected
                or load_personal_host_release_reference(**arguments) != reference
            ):
                raise VenueSchedulingSourceUnavailableError
            return tuple(ReleasedRoomWayfinding(*row) for row in rows)
    except DatabaseError as error:
        raise VenueSchedulingSourceUnavailableError from error
