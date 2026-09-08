"""Fresh conflict review without mistaking retained warnings for current authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from django.db.models import Exists, OuterRef

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER, VIEW_CONFLICTS
from .catalogs import MAX_CONFLICTS, SchedulingConflictCode, SchedulingConflictSeverity
from .command_support import SchedulingLimitError, SchedulingUnavailableError
from .conflicts import SchedulingFinding
from .evaluation_sources import (
    _current_evaluation,
    _finding_fingerprint,
    _SchedulingSourceRead,
)
from .inputs import require_identifier, require_version
from .models import (
    SchedulingConflict,
    SchedulingEvaluation,
    SchedulingWarningAcknowledgement,
)
from .planning_preview import (
    PREVIEW_FIELDS,
    SchedulingPlanningPreview,
    _preview_projection,
)
from .planning_queries import _ownership, _read

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from .authorization import AuthorizedSchedulingScope, SchedulingAuthorizer
    from .evaluation_sources import _CurrentEvaluation
    from .planning_queries import SchedulingReadRequest


class PlanningReviewState(StrEnum):
    """Saved evidence status; none of these values means approved or published."""

    NOT_RECORDED = "not_recorded"
    CURRENT = "current"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class PlanningSavedFinding:
    """Minimized retained finding and its fresh dependency eligibility.

    Attributes
    ----------
    id
        Exact persisted conflict identifier, never a preview identifier.
    finding
        Closed cause/severity and Scheduling occurrence references only.
    acknowledged
        Whether retained acknowledgement exists; no actor or rationale is copied.
    eligible_for_acknowledgement
        Fresh complete warning without acknowledgement, not mutation permission.
    """

    id: UUID
    finding: SchedulingFinding
    acknowledged: bool
    eligible_for_acknowledgement: bool


@dataclass(frozen=True, slots=True)
class SchedulingPlanningReview:
    """Current checks and separately labelled saved evidence for one exact draft.

    Attributes
    ----------
    current
        Fresh minimized checks from the same evaluator used by saved commands.
    state
        Whether the selected revision has a current, stale or unavailable report.
    evaluation_id
        Latest report for this exact revision, or none before evaluation.
    evaluated_at
        Retained report creation time, not the time of this fresh comparison.
    saved_complete
        Historical completeness flag, or none; never current source availability.
    saved_findings
        Complete bounded saved findings, with acknowledgement eligibility rechecked.
    """

    current: SchedulingPlanningPreview
    state: PlanningReviewState
    evaluation_id: UUID | None
    evaluated_at: datetime | None
    saved_complete: bool | None
    saved_findings: tuple[PlanningSavedFinding, ...]


def _saved_review(
    request: SchedulingReadRequest, current: _CurrentEvaluation
) -> SchedulingPlanningReview:
    scope = _ownership(request)
    report = (
        SchedulingEvaluation.objects.filter(**scope, revision_id=current.revision.id)
        .only("id", "occurred_at", "dependency_digest", "conflict_count", "is_complete")
        .order_by("-occurred_at", "-id")
        .first()
    )
    if report is None:
        return SchedulingPlanningReview(
            _preview_projection(current),
            PlanningReviewState.NOT_RECORDED,
            None,
            None,
            None,
            (),
        )
    rows = tuple(
        SchedulingConflict.objects.filter(**scope, evaluation_id=report.id)
        .annotate(
            has_ack=Exists(
                SchedulingWarningAcknowledgement.objects.filter(
                    **scope, conflict_id=OuterRef("id")
                )
            )
        )
        .order_by("id")
        .values_list(
            "id",
            "source_code",
            "code",
            "severity",
            "occurrence_id",
            "other_occurrence_id",
            "fingerprint",
            "has_ack",
        )[: MAX_CONFLICTS + 1]
    )
    if len(rows) > MAX_CONFLICTS:
        raise SchedulingLimitError
    if len(rows) != report.conflict_count:
        raise SchedulingUnavailableError
    findings = []
    for identifier, source, code, severity, occurrence, other, fingerprint, ack in rows:
        try:
            finding = SchedulingFinding(
                source,
                SchedulingConflictCode(code),
                SchedulingConflictSeverity(severity),
                occurrence,
                other,
            )
        except ValueError as error:
            raise SchedulingUnavailableError from error
        if _finding_fingerprint(report.dependency_digest, finding) != fingerprint:
            raise SchedulingUnavailableError
        findings.append((identifier, finding, bool(ack)))
    fresh = (
        current.complete
        and report.is_complete
        and current.digest == report.dependency_digest
        and {finding for _, finding, _ in findings} == set(current.findings)
    )
    state = (
        PlanningReviewState.CURRENT
        if fresh
        else PlanningReviewState.STALE
        if current.complete
        else PlanningReviewState.UNAVAILABLE
    )
    return SchedulingPlanningReview(
        _preview_projection(current),
        state,
        report.id,
        report.occurred_at,
        report.is_complete,
        tuple(
            PlanningSavedFinding(
                identifier,
                finding,
                acknowledged,
                fresh
                and finding.severity == SchedulingConflictSeverity.WARNING
                and not acknowledged,
            )
            for identifier, finding, acknowledged in findings
        ),
    )


def load_scheduling_candidate_review(
    request: SchedulingReadRequest,
    *,
    candidate_id: UUID,
    expected_version: int,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingPlanningReview:
    """Compare saved warning evidence against freshly authorized owner dependencies.

    Only the latest report for the exact current draft revision is selected.
    Previous candidate versions are not silently relabelled as current. Calendar
    content, dependency digests, fingerprints and acknowledgement rationale are
    withheld. Only minimized read audits are written; warning submission still
    independently authorizes and rechecks its complete fingerprint transactionally.

    Parameters
    ----------
    request : SchedulingReadRequest
        Trusted actor, organization, edition and trace attribution.
    candidate_id : UUID
        Exact scoped current draft candidate.
    expected_version : int
        Observed version, never automatically rebased.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent conflict-read policy or existing isolated-test admission.

    Returns
    -------
    SchedulingPlanningReview
        Fresh checks and a separately labelled complete saved-evidence projection.
    """
    require_identifier(candidate_id)
    require_version(expected_version)

    def load(_scope: AuthorizedSchedulingScope) -> SchedulingPlanningReview:
        current = _current_evaluation(
            _SchedulingSourceRead(
                request.actor_id,
                request.organization_id,
                request.edition_id,
                request.correlation_id,
            ),
            candidate_id=candidate_id,
            expected_version=expected_version,
        )
        return _saved_review(request, current)

    return _read(
        request,
        capability=VIEW_CONFLICTS,
        fields=PREVIEW_FIELDS,
        purpose="candidate_review",
        authorizer=authorizer,
        loader=load,
    )
