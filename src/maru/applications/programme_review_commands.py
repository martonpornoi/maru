"""Transactional, exact-revision commands for the dormant Programme review kernel."""

from __future__ import annotations

import hashlib
import re
from contextlib import suppress
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final, TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from maru.applications.models import (
    ApplicationCommandReceipt,
    ApplicationQuestion,
    ProgrammeCall,
    ProgrammeCommandReceipt,
    ProgrammeDecisionAcknowledgement,
    ProgrammeImportCommandReceipt,
    ProgrammeProposal,
    ProgrammeProposalState,
    ProgrammeReviewAction,
    ProgrammeReviewAssignment,
    ProgrammeReviewAssignmentState,
    ProgrammeReviewCase,
    ProgrammeReviewDecision,
    ProgrammeReviewEntry,
    ProgrammeReviewPolicy,
    ProgrammeReviewReceipt,
    ProgrammeReviewState,
)
from maru.applications.programme_authorization import (
    DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER,
    ApplicationsProgrammeAuthorizationDeniedError,
    authorize_programme_retry_scope,
)
from maru.applications.programme_commands import (
    ApplicationsProgrammeIdempotencyConflictError,
)
from maru.applications.programme_inputs import (
    canonical_programme_digest,
    normalized_programme_text,
    require_programme_uuid,
)
from maru.applications.programme_review_authorization import (
    ACKNOWLEDGE_SELF,
    DECIDE,
    MANAGE_REVIEW,
    MODERATE,
    REVIEW,
    AuthorizedProgrammeReviewScope,
    authorize_programme_review_scope,
    require_sensitive_programme_review_authority,
)
from maru.applications.programme_review_events import PROGRAMME_REVIEW_CHANGED_EVENT
from maru.applications.programme_review_inputs import (
    MAX_REVIEW_REASON,
    MAX_STAGE_REVIEWERS,
    ProgrammeReviewCommandInput,
)
from maru.applications.programme_review_rules import (
    ProgrammeReviewConflictError,
    ProgrammeReviewUnavailableError,
    is_decision_recipient,
    is_proposal_contributor,
    load_review_case,
    require_independent_actor,
    revision_is_current,
    stage_is_ready,
)
from maru.applications.programme_write_scope import lock_programme_edition_write_scope
from maru.applications.programme_writer_boundary import (
    programme_application_database_writer,
)
from maru.applications.retry_namespace import lock_applications_retry_namespace
from maru.audit.services import AuditRecord, append_audit
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.queries import resolve_active_verified_person_reference

if TYPE_CHECKING:
    from maru.applications.programme_authorization import (
        ApplicationsProgrammeAuthorizer,
    )

_DEFAULT_AUTHORIZER: Final = DEFAULT_APPLICATIONS_PROGRAMME_AUTHORIZER
_SOURCE: Final = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAX_VERSION: Final = 2**63 - 2
_PERSONAL_ACTIONS: Final = frozenset(
    {
        ProgrammeReviewAction.CONFLICT_CLEARED,
        ProgrammeReviewAction.REVIEWER_RECUSED,
        ProgrammeReviewAction.ACKNOWLEDGED,
    }
)
_CAPABILITIES: Final = {
    ProgrammeReviewAction.POLICY_CREATED: MANAGE_REVIEW,
    ProgrammeReviewAction.CASE_OPENED: MANAGE_REVIEW,
    ProgrammeReviewAction.REVIEWER_ASSIGNED: MANAGE_REVIEW,
    ProgrammeReviewAction.REVIEWER_REMOVED: MANAGE_REVIEW,
    ProgrammeReviewAction.CONFLICT_CLEARED: REVIEW,
    ProgrammeReviewAction.REVIEWER_RECUSED: REVIEW,
    ProgrammeReviewAction.SCORED: REVIEW,
    ProgrammeReviewAction.DISCUSSED: REVIEW,
    ProgrammeReviewAction.MODERATED: MODERATE,
    ProgrammeReviewAction.STAGE_ADVANCED: MODERATE,
    ProgrammeReviewAction.STAGE_REOPENED: MODERATE,
    ProgrammeReviewAction.DECIDED: DECIDE,
    ProgrammeReviewAction.ACKNOWLEDGED: ACKNOWLEDGE_SELF,
}


