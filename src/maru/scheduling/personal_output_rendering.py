"""Closed bounded private timetable formats, separate from public serialization."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maru.events.personal_timetable_queries import PersonalTimetableEditionLabel
from maru.programme.timetable_queries import (
    MAX_PERSONAL_HOST_PURPOSES,
    PersonalHostPurpose,
)
from maru.venues.programme_output_queries import ReleasedRoomWayfinding
from maru.workforce.shift_queries import MAX_SHIFT_COMMITMENTS
from maru.workforce.timetable_queries import (
    PersonalShiftInstructions,
    PersonalShiftTimetableEntry,
)

from .catalogs import MAX_OCCURRENCES
from .output_rendering import (
    TimetableOutputInvalidError,
    _bounded_bytes,
    _calendar_instant,
    _calendar_text,
    _fold,
    _identifier,
    _instant,
    _text,
    _version,
)
from .personal_output_queries import PersonalHostingLayer, PersonalTimetable
from .personal_release_references import (
    PersonalHostPresence,
    PersonalHostReleaseReference,
)
from .release_queries import ProgrammeReleaseState
from .time_rules import SchedulingEnvelope

if TYPE_CHECKING:
    from datetime import datetime

PERSONAL_TIMETABLE_CONTRACT: Final = "scheduling.personal-timetable@1"
_HOST_STATES: Final = frozenset(
    {"invited", "confirmed", "declined", "withdrawn", "removed"}
)
_WORK_STATES: Final = frozenset({"claimed", "confirmed", "removed", "completed"})
_DEMAND_STATES: Final = frozenset({"draft", "open", "locked", "completed", "cancelled"})


class PersonalCalendarUnavailableError(ValueError):
    """Withhold combined imports when hosting was withdrawn or needs review."""

    def __init__(self) -> None:
        """Initialize safe guidance without exposing prior room or host content."""
        super().__init__(
            "Recheck the hosting release before downloading a combined calendar."
        )


def _date(value: datetime | None) -> str | None:
    return _instant(value).isoformat() if value is not None else None


def _purpose(row: PersonalHostPurpose) -> dict[str, object]:
    if (
        type(row) is not PersonalHostPurpose
        or type(row.state) is not str
        or type(row.role) is not str
        or row.state not in _HOST_STATES
        or row.role not in {"host", "co_host"}
    ):
        raise TimetableOutputInvalidError
    _version(row.version)
    _version(row.invitation_sequence)
    return {
        "host_id": _identifier(row.host_id),
        "item_id": _identifier(row.item_id),
        "role": row.role,
        "state": row.state,
        "version": row.version,
        "invitation_sequence": row.invitation_sequence,
        "title": _text(row.title, 240, required=True),
        "briefing": _text(row.briefing, 2000),
    }


def _room(row: ReleasedRoomWayfinding) -> dict[str, object]:
    if type(row) is not ReleasedRoomWayfinding:
        raise TimetableOutputInvalidError
    _version(row.space_version)
    _version(row.venue_version)
    return {
        "space_id": _identifier(row.space_id),
        "space_version": row.space_version,
        "venue_version": row.venue_version,
        "room_name": _text(row.room_name, 200, required=True),
        "venue_name": _text(row.venue_name, 200, required=True),
    }


def _presence(row: PersonalHostPresence) -> dict[str, object]:
    if (
        type(row) is not PersonalHostPresence
        or type(row.envelope) is not SchedulingEnvelope
    ):
        raise TimetableOutputInvalidError
    envelope = row.envelope
    if not (
        _instant(row.day_starts_at)
        <= _instant(envelope.setup_starts_at)
        <= _instant(envelope.effective_starts_at)
        < _instant(envelope.effective_ends_at)
        <= _instant(envelope.teardown_ends_at)
        <= _instant(row.day_ends_at)
        and _instant(envelope.setup_starts_at)
        <= _instant(row.starts_at)
        < _instant(row.ends_at)
        <= _instant(envelope.teardown_ends_at)
    ):
        raise TimetableOutputInvalidError
    return {
        "host_id": _identifier(row.host_id),
        "occurrence_id": _identifier(row.occurrence_id),
        "placement_id": _identifier(row.placement_id),
        "space_id": _identifier(row.space_id),
        "day_id": _identifier(row.day_id),
        "day_starts_at": _date(row.day_starts_at),
        "day_ends_at": _date(row.day_ends_at),
        "starts_at": _date(row.starts_at),
        "ends_at": _date(row.ends_at),
        "envelope": {
            "setup_starts_at": _date(envelope.setup_starts_at),
            "effective_starts_at": _date(envelope.effective_starts_at),
            "effective_ends_at": _date(envelope.effective_ends_at),
            "teardown_ends_at": _date(envelope.teardown_ends_at),
        },
    }


def _host_state(reference: PersonalHostReleaseReference, checked_at: datetime) -> None:
    confirmed = any(row.state == "confirmed" for row in reference.purposes)
    state = reference.state
    if state is None:
        if (
            confirmed
            or any(
                value is not None
                for value in (
                    reference.pointer_version,
                    reference.release_id,
                    reference.published_at,
                )
            )
            or reference.presences
        ):
            raise TimetableOutputInvalidError
        return
    if type(state) is not ProgrammeReleaseState or not confirmed:
        raise TimetableOutputInvalidError
    if reference.pointer_version is None:
        raise TimetableOutputInvalidError
    _version(reference.pointer_version, initial=state is ProgrammeReleaseState.ABSENT)
    if state is ProgrammeReleaseState.ABSENT:
        if (
            reference.pointer_version != 0
            or reference.release_id is not None
            or reference.published_at is not None
        ):
            raise TimetableOutputInvalidError
    elif state is ProgrammeReleaseState.WITHDRAWN:
        if reference.release_id is not None or reference.published_at is not None:
            raise TimetableOutputInvalidError
    else:
        if reference.release_id is None or reference.published_at is None:
            raise TimetableOutputInvalidError
        _identifier(reference.release_id)
        if _instant(reference.published_at) > _instant(checked_at):
            raise TimetableOutputInvalidError
    if state is not ProgrammeReleaseState.AVAILABLE and reference.presences:
        raise TimetableOutputInvalidError


def _hosting(
    layer: PersonalHostingLayer, checked_at: datetime, zone_name: str
) -> dict[str, object]:
    if (
        type(layer) is not PersonalHostingLayer
        or type(layer.reference) is not PersonalHostReleaseReference
    ):
        raise TimetableOutputInvalidError
    reference = layer.reference
    if reference.zone_name != zone_name or (
        type(reference.purposes) is not tuple
        or len(reference.purposes) > MAX_PERSONAL_HOST_PURPOSES
        or type(reference.presences) is not tuple
        or len(reference.presences) > MAX_OCCURRENCES
        or type(layer.rooms) is not tuple
        or len(layer.rooms) > MAX_OCCURRENCES
    ):
        raise TimetableOutputInvalidError
    # Validate exact shapes before sorting or joining any alleged owner rows.
    purposes = [_purpose(row) for row in reference.purposes]
    presences = [_presence(row) for row in reference.presences]
    rooms = [_room(row) for row in layer.rooms]
    hosts = {row.host_id for row in reference.purposes if row.state == "confirmed"}
    if (
        len({row.host_id for row in reference.purposes}) != len(purposes)
        or len({row.item_id for row in reference.purposes}) != len(purposes)
        or len({row.occurrence_id for row in reference.presences}) != len(presences)
        or len({row.space_id for row in layer.rooms}) != len(rooms)
        or {row.space_id for row in reference.presences}
        != {row.space_id for row in layer.rooms}
        or any(row.host_id not in hosts for row in reference.presences)
    ):
        raise TimetableOutputInvalidError
    _host_state(reference, checked_at)
    return {
        "state": reference.state.value if reference.state is not None else None,
        "pointer_version": reference.pointer_version,
        "release_id": str(reference.release_id) if reference.release_id else None,
        "published_at": _date(reference.published_at),
        "purposes": sorted(purposes, key=lambda row: str(row["host_id"])),
        "presences": sorted(
            presences,
            key=lambda row: (str(row["starts_at"]), str(row["occurrence_id"])),
        ),
        "rooms": sorted(rooms, key=lambda row: str(row["space_id"])),
        "room_label_source": "current_venue_wayfinding",
        "envelope_meaning": "placement_context_not_full_person_assignment",
    }


def _shift(row: PersonalShiftTimetableEntry) -> dict[str, object]:
    if (
        type(row) is not PersonalShiftTimetableEntry
        or type(row.instructions) is not PersonalShiftInstructions
    ):
        raise TimetableOutputInvalidError
    instructions = row.instructions
    if (
        type(row.status) is not str
        or type(instructions.status) is not str
        or row.status not in _WORK_STATES
        or instructions.status not in _DEMAND_STATES
        or not (
            _instant(row.starts_at)
            < _instant(row.ends_at)
            <= _instant(row.rest_ends_at)
        )
    ):
        raise TimetableOutputInvalidError
    _version(row.version)
    _version(instructions.version)
    return {
        "commitment_id": _identifier(row.commitment_id),
        "version": row.version,
        "status": row.status,
        "starts_at": _date(row.starts_at),
        "ends_at": _date(row.ends_at),
        "rest_ends_at": _date(row.rest_ends_at),
        "instructions": {
            "demand_id": _identifier(instructions.demand_id),
            "version": instructions.version,
            "status": instructions.status,
            "title": _text(instructions.title, 160, required=True),
            "location": _text(instructions.location, 160, required=True),
            "briefing": _text(instructions.briefing, 1000, required=True),
            "supervision_note": _text(instructions.supervision_note, 500),
            "department_id": _identifier(instructions.department_id),
            "department_name": _text(instructions.department_name, 160, required=True),
            "position_title": _text(instructions.position_title, 160, required=True),
        },
    }


def personal_timetable_document(snapshot: PersonalTimetable) -> dict[str, object]:
    """Validate and materialize only the explicitly owned private output fields.

    Parameters
    ----------
    snapshot : PersonalTimetable
        Fresh complete exact-person projection, not a public object or dictionary.

    Returns
    -------
    dict[str, object]
        Deterministically ordered audience-labelled document with explicit layers.

    Raises
    ------
    TimetableOutputInvalidError
        If a row, audience, identity, bound, source state or interval is invalid.

    Notes
    -----
    This pure format boundary grants no authority or caching permission. HTTP
    consumers must obtain a new independently authorized owner projection.
    """
    if type(snapshot) is not PersonalTimetable or (
        snapshot.hosting is None and snapshot.shifts is None
    ):
        raise TimetableOutputInvalidError
    for identifier in (
        snapshot.actor_id,
        snapshot.organization_id,
        snapshot.edition_id,
    ):
        _identifier(identifier)
    _instant(snapshot.checked_at)
    if snapshot.edition_label is not None:
        if type(snapshot.edition_label) is not PersonalTimetableEditionLabel:
            raise TimetableOutputInvalidError
        _text(snapshot.edition_label.name, 160, required=True)
        _version(snapshot.edition_label.version)
    _text(snapshot.zone_name, 100, required=True)
    try:
        ZoneInfo(snapshot.zone_name)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise TimetableOutputInvalidError from error
    hosting = (
        _hosting(snapshot.hosting, snapshot.checked_at, snapshot.zone_name)
        if snapshot.hosting is not None
        else None
    )
    shifts = None
    if snapshot.shifts is not None:
        if (
            type(snapshot.shifts) is not tuple
            or len(snapshot.shifts) > MAX_SHIFT_COMMITMENTS
        ):
            raise TimetableOutputInvalidError
        shifts = [_shift(row) for row in snapshot.shifts]
        if len({row.commitment_id for row in snapshot.shifts}) != len(shifts):
            raise TimetableOutputInvalidError
        shifts.sort(key=lambda row: (str(row["starts_at"]), str(row["commitment_id"])))
    if (
        snapshot.edition_label is not None
        and not snapshot.shifts
        and not (snapshot.hosting is not None and snapshot.hosting.reference.purposes)
    ):
        raise TimetableOutputInvalidError
    return {
        "contract": PERSONAL_TIMETABLE_CONTRACT,
        "audience": "exact_person",
        "actor_id": str(snapshot.actor_id),
        "organization_id": str(snapshot.organization_id),
        "edition_id": str(snapshot.edition_id),
        "checked_at": _date(snapshot.checked_at),
        "zone_name": snapshot.zone_name,
        "edition_label": (
            {
                "name": snapshot.edition_label.name,
                "version": snapshot.edition_label.version,
            }
            if snapshot.edition_label is not None
            else None
        ),
        "hosting": hosting,
        "shifts": shifts,
        "absent_layer_meaning": "unadopted_not_unavailable",
        "work_time_source": "retained_shift_commitment",
        "work_instruction_source": "separately_versioned_current_demand",
        "attendance_evidence": False,
    }


def render_personal_timetable_json(snapshot: PersonalTimetable) -> bytes:
    """Encode a complete closed private document under the shared eight-MiB bound.

    Parameters
    ----------
    snapshot : PersonalTimetable
        Newly authorized exact-person owner composition.

    Returns
    -------
    bytes
        UTF-8 JSON with explicit privacy, lifecycle and current-owner source meaning.
    """
    return _bounded_bytes(
        json.JSONEncoder(
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).iterencode(personal_timetable_document(snapshot))
    )


def _host_calendar_events(snapshot: PersonalTimetable, stamp: str) -> list[str]:
    layer = snapshot.hosting
    if layer is None:
        return []
    reference = layer.reference
    purposes = {row.host_id: row for row in reference.purposes}
    rooms = {row.space_id: row for row in layer.rooms}
    lines: list[str] = []
    for row in sorted(
        reference.presences, key=lambda row: (row.starts_at, str(row.occurrence_id))
    ):
        purpose, room = purposes[row.host_id], rooms[row.space_id]
        envelope = row.envelope
        description = "\n".join(
            (
                purpose.briefing,
                "The event times are your approved required presence, "
                "not every work phase.",
                f"Placement preparation: {_date(envelope.setup_starts_at)}.",
                f"Effective programme: {_date(envelope.effective_starts_at)} "
                f"to {_date(envelope.effective_ends_at)}.",
                f"Placement teardown ends: {_date(envelope.teardown_ends_at)}.",
                "Room and venue labels are current wayfinding, "
                "not historical snapshots.",
                "This is not attendance evidence or an offline freshness guarantee.",
            )
        )
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:host-{row.host_id}-{row.occurrence_id}@maru.invalid",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_calendar_instant(row.starts_at)}",
                f"DTEND:{_calendar_instant(row.ends_at)}",
                "CLASS:PRIVATE",
                "STATUS:CONFIRMED",
                "TRANSP:OPAQUE",
                f"SUMMARY:{_calendar_text('Hosting: ' + purpose.title)}",
                f"DESCRIPTION:{_calendar_text(description)}",
                f"LOCATION:{_calendar_text(room.venue_name + ' / ' + room.room_name)}",
                f"X-MARU-RELEASE-ID:{reference.release_id}",
                f"X-MARU-POINTER-VERSION:{reference.pointer_version}",
                f"X-MARU-PLACEMENT-ID:{row.placement_id}",
                f"X-MARU-HOST-VERSION:{purpose.version}",
                f"X-MARU-INVITATION-SEQUENCE:{purpose.invitation_sequence}",
                f"X-MARU-SPACE-VERSION:{room.space_version}",
                f"X-MARU-VENUE-VERSION:{room.venue_version}",
                "END:VEVENT",
            )
        )
    return lines


def _work_calendar_events(snapshot: PersonalTimetable, stamp: str) -> list[str]:
    labels = {
        "claimed": ("Claim (not confirmed)", "TENTATIVE", "OPAQUE"),
        "confirmed": ("Confirmed work", "CONFIRMED", "OPAQUE"),
        "removed": ("Removed work record", "CANCELLED", "TRANSPARENT"),
        "completed": ("Completed work record", "CONFIRMED", "TRANSPARENT"),
    }
    lines: list[str] = []
    for row in sorted(
        snapshot.shifts or (), key=lambda row: (row.starts_at, str(row.commitment_id))
    ):
        label, status, transparency = labels[row.status]
        instructions = row.instructions
        description = "\n".join(
            (
                f"Retained work state: {row.status}. These are retained work times, "
                "not attendance evidence.",
                f"Current demand instructions (version {instructions.version}, "
                f"state {instructions.status}):",
                f"Current location label: {instructions.location}.",
                "Current instructions are not a snapshot of accepted location "
                "or a silent relocation approval.",
                instructions.briefing,
                instructions.supervision_note,
                f"Department: {instructions.department_name}. "
                f"Position: {instructions.position_title}.",
                f"Retained rest boundary: {_date(row.rest_ends_at)}.",
                "A saved calendar cannot prove later changes "
                "or reliably erase earlier imports.",
            )
        )
        # No LOCATION property: a current demand label is not immutable accepted
        # work-location evidence. Its explicit source meaning stays in DESCRIPTION.
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:shift-{row.commitment_id}@maru.invalid",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_calendar_instant(row.starts_at)}",
                f"DTEND:{_calendar_instant(row.ends_at)}",
                "CLASS:PRIVATE",
                f"STATUS:{status}",
                f"TRANSP:{transparency}",
                f"SUMMARY:{_calendar_text(label + ': ' + instructions.title)}",
                f"DESCRIPTION:{_calendar_text(description)}",
                f"X-MARU-WORK-STATE:{row.status}",
                f"X-MARU-WORK-VERSION:{row.version}",
                f"X-MARU-DEMAND-VERSION:{instructions.version}",
                "END:VEVENT",
            )
        )
    return lines


def render_personal_timetable_calendar(snapshot: PersonalTimetable) -> bytes:
    """Encode purpose-labelled private host presence and retained work, never iTIP.

    Parameters
    ----------
    snapshot : PersonalTimetable
        Fresh complete independently authorized personal projection.

    Returns
    -------
    bytes
        Bounded RFC 5545 text with stable audience-distinct IDs and owner states.

    Raises
    ------
    PersonalCalendarUnavailableError
        If an adopted hosting release is withdrawn or invalidated.

    Notes
    -----
    Only approved host presence creates a hosting event. Shift claims remain
    tentative, removals cancelled and completed records explicitly historical;
    none proves attendance. Withdrawn/invalidated hosting blocks the combined
    import rather than implying a complete current calendar; JSON/print can
    still describe that known state alongside unchanged retained work. The
    eight-MiB byte bound, escaping and UTF-8 octet folding are shared with public
    formats, never their authority or payload. No method, recipients, alerts or
    remote-import cancellation guarantee is emitted.
    """
    personal_timetable_document(snapshot)
    if snapshot.hosting is not None and snapshot.hosting.reference.state in {
        ProgrammeReleaseState.WITHDRAWN,
        ProgrammeReleaseState.INVALIDATED,
    }:
        raise PersonalCalendarUnavailableError
    stamp = _calendar_instant(snapshot.checked_at.replace(microsecond=0))
    state = (
        snapshot.hosting.reference.state.value
        if snapshot.hosting is not None and snapshot.hosting.reference.state is not None
        else "no-confirmed-hosting"
        if snapshot.hosting is not None
        else "unadopted"
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Maru//Personal timetable//EN",
        "CALSCALE:GREGORIAN",
        f"X-MARU-CHECKED-AT:{stamp}",
        f"X-MARU-HOST-RELEASE-STATE:{state}",
        *(
            [
                "X-MARU-EDITION-NAME:" + _calendar_text(snapshot.edition_label.name),
                f"X-MARU-EDITION-VERSION:{snapshot.edition_label.version}",
            ]
            if snapshot.edition_label is not None
            else []
        ),
        *_host_calendar_events(snapshot, stamp),
        *_work_calendar_events(snapshot, stamp),
        "END:VCALENDAR",
    ]
    return _bounded_bytes(_fold(line) for line in lines)
