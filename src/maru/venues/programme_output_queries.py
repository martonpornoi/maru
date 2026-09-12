"""Current minimal wayfinding for rooms selected by the single Programme release."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction

from maru.scheduling.inputs import require_identifier
from maru.scheduling.public_release_references import load_public_release_reference
from maru.scheduling.release_queries import ProgrammeReleaseState

from .models import EditionSpaceSelection
from .scheduling_queries import VenueSchedulingSourceUnavailableError

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReleasedRoomWayfinding:
    """Current public wayfinding, explicitly not a historical label snapshot.

    Attributes
    ----------
    space_id
        Exact selected room identity from the checked Programme release.
    space_version
        Current room-selection version owning its wayfinding name.
    venue_version
        Current venue-selection version owning its wayfinding name.
    room_name
        Current edition-local room name, already a Venue public wayfinding field.
    venue_name
        Current edition-local venue name, not the provider's private legal name.
    """

    space_id: UUID
    space_version: int
    venue_version: int
    room_name: str
    venue_name: str


def load_released_room_wayfinding(
    *, organization_id: UUID, edition_id: UUID, expected_release_id: UUID
) -> tuple[ReleasedRoomWayfinding, ...]:
    """Read only current wayfinding for every room in the exact active release.

    Parameters
    ----------
    organization_id : UUID
        Exact expected room, venue and release owner.
    edition_id : UUID
        Exact edition, independently checked by public-release admission.
    expected_release_id : UUID
        Optimistic release identity, not permission for arbitrary room discovery.

    Returns
    -------
    tuple[ReleasedRoomWayfinding, ...]
        Complete current wayfinding with its own versions in stable ID order.

    Raises
    ------
    VenueSchedulingSourceUnavailableError
        For unavailable, changed or incomplete release/room evidence.

    Notes
    -----
    The owner reference propagates SchedulingAuthorizationDeniedError for failed
    public admission, SchedulingUnavailableError for unverifiable release
    evidence and ValidationError for malformed exact scope identifiers.
    Public contacts, access instructions, layouts, private restrictions and
    department/staff identities are excluded. No independent Venue booking
    publication is consulted. Native governing release invalidation determines
    whether approved physical timing may still be served, including its defined
    historical consequence; labels remain explicitly current owner facts.
    """
    require_identifier(expected_release_id)
    try:
        with transaction.atomic():
            reference = load_public_release_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            if (
                reference.manifest.state is not ProgrammeReleaseState.AVAILABLE
                or reference.manifest.release_id != expected_release_id
            ):
                raise VenueSchedulingSourceUnavailableError
            selected = {row.space_id for row in reference.occurrences}
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
            if len(rows) != len(selected):
                raise VenueSchedulingSourceUnavailableError
            if (
                load_public_release_reference(
                    organization_id=organization_id, edition_id=edition_id
                )
                != reference
            ):
                raise VenueSchedulingSourceUnavailableError
            return tuple(ReleasedRoomWayfinding(*row) for row in rows)
    except DatabaseError as error:
        raise VenueSchedulingSourceUnavailableError from error
