"""Audited, bounded role projections for exact Programme review evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from maru.applications.models import (
    ProgrammeDecisionAcknowledgement,
    ProgrammeProposalRevisionAnswer,
    ProgrammeProposalRevisionContributor,
    ProgrammeReviewAction,
    ProgrammeReviewAssignment,
    ProgrammeReviewAssignmentState,
    ProgrammeReviewCase,
    ProgrammeReviewDecision,
    ProgrammeReviewEntry,
)
from maru.applications.programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
)
from maru.applications.programme_inputs import require_programme_uuid
from maru.applications.programme_queries import _audit_inputs
from maru.applications.programme_review_authorization import (
    DECIDE,
    MANAGE_REVIEW,
    MODERATE,
    REVIEW,
    REVIEW_STAFF_CAPABILITIES,
    SENSITIVE_REVIEW,
    VIEW_DECISION_SELF,
    AuthorizedProgrammeReviewScope,
    authorize_programme_review_scope,
    require_sensitive_programme_review_authority,
)
from maru.applications.programme_review_rules import (
    ProgrammeReviewConflictError,
    ProgrammeReviewUnavailableError,
    accepted_review_is_effective,
    is_proposal_contributor,
    load_review_case,
    require_independent_actor,
    revision_is_current,
)
from maru.applications.programme_write_scope import lock_programme_edition_write_scope
from maru.audit.services import AuditRecord, append_audit

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from django.db.models import QuerySet

    from maru.applications.programme_authorization import (
        ApplicationsProgrammeAuthorizer,
    )

_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_MAX_PAGE: Final = 100
_MAX_ANSWERS: Final = 500
_MAX_ASSIGNMENTS: Final = 128
_ANONYMOUS_OMISSIONS: Final = frozenset(
    {
        "email",
        "phone",
        "address",
        "person_reference",
        "domain_reference",
        "safe_file",
        "url",
    }
)


@dataclass(frozen=True, slots=True)
class ProgrammeReviewReadRequest:
    """Name exact actor, tenant, purpose, nonempty fields, and audit correlation.

    Department is required for staff and None for self. This value carries no
    authority: each read proves current policy and object relationship again.

    Attributes
    ----------
    actor_id : UUID
        Exact active, verified person requesting the projection.
    organization_id : UUID
        Owning organization boundary.
    edition_id : UUID
        Exact event edition boundary.
    department_id : UUID | None
        Current owner Department for staff, absent for recipient self access.
    capability_code : str
        Dedicated purpose admitted by the selected query.
    requested_fields : frozenset[str]
        Nonempty explicit field ceiling, independently authorized on every read.
    correlation_id : UUID
        Correlation for the mandatory minimized read audit.
    source_channel : str
        Bounded audit channel without source content or secrets.
    """

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID
    department_id: UUID | None
    capability_code: str
    requested_fields: frozenset[str]
    correlation_id: UUID
    source_channel: str


@dataclass(frozen=True, slots=True)
class ProgrammeReviewCaseSummary:
    """Minimize queue context without answers, identities, or private evidence.

    Attributes
    ----------
    case_id : UUID
        Opaque authorized review case identifier.
    version : int
        Current optimistic case version.
    stage : int
        Zero-based current policy stage.
    state : str
        Closed current review lifecycle code.
    current_revision : bool
        Whether the exact reviewed seal remains the submitted candidate.
    own_assignment_id : UUID | None
        Caller's pending or active assignment in the current stage, if any.
    own_assignment_state : str | None
        State of that current-stage assignment, without peer information.
    own_assignments : tuple[tuple[UUID, int, str], ...]
        Caller's pending/active assignment identifiers, stages, and states,
        including earlier stages so late recusal remains actionable.
    """

    case_id: UUID
    version: int
    stage: int
    state: str
    current_revision: bool
    own_assignment_id: UUID | None
    own_assignment_state: str | None
    own_assignments: tuple[tuple[UUID, int, str], ...]


@dataclass(frozen=True, slots=True)
class ProgrammeReviewCasePage:
    """Return a complete bounded queue page with an exclusive UUID cursor.

    Attributes
    ----------
    items : tuple[ProgrammeReviewCaseSummary, ...]
        Authorized summaries in ascending case identifier order.
    next_cursor : UUID | None
        Last returned case identifier when another page exists, otherwise None.
    """

    items: tuple[ProgrammeReviewCaseSummary, ...]
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class ProgrammeReviewDetail:
    """Return immutable, field-filtered sealed content and a history page.

    JSON strings contain only the documented projection schema, never raw model
    dictionaries. Nested source values remain immutable at this boundary.
    Evidence uses an exclusive case-version cursor; omitted fields are None.

    Attributes
    ----------
    case_id : UUID
        Exact authorized case identifier.
    version : int
        Current optimistic case version at the locked read boundary.
    context_json : str | None
        Explicit policy and role-specific context projection, if requested.
    answers_json : str | None
        Exact-seal, stage-allowlisted answer projection, if authorized/requested.
    evidence_json : str | None
        Bounded role-filtered evidence page, if authorized/requested.
    next_evidence_version : int | None
        Exclusive last evidence version when another authorized page exists.
    """

    case_id: UUID
    version: int
    context_json: str | None
    answers_json: str | None
    evidence_json: str | None
    next_evidence_version: int | None


@dataclass(frozen=True, slots=True)
class ProgrammeDecisionMessage:
    """Project an exact addressed decision without another recipient's state.

    Attributes
    ----------
    decision_id : UUID
        Immutable addressed decision identifier.
    case_id : UUID
        Exact case retaining the decision.
    case_version : int
        Current optimistic case version for a subsequent self acknowledgement.
    decision_version : int
        Immutable case version at which this decision was made.
    decided_at : datetime
        Aware timestamp of the immutable decision entry.
    outcome : str | None
        Closed decision outcome only when message access was requested.
    message : str | None
        Pinned template plus deliberate recipient text, without private rationale.
    acknowledgement_required : bool | None
        Pinned template policy only when own-acknowledgement access was requested.
    own_acknowledged : bool | None
        Caller's acknowledgement state, or None when that field was not requested.
    own_acknowledged_at : datetime | None
        Caller's retained acknowledgement time, absent when unacknowledged or
        when own-acknowledgement access was not requested.
    """

    decision_id: UUID
    case_id: UUID
    case_version: int
    decision_version: int
    decided_at: datetime
    outcome: str | None
    message: str | None
    acknowledgement_required: bool | None
    own_acknowledged: bool | None
    own_acknowledged_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProgrammeDecisionPage:
    """Return chronological recipient history with an exclusive opaque cursor.

    Attributes
    ----------
    items : tuple[ProgrammeDecisionMessage, ...]
        Addressed messages ordered by decision time and identifier.
    next_cursor : UUID | None
        Last returned decision identifier when another addressed page exists.
    """

    items: tuple[ProgrammeDecisionMessage, ...]
    next_cursor: UUID | None


def _limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= _MAX_PAGE:
        raise ApplicationsProgrammeAuthorizationDeniedError


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _scope(
    request: ProgrammeReviewReadRequest, authorizer: ApplicationsProgrammeAuthorizer
) -> AuthorizedProgrammeReviewScope:
    for field, identifier in (
        ("actor_id", request.actor_id),
        ("organization_id", request.organization_id),
        ("edition_id", request.edition_id),
    ):
        require_programme_uuid(identifier, field=field)
    if request.department_id is not None:
        require_programme_uuid(request.department_id, field="department_id")
    _audit_inputs(
        correlation_id=request.correlation_id, source_channel=request.source_channel
    )
    if (
        not isinstance(request.requested_fields, frozenset)
        or not request.requested_fields
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    return authorize_programme_review_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        department_id=request.department_id,
        capability_code=request.capability_code,
        requested_fields=request.requested_fields,
        authorizer=authorizer,
    )


def _locked_scope(
    request: ProgrammeReviewReadRequest, authorizer: ApplicationsProgrammeAuthorizer
) -> AuthorizedProgrammeReviewScope:
    _scope(request, authorizer)
    lock_programme_edition_write_scope(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        department_ids=(
            () if request.department_id is None else (request.department_id,)
        ),
        actor_id=request.actor_id,
    )
    return _scope(request, authorizer)


def _audit(
    request: ProgrammeReviewReadRequest,
    operation: str,
    target_id: UUID | None,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> None:
    scope = _scope(request, authorizer)
    if "audit_sensitive_read" not in scope.decision.obligations:
        raise ApplicationsProgrammeAuthorizationDeniedError
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=scope.capability_code,
            operation=f"applications.programme_review.query.{operation}",
            target_type="applications.programme_review",
            target_id=target_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel=request.source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            retention_class="applications-programme-restricted",
        ),
        occurred_at=timezone.now(),
    )


def _cases(request: ProgrammeReviewReadRequest) -> QuerySet[ProgrammeReviewCase]:
    return ProgrammeReviewCase.objects.select_related("proposal", "policy").filter(
        proposal__organization_id=request.organization_id,
        proposal__edition_id=request.edition_id,
        proposal__call__owner_department_id=request.department_id,
        revision__organization_id=request.organization_id,
        revision__edition_id=request.edition_id,
    )


def _own_assignments(
    request: ProgrammeReviewReadRequest,
) -> QuerySet[ProgrammeReviewAssignment]:
    return ProgrammeReviewAssignment.objects.filter(
        case__proposal__organization_id=request.organization_id,
        case__proposal__edition_id=request.edition_id,
        account_id=request.actor_id,
        state__in=(
            ProgrammeReviewAssignmentState.PENDING,
            ProgrammeReviewAssignmentState.ACTIVE,
        ),
    )


@transaction.atomic
def list_programme_review_cases(
    *,
    request: ProgrammeReviewReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammeReviewCasePage:
    """List management cases or the reviewer's own pending/active assignments.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact manage/review purpose with only ``review_context`` requested.
    after_id : UUID | None, default=None
        Exclusive ascending case cursor from the previous page.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ProgrammeReviewCasePage
        Content-free queue; pending assignments never expose submission content.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If purpose, fields, scope, identity, or bounds are not authorized.
    """
    _limit(limit)
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    if request.capability_code not in {
        MANAGE_REVIEW,
        REVIEW,
    } or request.requested_fields != frozenset({"review_context"}):
        raise ApplicationsProgrammeAuthorizationDeniedError
    _locked_scope(request, authorizer)
    cases = _cases(request)
    if request.capability_code == REVIEW:
        cases = cases.filter(id__in=_own_assignments(request).values("case_id"))
    if after_id is not None:
        cases = cases.filter(id__gt=after_id)
    rows = tuple(cases.order_by("id")[: limit + 1])
    assignments = {
        (row.case_id, row.stage): row
        for row in _own_assignments(request).filter(
            case_id__in=[case.id for case in rows]
        )
    }
    items = []
    for case in rows[:limit]:
        assignment = assignments.get((case.id, case.stage))
        items.append(
            ProgrammeReviewCaseSummary(
                case_id=case.id,
                version=case.version,
                stage=case.stage,
                state=case.state,
                current_revision=revision_is_current(case),
                own_assignment_id=assignment.id if assignment else None,
                own_assignment_state=assignment.state if assignment else None,
                own_assignments=tuple(
                    (row.id, row.stage, row.state)
                    for (assigned_case, _stage), row in sorted(assignments.items())
                    if assigned_case == case.id
                ),
            )
        )
    _audit(request, "cases", None, authorizer)
    return ProgrammeReviewCasePage(
        tuple(items), rows[limit - 1].id if len(rows) > limit else None
    )


def _detail_assignment(
    request: ProgrammeReviewReadRequest, case: ProgrammeReviewCase
) -> ProgrammeReviewAssignment | None:
    if case.proposal.call.owner_department_id != request.department_id:
        raise ApplicationsProgrammeAuthorizationDeniedError
    if request.capability_code == MANAGE_REVIEW:
        if request.requested_fields != frozenset({"review_context"}):
            raise ApplicationsProgrammeAuthorizationDeniedError
        return None
    if request.capability_code in {MODERATE, DECIDE}:
        try:
            require_independent_actor(
                case, request.actor_id, decision=request.capability_code == DECIDE
            )
        except ProgrammeReviewConflictError as error:
            raise ApplicationsProgrammeAuthorizationDeniedError from error
        return None
    assignment = (
        _own_assignments(request)
        .filter(
            case=case, stage=case.stage, state=ProgrammeReviewAssignmentState.ACTIVE
        )
        .first()
    )
    if (
        assignment is None
        or not revision_is_current(case)
        or is_proposal_contributor(case.proposal, request.actor_id)
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    return assignment


def _answers(
    request: ProgrammeReviewReadRequest,
    scope: AuthorizedProgrammeReviewScope,
    case: ProgrammeReviewCase,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> str:
    query = ProgrammeProposalRevisionAnswer.objects.select_related(
        "question", "answer_revision"
    ).filter(
        revision_id=case.revision_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        question_key__in=case.policy.stages[case.stage]["question_keys"],
    )
    if case.policy.stages[case.stage]["anonymous"]:
        query = query.exclude(question_type__in=_ANONYMOUS_OMISSIONS).filter(
            question__source_binding=""
        )
    rows = tuple(query.order_by("question_key")[: _MAX_ANSWERS + 1])
    if len(rows) > _MAX_ANSWERS:
        raise ProgrammeReviewUnavailableError
    if any(row.classification in {"C3", "C4"} for row in rows):
        authorize_programme_review_scope(
            actor_id=scope.actor_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            capability_code=SENSITIVE_REVIEW,
            requested_fields=request.requested_fields,
            authorizer=authorizer,
        )
    return _json(
        [
            {
                "key": row.question_key,
                "label": row.question.label,
                "type": row.question_type,
                "classification": row.classification,
                "value": row.answer_revision.value
                if row.answer_revision is not None
                else None,
            }
            for row in rows
        ]
    )


def _context(case: ProgrammeReviewCase, request: ProgrammeReviewReadRequest) -> str:
    context: dict[str, object] = {
        "stage": case.stage,
        "state": case.state,
        "current_revision": revision_is_current(case),
        "policy_id": str(case.policy_id),
        "policy_version": case.policy.version,
        "stages": case.policy.stages,
    }
    if request.capability_code in {MODERATE, DECIDE}:
        context["accepted_review_effective"] = accepted_review_is_effective(case)
    if request.capability_code == DECIDE:
        context["decision_templates"] = case.policy.templates
    if request.capability_code == MANAGE_REVIEW:
        assignments = tuple(
            ProgrammeReviewAssignment.objects.filter(case=case).order_by("stage", "id")[
                : _MAX_ASSIGNMENTS + 1
            ]
        )
        if len(assignments) > _MAX_ASSIGNMENTS:
            raise ProgrammeReviewUnavailableError
        context["assignments"] = [
            {
                "assignment_id": str(row.id),
                "account_id": str(row.account_id),
                "stage": row.stage,
                "state": row.state,
            }
            for row in assignments
        ]
    if request.capability_code != MANAGE_REVIEW:
        selection = case.revision.selection_revision
        context["selection"] = {
            "track_code": selection.track.code,
            "format_code": selection.format.code,
            "requested_duration_minutes": selection.requested_duration_minutes,
        }
    if (
        request.capability_code != MANAGE_REVIEW
        and not case.policy.stages[case.stage]["anonymous"]
    ):
        context["contributors"] = [
            {
                "public_name": row.profile_revision.public_name,
                "biography": row.profile_revision.biography,
            }
            for row in ProgrammeProposalRevisionContributor.objects.select_related(
                "profile_revision"
            )
            .filter(
                revision_id=case.revision_id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
            )
            .order_by("role", "id")[:17]
        ]
    return _json(context)


def _evidence(
    case: ProgrammeReviewCase,
    assignment: ProgrammeReviewAssignment | None,
    after_version: int,
    limit: int,
) -> tuple[str, int | None]:
    query = ProgrammeReviewEntry.objects.filter(case=case, version__gt=after_version)
    if assignment is not None:
        allowed = Q(assignment=assignment)
        if (
            case.policy.stages[case.stage]["discussion"]
            and ProgrammeReviewEntry.objects.filter(
                case=case, assignment=assignment, action=ProgrammeReviewAction.SCORED
            ).exists()
        ):
            allowed |= Q(
                stage=case.stage,
                action=ProgrammeReviewAction.DISCUSSED,
                assignment__state=ProgrammeReviewAssignmentState.ACTIVE,
            )
        query = query.filter(allowed)
    rows = tuple(query.order_by("version")[: limit + 1])
    items = []
    for entry in rows[:limit]:
        item: dict[str, object] = {
            "version": entry.version,
            "stage": entry.stage,
            "action": entry.action,
        }
        if assignment is None:
            item.update(
                actor_id=str(entry.actor_id),
                assignment_id=str(entry.assignment_id) if entry.assignment_id else None,
                payload=entry.payload,
                reason=entry.reason,
            )
        elif entry.assignment_id == assignment.id:
            item.update(
                payload={
                    key: value
                    for key, value in entry.payload.items()
                    if key != "reviewer_id"
                },
                reason=entry.reason if entry.actor_id == assignment.account_id else "",
            )
        else:
            item["payload"] = {"text": entry.payload["text"]}
        items.append(item)
    return _json(items), rows[limit - 1].version if len(rows) > limit else None


@transaction.atomic
def get_programme_review_detail(  # noqa: DOC503 -- Content-bound checks delegate unavailable errors.
    *,
    request: ProgrammeReviewReadRequest,
    case_id: UUID,
    after_version: int = 0,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammeReviewDetail:
    """Read exact sealed content and role-filtered, paginated private evidence.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact staff purpose and explicit review field ceiling.
    case_id : UUID
        Opaque case identifier; content requires own conflict clearance for reviewers.
    after_version : int, default=0
        Exclusive case-version cursor for this role's evidence page.
    limit : int, default=50
        Complete evidence page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ProgrammeReviewDetail
        Immutable filtered values; manager scope alone yields context only.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If exact scope, role, object relationship, or field authority is absent.
    ProgrammeReviewUnavailableError
        If a configured content bound cannot be projected completely.
    """
    require_programme_uuid(case_id, field="case_id")
    _limit(limit)
    if (
        type(after_version) is not int
        or not 0 <= after_version <= 2**63 - 1
        or request.capability_code not in REVIEW_STAFF_CAPABILITIES
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    scope = _locked_scope(request, authorizer)
    try:
        case = load_review_case(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            case_id=case_id,
        )
    except ProgrammeReviewUnavailableError as error:
        raise ApplicationsProgrammeAuthorizationDeniedError from error
    assignment = _detail_assignment(request, case)
    if request.capability_code != MANAGE_REVIEW:
        require_sensitive_programme_review_authority(
            scope=scope,
            case=case,
            requested_fields=request.requested_fields,
            authorizer=authorizer,
        )
    fields = request.requested_fields
    evidence, cursor = (
        _evidence(case, assignment, after_version, limit)
        if "review_evidence" in fields
        else (None, None)
    )
    result = ProgrammeReviewDetail(
        case.id,
        case.version,
        _context(case, request) if "review_context" in fields else None,
        _answers(request, scope, case, authorizer)
        if "review_answers" in fields
        else None,
        evidence,
        cursor,
    )
    _audit(request, "detail", case.id, authorizer)
    return result


@transaction.atomic
def list_self_programme_decisions(
    *,
    request: ProgrammeReviewReadRequest,
    after_id: UUID | None = None,
    limit: int = 50,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammeDecisionPage:
    """Read only exact-seal addressed messages and the caller's own receipt.

    Parameters
    ----------
    request : ProgrammeReviewReadRequest
        Exact recipient self purpose and message/own-acknowledgement field ceiling.
    after_id : UUID | None, default=None
        Exact prior addressed decision UUID in chronological history.
    limit : int, default=50
        Complete page size between one and 100.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the established isolated-test seam.

    Returns
    -------
    ProgrammeDecisionPage
        Addressed decisions, including history after withdrawal or owner retirement.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If identity, exact self purpose, fields, scope, or page bounds fail.
    """
    _limit(limit)
    if after_id is not None:
        require_programme_uuid(after_id, field="after_id")
    if request.capability_code != VIEW_DECISION_SELF:
        raise ApplicationsProgrammeAuthorizationDeniedError
    _locked_scope(request, authorizer)
    recipients = ProgrammeProposalRevisionContributor.objects.filter(
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        account_id=request.actor_id,
    ).values("revision_id")
    query = ProgrammeReviewDecision.objects.select_related("entry__case").filter(
        revision_id__in=recipients,
        revision__organization_id=request.organization_id,
        revision__edition_id=request.edition_id,
        entry__case__proposal__organization_id=request.organization_id,
        entry__case__proposal__edition_id=request.edition_id,
    )
    if after_id is not None:
        previous = (
            query.filter(id=after_id).values_list("entry__created_at", "id").first()
        )
        if previous is None:
            raise ApplicationsProgrammeAuthorizationDeniedError
        query = query.filter(
            Q(entry__created_at__gt=previous[0])
            | Q(entry__created_at=previous[0], id__gt=previous[1])
        )
    rows = tuple(query.order_by("entry__created_at", "id")[: limit + 1])
    acknowledged = dict(
        ProgrammeDecisionAcknowledgement.objects.filter(
            decision_id__in=[row.id for row in rows], account_id=request.actor_id
        ).values_list("decision_id", "created_at")
    )
    own_ack = "own_acknowledgement" in request.requested_fields
    items = tuple(
        ProgrammeDecisionMessage(
            decision_id=row.id,
            case_id=row.entry.case_id,
            case_version=row.entry.case.version,
            decision_version=row.entry.version,
            decided_at=row.entry.created_at,
            outcome=row.outcome
            if "decision_message" in request.requested_fields
            else None,
            message=row.message
            if "decision_message" in request.requested_fields
            else None,
            acknowledgement_required=row.acknowledgement_required if own_ack else None,
            own_acknowledged=row.id in acknowledged if own_ack else None,
            own_acknowledged_at=acknowledged.get(row.id) if own_ack else None,
        )
        for row in rows[:limit]
    )
    _audit(request, "self_decisions", None, authorizer)
    return ProgrammeDecisionPage(
        items, rows[limit - 1].id if len(rows) > limit else None
    )
