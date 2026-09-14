"""Audited own-assignment metadata, separate from protected review content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F

from .models import ProgrammeReviewAssignment, ProgrammeReviewEntry
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import REVIEW
from .programme_review_documents import decode_review_stage
from .programme_review_management_queries import (
    ReviewManagerCase,
    _case,
    _stage_code,
    _summary,
)
from .programme_review_queries import (
    ProgrammeReviewReadRequest,
    _audit,
    _cases,
    _limit,
    _locked_scope,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .models import ProgrammeReviewCase
    from .programme_authorization import ApplicationsProgrammeAuthorizer
    from .programme_review_authorization import AuthorizedProgrammeReviewScope
    from .programme_review_inputs import ProgrammeReviewStageInput

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ReviewerWork:
    """Describe one own assignment without submission content or peer evidence.

    Attributes
    ----------
    case : ReviewManagerCase
        Shared content-free call/seal/policy labels, not manager authority.
    assignment_id : UUID
        Exact retained own assignment.
    state : str
        Pending, active, removed or recused relationship state.
    stage : int
        Immutable original assignment stage, not necessarily current case stage.
    rubric : ProgrammeReviewStageInput
        Original immutable stage configuration, never answer values.
    writable : bool
        Current planning hint; canonical writes revalidate independently.
    has_scored : bool
        Whether an own score exists for discussion eligibility, never its value.
    """

    case: ReviewManagerCase
    assignment_id: UUID
    state: str
    stage: int
    rubric: ProgrammeReviewStageInput
    writable: bool
    has_scored: bool


@dataclass(frozen=True, slots=True)
class ReviewerWorkPage:
    """Return a complete bounded own-assignment discovery page.

    Attributes
    ----------
    items : tuple[ReviewerWork, ...]
        Own pending/active assignments ordered by assignment identifier.
    next_cursor : UUID | None
        Exclusive last assignment identifier when more are available.
    """

    items: tuple[ReviewerWork, ...]
    next_cursor: UUID | None


def _scope(
    request: ProgrammeReviewReadRequest, authorizer: ApplicationsProgrammeAuthorizer
) -> AuthorizedProgrammeReviewScope:
    if (
        request.capability_code != REVIEW
        or request.requested_fields != frozenset({"review_context"})
        or request.department_id is None
    ):
        raise Denied
    return _locked_scope(request, authorizer)


def _work(
    case: ProgrammeReviewCase,
    row: ProgrammeReviewAssignment,
    scope: AuthorizedProgrammeReviewScope,
    *,
    has_scored: bool,
) -> ReviewerWork:
    # Validate the historical index before decoding; never substitute case.stage.
    _stage_code(case, row.stage)
    return ReviewerWork(
        _summary(case),
        row.id,
        row.state,
        row.stage,
        decode_review_stage(case.policy.stages[row.stage]),
        scope.accepts_private_planning_writes,
        has_scored,
    )


@transaction.atomic
def get_programme_reviewer_work(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    assignment_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewerWork:
    """Read exact retained own metadata without requiring current content access.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Independent exact Department review_context purpose.
    case_id : UUID
        Exact scoped review case, including retained lifecycle states.
    assignment_id : UUID
        Exact own retained assignment, including removed or recused states.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ReviewerWork
        Audited original-stage metadata for conflict tasks and receipt recovery.

    Raises
    ------
    Denied
        If the requested assignment is absent or belongs to another person/case.
    """
    require_programme_uuid(case_id, field="case_id")
    require_programme_uuid(assignment_id, field="assignment_id")
    scope = _scope(request, authorizer)
    case = _case(request, case_id)
    row = ProgrammeReviewAssignment.objects.filter(
        case_id=case.id, id=assignment_id, account_id=request.actor_id
    ).first()
    if row is None:
        raise Denied
    result = _work(
        case,
        row,
        scope,
        has_scored=ProgrammeReviewEntry.objects.filter(
            case_id=case.id, assignment_id=row.id, action="scored"
        ).exists(),
    )
    _audit(request, "own_assignment", case.id, authorizer)
    return result


@transaction.atomic
def list_programme_reviewer_work(
    *,
    request: ProgrammeReviewReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewerWorkPage:
    """Discover only own pending/active assignments before complete pagination.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact independently authorized review_context purpose.
    after_id : UUID | None, default=None
        Exclusive ascending assignment cursor.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ReviewerWorkPage
        Audited content-free task labels, not peer or proposal discovery.
    """
    _limit(limit)
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    scope = _scope(request, authorizer)
    query = ProgrammeReviewAssignment.objects.filter(
        case_id__in=_cases(request)
        .filter(
            policy__call__organization_id=request.organization_id,
            policy__call__edition_id=request.edition_id,
            policy__call_id=F("proposal__call_id"),
            revision__proposal_id=F("proposal_id"),
        )
        .values("id"),
        account_id=request.actor_id,
        state__in=("pending", "active"),
    ).select_related(
        "case__proposal__call__definition", "case__revision", "case__policy"
    )
    if after_id is not None:
        query = query.filter(id__gt=after_id)
    rows = tuple(query.order_by("id")[: limit + 1])
    scored = set(
        ProgrammeReviewEntry.objects.filter(
            assignment_id__in=[row.id for row in rows[:limit]],
            action="scored",
            case_id__in=[row.case_id for row in rows[:limit]],
        ).values_list("assignment_id", flat=True)
    )
    result = ReviewerWorkPage(
        tuple(
            _work(row.case, row, scope, has_scored=row.id in scored)
            for row in rows[:limit]
        ),
        rows[limit - 1].id if len(rows) > limit else None,
    )
    _audit(request, "own_assignments", None, authorizer)
    return result
