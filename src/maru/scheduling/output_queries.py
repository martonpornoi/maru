"""Complete current-release Programme projections, separated by audience purpose."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction
from django.utils import timezone

from maru.programme.output_queries import (
    ReleasedProgrammeCopy,
    load_released_programme_copy,
)
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.venues.programme_output_queries import (
    ReleasedRoomWayfinding,
    load_released_room_wayfinding,
)
from maru.venues.scheduling_queries import VenueSchedulingSourceUnavailableError

from .command_support import SchedulingUnavailableError
from .public_release_references import load_public_release_reference
from .release_queries import ProgrammeReleaseState

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublicTimetableEntry:
    """One released effective interval with independently public owner fields.

    Attributes
    ----------
    occurrence_id
        Stable Scheduling identity across releases and output formats.
    copy
        Exact selected Programme reviewed rendition, not latest working copy.
    room
        Current Venue wayfinding names and their explicit owner versions.
    day_id
        Stable service-day identity without its private planning label.
    day_starts_at
        Exact selected service-day start instant, which may precede local midnight.
    day_ends_at
        Exact selected service-day end instant.
    starts_at
        Approved effective start; host/work preparation is not a public interval.
    ends_at
        Approved effective end; no private teardown instructions are included.
    """

    occurrence_id: UUID
    copy: ReleasedProgrammeCopy
    room: ReleasedRoomWayfinding
    day_id: UUID
    day_starts_at: datetime
    day_ends_at: datetime
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class PublicProgrammeTimetable:
    """Point-in-time complete public projection; not an offline freshness lease.

    Attributes
    ----------
    state
        Absent, withdrawn, invalidated or available; only available has entries.
    pointer_version
        Exact edition release pointer sequence observed in this read.
    release_id
        Exact selected active release, if present; never a caller-chosen draft.
    published_at
        Immutable selected release creation instant.
    checked_at
        Server time after complete owner reads and final release recheck.
    zone_name
        Events-owned IANA zone for date/day presentation.
    entries
        Complete deterministic effective entries with no private owner fields.
    """

    state: ProgrammeReleaseState
    pointer_version: int
    release_id: UUID | None
    published_at: datetime | None
    checked_at: datetime
    zone_name: str
    entries: tuple[PublicTimetableEntry, ...]


def load_public_programme_timetable(
    *, organization_id: UUID, edition_id: UUID
) -> PublicProgrammeTimetable:
    """Compose the complete current public release through independent owner reads.

    Parameters
    ----------
    organization_id : UUID
        Expected exact owner; no organizer authority or synthetic actor is supplied.
    edition_id : UUID
        Exact edition whose current profile must pin the public-output adapter.

    Returns
    -------
    PublicProgrammeTimetable
        Complete current release with explicitly versioned current wayfinding.
        Absence, withdrawal or invalidation returns no normal timetable entries.

    Raises
    ------
    SchedulingUnavailableError
        If any required owner result or release evidence is missing or moving.

    Notes
    -----
    The release owner propagates SchedulingAuthorizationDeniedError for failed
    public admission and ValidationError for malformed scope identifiers.
    Owners resolve the checked release themselves; returned references grant no
    enduring authority. The outer transaction retains canonical shared parents
    across composition, while final native checks catch governing invalidation.
    No private dictionary augmentation, attendee Participation, unclaimed Shift,
    host identity, anonymous activity audit or cross-audience cache is involved.
    """
    try:
        with transaction.atomic():
            reference = load_public_release_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            entries: tuple[PublicTimetableEntry, ...] = ()
            if reference.manifest.state is ProgrammeReleaseState.AVAILABLE:
                release_id = reference.manifest.release_id
                if release_id is None:
                    raise SchedulingUnavailableError
                copies = load_released_programme_copy(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    expected_release_id=release_id,
                )
                rooms = load_released_room_wayfinding(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    expected_release_id=release_id,
                )
                copy_by_id = {row.rendition_id: row for row in copies}
                room_by_id = {row.space_id: row for row in rooms}
                if (
                    len(copy_by_id) != len(copies)
                    or len(room_by_id) != len(rooms)
                    or copy_by_id.keys()
                    != {row.public_rendition_id for row in reference.occurrences}
                    or room_by_id.keys()
                    != {row.space_id for row in reference.occurrences}
                ):
                    raise SchedulingUnavailableError
                entries = tuple(
                    PublicTimetableEntry(
                        row.occurrence_id,
                        copy_by_id[row.public_rendition_id],
                        room_by_id[row.space_id],
                        row.day_id,
                        row.day_starts_at,
                        row.day_ends_at,
                        row.starts_at,
                        row.ends_at,
                    )
                    for row in reference.occurrences
                )
            if (
                load_public_release_reference(
                    organization_id=organization_id, edition_id=edition_id
                )
                != reference
            ):
                raise SchedulingUnavailableError
            return PublicProgrammeTimetable(
                reference.manifest.state,
                reference.manifest.pointer_version,
                reference.manifest.release_id,
                reference.published_at,
                timezone.now(),
                reference.zone_name,
                entries,
            )
    except (
        DatabaseError,
        ProgrammeQueryUnavailableError,
        VenueSchedulingSourceUnavailableError,
    ) as error:
        raise SchedulingUnavailableError from error
