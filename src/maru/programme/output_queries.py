"""Exact release-selected reviewed copy, independently admitted by its owner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import DatabaseError, transaction
from django.db.models import Exists, OuterRef

from maru.scheduling.public_release_references import load_public_release_reference
from maru.scheduling.release_queries import ProgrammeReleaseState

from .inputs import require_uuid
from .models import ProgrammePublicRendition, ProgrammePublicRenditionWithdrawal
from .queries import ProgrammeQueryUnavailableError

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReleasedProgrammeCopy:
    """Only explicitly public text from one exact immutable selected rendition.

    Attributes
    ----------
    rendition_id
        Exact reviewed rendition identity selected by the checked current release.
    title
        Deliberately reviewed public title, not the current working title.
    summary
        Deliberately reviewed public summary.
    content_note
        Deliberately reviewed public content note, not private accessibility data.
    """

    rendition_id: UUID
    title: str
    summary: str
    content_note: str


def load_released_programme_copy(
    *, organization_id: UUID, edition_id: UUID, expected_release_id: UUID
) -> tuple[ReleasedProgrammeCopy, ...]:
    """Read the complete exact reviewed-copy set for the current public release.

    Parameters
    ----------
    organization_id : UUID
        Expected exact owner, independently verified by the release boundary.
    edition_id : UUID
        Exact edition whose current profile must admit public output.
    expected_release_id : UUID
        Optimistic source identity, not permission to read arbitrary history.

    Returns
    -------
    tuple[ReleasedProgrammeCopy, ...]
        Complete distinct released renditions, deterministically ordered by ID.

    Raises
    ------
    ProgrammeQueryUnavailableError
        For changed releases, withdrawn copy, missing or inconsistent owner rows.

    Notes
    -----
    Propagates SchedulingAuthorizationDeniedError for failed public admission,
    SchedulingUnavailableError for unverifiable release evidence and
    ValidationError for malformed identifiers from the owner reference boundary.
    Re-resolves Scheduling's owner reference; a caller cannot submit selections
    or promote a planner's manifest into permission. No reviewer, working-copy,
    host or private-reason column is fetched. Withdrawal never falls back to an
    older rendition, and newer approved copy does not replace the released one.
    """
    for value in (organization_id, edition_id, expected_release_id):
        require_uuid(value, field="release_reference")
    try:
        with transaction.atomic():
            reference = load_public_release_reference(
                organization_id=organization_id, edition_id=edition_id
            )
            if (
                reference.manifest.state is not ProgrammeReleaseState.AVAILABLE
                or reference.manifest.release_id != expected_release_id
            ):
                raise ProgrammeQueryUnavailableError
            selected = {
                row.public_rendition_id: row.item_id for row in reference.occurrences
            }
            if any(
                selected[row.public_rendition_id] != row.item_id
                for row in reference.occurrences
            ):
                raise ProgrammeQueryUnavailableError
            rows = tuple(
                ProgrammePublicRendition.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                    item__organization_id=organization_id,
                    item__edition_id=edition_id,
                    id__in=selected,
                )
                .annotate(
                    is_withdrawn=Exists(
                        ProgrammePublicRenditionWithdrawal.objects.filter(
                            rendition_id=OuterRef("pk")
                        )
                    )
                )
                .order_by("id")
                .values_list(
                    "id",
                    "item_id",
                    "public_title",
                    "public_summary",
                    "public_content_note",
                    "is_withdrawn",
                )[: len(selected) + 1]
            )
            if len(rows) != len(selected) or any(
                selected[identifier] != item or withdrawn
                for identifier, item, _title, _summary, _note, withdrawn in rows
            ):
                raise ProgrammeQueryUnavailableError
            if (
                load_public_release_reference(
                    organization_id=organization_id, edition_id=edition_id
                )
                != reference
            ):
                raise ProgrammeQueryUnavailableError
            return tuple(
                ReleasedProgrammeCopy(identifier, title, summary, note)
                for identifier, _item, title, summary, note, _withdrawn in rows
            )
    except DatabaseError as error:
        raise ProgrammeQueryUnavailableError from error