class _ScopeIds(TypedDict):
    """Name the exact three identifiers shared by authorization entrypoints."""

    actor_id: UUID
    organization_id: UUID
    edition_id: UUID


def _reference(value: UUID | None) -> UUID:
    if value is None:
        raise ProgrammeReviewUnavailableError
    return value


def _source_channel(value: str) -> str:
    if not isinstance(value, str) or _SOURCE.fullmatch(value) is None:
        raise ValidationError(
            "Use a bounded source channel.",
            code="applications_programme_review_input_invalid",
        )
    return value


@dataclass(frozen=True, slots=True)
class ProgrammeReviewResult:
    """Return minimized retained identifiers without content or renewed authority.

    Attributes
    ----------
    receipt_id
        Exact immutable intent/evidence receipt.
    target_id
        Created policy, case, assignment, entry, decision, or acknowledgement.
    case_id
        Exact review case, or None for a policy-only operation.
    version
        Resulting policy or review-case version.
    replayed
        Whether the original receipt was returned without another mutation.
    """

    receipt_id: UUID
    target_id: UUID
    case_id: UUID | None
    version: int
    replayed: bool


def _result(
    receipt: ProgrammeReviewReceipt, *, replayed: bool
) -> ProgrammeReviewResult:
    return ProgrammeReviewResult(
        receipt.id,
        receipt.target_id,
        receipt.case_id,
        receipt.resulting_version,
        replayed,
    )


def _replay(
    scope: _ScopeIds, retry_key: UUID, digest: str
) -> ProgrammeReviewResult | None:
    lock_applications_retry_namespace(
        edition_id=scope["edition_id"], actor_id=scope["actor_id"], retry_key=retry_key
    )
    filters = {
        "edition_id": scope["edition_id"],
        "actor_id": scope["actor_id"],
        "retry_key": retry_key,
    }
    receipt = ProgrammeReviewReceipt.objects.filter(**filters).first()
    if receipt is not None:
        if (
            receipt.organization_id != scope["organization_id"]
            or receipt.request_digest != digest
        ):
            raise ApplicationsProgrammeIdempotencyConflictError
        return _result(receipt, replayed=True)
    if any(
        model.objects.filter(**filters).exists()
        for model in (
            ApplicationCommandReceipt,
            ProgrammeCommandReceipt,
            ProgrammeImportCommandReceipt,
        )
    ):
        raise ApplicationsProgrammeIdempotencyConflictError
    return None


def _policy(
    scope: AuthorizedProgrammeReviewScope,
    command: ProgrammeReviewCommandInput,
    expected_version: int,
    reason: str,
) -> tuple[ProgrammeReviewPolicy, UUID]:
    call = ProgrammeCall.objects.filter(
        id=command.target_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        owner_department_id=scope.department_id,
    ).first()
    if call is None or command.policy is None:
        raise ProgrammeReviewUnavailableError
    selected_questions = {
        key for stage in command.policy.stages for key in stage.question_keys
    }
    if selected_questions != set(
        ApplicationQuestion.objects.filter(
            definition_id=call.definition_id,
            key__in=selected_questions,
        ).values_list("key", flat=True)
    ):
        raise ProgrammeReviewConflictError
    latest = (
        ProgrammeReviewPolicy.objects.filter(call=call).aggregate(value=Max("version"))[
            "value"
        ]
        or 0
    )
    if latest != expected_version:
        raise ProgrammeReviewConflictError
    values = asdict(command.policy)
    policy = ProgrammeReviewPolicy.objects.create(
        call=call,
        version=expected_version + 1,
        stages=list(values["stages"]),
        templates=list(values["templates"]),
        digest=command.policy.digest,
        actor_id=scope.actor_id,
        reason=reason,
    )
    return policy, policy.id


def _open_case(
    scope: AuthorizedProgrammeReviewScope,
    command: ProgrammeReviewCommandInput,
    expected_version: int,
) -> ProgrammeReviewCase:
    proposal = (
        ProgrammeProposal.objects.select_related("call", "submission")
        .filter(
            id=command.target_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            call__owner_department_id=scope.department_id,
            state=ProgrammeProposalState.SUBMITTED,
        )
        .first()
    )
    if proposal is None:
        raise ProgrammeReviewUnavailableError
    policy = ProgrammeReviewPolicy.objects.filter(
        id=_reference(command.policy_id),
        call_id=proposal.call_id,
        call__organization_id=scope.organization_id,
        call__edition_id=scope.edition_id,
    ).first()
    if (
        expected_version != 0
        or policy is None
        or is_proposal_contributor(proposal, scope.actor_id)
        or ProgrammeReviewCase.objects.filter(
            revision_id=proposal.submitted_revision_id
        ).exists()
    ):
        raise ProgrammeReviewConflictError
    return ProgrammeReviewCase.objects.create(
        proposal=proposal,
        revision_id=_reference(proposal.submitted_revision_id),
        policy=policy,
        created_by_id=scope.actor_id,
    )


