"""Independent decision discovery, pinned policy and purpose-scoped histories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F

from .models import (
    ProgrammeProposalCollaborator,
    ProgrammeReviewAssignment,
    ProgrammeReviewDecision,
    ProgrammeReviewEntry,
)
from .programme_authorization import DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import (
    DECIDE,
    require_sensitive_programme_review_authority,
)
from .programme_review_documents import decode_review_policy
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
    from datetime import datetime
    from uuid import UUID

    from .models import ProgrammeReviewCase
    from .programme_authorization import ApplicationsProgrammeAuthorizer
    from .programme_review_inputs import ProgrammeReviewPolicyInput

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER


@dataclass(frozen=True, slots=True)
class DecisionWork:
    """Carry pinned policy and independently protected exact-case context.

    Attributes
    ----------
    case : ReviewManagerCase
        Content-free call/seal labels and current case lifecycle.
    policy : ProgrammeReviewPolicyInput
        Complete immutable stages and templates under protected context authority.
    detail : ProgrammeReviewDetail
        Existing owner's classification-checked context projection.
    writable : bool
        Planning hint, never a substitute for canonical command admission.
    """

    case: ReviewManagerCase
    policy: ProgrammeReviewPolicyInput
    detail: ProgrammeReviewDetail
    writable: bool


@dataclass(frozen=True, slots=True)
class DecisionStage:
    """Explain one configured stage without recommending a decision.

    Attributes
    ----------
    code : str
        Immutable human-readable stage code.
    valid_scores : int
        Live verified assignments with a latest complete score.
    required_reviews : int
        Configured independent review count, never a score threshold.
    ready : bool
        Existing owner's current readiness rule, not a write grant.
    """

    code: str
    valid_scores: int
    required_reviews: int
    ready: bool


@dataclass(frozen=True, slots=True)
class DecisionEvidence:
    """Bind one complete evidence page and all-stage facts to one case version.

    Attributes
    ----------
    detail : ProgrammeReviewDetail
        Existing owner's separately authorized history projection.
    stages : tuple[DecisionStage, ...]
        Complete configured stage readiness, never a truncated subset.
    """

    detail: ProgrammeReviewDetail
    stages: tuple[DecisionStage, ...]


@dataclass(frozen=True, slots=True)
class DecisionMessage:
    """Retain outgoing text without any recipient directory or receipt state.

    Attributes
    ----------
    decision_id : UUID
        Exact immutable decision reference.
    version : int
        Case version at the original decision.
    decided_at : datetime
        Original evidence entry timestamp.
    outcome : str
        Closed final or wait-list outcome.
    message : str
        Immutable composed recipient-visible text, never private rationale.
    acknowledgement_required : bool
        Pinned receipt policy, not proof anyone has acknowledged.
    """

    decision_id: UUID
    version: int
    decided_at: datetime
    outcome: str
    message: str
    acknowledgement_required: bool


@dataclass(frozen=True, slots=True)
class DecisionMessages:
    """Return a bounded complete retained-message page at an exact case version.

    Attributes
    ----------
    version : int
        Current inspected case version for snapshot continuation.
    items : tuple[DecisionMessage, ...]
        Authorized outgoing decisions in ascending original-version order.
    next_version : int | None
        Exclusive last returned decision version when more remain.
    """

    version: int
    items: tuple[DecisionMessage, ...]
    next_version: int | None


def _purpose(request: ProgrammeReviewReadRequest, field: str) -> None:
    if (
        request.capability_code != DECIDE
        or request.requested_fields != frozenset({field})
        or request.department_id is None
    ):
        raise Denied


def _independent(
    request: ProgrammeReviewReadRequest, case_id: UUID
) -> ProgrammeReviewCase:
    case = _case(request, case_id)
    try:
        require_independent_actor(case, request.actor_id, decision=True)
    except ProgrammeReviewConflictError as error:
        raise Denied from error
    return case


@transaction.atomic
def list_programme_decision_cases(
    *,
    request: ProgrammeReviewReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewManagerPage:
    """Exclude contributors, all assignments and prior moderators before paging.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Independent exact-Department decider requesting only review_context.
    after_id : UUID | None, default=None
        Exclusive ascending case identifier.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ReviewManagerPage
        Audited labels without private titles, templates or hidden totals.
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
    scope = {
        "case__proposal__organization_id": request.organization_id,
        "case__proposal__edition_id": request.edition_id,
    }
    assignments = ProgrammeReviewAssignment.objects.filter(
        **scope,
        account_id=request.actor_id,
    ).values("case_id")
    moderated = ProgrammeReviewEntry.objects.filter(
        **scope,
        actor_id=request.actor_id,
        action="moderated",
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
        .exclude(id__in=moderated)
    )
    if after_id is not None:
        query = query.filter(id__gt=after_id)
    rows = tuple(query.order_by("id")[: limit + 1])
    result = ReviewManagerPage(
        tuple(_summary(row) for row in rows[:limit]),
        rows[limit - 1].id if len(rows) > limit else None,
    )
    _audit(request, "decision_cases", None, authorizer)
    return result


