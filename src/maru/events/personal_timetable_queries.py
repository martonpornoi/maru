"""Minimized edition label for independently proven personal timetable purposes."""

from dataclasses import dataclass
from uuid import UUID

from .models import EventEdition


@dataclass(frozen=True, slots=True)
class PersonalTimetableEditionChoice:
    """Minimized edition context for a separately proven own timetable purpose.

    Attributes
    ----------
    organization_id, edition_id, series_id
        Exact coherent owner chain, not discovery authority.
    name, code
        Current human label and stable series-local edition code.
    version
        Current Events aggregate version for source comparison.
    """

    organization_id: UUID
    edition_id: UUID
    series_id: UUID
    name: str
    code: str
    version: int


def resolve_personal_timetable_edition_choice(
    *, organization_id: UUID, edition_id: UUID
) -> PersonalTimetableEditionChoice | None:
    """Resolve minimal choice context after independent actual own-purpose proof.

    Parameters
    ----------
    organization_id : UUID
        Independently admitted owner under the consumer's canonical parent locks.
    edition_id : UUID
        Edition with actual retained own hosting/work and current owner authority.

    Returns
    -------
    PersonalTimetableEditionChoice | None
        Coherent minimal labels and owner IDs, or unavailable ownership.

    Notes
    -----
    This internal reference grants no permission and is not an edition directory.
    The consumer owns complete source comparison and required disclosure audit.
    """
    row = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .values_list(
            "organization_id", "id", "series_id", "name", "slug", "aggregate_version"
        )
        .first()
    )
    return PersonalTimetableEditionChoice(*row) if row is not None else None


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
