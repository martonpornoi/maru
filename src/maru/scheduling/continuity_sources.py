"""Minimize validated owner outputs; these pure transformations grant no read access."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from .continuity_payload import (
    ContinuityEntry,
    ContinuityFact,
    ContinuityProjection,
    encode_continuity_payload,
)
from .continuity_protocol import ContinuityInvalidError, ContinuityScope, _utc
from .output_rendering import PUBLIC_TIMETABLE_CONTRACT, render_public_timetable_json
from .personal_output_rendering import (
    PERSONAL_TIMETABLE_CONTRACT,
    render_personal_timetable_json,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.programme.output_queries import ReleasedProgrammeCopy
    from maru.venues.programme_output_queries import ReleasedRoomWayfinding
    from maru.workforce.timetable_queries import PersonalShiftTimetableEntry

    from .output_queries import PublicProgrammeTimetable
    from .personal_output_queries import PersonalHostingLayer, PersonalTimetable
    from .time_rules import SchedulingEnvelope


def _wayfinding(room: ReleasedRoomWayfinding) -> tuple[ContinuityFact, ...]:
    return (
        ContinuityFact("room", room.room_name),
        ContinuityFact("venue", room.venue_name),
        ContinuityFact(
            "wayfinding_version",
            f"room {room.space_id} version {room.space_version}; "
            f"venue label version {room.venue_version}",
        ),
    )


def _reviewed_copy(copy: ReleasedProgrammeCopy) -> tuple[ContinuityFact, ...]:
    return (
        ContinuityFact("summary", copy.summary),
        ContinuityFact("content_note", copy.content_note),
        ContinuityFact("reviewed_copy", str(copy.rendition_id)),
    )


def _service_day(day_id: UUID, start: datetime, end: datetime) -> ContinuityFact:
    return ContinuityFact(
        "service_day", f"{day_id}: {_utc(start).isoformat()} to {_utc(end).isoformat()}"
    )


def _context(
    envelope: SchedulingEnvelope,
) -> tuple[datetime, datetime, datetime, datetime]:
    return (
        envelope.setup_starts_at,
        envelope.effective_starts_at,
        envelope.effective_ends_at,
        envelope.teardown_ends_at,
    )


def public_continuity_projection(
    source: PublicProgrammeTimetable, *, organization_id: UUID, edition_id: UUID
) -> ContinuityProjection:
    """Minimize an already authorized complete public timetable without private reads.

    Parameters
    ----------
    source : PublicProgrammeTimetable
        Fresh owner projection obtained with the exact organization/edition arguments.
    organization_id : UUID
        Trusted tenant query argument, not inferred from caller-provided content.
    edition_id : UUID
        Trusted edition query argument used by the owning read.

    Returns
    -------
    ContinuityProjection
        Reviewed effective-time cards and complete nonavailable release metadata.

    Notes
    -----
    Owner serialization validates the entire DTO before extraction. Validation errors
    propagate without returning a partial pack. This transformation grants no access.
    """
    raw = render_public_timetable_json(source)
    result = ContinuityProjection(
        ContinuityScope(organization_id, edition_id, "public"),
        PUBLIC_TIMETABLE_CONTRACT,
        hashlib.sha256(raw).hexdigest(),
        source.checked_at,
        source.zone_name,
        source.state.value,
        source.pointer_version,
        source.release_id,
        source.published_at,
        "not_applicable",
        "not_applicable",
        tuple(
            ContinuityEntry(
                f"public:{row.occurrence_id}",
                "public_event",
                row.copy.title,
                row.starts_at,
                row.ends_at,
                row.room.space_id,
                row.day_id,
                None,
                (
                    *_reviewed_copy(row.copy),
                    *_wayfinding(row.room),
                    _service_day(row.day_id, row.day_starts_at, row.day_ends_at),
                ),
            )
            for row in source.entries
        ),
    )
    encode_continuity_payload(result)
    return result


def _hosting(layer: PersonalHostingLayer | None) -> tuple[ContinuityEntry, ...]:
    if layer is None:
        return ()
    purposes = {row.host_id: row for row in layer.reference.purposes}
    rooms = {row.space_id: row for row in layer.rooms}
    result = []
    for row in layer.reference.presences:
        purpose = purposes[row.host_id]
        result.append(
            ContinuityEntry(
                f"host:{row.host_id}:{row.occurrence_id}",
                "host_presence",
                purpose.title,
                row.starts_at,
                row.ends_at,
                row.space_id,
                row.day_id,
                _context(row.envelope),
                (
                    ContinuityFact("role", purpose.role),
                    ContinuityFact("briefing", purpose.briefing),
                    ContinuityFact(
                        "host_version",
                        f"host {purpose.host_id} version {purpose.version}; "
                        f"invitation {purpose.invitation_sequence}",
                    ),
                    *_wayfinding(rooms[row.space_id]),
                    _service_day(row.day_id, row.day_starts_at, row.day_ends_at),
                ),
            )
        )
    return tuple(result)


def _work(row: PersonalShiftTimetableEntry) -> ContinuityEntry:
    instructions = row.instructions
    return ContinuityEntry(
        f"work:{row.commitment_id}",
        f"work_{row.status}",
        instructions.title,
        row.starts_at,
        row.ends_at,
        None,
        None,
        None,
        (
            ContinuityFact("status", row.status),
            ContinuityFact("location", instructions.location),
            ContinuityFact("briefing", instructions.briefing),
            ContinuityFact("supervision", instructions.supervision_note),
            ContinuityFact("department", instructions.department_name),
            ContinuityFact("position", instructions.position_title),
            ContinuityFact("commitment_version", str(row.version)),
            ContinuityFact(
                "demand_version",
                f"{instructions.demand_id} version {instructions.version}",
            ),
            ContinuityFact("demand_status", instructions.status),
            ContinuityFact("rest_until", _utc(row.rest_ends_at).isoformat()),
        ),
    )


def personal_continuity_projection(
    source: PersonalTimetable,
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
) -> ContinuityProjection:
    """Preserve exact-person host presence and independently retained work terms.

    Parameters
    ----------
    source : PersonalTimetable
        Fresh independently admitted owner composition, not a public augmentation.
    actor_id : UUID
        Exact authenticated person, matching the source DTO.
    organization_id : UUID
        Exact tenant query argument, matching the source DTO.
    edition_id : UUID
        Exact edition query argument, matching the source DTO.

    Returns
    -------
    ContinuityProjection
        Separate unadopted/unobserved/empty layers and source-versioned own cards.

    Raises
    ------
    ContinuityInvalidError
        If the valid source belongs to another actor, organization or edition.

    Notes
    -----
    Complete owner validation and bounded encoding errors propagate. Confirmed host
    presence does not extend to the full placement envelope; retained work is neither
    rescheduled to current demand times nor evidence of attendance.
    """
    raw = render_personal_timetable_json(source)
    if (source.actor_id, source.organization_id, source.edition_id) != (
        actor_id,
        organization_id,
        edition_id,
    ):
        raise ContinuityInvalidError
    reference = source.hosting.reference if source.hosting is not None else None
    state = (
        (reference.state.value if reference.state is not None else "unobserved")
        if reference is not None
        else "unadopted"
    )
    result = ContinuityProjection(
        ContinuityScope(
            organization_id, edition_id, "exact_person", actor_id, "personal"
        ),
        PERSONAL_TIMETABLE_CONTRACT,
        hashlib.sha256(raw).hexdigest(),
        source.checked_at,
        source.zone_name,
        state,
        reference.pointer_version if reference is not None else None,
        reference.release_id if reference is not None else None,
        reference.published_at if reference is not None else None,
        state,
        "available" if source.shifts is not None else "unadopted",
        (*_hosting(source.hosting), *(_work(row) for row in source.shifts or ())),
    )
    encode_continuity_payload(result)
    return result
