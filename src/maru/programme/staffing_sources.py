"""Independently authorized exact requirement and timetable selection for demand."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from maru.scheduling.authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizer,
)
from maru.scheduling.planning_queries import (
    SchedulingReadRequest,
    load_scheduling_planning,
)

from .authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    PROGRAMME_VIEW_STAFFING,
    ProgrammeAuthorizer,
    authorize_programme_scope,
)
from .inputs import canonical_digest
from .staffing_inputs import ProgrammeStaffingExpectation, ProgrammeStaffingSource
from .staffing_queries import (
    ProgrammeStaffingReadRequest,
    load_programme_staffing_requirements,
)

if TYPE_CHECKING:
    from uuid import UUID


class ProgrammeStaffingSourceConflictError(RuntimeError):
    """An authorized explicit source selection is stale, absent or no longer usable."""


@dataclass(frozen=True, slots=True)
class ProgrammeStaffingSelection:
    """Freeze exact work and timetable evidence; this is not portable authority.

    Attributes
    ----------
    item_id
        Exact Programme item owning the requirement.
    source
        Explicit immutable requirement/candidate/placement selection.
    requirement_item_version
        Item version when the chosen requirement revision was recorded.
    candidate_version
        Current version of the explicitly selected private alternative.
    edition_version
        Current Events version used by the timetable snapshot.
    expectation
        Explicit Programme work terms, never inferred from audience-facing times.
    evidence_digest
        Exact selection/work fingerprint for later preview comparison, not authority.
    """

    item_id: UUID
    source: ProgrammeStaffingSource
    requirement_item_version: int
    candidate_version: int
    edition_version: int
    expectation: ProgrammeStaffingExpectation
    evidence_digest: str


def load_programme_staffing_selection(
    request: ProgrammeStaffingReadRequest,
    *,
    source: ProgrammeStaffingSource,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
    scheduling_authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> ProgrammeStaffingSelection:
    """Resolve both owners before using an exact private alternative as staffing input.

    Callers performing writes acquire the canonical Workforce scope before this
    read. The retained edition mutex makes both owner projections coherent until
    the surrounding transaction ends. A later command must resolve again: neither
    the typed result nor its digest grants authority or proves freshness later.

    Parameters
    ----------
    request : ProgrammeStaffingReadRequest
        Exact actor/tenant/edition/item scope and trusted audit attribution.
    source : ProgrammeStaffingSource
        Deliberately selected requirement revision and candidate manifest placement.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Independent current Programme read policy, including its field ceiling.
    scheduling_authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent current Scheduling policy; Programme authority never substitutes.

    Returns
    -------
    ProgrammeStaffingSelection
        Complete current source evidence and explicit work terms, with no personnel.

    Raises
    ------
    ProgrammeStaffingSourceConflictError
        If the exact requirement or private alternative no longer matches selection.
    """
    with transaction.atomic():
        # Admission precedes parsing the opaque selection. The Programme reader
        # retains the edition mutex, reused by Scheduling and a calling writer.
        overview = load_programme_staffing_requirements(
            request, authorizer=programme_authorizer
        )
        if not isinstance(source, ProgrammeStaffingSource):
            raise ProgrammeStaffingSourceConflictError
        source = source.validated()
        requirement = next(
            (
                row
                for row in overview.requirements
                if row.requirement_id == source.requirement_id
            ),
            None,
        )
        if (
            requirement is None
            or requirement.lifecycle != "active"
            or (
                requirement.revision_id,
                requirement.version,
                requirement.occurrence_id,
                requirement.occurrence_version,
            )
            != (
                source.requirement_revision_id,
                source.requirement_version,
                source.occurrence_id,
                source.occurrence_version,
            )
        ):
            raise ProgrammeStaffingSourceConflictError
        planning = load_scheduling_planning(
            SchedulingReadRequest(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                request.correlation_id,
            ),
            candidate_id=source.candidate_id,
            authorizer=scheduling_authorizer,
        )
        candidate = next(
            (row for row in planning.candidates if row.id == source.candidate_id), None
        )
        occurrence = next(
            (row for row in planning.occurrences if row.id == source.occurrence_id),
            None,
        )
        placement = next(
            (row for row in planning.placements if row.id == source.placement_id), None
        )
        day = next(
            (
                row
                for row in planning.days
                if placement is not None and row.id == placement.day_id
            ),
            None,
        )
        if (
            candidate is None
            or occurrence is None
            or placement is None
            or day is None
            or candidate.lifecycle != "draft"
            or candidate.revision_id != source.candidate_revision_id
            or occurrence.lifecycle != "active"
            or occurrence.item_id != request.item_id
            or occurrence.version != source.occurrence_version
            or placement.occurrence_id != source.occurrence_id
            or placement.occurrence_revision_id != occurrence.revision_id
            or day.lifecycle != "active"
            or placement.day_revision_id != day.revision_id
            or planning.selected_candidate_id != source.candidate_id
            or not planning.accepts_writes
        ):
            raise ProgrammeStaffingSourceConflictError
        authorize_programme_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=PROGRAMME_VIEW_STAFFING,
            requested_fields=frozenset({"staffing_requirements"}),
            authorizer=programme_authorizer,
        )
        evidence = canonical_digest(
            {
                "item_id": request.item_id,
                "source": asdict(source),
                "requirement_item_version": requirement.item_version,
                "candidate_version": candidate.version,
                "edition_version": planning.edition_version,
                "expectation": asdict(requirement.expectation),
            }
        )
        return ProgrammeStaffingSelection(
            request.item_id,
            source,
            requirement.item_version,
            candidate.version,
            planning.edition_version,
            requirement.expectation,
            evidence,
        )
