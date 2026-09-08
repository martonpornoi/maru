"""Audited non-mutating candidate and unsaved-placement conflict previews."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from django.db.models import F

from .adoption import SCHEDULING_TIME_CONFLICT_SOURCE
from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_CONFLICTS
from .catalogs import DEFERRED_SCHEDULING_CHECKS, MAX_OCCURRENCES
from .command_support import (
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from .conflicts import (
    SchedulingDayFacts,
    SchedulingOccurrenceFacts,
    SchedulingPlacementFacts,
)
from .evaluation_sources import (
    _evaluate_candidate_facts,
    _placement_facts,
    _require_source_adoption,
    _SchedulingSourceRead,
)
from .inputs import require_identifier, require_version
from .models import SchedulingCandidateRevision
from .placement_commands import _placement_revisions
from .planning_queries import _ownership, _read
from .time_rules import SchedulingWindow

if TYPE_CHECKING:
    from uuid import UUID

    from .authorization import AuthorizedSchedulingScope, SchedulingAuthorizer
    from .conflicts import SchedulingFinding
    from .inputs import SchedulingPlacementInput
    from .planning_queries import SchedulingReadRequest

PREVIEW_FIELDS: Final = frozenset({"conflicts", "dependency_versions"})


@dataclass(frozen=True, slots=True)
class PlanningSourceStatus:
    """Availability of one declared source, independent of finding severity.

    Attributes
    ----------
    source_code
        Exact closed conflict-source contract.
    available
        Whether the owner supplied its complete authorized snapshot.
    """

    source_code: str
    available: bool


@dataclass(frozen=True, slots=True)
class SchedulingPlanningPreview:
    """Ephemeral findings, never saved evaluation or reservation authority.

    Attributes
    ----------
    candidate_id
        Exact scoped private candidate.
    candidate_version
        Base version observed under the edition mutex.
    proposed_occurrence_id
        Replaced or added occurrence, or none for the saved manifest.
    findings
        Closed minimized findings without personal calendars or host identifiers.
    sources
        Availability of each declared owner source, not a passing-check claim.
    not_evaluated
        Explicit concerns outside this evaluator, even when findings are empty.
    complete
        Whether all implemented checks were available; blockers may still exist.
    """

    candidate_id: UUID
    candidate_version: int
    proposed_occurrence_id: UUID | None
    findings: tuple[SchedulingFinding, ...]
    sources: tuple[PlanningSourceStatus, ...]
    not_evaluated: tuple[str, ...]
    complete: bool


def _proposed_facts(
    request: SchedulingReadRequest, placement: SchedulingPlacementInput
) -> SchedulingPlacementFacts:
    sources = _placement_revisions(**_ownership(request), intent=placement)
    occurrence, day = sources.occurrence, sources.day
    # A new draft placement is not the old physically reserved placement.
    # Its transient identifier cannot exclude a retained reservation as "own".
    return SchedulingPlacementFacts(
        uuid4(),
        SchedulingOccurrenceFacts(
            occurrence.occurrence_id,
            occurrence.occurrence.programme_item_id,
            occurrence.sequence,
            occurrence.sequence,
            occurrence.lifecycle == "active",
        ),
        SchedulingDayFacts(
            day.day_id,
            day.sequence,
            day.sequence,
            day.lifecycle == "active",
            SchedulingWindow(day.starts_at, day.ends_at),
            day.precision_minutes,
        ),
        placement.space_selection_id,
        placement.envelope,
        placement.capacity_mode,
        placement.expected_attendance,
        placement.host_presences,
    )


def preview_scheduling_candidate(
    request: SchedulingReadRequest,
    *,
    candidate_id: UUID,
    expected_version: int,
    placement: SchedulingPlacementInput | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingPlanningPreview:
    """Evaluate an exact candidate with an optional unsaved replacement or addition.

    Both input paths reuse the stored-report evaluator and independent owner
    queries. Only minimized read audits may be written. This query never records
    a report, advances a version, creates a booking or acknowledges a warning.
    A later save, evaluation or reservation must reauthorize and check versions.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted scope and actor attribution, not a command or consent receipt.
    candidate_id : UUID
        Exact current draft in the authorized edition.
    expected_version : int
        Explicit observed candidate version; a stale form is not silently rebased.
    placement : SchedulingPlacementInput | None, default=None
        Complete unsaved placement intent, or none to inspect the saved manifest.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary conflict-read policy or doubly gated isolated-test admission.

    Returns
    -------
    SchedulingPlanningPreview
        Ephemeral minimized current findings with unavailable and deferred checks.
    """
    require_identifier(candidate_id)
    require_version(expected_version)

    def load(_scope: AuthorizedSchedulingScope) -> SchedulingPlanningPreview:
        source_request = _SchedulingSourceRead(
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
        )
        _require_source_adoption(source_request)
        revision = (
            SchedulingCandidateRevision.objects.filter(
                **_ownership(request),
                candidate_id=candidate_id,
                sequence=F("candidate__aggregate_version"),
            )
            .select_related("candidate")
            .first()
        )
        if revision is None:
            raise SchedulingUnavailableError
        if revision.sequence != expected_version:
            raise SchedulingVersionConflictError
        if revision.candidate.lifecycle != "draft":
            raise SchedulingLifecycleConflictError
        facts = _placement_facts(revision)
        if placement is not None:
            intent = placement.normalized()
            retained = tuple(
                fact for fact in facts if fact.occurrence.id != intent.occurrence_id
            )
            if len(retained) >= MAX_OCCURRENCES:
                raise SchedulingLimitError
            facts = (*retained, _proposed_facts(request, intent))
        current = _evaluate_candidate_facts(source_request, revision, facts)
        return SchedulingPlanningPreview(
            candidate_id,
            revision.sequence,
            placement.occurrence_id if placement is not None else None,
            current.findings,
            tuple(
                PlanningSourceStatus(
                    str(source["source_code"]),
                    source["edition_version"] is not None
                    if source["source_code"] == SCHEDULING_TIME_CONFLICT_SOURCE
                    else source["available"] is True,
                )
                for source in current.evidence
            ),
            DEFERRED_SCHEDULING_CHECKS,
            current.complete,
        )

    return _read(
        request,
        capability=VIEW_CONFLICTS,
        fields=PREVIEW_FIELDS,
        purpose="candidate_preview",
        authorizer=authorizer,
        loader=load,
    )
