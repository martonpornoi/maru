"""Minimized organizer labels for independently proven own timetable purposes."""

from dataclasses import dataclass
from uuid import UUID

from .models import ConventionSeries


@dataclass(frozen=True, slots=True)
class PersonalTimetableOrganizerLabels:
    """Human labels and codes, never organizer governance or contact records.

    Attributes
    ----------
    organization_id, series_id
        Exact independently admitted owner chain.
    organization_name, organization_code, series_name, series_code
        Current public labels and stable human codes distinguishing duplicate names.
    """

    organization_id: UUID
    series_id: UUID
    organization_name: str
    organization_code: str
    series_name: str
    series_code: str


def resolve_personal_timetable_organizer_labels(
    *, organization_id: UUID, series_id: UUID
) -> PersonalTimetableOrganizerLabels | None:
    """Resolve minimal labels only after a consumer proves its own retained purpose.

    Parameters
    ----------
    organization_id : UUID
        Independently admitted owner under the consumer's canonical parent locks.
    series_id : UUID
        Exact Events-owned series reference for the admitted purpose's edition.

    Returns
    -------
    PersonalTimetableOrganizerLabels | None
        Current minimal coherent labels, or unavailable ownership.

    Notes
    -----
    This internal reference is not a directory or a permission token. The consumer
    must require actual retained own work/hosting and independent current owner
    authorization, recheck source facts and audit before any disclosure.
    """
    row = (
        ConventionSeries.objects.filter(id=series_id, organization_id=organization_id)
        .values_list(
            "organization_id",
            "id",
            "organization__name",
            "organization__slug",
            "name",
            "slug",
        )
        .first()
    )
    return PersonalTimetableOrganizerLabels(*row) if row is not None else None