def _assign_reviewer(
    case: ProgrammeReviewCase, command: ProgrammeReviewCommandInput
) -> ProgrammeReviewAssignment:
    if command.reference_id is None:
        raise ProgrammeReviewConflictError
    reviewer = resolve_active_verified_person_reference(account_id=command.reference_id)
    if (
        reviewer is None
        or reviewer.account_id == case.created_by_id
        or is_proposal_contributor(case.proposal, reviewer.account_id)
        or ProgrammeReviewEntry.objects.filter(
            case=case,
            actor_id=reviewer.account_id,
            action__in=(ProgrammeReviewAction.MODERATED, ProgrammeReviewAction.DECIDED),
        ).exists()
        or ProgrammeReviewAssignment.objects.filter(case=case, stage=case.stage).count()
        >= MAX_STAGE_REVIEWERS
        or ProgrammeReviewAssignment.objects.filter(
            case=case, stage=case.stage, account_id=reviewer.account_id
        ).exists()
    ):
        raise ProgrammeReviewConflictError
    return ProgrammeReviewAssignment.objects.create(
        case=case,
        stage=case.stage,
        account_id=reviewer.account_id,
        version=case.version,
    )


def _assignment(
    case: ProgrammeReviewCase, reference_id: UUID | None
) -> ProgrammeReviewAssignment:
    assignment = ProgrammeReviewAssignment.objects.filter(
        id=_reference(reference_id), case=case
    ).first()
    if assignment is None:
        raise ProgrammeReviewUnavailableError
    return assignment


def _require_reviewer(
    case: ProgrammeReviewCase,
    assignment: ProgrammeReviewAssignment,
    actor_id: UUID,
    *,
    active: bool = True,
) -> None:
    allowed = (
        {ProgrammeReviewAssignmentState.ACTIVE}
        if active
        else {
            ProgrammeReviewAssignmentState.PENDING,
            ProgrammeReviewAssignmentState.ACTIVE,
        }
    )
    if (
        assignment.account_id != actor_id
        or assignment.state not in allowed
        or is_proposal_contributor(case.proposal, actor_id)
    ):
        raise ProgrammeReviewConflictError


def _assignment_action(
    case: ProgrammeReviewCase, command: ProgrammeReviewCommandInput, actor_id: UUID
) -> tuple[ProgrammeReviewAssignment, dict[str, object]]:
    assignment = _assignment(case, command.reference_id)
    if command.action != ProgrammeReviewAction.REVIEWER_REMOVED:
        _require_reviewer(case, assignment, actor_id, active=False)
    elif assignment.state not in {
        ProgrammeReviewAssignmentState.PENDING,
        ProgrammeReviewAssignmentState.ACTIVE,
    }:
        raise ProgrammeReviewConflictError
    if command.action == ProgrammeReviewAction.CONFLICT_CLEARED:
        if (
            assignment.state != ProgrammeReviewAssignmentState.PENDING
            or assignment.stage != case.stage
        ):
            raise ProgrammeReviewConflictError
        assignment.state = ProgrammeReviewAssignmentState.ACTIVE
    elif command.action == ProgrammeReviewAction.REVIEWER_RECUSED:
        assignment.state = ProgrammeReviewAssignmentState.RECUSED
    else:
        assignment.state = ProgrammeReviewAssignmentState.REMOVED
    assignment.version = case.version
    assignment.save()
    return assignment, {"state": assignment.state}


