"""Audited Department-only configuration discovery without proposal content."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from .models import ApplicationQuestion, ProgrammeReviewPolicy
from .programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
)
from .programme_inputs import require_programme_uuid
from .programme_queries import _call_query
from .programme_review_authorization import MANAGE_REVIEW
from .programme_review_documents import decode_review_policy
from .programme_review_queries import (
    ProgrammeReviewReadRequest,
    _audit,
    _limit,
    _locked_scope,
)
from .programme_review_rules import ProgrammeReviewUnavailableError

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from django.db.models import QuerySet

    from .models import ProgrammeCall
    from .programme_authorization import ApplicationsProgrammeAuthorizer
    from .programme_review_authorization import AuthorizedProgrammeReviewScope
    from .programme_review_inputs import ProgrammeReviewPolicyInput

_DEFAULT_AUTHORIZER = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_QUESTIONS = 500


@dataclass(frozen=True, slots=True)
class ReviewSetupCall:
    """Identify a scoped call without submissions, people or private answers.

    Attributes
    ----------
    call_id : UUID
        Exact authorized call reference.
    name : str
        Owner-supplied call name.
    code : str
        Stable call code.
    status : str
        Draft, active or retired configuration state.
    definition_version : int
        Immutable question definition version.
    """

    call_id: UUID
    name: str
    code: str
    status: str
    definition_version: int


@dataclass(frozen=True, slots=True)
class ReviewSetupCallPage:
    """Carry one complete bounded call page.

    Attributes
    ----------
    items : tuple[ReviewSetupCall, ...]
        Authorized call labels in ascending identifier order.
    next_cursor : UUID | None
        Exclusive last identifier when more calls exist.
    """

    items: tuple[ReviewSetupCall, ...]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class ReviewSetupQuestion:
    """Describe a configuration choice, never a submitted response.

    Attributes
    ----------
    key : str
        Stable owner question key.
    label : str
        Human-readable question label.
    field_type : str
        Structured input kind, including identity-bearing kinds.
    classification : str
        Explicit information classification of the question.
    """

    key: str
    label: str
    field_type: str
    classification: str


@dataclass(frozen=True, slots=True)
class ReviewSetupContext:
    """Return complete call metadata and the current policy sequence proof.

    Attributes
    ----------
    call : ReviewSetupCall
        Independently scoped source call.
    questions : tuple[ReviewSetupQuestion, ...]
        Complete bounded configuration choices, with no source answers.
    policy_version : int
        Current append-only policy sequence, zero when absent.
    writable : bool
        Current edition planning status, not a mutation grant or future promise.
    """

    call: ReviewSetupCall
    questions: tuple[ReviewSetupQuestion, ...]
    policy_version: int
    writable: bool


@dataclass(frozen=True, slots=True)
class ReviewSetupPolicy:
    """Expose the deliberately configured immutable policy and its rationale.

    Attributes
    ----------
    policy_id : UUID
        Exact immutable policy reference.
    call_id : UUID
        Independently scoped owning call.
    version : int
        Immutable call-policy sequence.
    created_at : datetime
        Creation timestamp.
    reason : str
        Privileged policy-creation rationale; never case evidence.
    policy : ProgrammeReviewPolicyInput
        Validated complete stage and outcome configuration.
    """

    policy_id: UUID
    call_id: UUID
    version: int
    created_at: datetime
    reason: str
    policy: ProgrammeReviewPolicyInput


def _scope(
    request: ProgrammeReviewReadRequest, authorizer: ApplicationsProgrammeAuthorizer
) -> AuthorizedProgrammeReviewScope:
    if (
        request.capability_code != MANAGE_REVIEW
        or request.requested_fields != frozenset({"review_setup"})
        or request.department_id is None
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    return _locked_scope(request, authorizer)


def _calls(request: ProgrammeReviewReadRequest) -> QuerySet[ProgrammeCall]:
    if request.department_id is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    return _call_query(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        department_id=request.department_id,
    )


def _summary(call: ProgrammeCall) -> ReviewSetupCall:
    return ReviewSetupCall(
        call.id,
        call.definition.name,
        call.definition.code,
        call.definition.status,
        call.definition.version,
    )


@transaction.atomic
def list_programme_review_setup_calls(
    *,
    request: ProgrammeReviewReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewSetupCallPage:
    """List exact-Department calls using review-setup authority, not call management.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact manager purpose requesting only review_setup.
    after_id : UUID | None, default=None
        Exclusive ascending call cursor.
    limit : int, default=50
        Page size from one through 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ReviewSetupCallPage
        Bounded labels audited before release, without private proposal data.
    """
    _limit(limit)
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    _scope(request, authorizer)
    query = _calls(request)
    if after_id is not None:
        query = query.filter(id__gt=after_id)
    rows = tuple(query.order_by("id")[: limit + 1])
    result = ReviewSetupCallPage(
        tuple(_summary(row) for row in rows[:limit]),
        rows[limit - 1].id if len(rows) > limit else None,
    )
    _audit(request, "setup_calls", None, authorizer)
    return result


@transaction.atomic
def get_programme_review_setup(
    *,
    request: ProgrammeReviewReadRequest,
    call_id: UUID,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewSetupContext:
    """Read complete bounded question configuration and current policy sequence.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact manager purpose requesting only review_setup.
    call_id : UUID
        Exact owning call reference.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ReviewSetupContext
        Complete configuration; no current or retained submission content.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the exact call is absent from the authorized Department scope.
    ProgrammeReviewUnavailableError
        If the call configuration exceeds the supported complete projection.
    """
    require_programme_uuid(call_id, field="call_id")
    scope = _scope(request, authorizer)
    call = _calls(request).filter(id=call_id).first()
    if call is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    rows = tuple(
        ApplicationQuestion.objects.filter(
            definition_id=call.definition_id,
            definition__organization_id=request.organization_id,
            definition__edition_id=request.edition_id,
        ).order_by("section__position", "position", "id")[:501]
    )
    if len(rows) > _MAX_QUESTIONS:
        raise ProgrammeReviewUnavailableError
    latest = (
        ProgrammeReviewPolicy.objects.filter(call_id=call.id).aggregate(
            value=Max("version")
        )["value"]
        or 0
    )
    result = ReviewSetupContext(
        _summary(call),
        tuple(
            ReviewSetupQuestion(row.key, row.label, row.field_type, row.classification)
            for row in rows
        ),
        latest,
        scope.accepts_private_planning_writes,
    )
    _audit(request, "setup_configuration", call_id, authorizer)
    return result


@transaction.atomic
def get_programme_review_setup_policy(
    *,
    request: ProgrammeReviewReadRequest,
    call_id: UUID,
    version: int,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ReviewSetupPolicy:
    """Read one scoped immutable policy version with complete normalized content.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact manager purpose requesting only review_setup.
    call_id : UUID
        Exact scoped owning call.
    version : int
        Explicit positive policy sequence; neighboring history uses this sequence.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ReviewSetupPolicy
        Immutable policy and creation reason, never case discussion or scores.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If the version is invalid, absent or foreign to this exact call scope.
    ProgrammeReviewUnavailableError
        If stored policy cannot be projected through the closed owner contract.
    """
    require_programme_uuid(call_id, field="call_id")
    if type(version) is not int or not 1 <= version < 2**63:
        raise ApplicationsProgrammeAuthorizationDeniedError
    _scope(request, authorizer)
    row = ProgrammeReviewPolicy.objects.filter(
        call_id__in=_calls(request).filter(id=call_id).values("id"),
        version=version,
    ).first()
    if row is None:
        raise ApplicationsProgrammeAuthorizationDeniedError
    try:
        policy = decode_review_policy(
            {"stages": row.stages, "templates": row.templates}
        )
    except ValidationError as error:
        raise ProgrammeReviewUnavailableError from error
    result = ReviewSetupPolicy(
        row.id, call_id, row.version, row.created_at, row.reason, policy
    )
    _audit(request, "setup_policy", row.id, authorizer)
    return result
