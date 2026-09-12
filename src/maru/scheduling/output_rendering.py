"""Bounded deterministic public formats; serializers never confer serving authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maru.programme.output_queries import ReleasedProgrammeCopy
from maru.venues.programme_output_queries import ReleasedRoomWayfinding

from .catalogs import MAX_OCCURRENCES
from .output_queries import PublicProgrammeTimetable, PublicTimetableEntry
from .release_queries import ProgrammeReleaseState

if TYPE_CHECKING:
    from collections.abc import Iterable

PUBLIC_TIMETABLE_CONTRACT: Final = "scheduling.public-timetable@1"
MAX_TIMETABLE_OUTPUT_BYTES: Final = 8 * 1024 * 1024
_ASCII_SPACE: Final = 32
_ASCII_DELETE: Final = 127
_CALENDAR_LINE_OCTETS: Final = 75


class TimetableOutputInvalidError(ValueError):
    """Reject malformed, cross-audience, incomplete or oversized output safely."""

    def __init__(self) -> None:
        """Initialize a stable error without echoing unsafe source content."""
        super().__init__("A complete bounded audience-specific timetable is required.")


class TimetableOutputUnavailableError(ValueError):
    """Withhold calendar downloads when no currently available release exists."""

    def __init__(self) -> None:
        """Initialize a stable non-content state error."""
        super().__init__("No currently available Programme release can be downloaded.")


def _identifier(value: UUID) -> str:
    if type(value) is not UUID or value.int == 0:
        raise TimetableOutputInvalidError
    return str(value)


def _instant(value: datetime) -> datetime:
    if type(value) is not datetime or value.utcoffset() is None:
        raise TimetableOutputInvalidError
    try:
        return value.astimezone(UTC)
    except (ValueError, OverflowError) as error:
        raise TimetableOutputInvalidError from error


def _text(value: str, maximum: int, *, required: bool = False) -> str:
    if (
        type(value) is not str
        or len(value) > maximum
        or (required and not value.strip())
        or any(
            (ord(char) < _ASCII_SPACE and char not in "\t\n\r")
            or ord(char) == _ASCII_DELETE
            for char in value
        )
    ):
        raise TimetableOutputInvalidError
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise TimetableOutputInvalidError from error
    return value


def _version(value: int, *, initial: bool = False) -> None:
    if type(value) is not int or not (0 if initial else 1) <= value < 2**63 - 1:
        raise TimetableOutputInvalidError


def _validated_entries(
    snapshot: PublicProgrammeTimetable,
) -> tuple[PublicTimetableEntry, ...]:
    if (
        type(snapshot) is not PublicProgrammeTimetable
        or type(snapshot.state) is not ProgrammeReleaseState
    ):
        raise TimetableOutputInvalidError
    _version(snapshot.pointer_version, initial=True)
    checked_at = _instant(snapshot.checked_at)
    zone = _text(snapshot.zone_name, 100, required=True)
    try:
        ZoneInfo(zone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise TimetableOutputInvalidError from error
    if snapshot.release_id is not None:
        _identifier(snapshot.release_id)
    if (
        snapshot.published_at is not None
        and _instant(snapshot.published_at) > checked_at
    ):
        raise TimetableOutputInvalidError
    if type(snapshot.entries) is not tuple or len(snapshot.entries) > MAX_OCCURRENCES:
        raise TimetableOutputInvalidError
    _validate_state(snapshot)
    seen = set()
    for row in snapshot.entries:
        _validate_entry(row)
        if row.occurrence_id in seen:
            raise TimetableOutputInvalidError
        seen.add(row.occurrence_id)
    return tuple(
        sorted(
            snapshot.entries,
            key=lambda row: (_instant(row.starts_at), str(row.occurrence_id)),
        )
    )


def _validate_state(snapshot: PublicProgrammeTimetable) -> None:
    if snapshot.state is ProgrammeReleaseState.AVAILABLE:
        if (
            not snapshot.entries
            or snapshot.release_id is None
            or snapshot.published_at is None
            or snapshot.pointer_version == 0
        ):
            raise TimetableOutputInvalidError
    elif snapshot.entries:
        raise TimetableOutputInvalidError
    if snapshot.state is ProgrammeReleaseState.ABSENT and (
        snapshot.pointer_version != 0
        or snapshot.release_id is not None
        or snapshot.published_at is not None
    ):
        raise TimetableOutputInvalidError
    if snapshot.state is ProgrammeReleaseState.WITHDRAWN and (
        snapshot.pointer_version == 0
        or snapshot.release_id is not None
        or snapshot.published_at is not None
    ):
        raise TimetableOutputInvalidError
    if snapshot.state is ProgrammeReleaseState.INVALIDATED and (
        snapshot.pointer_version == 0
        or snapshot.release_id is None
        or snapshot.published_at is None
    ):
        raise TimetableOutputInvalidError


def _validate_entry(row: PublicTimetableEntry) -> None:
    if (
        type(row) is not PublicTimetableEntry
        or type(row.copy) is not ReleasedProgrammeCopy
        or type(row.room) is not ReleasedRoomWayfinding
    ):
        raise TimetableOutputInvalidError
    for identifier in (
        row.occurrence_id,
        row.copy.rendition_id,
        row.room.space_id,
        row.day_id,
    ):
        _identifier(identifier)
    _version(row.room.space_version)
    _version(row.room.venue_version)
    _text(row.copy.title, 240, required=True)
    _text(row.copy.summary, 2_000)
    _text(row.copy.content_note, 500)
    _text(row.room.room_name, 200, required=True)
    _text(row.room.venue_name, 200, required=True)
    if not (
        _instant(row.day_starts_at)
        <= _instant(row.starts_at)
        < _instant(row.ends_at)
        <= _instant(row.day_ends_at)
    ):
        raise TimetableOutputInvalidError


def _bounded_bytes(chunks: Iterable[str]) -> bytes:
    result = bytearray()
    for chunk in chunks:
        encoded = chunk.encode("utf-8")
        if len(result) + len(encoded) > MAX_TIMETABLE_OUTPUT_BYTES:
            raise TimetableOutputInvalidError
        result.extend(encoded)
    return bytes(result)


def render_public_timetable_json(snapshot: PublicProgrammeTimetable) -> bytes:
    """Serialize one fresh public projection with explicit state and source meaning.

    Parameters
    ----------
    snapshot : PublicProgrammeTimetable
        Complete audience-specific result obtained by the serving query now.

    Returns
    -------
    bytes
        Deterministic UTF-8 JSON, bounded to eight MiB with UTC ISO timestamps.

    Notes
    -----
    Validation and byte-bound helpers propagate TimetableOutputInvalidError for
    invalid shape, duplicate identity, private audience or exceeded bounds.
    This pure function authenticates no caller and establishes no freshness.
    Serve as application/json with no-store and nosniff, never inline HTML.
    No generic dataclass serialization can accidentally include a private field.
    """
    entries = _validated_entries(snapshot)
    document = {
        "contract": PUBLIC_TIMETABLE_CONTRACT,
        "audience": "public",
        "state": snapshot.state.value,
        "pointer_version": snapshot.pointer_version,
        "release_id": str(snapshot.release_id) if snapshot.release_id else None,
        "published_at": _instant(snapshot.published_at).isoformat()
        if snapshot.published_at
        else None,
        "checked_at": _instant(snapshot.checked_at).isoformat(),
        "zone_name": snapshot.zone_name,
        "room_label_source": "current_venue_wayfinding",
        "entries": [
            {
                "occurrence_id": str(row.occurrence_id),
                "public_rendition_id": str(row.copy.rendition_id),
                "title": row.copy.title,
                "summary": row.copy.summary,
                "content_note": row.copy.content_note,
                "space_id": str(row.room.space_id),
                "space_version": row.room.space_version,
                "venue_version": row.room.venue_version,
                "room_name": row.room.room_name,
                "venue_name": row.room.venue_name,
                "day_id": str(row.day_id),
                "day_starts_at": _instant(row.day_starts_at).isoformat(),
                "day_ends_at": _instant(row.day_ends_at).isoformat(),
                "starts_at": _instant(row.starts_at).isoformat(),
                "ends_at": _instant(row.ends_at).isoformat(),
            }
            for row in entries
        ],
    }
    return _bounded_bytes(
        json.JSONEncoder(
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).iterencode(document)
    )


def _calendar_text(value: str) -> str:
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _calendar_instant(value: datetime) -> str:
    current = _instant(value)
    if current.microsecond:
        # Approved Scheduling intervals have minute precision. Do not silently
        # round invalid event geometry. Observation stamps are truncated explicitly.
        raise TimetableOutputInvalidError
    return (
        f"{current.year:04d}{current.month:02d}{current.day:02d}T"
        f"{current.hour:02d}{current.minute:02d}{current.second:02d}Z"
    )


def _fold(line: str) -> str:
    segments: list[str] = []
    current: list[str] = []
    width = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if width + size > _CALENDAR_LINE_OCTETS:
            segments.append("".join(current))
            current = [" "]
            width = 1
        current.append(char)
        width += size
    segments.append("".join(current))
    return "\r\n".join(segments) + "\r\n"


def render_public_timetable_calendar(snapshot: PublicProgrammeTimetable) -> bytes:
    """Serialize a current available public release as a bounded iCalendar download.

    Parameters
    ----------
    snapshot : PublicProgrammeTimetable
        Fresh complete public result, never personal work or a retained cache.

    Returns
    -------
    bytes
        Deterministic RFC 5545 UTF-8 text with CRLF, octet folding and UTC instants.

    Raises
    ------
    TimetableOutputUnavailableError
        For absent, withdrawn or invalidated releases; no misleading empty download.

    Notes
    -----
    Stable occurrence UIDs survive republication. Public entries are transparent,
    and validation helpers propagate TimetableOutputInvalidError for invalid
    input, subsecond event timing or exceeded output bounds. Entries are
    not personal commitments. DTSTAMP records this materialized observation;
    release/owner versions remain explicit extension properties. No invitation,
    alarm, recipient, URL, recurrence or iTIP method is emitted. Downloads cannot
    remotely remove already imported entries or promise continuing freshness.
    """
    entries = _validated_entries(snapshot)
    if snapshot.state is not ProgrammeReleaseState.AVAILABLE:
        raise TimetableOutputUnavailableError
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Maru//Programme timetable//EN",
        "CALSCALE:GREGORIAN",
        f"X-MARU-RELEASE-ID:{snapshot.release_id}",
        f"X-MARU-POINTER-VERSION:{snapshot.pointer_version}",
        f"X-MARU-CHECKED-AT:{_calendar_instant(snapshot.checked_at.replace(microsecond=0))}",
    ]
    stamp = _calendar_instant(snapshot.checked_at.replace(microsecond=0))
    for row in entries:
        location = _calendar_text(row.room.venue_name + " / " + row.room.room_name)
        description = "\n\n".join(
            value for value in (row.copy.summary, row.copy.content_note) if value
        )
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:programme-{row.occurrence_id}@maru.invalid",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_calendar_instant(row.starts_at)}",
                f"DTEND:{_calendar_instant(row.ends_at)}",
                "CLASS:PUBLIC",
                "TRANSP:TRANSPARENT",
                f"SUMMARY:{_calendar_text(row.copy.title)}",
                f"DESCRIPTION:{_calendar_text(description)}",
                f"LOCATION:{location}",
                f"X-MARU-RELEASE-ID:{snapshot.release_id}",
                f"X-MARU-POINTER-VERSION:{snapshot.pointer_version}",
                f"X-MARU-RENDITION-ID:{row.copy.rendition_id}",
                f"X-MARU-DAY-ID:{row.day_id}",
                f"X-MARU-SPACE-VERSION:{row.room.space_version}",
                f"X-MARU-VENUE-VERSION:{row.room.venue_version}",
                "END:VEVENT",
            )
        )
    lines.append("END:VCALENDAR")
    return _bounded_bytes(_fold(line) for line in lines)
