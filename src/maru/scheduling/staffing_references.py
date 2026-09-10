"""Opaque occurrence references for independently governed Programme staffing."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from maru.scheduling.models import SchedulingOccurrence


@dataclass(frozen=True, slots=True)
class StaffingOccurrenceReference:
    """Expose only an exact occurrence's version and lifecycle.

    Attributes
    ----------
    occurrence_id
        Stable Scheduling-owned identifier.
    version
        Current metadata version, not a candidate or release version.
    active
        Whether this retained occurrence accepts new planning work.
    """

    occurrence_id: UUID
    version: int
    active: bool


def resolve_staffing_occurrence_reference(
    *, organization_id: UUID, edition_id: UUID, item_id: UUID, occurrence_id: UUID
) -> StaffingOccurrenceReference | None:
    """Resolve an exact item-linked occurrence without private timetable content.

    Callers authorize their own command and hold the canonical edition write
    scope. This internal reference seam is not a user-facing discovery reader,
    does not grant authority, and does not disclose candidate placements.

    Parameters
    ----------
    organization_id : UUID
        Exact expected tenant.
    edition_id : UUID
        Exact expected edition.
    item_id : UUID
        Independently authorized Programme owner identifier.
    occurrence_id : UUID
        Exact Scheduling occurrence supplied by the caller.

    Returns
    -------
    StaffingOccurrenceReference | None
        Minimal metadata, or indistinguishable invalid/foreign absence.
    """
    if any(
        not isinstance(value, UUID)
        for value in (organization_id, edition_id, item_id, occurrence_id)
    ):
        return None
    row = (
        SchedulingOccurrence.objects.filter(
            id=occurrence_id,
            organization_id=organization_id,
            edition_id=edition_id,
            programme_item_id=item_id,
        )
        .values("id", "aggregate_version", "lifecycle")
        .first()
    )
    if row is None:
        return None
    return StaffingOccurrenceReference(
        row["id"], row["aggregate_version"], row["lifecycle"] == "active"
    )