def _reviewer_entry(
    case: ProgrammeReviewCase, command: ProgrammeReviewCommandInput, actor_id: UUID
) -> tuple[ProgrammeReviewAssignment, dict[str, object]]:
    assignment = _assignment(case, command.reference_id)
    _require_reviewer(case, assignment, actor_id)
    if assignment.stage != case.stage:
        raise ProgrammeReviewConflictError
    stage = case.policy.stages[case.stage]
    if command.action == ProgrammeReviewAction.SCORED:
        scores = dict(command.scores)
        criteria = {criterion["code"]: criterion for criterion in stage["criteria"]}
        if set(scores) != set(criteria) or any(
            not criteria[code]["minimum"] <= score <= criteria[code]["maximum"]
            for code, score in scores.items()
        ):
            raise ProgrammeReviewConflictError
        return assignment, {"scores": scores}
    if (
        not stage["discussion"]
        or not ProgrammeReviewEntry.objects.filter(
            case=case, assignment=assignment, action=ProgrammeReviewAction.SCORED
        ).exists()
    ):
        raise ProgrammeReviewConflictError
    return assignment, {"text": command.text}


def _moderator_entry(
    case: ProgrammeReviewCase,
    command: ProgrammeReviewCommandInput,
    actor_id: UUID,
    expected_version: int,
) -> dict[str, object]:
    require_independent_actor(case, actor_id)
    if command.action == ProgrammeReviewAction.MODERATED:
        return {"evidence_version": expected_version}
    if command.action == ProgrammeReviewAction.STAGE_REOPENED:
        if command.stage is None or command.stage > case.stage:
            raise ProgrammeReviewConflictError
        previous_stage = case.stage
        case.stage = command.stage
        case.state = ProgrammeReviewState.OPEN
        return {"from_stage": previous_stage, "to_stage": case.stage}
    if case.stage + 1 >= len(case.policy.stages) or not stage_is_ready(
        case, case.stage
    ):
        raise ProgrammeReviewConflictError
    case.stage += 1
    return {"to_stage": case.stage}


def _decide(
    case: ProgrammeReviewCase, command: ProgrammeReviewCommandInput, actor_id: UUID
) -> dict[str, object]:
    require_independent_actor(case, actor_id, decision=True)
    if (
        case.stage != len(case.policy.stages) - 1
        or not all(
            stage_is_ready(case, stage) for stage in range(len(case.policy.stages))
        )
        or (
            case.state == ProgrammeReviewState.WAITLISTED
            and command.outcome == ProgrammeReviewState.WAITLISTED
        )
    ):
        raise ProgrammeReviewConflictError
    case.state = command.outcome
    return {"outcome": command.outcome}


def _mutate_case(
    scope: AuthorizedProgrammeReviewScope,
    command: ProgrammeReviewCommandInput,
    case: ProgrammeReviewCase,
    expected_version: int,
    reason: str,
) -> UUID:
    action = command.action
    assignment = None
    payload: dict[str, object] = {}
    entry_stage = case.stage
    if action == ProgrammeReviewAction.REVIEWER_ASSIGNED:
        assignment = _assign_reviewer(case, command)
        payload = {"reviewer_id": str(assignment.account_id), "state": assignment.state}
    elif action in {
        ProgrammeReviewAction.CONFLICT_CLEARED,
        ProgrammeReviewAction.REVIEWER_RECUSED,
        ProgrammeReviewAction.REVIEWER_REMOVED,
    }:
        assignment, payload = _assignment_action(case, command, scope.actor_id)
        entry_stage = assignment.stage
    elif action in {ProgrammeReviewAction.SCORED, ProgrammeReviewAction.DISCUSSED}:
        assignment, payload = _reviewer_entry(case, command, scope.actor_id)
    elif action in {
        ProgrammeReviewAction.MODERATED,
        ProgrammeReviewAction.STAGE_ADVANCED,
        ProgrammeReviewAction.STAGE_REOPENED,
    }:
        payload = _moderator_entry(case, command, scope.actor_id, expected_version)
        if action == ProgrammeReviewAction.STAGE_REOPENED:
            entry_stage = case.stage
    elif action == ProgrammeReviewAction.DECIDED:
        payload = _decide(case, command, scope.actor_id)
    elif action == ProgrammeReviewAction.CASE_OPENED:
        payload = {"policy_id": str(case.policy_id)}
    elif action == ProgrammeReviewAction.ACKNOWLEDGED:
        payload = {"decision_id": str(command.reference_id)}
    else:
        raise ProgrammeReviewConflictError
    if action != ProgrammeReviewAction.CASE_OPENED:
        case.save()
    entry = ProgrammeReviewEntry.objects.create(
        case=case,
        version=case.version,
        stage=entry_stage,
        actor_id=scope.actor_id,
        action=action,
        assignment=assignment,
        payload=payload,
        reason=reason,
    )
    return _case_result(scope, command, case, entry, assignment)


