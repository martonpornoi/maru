"""Minimized edition label for independently proven personal timetable purposes."""

from dataclasses import dataclass
from uuid import UUID

from .models import EventEdition


@dataclass(frozen=True, slots=True)
class PersonalTimetableEditionLabel:
    """Current human-readable context, not public event discovery.

    Attributes
    ----------
    name
        Current edition label only; no lifecycle, settings or organizer contacts.
    version
        Current Events aggregate version identifying the observed label source.
    """

    name: str
    version: int


def resolve_personal_timetable_edition_label(
    *, organization_id: UUID, edition_id: UUID
) -> PersonalTimetableEditionLabel | None:
    """Resolve a label after the compositor proves actual own records and authority.

    Parameters
    ----------
    organization_id : UUID
        Exact tenant owning both edition and series, locked by the compositor.
    edition_id : UUID
        Edition in independently authorized nonempty own hosting or work records.

    Returns
    -------
    PersonalTimetableEditionLabel | None
        Current label/version, or unavailable for missing or incoherent scope.

    Notes
    -----
    This internal owner reference grants no permission. The consumer must hold
    canonical parents, require current exact-person owner authority and actual
    records before calling, and recheck those owners before disclosure. Empty
    personal scopes and anonymous public output must not use this reference.
    """
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .values_list("name", "aggregate_version")
        .first()
    )
    return PersonalTimetableEditionLabel(*row) if row is not None else None
