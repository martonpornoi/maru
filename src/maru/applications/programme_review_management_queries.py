"""Audited manager-only case labels and complete named assignment rosters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F

from maru.identity.queries import active_verified_person_account_display_labels

from .models import ProgrammeReviewAssignment
from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
)
from .programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from .programme_inputs import require_programme_uuid
from .programme_review_authorization import MANAGE_REVIEW
from .programme_review_documents import decode_review_stage
from .programme_review_inputs import MAX_REVIEW_STAGES
from .programme_review_queries import (
    ProgrammeReviewReadRequest,
    _audit,
    _cases,
    _limit,
    _locked_scope,
)
from .programme_review_rules import (
    ProgrammeReviewUnavailableError,
    load_review_case,
    revision_is_current,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from .models import ProgrammeReviewCase
    from .programme_authorization import ApplicationsProgrammeAuthorizer
    from .programme_review_authorization import AuthorizedProgrammeReviewScope

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_ASSIGNMENTS = 128


@dataclass(frozen=True, slots=True)
class ReviewManagerCase:
    """Describe one authorized case without proposal answers or private evidence.

    Attributes
    ----------
    case_id : UUID
        Exact review aggregate identifier.
    call_id : UUID
        Owning call reference, not call-setup authority.
    call_name : str
        Configured call label, not an answer-derived proposal title.
    revision_id : UUID
        Exact pinned source seal.
    sequence : int
        Proposal-local immutable seal sequence.
    sealed_at : datetime
        Source sealing timestamp.
    policy_version : int
        Immutable call-policy version pinned to this case.
    version : int
        Current optimistic case version.
    stage : int
        Current zero-based policy stage.
    stage_code : str
        Explicit human-readable stage code.
    state : str
        Current review lifecycle state.
    current_revision : bool
        Whether the pinned source remains the current submitted seal.
    """

    case_id: UUID
    call_id: UUID
    call_name: str
    revision_id: UUID
    sequence: int
    sealed_at: datetime
    policy_version: int
    version: int
    stage: int
    stage_code: str
    state: str
    current_revision: bool


@dataclass(frozen=True, slots=True)
class ReviewManagerPage:
    """Carry one complete bounded case page.

    Attributes
    ----------
    items : tuple[ReviewManagerCase, ...]
        Authorized labels in ascending case identifier order.
    next_cursor : UUID | None
        Exclusive last case identifier when more exist.
    """

    items: tuple[ReviewManagerCase, ...]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class ReviewManagerAssignment:
    """Label one already-scoped retained assignment without contact information.

    Attributes
    ----------
    assignment_id : UUID
        Stable owner assignment reference.
    account_id : UUID
        Exact already-authorized relationship person identifier.
    display_label : str
        Current active verified person's label, otherwise a neutral fallback.
    stage : int
        Assignment's original zero-based stage, including historical stages.
    stage_code : str
        Label from the immutable case policy.
    state : str
        Pending, active, removed or recused assignment state.
    """

    assignment_id: UUID
    account_id: UUID
    display_label: str
    stage: int
    stage_code: str
    state: str


@dataclass(frozen=True, slots=True)
class ReviewManagerContext:
    """Return one scoped case and its complete bounded assignment roster.

    Attributes
    ----------
    case : ReviewManagerCase
        Content-free case and source context.
    assignments : tuple[ReviewManagerAssignment, ...]
        All retained stages and relationship states, never silently truncated.
    writable : bool
        Current planning state, not a fresh mutation guarantee.
    """

    case: ReviewManagerCase
    assignments: tuple[ReviewManagerAssignment, ...]
    writable: bool


def _scope(
    request: ProgrammeReviewReadRequest, authorizer: ApplicationsProgrammeAuthorizer
) -> AuthorizedProgrammeReviewScope:
    if (
        request.capability_code != MANAGE_REVIEW
        or request.requested_fields != frozenset({"review_context"})
        or request.department_id is None
    ):
        raise Denied
    return _locked_scope(request, authorizer)


def _case(request: ProgrammeReviewReadRequest, case_id: UUID) -> ProgrammeReviewCase:
    try:
        case = load_review_case(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            case_id=case_id,
        )
    except ProgrammeReviewUnavailableError as error:
        raise Denied from error
    if case.proposal.call.owner_department_id != request.department_id:
        raise Denied
    return case


def _stage_code(case: ProgrammeReviewCase, stage: int) -> str:
    try:
        if (
            not isinstance(case.policy.stages, list)
            or not 1 <= len(case.policy.stages) <= MAX_REVIEW_STAGES
            or type(stage) is not int
            or not 0 <= stage < len(case.policy.stages)
        ):
            raise ProgrammeReviewUnavailableError
        return decode_review_stage(case.policy.stages[stage]).code
    except (ValidationError, TypeError, KeyError, IndexError) as error:
        raise ProgrammeReviewUnavailableError from error


def _summary(case: ProgrammeReviewCase) -> ReviewManagerCase:
    return ReviewManagerCase(
        case.id,
        case.proposal.call_id,
        case.proposal.call.definition.name,
        case.revision_id,
        case.revision.sequence,
        case.revision.sealed_at,
        case.policy.version,
        case.version,
        case.stage,
        _stage_code(case, case.stage),
        case.state,
        revision_is_current(case),
    )


@transaction.atomic
def list_programme_review_management_cases(
    *,
    request: ProgrammeReviewReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewManagerPage:
    """Read exact-Department case labels with complete exclusive-cursor pagination.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact manager purpose requesting only review_context.
    after_id : UUID | None, default=None
        Exclusive ascending case cursor.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ReviewManagerPage
        Audited case labels, not private answers or review evidence.
    """
    _limit(limit)
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    _scope(request, authorizer)
    query = (
        _cases(request)
        .select_related("proposal__call__definition", "revision")
        .filter(
            policy__call__organization_id=request.organization_id,
            policy__call__edition_id=request.edition_id,
            policy__call_id=F("proposal__call_id"),
            revision__proposal_id=F("proposal_id"),
        )
    )
    if after_id is not None:
        query = query.filter(id__gt=after_id)
    rows = tuple(query.order_by("id")[: limit + 1])
    result = ReviewManagerPage(
        tuple(_summary(row) for row in rows[:limit]),
        rows[limit - 1].id if len(rows) > limit else None,
    )
    _audit(request, "management_cases", None, authorizer)
    return result


@transaction.atomic
def get_programme_review_management(
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewManagerContext:
    """Read the complete retained manager roster with current minimized labels.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact Department manager requesting only review_context.
    case_id : UUID
        Exact case selected from independently authorized discovery.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test admission seam.

    Returns
    -------
    ReviewManagerContext
        Current and historical assignment states, never answer or score content.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If the roster cannot be projected completely within the owner bound.
    """
    require_programme_uuid(case_id, field="case_id")
    scope = _scope(request, authorizer)
    case = _case(request, case_id)
    rows = tuple(
        ProgrammeReviewAssignment.objects.filter(case_id=case.id).order_by(
            "stage", "id"
        )[: _MAX_ASSIGNMENTS + 1]
    )
    if len(rows) > _MAX_ASSIGNMENTS:
        raise ProgrammeReviewUnavailableError
    labels = active_verified_person_account_display_labels(
        {row.account_id for row in rows}
    )
    result = ReviewManagerContext(
        _summary(case),
        tuple(
            ReviewManagerAssignment(
                row.id,
                row.account_id,
                labels.get(row.account_id, "Unavailable person"),
                row.stage,
                _stage_code(case, row.stage),
                row.state,
            )
            for row in rows
        ),
        scope.accepts_private_planning_writes,
    )
    _audit(request, "management_case", case_id, authorizer)
    return result