def _case_result(
    scope: AuthorizedProgrammeReviewScope,
    command: ProgrammeReviewCommandInput,
    case: ProgrammeReviewCase,
    entry: ProgrammeReviewEntry,
    assignment: ProgrammeReviewAssignment | None,
) -> UUID:
    action = command.action
    if action == ProgrammeReviewAction.DECIDED:
        template = next(
            item for item in case.policy.templates if item["outcome"] == command.outcome
        )
        decision = ProgrammeReviewDecision.objects.create(
            entry=entry,
            revision_id=case.revision_id,
            outcome=command.outcome,
            message=template["text"] + "\n\n" + command.text,
            acknowledgement_required=template["acknowledgement_required"],
        )
        return decision.id
    if action == ProgrammeReviewAction.ACKNOWLEDGED:
        return ProgrammeDecisionAcknowledgement.objects.create(
            decision_id=_reference(command.reference_id),
            entry=entry,
            account_id=scope.actor_id,
        ).id
    if action == ProgrammeReviewAction.CASE_OPENED:
        return case.id
    return assignment.id if assignment is not None else entry.id


def _require_case_action(
    scope: AuthorizedProgrammeReviewScope,
    case: ProgrammeReviewCase,
    command: ProgrammeReviewCommandInput,
    expected_version: int,
) -> None:
    if command.action == ProgrammeReviewAction.ACKNOWLEDGED:
        decision = (
            ProgrammeReviewDecision.objects.select_related("revision")
            .filter(
                id=_reference(command.reference_id),
                entry__case=case,
                revision_id=case.revision_id,
            )
            .first()
        )
        if decision is None or not is_decision_recipient(decision, scope.actor_id):
            raise ApplicationsProgrammeAuthorizationDeniedError
        if case.version != expected_version:
            raise ProgrammeReviewConflictError
        if (
            not decision.acknowledgement_required
            or ProgrammeDecisionAcknowledgement.objects.filter(
                decision=decision, account_id=scope.actor_id
            ).exists()
        ):
            raise ProgrammeReviewConflictError
        return
    if case.proposal.call.owner_department_id != scope.department_id:
        raise ApplicationsProgrammeAuthorizationDeniedError
    if (
        scope.capability_code == REVIEW
        and not ProgrammeReviewAssignment.objects.filter(
            id=_reference(command.reference_id),
            case=case,
            account_id=scope.actor_id,
            state__in=(
                ProgrammeReviewAssignmentState.PENDING,
                ProgrammeReviewAssignmentState.ACTIVE,
            ),
        ).exists()
    ):
        raise ApplicationsProgrammeAuthorizationDeniedError
    if case.version != expected_version:
        raise ProgrammeReviewConflictError
    if not revision_is_current(case):
        raise ProgrammeReviewConflictError
    late_conflict = command.action in {
        ProgrammeReviewAction.REVIEWER_RECUSED,
        ProgrammeReviewAction.REVIEWER_REMOVED,
    }
    waiting_successor = (
        case.state == ProgrammeReviewState.WAITLISTED
        and command.action
        in {ProgrammeReviewAction.DECIDED, ProgrammeReviewAction.STAGE_REOPENED}
    )
    if (
        case.state != ProgrammeReviewState.OPEN
        and not late_conflict
        and not waiting_successor
    ):
        raise ProgrammeReviewConflictError


