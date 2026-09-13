"""Closed bounded private operator formats, independent of public/person outputs."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maru.programme.catalogs import MAX_PROGRAMME_PRIVATE_TEXT_LENGTH
from maru.programme.operator_queries import OperatorDeliveryInstructions
from maru.programme.output_queries import ReleasedProgrammeCopy
from maru.venues.programme_output_queries import ReleasedRoomWayfinding
from maru.workforce.operator_links import OperatorWorkLink
from maru.workforce.operator_queries import (
    OperatorRetainedWork,
    OperatorStaffingDemand,
    OperatorStaffingSnapshot,
)
from maru.workforce.shift_queries import MAX_SHIFT_COMMITMENTS, MAX_SHIFT_DEMANDS

from .catalogs import MAX_OCCURRENCES
from .operator_output_queries import (
    OPERATOR_OPTIONAL_LAYERS,
    OperatorRunSheet,
    OperatorRunSheetEntry,
)
from .operator_release_references import (
    OperatorReleaseOccurrence,
    OperatorReleaseReference,
)
from .operator_scope import OperatorScopeKind
from .output_rendering import (
    TimetableOutputInvalidError,
    TimetableOutputUnavailableError,
    _bounded_bytes,
    _calendar_instant,
    _calendar_text,
    _fold,
    _identifier,
    _instant,
    _text,
    _version,
)
from .release_queries import ProgrammeReleaseState
from .time_rules import SchedulingEnvelope

if TYPE_CHECKING:
    from datetime import datetime

OPERATOR_RUN_SHEET_CONTRACT = "scheduling.operator-run-sheet@1"
SAVED_COPY_NOTICE = (
    "Private point-in-time operator copy. Recheck Maru before use; saved copies "
    "cannot receive withdrawal, instruction changes or remote erasure. "
    "Timetable context is not a personal assignment or proof of attendance."
)
_WORK_STATES = frozenset({"claimed", "confirmed", "removed", "completed"})
_DEMAND_STATES = frozenset({"draft", "open", "locked", "completed", "cancelled"})
_MAX_DEMAND_HEADCOUNT = 1024


def _date(value: datetime | None) -> str | None:
    return _instant(value).isoformat() if value is not None else None


def _state(reference: OperatorReleaseReference, checked_at: datetime) -> None:
    if (
        type(reference) is not OperatorReleaseReference
        or type(reference.state) is not ProgrammeReleaseState
    ):
        raise TimetableOutputInvalidError
    _version(reference.pointer_version, initial=True)
    if type(reference.staffing_adopted) is not bool:
        raise TimetableOutputInvalidError
    if reference.release_id is not None:
        _identifier(reference.release_id)
    if (
        reference.published_at is not None
        and _instant(reference.published_at) > checked_at
    ):
        raise TimetableOutputInvalidError
    if reference.state in {
        ProgrammeReleaseState.AVAILABLE,
        ProgrammeReleaseState.INVALIDATED,
    }:
        if (
            reference.release_id is None
            or reference.published_at is None
            or reference.pointer_version == 0
        ):
            raise TimetableOutputInvalidError
    elif reference.release_id is not None or reference.published_at is not None:
        raise TimetableOutputInvalidError
    if (
        reference.state is ProgrammeReleaseState.ABSENT
        and reference.pointer_version != 0
    ):
        raise TimetableOutputInvalidError
    if (
        reference.state is ProgrammeReleaseState.WITHDRAWN
        and reference.pointer_version == 0
    ):
        raise TimetableOutputInvalidError


def _placement(row: OperatorReleaseOccurrence) -> dict[str, object]:
    if (
        type(row) is not OperatorReleaseOccurrence
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
    ):
        raise TimetableOutputInvalidError
    return {
        "occurrence_id": _identifier(row.occurrence_id),
        "placement_id": _identifier(row.placement_id),
        "item_id": _identifier(row.item_id),
        "rendition_id": _identifier(row.public_rendition_id),
        "space_id": _identifier(row.space_id),
        "day_id": _identifier(row.day_id),
        "day_starts_at": _date(row.day_starts_at),
        "day_ends_at": _date(row.day_ends_at),
        "setup_starts_at": _date(envelope.setup_starts_at),
        "effective_starts_at": _date(envelope.effective_starts_at),
        "effective_ends_at": _date(envelope.effective_ends_at),
        "teardown_ends_at": _date(envelope.teardown_ends_at),
    }


def _delivery(
    row: OperatorDeliveryInstructions | None, snapshot: OperatorRunSheet
) -> dict[str, object] | None:
    fields = snapshot.layers - {"staffing"}
    if not fields:
        if row is not None:
            raise TimetableOutputInvalidError
        return None
    if type(row) is not OperatorDeliveryInstructions:
        raise TimetableOutputInvalidError
    _identifier(row.item_id)
    _version(row.version, initial=True)
    if row.version == 0:
        if row.revision_id is not None or row.occurred_at is not None:
            raise TimetableOutputInvalidError
    elif row.revision_id is None or row.occurred_at is None:
        raise TimetableOutputInvalidError
    else:
        _identifier(row.revision_id)
        if _instant(row.occurred_at) > _instant(snapshot.checked_at):
            raise TimetableOutputInvalidError
    result: dict[str, object] = {
        "item_id": str(row.item_id),
        "revision_id": str(row.revision_id) if row.revision_id is not None else None,
        "version": row.version,
        "occurred_at": _date(row.occurred_at),
        "checked_at": _date(snapshot.checked_at),
    }
    for field in ("technical", "accessibility", "media"):
        value = getattr(row, field)
        if field in fields:
            result[field] = _text(value, MAX_PROGRAMME_PRIVATE_TEXT_LENGTH)
            if row.version == 0 and value != "":
                raise TimetableOutputInvalidError
        elif value is not None:
            raise TimetableOutputInvalidError
    return result


def _entry(row: OperatorRunSheetEntry, snapshot: OperatorRunSheet) -> dict[str, object]:
    if (
        type(row) is not OperatorRunSheetEntry
        or type(row.copy) is not ReleasedProgrammeCopy
        or type(row.room) is not ReleasedRoomWayfinding
    ):
        raise TimetableOutputInvalidError
    placement = _placement(row.placement)
    if (
        row.copy.rendition_id != row.placement.public_rendition_id
        or row.room.space_id != row.placement.space_id
        or (
            snapshot.kind is OperatorScopeKind.ROOM
            and row.room.space_id != snapshot.target_id
        )
    ):
        raise TimetableOutputInvalidError
    delivery = _delivery(row.delivery, snapshot)
    if row.delivery is not None and row.delivery.item_id != row.placement.item_id:
        raise TimetableOutputInvalidError
    _version(row.room.space_version)
    _version(row.room.venue_version)
    return {
        "placement": placement,
        "copy": {
            "rendition_id": str(row.copy.rendition_id),
            "title": _text(row.copy.title, 240, required=True),
            "summary": _text(row.copy.summary, 2000),
            "content_note": _text(row.copy.content_note, 500),
        },
        "wayfinding": {
            "space_id": str(row.room.space_id),
            "space_version": row.room.space_version,
            "venue_version": row.room.venue_version,
            "room": _text(row.room.room_name, 200, required=True),
            "venue": _text(row.room.venue_name, 200, required=True),
        },
        "delivery": delivery,
    }


def _retained(row: OperatorRetainedWork) -> dict[str, object]:
    if (
        type(row) is not OperatorRetainedWork
        or type(row.state) is not str
        or row.state not in _WORK_STATES
    ):
        raise TimetableOutputInvalidError
    if (
        not _instant(row.starts_at)
        < _instant(row.ends_at)
        <= _instant(row.rest_ends_at)
    ):
        raise TimetableOutputInvalidError
    if type(row.count) is not int or not 1 <= row.count <= MAX_SHIFT_COMMITMENTS:
        raise TimetableOutputInvalidError
    return {
        "starts_at": _date(row.starts_at),
        "ends_at": _date(row.ends_at),
        "rest_ends_at": _date(row.rest_ends_at),
        "state": row.state,
        "count": row.count,
    }


def _demand(row: OperatorStaffingDemand) -> dict[str, object]:
    if (
        type(row) is not OperatorStaffingDemand
        or type(row.state) is not str
        or row.state not in _DEMAND_STATES
    ):
        raise TimetableOutputInvalidError
    _identifier(row.demand_id)
    _version(row.version)
    if not _instant(row.starts_at) < _instant(row.ends_at):
        raise TimetableOutputInvalidError
    if (
        type(row.required_headcount) is not int
        or not 1 <= row.required_headcount <= _MAX_DEMAND_HEADCOUNT
    ):
        raise TimetableOutputInvalidError
    if (
        type(row.retained_work) is not tuple
        or len(row.retained_work) > MAX_SHIFT_COMMITMENTS
    ):
        raise TimetableOutputInvalidError
    retained = [_retained(work) for work in row.retained_work]
    keys = {
        (work.starts_at, work.ends_at, work.rest_ends_at, work.state)
        for work in row.retained_work
    }
    if (
        len(keys) != len(retained)
        or sum(work.count for work in row.retained_work) > MAX_SHIFT_COMMITMENTS
    ):
        raise TimetableOutputInvalidError
    return {
        "demand_id": str(row.demand_id),
        "version": row.version,
        "state": row.state,
        "title": _text(row.title, 160, required=True),
        "location": _text(row.location, 160),
        "briefing": _text(row.briefing, 1000, required=True),
        "supervision": _text(row.supervision, 500),
        "starts_at": _date(row.starts_at),
        "ends_at": _date(row.ends_at),
        "required_headcount": row.required_headcount,
        "retained_work": retained,
    }


def _staffing(snapshot: OperatorRunSheet) -> dict[str, object] | None:
    layer = snapshot.staffing
    if "staffing" not in snapshot.layers:
        if layer is not None:
            raise TimetableOutputInvalidError
        return None
    if (
        type(layer) is not OperatorStaffingSnapshot
        or type(layer.adopted) is not bool
        or layer.adopted != snapshot.reference.staffing_adopted
    ):
        raise TimetableOutputInvalidError
    if (
        type(layer.links) is not tuple
        or type(layer.demands) is not tuple
        or max(len(layer.links), len(layer.demands)) > MAX_SHIFT_DEMANDS
    ):
        raise TimetableOutputInvalidError
    if not layer.adopted and (layer.links or layer.demands):
        raise TimetableOutputInvalidError
    demands = [_demand(row) for row in layer.demands]
    indexed = {row.demand_id: row for row in layer.demands}
    if (
        len(indexed) != len(demands)
        or sum(work.count for row in layer.demands for work in row.retained_work)
        > MAX_SHIFT_COMMITMENTS
    ):
        raise TimetableOutputInvalidError
    occurrences = {row.placement.occurrence_id for row in snapshot.entries}
    links = []
    seen = set()
    for row in layer.links:
        if type(row) is not OperatorWorkLink:
            raise TimetableOutputInvalidError
        for identifier in (row.occurrence_id, row.binding_id, row.demand_id):
            _identifier(identifier)
        _version(row.binding_version)
        _version(row.demand_version)
        key = (row.binding_id, row.demand_id)
        if (
            row.occurrence_id not in occurrences
            or key in seen
            or type(row.current) is not bool
            or row.demand_id not in indexed
            or indexed[row.demand_id].version != row.demand_version
        ):
            raise TimetableOutputInvalidError
        seen.add(key)
        links.append(
            {
                "occurrence_id": str(row.occurrence_id),
                "binding_id": str(row.binding_id),
                "binding_version": row.binding_version,
                "demand_id": str(row.demand_id),
                "demand_version": row.demand_version,
                "current": row.current,
            }
        )
    if set(indexed) != {row.demand_id for row in layer.links}:
        raise TimetableOutputInvalidError
    return {"adopted": layer.adopted, "links": links, "demands": demands}


def operator_run_sheet_document(snapshot: OperatorRunSheet) -> dict[str, object]:
    """Validate the exact closed operator graph before any format can disclose it.

    Parameters
    ----------
    snapshot : OperatorRunSheet
        Fresh complete operator query result, never a caller dictionary or cache.

    Returns
    -------
    dict[str, object]
        Closed deterministic private document with no unrequested delivery fields.

    Raises
    ------
    TimetableOutputInvalidError
        If the graph is cross-audience, inconsistent, malformed or over-bound.

    Notes
    -----
    Serialization is not authorization. Serving always performs a fresh owner
    query. Empty available scopes differ from nonavailable release states; no
    dropped requested field can masquerade as a complete operator document.
    """
    if (
        type(snapshot) is not OperatorRunSheet
        or type(snapshot.kind) is not OperatorScopeKind
    ):
        raise TimetableOutputInvalidError
    for identifier in (
        snapshot.organization_id,
        snapshot.edition_id,
        snapshot.target_id,
    ):
        _identifier(identifier)
    if (
        snapshot.kind is OperatorScopeKind.EDITION
        and snapshot.target_id != snapshot.edition_id
    ):
        raise TimetableOutputInvalidError
    if (
        type(snapshot.layers) is not frozenset
        or not snapshot.layers <= OPERATOR_OPTIONAL_LAYERS
    ):
        raise TimetableOutputInvalidError
    checked = _instant(snapshot.checked_at)
    _state(snapshot.reference, checked)
    reference = snapshot.reference
    try:
        ZoneInfo(_text(reference.zone_name, 100, required=True))
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise TimetableOutputInvalidError from error
    if (
        type(snapshot.entries) is not tuple
        or type(reference.occurrences) is not tuple
        or len(snapshot.entries) > MAX_OCCURRENCES
        or len(reference.occurrences) != len(snapshot.entries)
    ):
        raise TimetableOutputInvalidError
    entries = [_entry(row, snapshot) for row in snapshot.entries]
    if tuple(row.placement for row in snapshot.entries) != reference.occurrences:
        raise TimetableOutputInvalidError
    if len({row.placement.occurrence_id for row in snapshot.entries}) != len(entries):
        raise TimetableOutputInvalidError
    if reference.state is not ProgrammeReleaseState.AVAILABLE and entries:
        raise TimetableOutputInvalidError
    return {
        "contract": OPERATOR_RUN_SHEET_CONTRACT,
        "audience": "private_operator",
        "organization_id": str(snapshot.organization_id),
        "edition_id": str(snapshot.edition_id),
        "scope_kind": snapshot.kind.value,
        "scope_id": str(snapshot.target_id),
        "department_membership": "rooms_and_linked_work"
        if reference.staffing_adopted
        else "rooms_only",
        "requested_layers": sorted(snapshot.layers),
        "release_state": reference.state.value,
        "release_id": str(reference.release_id) if reference.release_id else None,
        "pointer_version": reference.pointer_version,
        "published_at": _date(reference.published_at),
        "checked_at": _date(snapshot.checked_at),
        "zone_name": reference.zone_name,
        "notice": SAVED_COPY_NOTICE,
        "entries": entries,
        "staffing": _staffing(snapshot),
    }


def render_operator_run_sheet_json(snapshot: OperatorRunSheet) -> bytes:
    """Render the complete closed private JSON graph with an incremental byte bound.

    Parameters
    ----------
    snapshot : OperatorRunSheet
        Fresh independently authorized complete operator result.

    Returns
    -------
    bytes
        Deterministic UTF-8 JSON, rejecting invalid or oversized output.

    Notes
    -----
    Validation and byte limits propagate TimetableOutputInvalidError. Transport
    must never cache or treat prior serialization as current serving authority.
    """
    document = operator_run_sheet_document(snapshot)
    return _bounded_bytes(
        json.JSONEncoder(
            ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).iterencode(document)
    )


def _description(row: OperatorRunSheetEntry, snapshot: OperatorRunSheet) -> str:
    envelope = row.placement.envelope
    parts = [
        SAVED_COPY_NOTICE,
        row.copy.summary,
        row.copy.content_note,
        f"Preparation: {envelope.setup_starts_at.isoformat()}",
        f"Delivery: {envelope.effective_starts_at.isoformat()} "
        f"to {envelope.effective_ends_at.isoformat()}",
        f"Teardown ends: {envelope.teardown_ends_at.isoformat()}",
    ]
    if row.delivery is not None:
        parts.append(
            f"Current delivery revision: {row.delivery.revision_id}; "
            f"version {row.delivery.version}"
        )
        parts.extend(
            f"{field.title()}: {getattr(row.delivery, field)}"
            for field in ("technical", "accessibility", "media")
            if field in snapshot.layers
        )
    if snapshot.staffing is not None:
        parts.append(
            "Staffing is unadopted."
            if not snapshot.staffing.adopted
            else "Work counts are not current qualification, availability "
            "or attendance."
        )
        linked = {
            link.demand_id: link.current
            for link in snapshot.staffing.links
            if link.occurrence_id == row.placement.occurrence_id
        }
        for demand in snapshot.staffing.demands:
            if demand.demand_id not in linked:
                continue
            link_label = (
                "Current" if linked[demand.demand_id] else "Retained predecessor"
            )
            parts.extend(
                (
                    f"{link_label} demand: {demand.title}; {demand.state}; "
                    f"version {demand.version}; "
                    f"requested headcount {demand.required_headcount}",
                    f"Current requested work: {demand.starts_at.isoformat()} "
                    f"to {demand.ends_at.isoformat()}",
                    f"Location: {demand.location}",
                    demand.briefing,
                    demand.supervision,
                )
            )
            parts.extend(
                f"Retained {work.state} count {work.count}: "
                f"{work.starts_at.isoformat()} to {work.ends_at.isoformat()}; "
                f"rest ends {work.rest_ends_at.isoformat()}"
                for work in demand.retained_work
            )
    return "\n\n".join(part for part in parts if part)


def render_operator_run_sheet_calendar(snapshot: OperatorRunSheet) -> bytes:
    """Render private transparent run-of-show context, never invitations or a roster.

    Parameters
    ----------
    snapshot : OperatorRunSheet
        Fresh complete operator result with the same explicitly requested layers.

    Returns
    -------
    bytes
        Bounded UTF-8 iCalendar with escaped text, CRLF and octet-aware folding.

    Raises
    ------
    TimetableOutputUnavailableError
        If the release is absent, withdrawn or invalidated.

    Notes
    -----
    Complete validation propagates TimetableOutputInvalidError. Event intervals
    cover room preparation through teardown and disclose delivery times explicitly.
    Operator-purpose UIDs cannot overwrite public or personal timetable events.
    No attendee, organizer, alarm, invitation method or attendance claim is added.
    """
    # Apply the identical complete graph and byte budget before calendar creation.
    render_operator_run_sheet_json(snapshot)
    reference = snapshot.reference
    if reference.state is not ProgrammeReleaseState.AVAILABLE:
        raise TimetableOutputUnavailableError
    stamp = _calendar_instant(snapshot.checked_at.replace(microsecond=0))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Maru//Private operator run sheet//EN",
        "CALSCALE:GREGORIAN",
        f"X-MARU-SCOPE:{snapshot.kind.value}:{snapshot.target_id}",
        f"X-MARU-RELEASE-ID:{reference.release_id}",
        f"X-MARU-CHECKED-AT:{stamp}",
    ]
    for row in snapshot.entries:
        envelope = row.placement.envelope
        lines.extend(
            (
                "BEGIN:VEVENT",
                f"UID:programme-operator-{snapshot.kind.value}-{snapshot.target_id}-"
                f"{row.placement.occurrence_id}@maru.invalid",
                f"DTSTAMP:{stamp}",
                f"DTSTART:{_calendar_instant(envelope.setup_starts_at)}",
                f"DTEND:{_calendar_instant(envelope.teardown_ends_at)}",
                "CLASS:PRIVATE",
                "TRANSP:TRANSPARENT",
                f"SUMMARY:{_calendar_text(row.copy.title)}",
                f"DESCRIPTION:{_calendar_text(_description(row, snapshot))}",
                "LOCATION:"
                + _calendar_text(row.room.venue_name + " / " + row.room.room_name),
                f"X-MARU-RELEASE-ID:{reference.release_id}",
                f"X-MARU-POINTER-VERSION:{reference.pointer_version}",
                f"X-MARU-RENDITION-ID:{row.copy.rendition_id}",
                f"X-MARU-SPACE-VERSION:{row.room.space_version}",
                f"X-MARU-VENUE-VERSION:{row.room.venue_version}",
                "END:VEVENT",
            )
        )
    lines.append("END:VCALENDAR")
    return _bounded_bytes(_fold(line) for line in lines)
