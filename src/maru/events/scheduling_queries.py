"""Minimized Events-owned lifecycle reference for timetable planning."""

from dataclasses import dataclass
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.events.models import EventEdition

_PLANNING_LIFECYCLES = frozenset({"draft", "preparing", "ready", "live"})


@dataclass(frozen=True, slots=True)
class SchedulingEditionReference:
    """Exact edition identity, source version and current planning consequence.

    Attributes
    ----------
    organization_id
        Organization owning both edition and convention series.
    edition_id
        Exact edition to which the caller is independently authorized.
    version
        Current Events aggregate version for dependency freshness.
    accepts_scheduling_writes
        Whether current lifecycle admits private timetable planning.
    zone_name
        Events-owned IANA zone for explicit local timetable input and display.
    """

    organization_id: UUID
    edition_id: UUID
    version: int
    accepts_scheduling_writes: bool
    zone_name: str


def resolve_scheduling_edition_reference(
    *, organization_id: UUID, edition_id: UUID, lock: bool = False
) -> SchedulingEditionReference | None:
    """Resolve timetable scope without reopening Programme content planning.

    Parameters
    ----------
    organization_id : UUID
        Expected exact organization and series owner.
    edition_id : UUID
        Exact edition requested by an independently authorized caller.
    lock : bool, default=False
        Whether to retain the edition mutex inside the caller's transaction.

    Returns
    -------
    SchedulingEditionReference | None
        Current version, time zone and scheduling consequence without labels or private
        edition facts; absent or incoherent scope returns unavailable.
    """
    query = EventEdition.objects.all()
    if lock:
        query = query.select_for_update(of=("self",))
    try:
        row = (
            query.filter(
                id=edition_id,
                organization_id=organization_id,
                series__organization_id=organization_id,
            )
            .values_list(
                "id", "organization_id", "aggregate_version", "lifecycle", "time_zone"
            )
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        return None
    if row is None:
        return None
    return SchedulingEditionReference(
        organization_id=row[1],
        edition_id=row[0],
        version=row[2],
        accepts_scheduling_writes=row[3] in _PLANNING_LIFECYCLES,
        zone_name=row[4],
    )