def _record(
    scope: AuthorizedProgrammeReviewScope,
    command: ProgrammeReviewCommandInput,
    policy: ProgrammeReviewPolicy,
    case: ProgrammeReviewCase | None,
    target_id: UUID,
    expected_version: int,
    retry_key: UUID,
    digest: str,
    correlation_id: UUID,
    source_channel: str,
) -> ProgrammeReviewResult:
    aggregate_id = case.id if case is not None else policy.call_id
    occurred_at = timezone.now()
    audit = append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor_id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=scope.capability_code,
            operation=f"applications.programme_review.command.{command.action}",
            target_type="applications.programme_review",
            target_id=aggregate_id,
            outcome="allow",
            reason_code=scope.decision.reason_code,
            correlation_id=correlation_id,
            request_id=correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=("review_evidence",),
            idempotency_key_hash=hashlib.sha256(str(retry_key).encode()).hexdigest(),
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )
    event, _outbox = publish_domain_event(
        DomainEventRecord(
            event_name=PROGRAMME_REVIEW_CHANGED_EVENT,
            schema_version=1,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            aggregate_type="applications.programme_review",
            aggregate_id=aggregate_id,
            aggregate_version=expected_version + 1,
            payload={
                "action": command.action,
                "aggregate_id": str(aggregate_id),
                "resulting_version": str(expected_version + 1),
            },
            correlation_id=correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=scope.actor_id,
            retention_class="applications-programme-restricted",
        ),
        occurred_at=occurred_at,
    )
    receipt = ProgrammeReviewReceipt.objects.create(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        actor_id=scope.actor_id,
        retry_key=retry_key,
        request_digest=digest,
        action=command.action,
        aggregate_id=aggregate_id,
        target_id=target_id,
        policy=policy,
        case=case,
        expected_version=expected_version,
        resulting_version=expected_version + 1,
        audit_event_id=audit.id,
        domain_event_id=event.id,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    return _result(receipt, replayed=False)


@transaction.atomic
def _execute(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID | None,
    command: ProgrammeReviewCommandInput,
    expected_version: int,
    retry_key: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ApplicationsProgrammeAuthorizer,
) -> ProgrammeReviewResult:
    identifiers: _ScopeIds = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }
    for name, identifier in (
        ("actor_id", actor_id),
        ("organization_id", organization_id),
        ("edition_id", edition_id),
        ("retry_key", retry_key),
        ("correlation_id", correlation_id),
    ):
        require_programme_uuid(identifier, field=name)
    if department_id is not None:
        require_programme_uuid(department_id, field="department_id")
    authorize_programme_retry_scope(**identifiers, authorizer=authorizer)
    if not isinstance(command, ProgrammeReviewCommandInput):
        raise ValidationError(
            "Use a typed review command.",
            code="applications_programme_review_input_invalid",
        )
    command = command.normalized()
    if type(expected_version) is not int or not 0 <= expected_version <= _MAX_VERSION:
        raise ValidationError(
            "Use an exact review version.",
            code="applications_programme_review_input_invalid",
        )
    reason = normalized_programme_text(
        reason,
        field="reason",
        maximum=MAX_REVIEW_REASON,
        required=command.action not in _PERSONAL_ACTIONS,
        multiline=True,
    )
    source_channel = _source_channel(source_channel)
    digest = canonical_programme_digest(
        {
            **identifiers,
            "department_id": department_id,
            "command": asdict(command),
            "expected_version": expected_version,
            "reason": reason,
            "source_channel": source_channel,
        }
    )
    replay = _replay(identifiers, retry_key, digest)
    if replay is not None:
        return replay
    scope = authorize_programme_review_scope(
        **identifiers,
        department_id=department_id,
        capability_code=_CAPABILITIES[command.action],
        authorizer=authorizer,
    )
    lock_programme_edition_write_scope(
        **identifiers,
        department_ids=() if department_id is None else (department_id,),
    )
    scope = authorize_programme_review_scope(
        **identifiers,
        department_id=department_id,
        capability_code=_CAPABILITIES[command.action],
        authorizer=authorizer,
    )
    if (
        command.action != ProgrammeReviewAction.ACKNOWLEDGED
        and not scope.accepts_private_planning_writes
    ):
        raise ProgrammeReviewConflictError
    with programme_application_database_writer():
        case = None
        if command.action == ProgrammeReviewAction.POLICY_CREATED:
            policy, target_id = _policy(scope, command, expected_version, reason)
        else:
            if command.action == ProgrammeReviewAction.CASE_OPENED:
                case = _open_case(scope, command, expected_version)
            else:
                case = _existing_case(scope, command, expected_version)
            if command.action in {
                ProgrammeReviewAction.SCORED,
                ProgrammeReviewAction.DISCUSSED,
                ProgrammeReviewAction.MODERATED,
                ProgrammeReviewAction.STAGE_ADVANCED,
                ProgrammeReviewAction.STAGE_REOPENED,
                ProgrammeReviewAction.DECIDED,
            }:
                require_sensitive_programme_review_authority(
                    scope=scope,
                    case=case,
                    authorizer=authorizer,
                )
            target_id = _mutate_case(scope, command, case, expected_version, reason)
            policy = case.policy
        return _record(
            scope,
            command,
            policy,
            case,
            target_id,
            expected_version,
            retry_key,
            digest,
            correlation_id,
            source_channel,
        )


