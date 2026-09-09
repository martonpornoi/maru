"""Closed human explanations for already-authorized timetable conflict findings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .catalogs import SchedulingConflictCode as Code

if TYPE_CHECKING:
    from .conflicts import SchedulingFinding


_EXPLANATIONS = {
    Code.EDITION_UNAVAILABLE: (
        "Edition dates are unavailable",
        "Restore the trusted edition date source before relying on these checks.",
    ),
    Code.DAY_CHANGED: (
        "Service-day metadata changed",
        "Review the current day and explicitly save the intended placement again.",
    ),
    Code.DAY_RETIRED: (
        "The selected service day is retired",
        "Choose an active service day; retained history is not "
        "a new planning destination.",
    ),
    Code.EDITION_BOUNDS: (
        "The envelope extends beyond the edition",
        "Keep preparation, delivery and teardown inside the trusted edition dates.",
    ),
    Code.DAY_BOUNDS: (
        "The envelope extends beyond the service day",
        "Adjust the explicit dates or select a service day "
        "covering the whole envelope.",
    ),
    Code.MINUTE_GRID: (
        "Times do not match the service-day precision",
        "Choose exact minutes on the selected day's configured grid.",
    ),
    Code.OCCURRENCE_CHANGED: (
        "Occurrence metadata changed",
        "Review the current occurrence and explicitly save "
        "the intended placement again.",
    ),
    Code.OCCURRENCE_RETIRED: (
        "The occurrence is retired",
        "Retain its history and use an active occurrence, or explicitly unplace it.",
    ),
    Code.PROGRAMME_UNAVAILABLE: (
        "Programme source checks are unavailable",
        "Restore the independently authorized Programme source "
        "before relying on this check.",
    ),
    Code.ITEM_RETIRED: (
        "The Programme item is retired",
        "Use an active item occurrence or explicitly remove "
        "this placement from the draft.",
    ),
    Code.HOST_REQUIRED: (
        "Required hosting has not been established",
        "Select the explicit confirmed host relationships "
        "and required presence intervals.",
    ),
    Code.HOST_NOT_CURRENT: (
        "A required host relationship is not current",
        "Review the host's current relationship; do not confirm on their behalf.",
    ),
    Code.HOST_SOURCE_UNAVAILABLE: (
        "Host availability checks are unavailable",
        "Restore the authorized current host source; missing data is not availability.",
    ),
    Code.HOST_UNAVAILABLE: (
        "A required host has no usable shared availability",
        "Ask the person to confirm and deliberately share "
        "suitable per-item availability.",
    ),
    Code.HOST_OUTSIDE_AVAILABILITY: (
        "Required presence is outside shared availability",
        "Choose a covered interval or ask the person "
        "to update their own shared periods.",
    ),
    Code.HOST_OUTSIDE_PREFERENCE: (
        "Required presence is outside a stated preference",
        "Discuss a preferred interval, or explicitly acknowledge "
        "a fresh warning with a reason.",
    ),
    Code.HOST_OVERLAP: (
        "Required host presence overlaps another occurrence",
        "Move or resize the affected required intervals; "
        "do not infer extra availability.",
    ),
    Code.VENUE_UNAVAILABLE: (
        "Venue checks are unavailable",
        "Restore the independently authorized room source "
        "before relying on this check.",
    ),
    Code.VENUE_INACTIVE: (
        "The selected venue or room is inactive",
        "Choose an active selected room or resolve its status with Venues.",
    ),
    Code.VENUE_CAPACITY: (
        "Requested attendance exceeds configured room capacity",
        "Choose a suitable room/configuration or explicitly "
        "reduce the requested attendance.",
    ),
    Code.VENUE_AVAILABILITY_MISSING: (
        "Explicit room availability is missing",
        "Ask Venues to establish availability; absence is not "
        "permission to occupy a room.",
    ),
    Code.VENUE_HARD_AVAILABILITY: (
        "The envelope is outside room availability",
        "Choose an available interval covering preparation, delivery and teardown.",
    ),
    Code.CANDIDATE_ROOM_OVERLAP: (
        "Room envelopes overlap in this private draft",
        "Move an occurrence or select a non-conflicting room for the whole envelope.",
    ),
    Code.RESERVED_ROOM_OVERLAP: (
        "An existing physical hold conflicts with this envelope",
        "Choose another interval or coordinate an explicit hold change with Venues.",
    ),
    Code.TURNOVER_OVERLAP: (
        "Preparation and teardown share a permitted turnover interval",
        "Review the handover, then adjust the intervals or explicitly "
        "acknowledge a fresh warning with a reason.",
    ),
    Code.EVALUATION_LIMIT: (
        "The complete conflict check exceeded its bound",
        "Reduce the candidate's planning complexity or resolve the limit; "
        "do not treat this as a pass.",
    ),
}


def describe_planning_findings(
    findings: tuple[SchedulingFinding, ...],
) -> tuple[dict[str, Any], ...]:
    """Attach closed causes and safe next actions without loading hidden owner data.

    Parameters
    ----------
    findings : tuple[SchedulingFinding, ...]
        Already-authorized current, proposed or explicitly historical findings.

    Returns
    -------
    tuple[dict[str, Any], ...]
        Finding plus plain-text explanation and next action; no automatic override.
    """
    return tuple(
        {
            "finding": finding,
            "explanation": _EXPLANATIONS[finding.code][0],
            "next_action": _EXPLANATIONS[finding.code][1],
        }
        for finding in findings
    )
