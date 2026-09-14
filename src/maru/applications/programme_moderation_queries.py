"""Independent moderator discovery and exact-version protected stage evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F

from .models import ProgrammeProposalCollaborator, ProgrammeReviewAssignment
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import MODERATE
from .programme_review_documents import decode_review_stage
from .programme_review_inputs import MAX_STAGE_REVIEWERS
from .programme_review_management_queries import (
    ReviewManagerCase,
    ReviewManagerPage,
    _case,
    _summary,
)
from .programme_review_queries import (
    ProgrammeReviewDetail,
    ProgrammeReviewReadRequest,
    _audit,
    _cases,
    _limit,
    _locked_scope,
    get_programme_review_detail,
)
from .programme_review_rules import (
    ProgrammeReviewConflictError,
    ProgrammeReviewUnavailableError,
    latest_stage_scores,
    require_independent_actor,
    stage_is_ready,
)

if TYPE_CHECKING:
    from uuid import UUID

    from .models import ProgrammeReviewCase
    from .programme_authorization import ApplicationsProgrammeAuthorizer
    from .programme_review_inputs import ProgrammeReviewStageInput

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class ModerationCase:
    """Carry independently authorized metadata without answers or review evidence.

    Attributes
    ----------
    case : ReviewManagerCase
        Content-free scoped call, seal and current lifecycle labels.
    stages : tuple[ProgrammeReviewStageInput, ...]
        Complete immutable configured stage labels and rubrics.
    writable : bool
        Planning hint; canonical writes revalidate all authority independently.
    """

    case: ReviewManagerCase
    stages: tuple[ProgrammeReviewStageInput, ...]
    writable: bool


@dataclass(frozen=True, slots=True)
class ModerationEvidence:
    """Bind a complete protected history page to current canonical stage facts.

    Attributes
    ----------
    detail : ProgrammeReviewDetail
        Audited exact-version evidence page with complete continuation cursor.
    valid_scores : int
        Current stage's live verified assignments with a latest complete score.
    required_reviews : int
        Explicit current-stage quorum, never a score threshold.
    ready : bool
        Existing owner's readiness rule, not a new mutation grant.
    """

    detail: ProgrammeReviewDetail
    valid_scores: int
    required_reviews: int
    ready: bool


def _purpose(request: ProgrammeReviewReadRequest, field: str) -> None:
    if (
        request.capability_code != MODERATE
        or request.requested_fields != frozenset({field})
        or request.department_id is None
    ):
        raise Denied


def _independent(
    request: ProgrammeReviewReadRequest, case_id: UUID
) -> ProgrammeReviewCase:
    case = _case(request, case_id)
    try:
        require_independent_actor(case, request.actor_id)
    except ProgrammeReviewConflictError as error:
        raise Denied from error
    return case


@transaction.atomic
def get_programme_moderation_case(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ModerationCase:
    """Read retained case metadata under exact independent moderator authority.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact Department moderator requesting only review_context.
    case_id : UUID
        Exact scoped case, including retained final and source-stale states.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ModerationCase
        Audited call/seal/policy labels, not private content or actor names.
    """
    require_programme_uuid(case_id, field="case_id")
    _purpose(request, "review_context")
    scope = _locked_scope(request, authorizer)
    case = _independent(request, case_id)
    summary = _summary(case)
    result = ModerationCase(
        summary,
        tuple(decode_review_stage(row) for row in case.policy.stages),
        scope.accepts_private_planning_writes,
    )
    _audit(request, "moderation_case", case.id, authorizer)
    return result


@transaction.atomic
def list_programme_moderation_cases(
    *,
    request: ProgrammeReviewReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewManagerPage:
    """Exclude all contributor and assignment conflicts before bounded pagination.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact Department moderator requesting only review_context.
    after_id : UUID | None, default=None
        Exclusive ascending case identifier.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ReviewManagerPage
        Audited content-free discovery without private titles or hidden totals.
    """
    _limit(limit)
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    _purpose(request, "review_context")
    _locked_scope(request, authorizer)
    collaborators = ProgrammeProposalCollaborator.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        account_id=request.actor_id,
    ).values("proposal_id")
    assignments = ProgrammeReviewAssignment.objects.filter(
        case__proposal__organization_id=request.organization_id,
        case__proposal__edition_id=request.edition_id,
        account_id=request.actor_id,
    ).values("case_id")
    query = (
        _cases(request)
        .select_related("proposal__call__definition", "revision")
        .filter(
            policy__call__organization_id=request.organization_id,
            policy__call__edition_id=request.edition_id,
            policy__call_id=F("proposal__call_id"),
            revision__proposal_id=F("proposal_id"),
        )
        .exclude(proposal__submission__account_id=request.actor_id)
        .exclude(proposal_id__in=collaborators)
        .exclude(id__in=assignments)
    )
    if after_id is not None:
        query = query.filter(id__gt=after_id)
    rows = tuple(query.order_by("id")[: limit + 1])
    result = ReviewManagerPage(
        tuple(_summary(row) for row in rows[:limit]),
        rows[limit - 1].id if len(rows) > limit else None,
    )
    _audit(request, "moderation_cases", None, authorizer)
    return result


@transaction.atomic
def get_programme_moderation_evidence(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    after_version: int = 0,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ModerationEvidence:
    """Read protected history and current-stage facts under one owning scope lock.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact independent moderator requesting only review_evidence.
    case_id : UUID
        Exact scoped review case.
    after_version : int, default=0
        Exclusive case-version history cursor with the owner's fixed page bound.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ModerationEvidence
        Audited sensitive-role projection and canonical readiness explanation.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If stage evidence cannot be projected completely at one case version.
    """
    _purpose(request, "review_evidence")
    detail = get_programme_review_detail(
        request=request,
        case_id=case_id,
        after_version=after_version,
        authorizer=authorizer,
    )
    case = _independent(request, case_id)
    _summary(case)  # Validate the immutable stage bound before indexing.
    count = len(latest_stage_scores(case, case.stage))
    if case.version != detail.version or count > MAX_STAGE_REVIEWERS:
        raise ProgrammeReviewUnavailableError
    result = ModerationEvidence(
        detail,
        count,
        case.policy.stages[case.stage]["required_reviews"],
        stage_is_ready(case, case.stage),
    )
    _audit(request, "moderation_evidence", case.id, authorizer)
    return result