def _existing_case(
    scope: AuthorizedProgrammeReviewScope,
    command: ProgrammeReviewCommandInput,
    expected_version: int,
) -> ProgrammeReviewCase:
    try:
        case = load_review_case(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            case_id=command.target_id,
        )
    except ProgrammeReviewUnavailableError as error:
        if scope.capability_code in {ACKNOWLEDGE_SELF, REVIEW}:
            raise ApplicationsProgrammeAuthorizationDeniedError from error
        raise
    _require_case_action(scope, case, command, expected_version)
    case.version = expected_version + 1
    return case


def apply_programme_review_command(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID | None,
    command: ProgrammeReviewCommandInput,
    expected_version: int,
    retry_key: UUID,
    reason: str,
    correlation_id: UUID,
    source_channel: str,
    authorizer: ApplicationsProgrammeAuthorizer = _DEFAULT_AUTHORIZER,
) -> ProgrammeReviewResult:
    """Apply one closed review intent with atomic state and retained evidence.

    Parameters
    ----------
    actor_id : UUID
        Authenticated active verified person.
    organization_id : UUID
        Exact organization expected to own the target.
    edition_id : UUID
        Exact edition containing the review workflow.
    department_id : UUID | None
        Current exact owner Department, or None for recipient acknowledgement.
    command : ProgrammeReviewCommandInput
        Typed closed action and its exact action-specific inputs.
    expected_version : int
        Current case or policy cursor; zero only for first policy or case creation.
    retry_key : UUID
        Actor-owned key in the shared Applications intent namespace.
    reason : str
        Bounded private rationale; personal conflict/receipt responses may be blank.
    correlation_id : UUID
        Request evidence identifier, not part of the idempotency intent.
    source_channel : str
        Bounded code identifying the caller adapter.
    authorizer : ApplicationsProgrammeAuthorizer, default=_DEFAULT_AUTHORIZER
        Real policy or the existing two-factor isolated-test admission seam.

    Returns
    -------
    ProgrammeReviewResult
        Minimized committed identifiers, version, and replay status.

    Raises
    ------
    ApplicationsProgrammeAuthorizationDeniedError
        If purpose, identity, recipient, scope, or adoption proof fails.
    ApplicationsProgrammeIdempotencyConflictError
        If the retry key already belongs to another intent or Applications workflow.
    ProgrammeReviewConflictError
        If lifecycle, independence, concurrency, or stage evidence is incompatible.
    ProgrammeReviewUnavailableError
        If a target or its exact scope cannot be resolved without disclosure.
    ValidationError
        If closed typed input or database-backed model validation fails.
    """
    try:
        return _execute(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            command=command,
            expected_version=expected_version,
            retry_key=retry_key,
            reason=reason,
            correlation_id=correlation_id,
            source_channel=source_channel,
            authorizer=authorizer,
        )
    except (
        ApplicationsProgrammeAuthorizationDeniedError,
        ApplicationsProgrammeIdempotencyConflictError,
        ProgrammeReviewConflictError,
        ProgrammeReviewUnavailableError,
        ValidationError,
    ) as error:
        if all(
            isinstance(value, UUID)
            for value in (actor_id, organization_id, edition_id, correlation_id)
        ):
            with suppress(Exception):
                append_audit(
                    AuditRecord(
                        principal_kind="account",
                        principal_id=actor_id,
                        principal_context_id=None,
                        organization_id=organization_id,
                        event_edition_id=edition_id,
                        capability_code=MANAGE_REVIEW,
                        operation="applications.programme_review.command.failed",
                        target_type="applications.programme_review",
                        target_id=None,
                        outcome="deny"
                        if isinstance(
                            error, ApplicationsProgrammeAuthorizationDeniedError
                        )
                        else "error",
                        reason_code=getattr(
                            error,
                            "reason_code",
                            "applications_programme_review_input_invalid",
                        ),
                        correlation_id=correlation_id,
                        request_id=correlation_id,
                        source_channel="system",
                        retention_class="applications-programme-restricted",
                    )
                )
        raise
