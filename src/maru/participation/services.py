"""Commands owned by participation and called by explicit workflows."""

from uuid import UUID

from django.core.exceptions import ValidationError

from maru.participation.models import Participation


def snapshot_participations_for_archive(*, edition_id: UUID) -> int:
    """Snapshot participations for archive.

    Parameters
    ----------
    edition_id : UUID
        The identifier of the event edition that scopes the operation.

    Returns
    -------
    int
        The number of records affected by the completed operation.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    participations = Participation.objects.filter(edition_id=edition_id)
    first = participations.select_related("edition__series").first()
    if first is None:
        return 0
    if first.edition.lifecycle != "closing":
        raise ValidationError(
            "Participation snapshots may be finalized only while closing.",
            code="edition_not_closing",
        )
    return participations.update(
        edition_name_snapshot=first.edition.name,
        series_name_snapshot=first.edition.series.name,
    )