@transaction.atomic
def get_programme_decision_work(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> DecisionWork:
    """Read immutable decision templates through the existing protected context.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Independent exact-Department decider requesting only review_context.
    case_id : UUID
        Exact current or retained case selected from authorized discovery.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    DecisionWork
        Audited pinned templates/context after sensitive and independence checks.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If the protected context and case version cannot be read consistently.
    """
    require_programme_uuid(case_id, field="case_id")
    _purpose(request, "review_context")
    scope = _locked_scope(request, authorizer)
    detail = get_programme_review_detail(
        request=request, case_id=case_id, authorizer=authorizer
    )
    case = _independent(request, case_id)
    if case.version != detail.version:
        raise ProgrammeReviewUnavailableError
    result = DecisionWork(
        _summary(case),
        decode_review_policy(
            {"stages": case.policy.stages, "templates": case.policy.templates}
        ),
        detail,
        scope.accepts_private_planning_writes,
    )
    _audit(request, "decision_work", case.id, authorizer)
    return result


@transaction.atomic
def get_programme_decision_evidence(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    after_version: int = 0,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> DecisionEvidence:
    """Read complete all-stage readiness with separately protected evidence.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Independent exact-Department decider requesting only review_evidence.
    case_id : UUID
        Exact scoped case.
    after_version : int, default=0
        Exclusive evidence cursor under the owner's fixed complete page bound.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    DecisionEvidence
        Audited history and existing readiness facts for every configured stage.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If current evidence exceeds its bound or cannot share one case version.
    """
    _purpose(request, "review_evidence")
    detail = get_programme_review_detail(
        request=request,
        case_id=case_id,
        after_version=after_version,
        authorizer=authorizer,
    )
    case = _independent(request, case_id)
    _summary(case)
    stages = []
    for index, stage in enumerate(case.policy.stages):
        count = len(latest_stage_scores(case, index))
        if count > MAX_STAGE_REVIEWERS:
            raise ProgrammeReviewUnavailableError
        stages.append(
            DecisionStage(
                stage["code"],
                count,
                stage["required_reviews"],
                stage_is_ready(case, index),
            )
        )
    if case.version != detail.version:
        raise ProgrammeReviewUnavailableError
    result = DecisionEvidence(detail, tuple(stages))
    _audit(request, "decision_evidence", case.id, authorizer)
    return result


@transaction.atomic
def list_programme_decision_messages(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    after_version: int = 0,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> DecisionMessages:
    """Read decider-only retained outgoing text without recipient receipt states.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Independent exact-Department decider requesting only review_evidence.
    case_id : UUID
        Exact case whose immutable source owns each returned message.
    after_version : int, default=0
        Exclusive original decision-version cursor.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    DecisionMessages
        Audited outgoing message history, never recipients or their responses.

    Raises
    ------
    Denied
        If the history cursor is outside the closed integer boundary.
    """
    require_programme_uuid(case_id, field="case_id")
    _limit(limit)
    if type(after_version) is not int or not 0 <= after_version <= 2**63 - 1:
        raise Denied
    _purpose(request, "review_evidence")
    scope = _locked_scope(request, authorizer)
    case = _independent(request, case_id)
    require_sensitive_programme_review_authority(
        scope=scope,
        case=case,
        requested_fields=request.requested_fields,
        authorizer=authorizer,
    )
    rows = tuple(
        ProgrammeReviewDecision.objects.select_related("entry")
        .filter(
            entry__case=case,
            revision_id=case.revision_id,
            revision__organization_id=request.organization_id,
            revision__edition_id=request.edition_id,
            entry__version__gt=after_version,
            entry__version__lte=case.version,
        )
        .order_by("entry__version")[: limit + 1]
    )
    result = DecisionMessages(
        case.version,
        tuple(
            DecisionMessage(
                row.id,
                row.entry.version,
                row.entry.created_at,
                row.outcome,
                row.message,
                row.acknowledgement_required,
            )
            for row in rows[:limit]
        ),
        rows[limit - 1].entry.version if len(rows) > limit else None,
    )
    _audit(request, "decision_messages", case.id, authorizer)
    return result
