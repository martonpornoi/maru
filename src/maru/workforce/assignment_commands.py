"""Owner-safe Position-assignment commands shared by browser and API adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.commands import revoke_role_assignment
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.adoption import profile_adopts_module
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.participation.models import ParticipationCapacity
from maru.workforce.assignment_inputs import (
    assignment_command_digest,
    normalize_assignment_reason,
    validate_assignment_interval,
)
from maru.workforce.assignment_queries import (
    AssignmentReadLimitExceededError,
    assignment_readiness,
    known_assignment_candidates,
)
from maru.workforce.edition_write_scope import (
    LockedWorkforceEditionWriteScope,
    lock_active_department_write_target,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    Position,
    PositionAssignment,
    PositionAssignmentCommandReceipt,
)
from maru.workforce.services import activate_position_assignment

if TYPE_CHECKING:
    from datetime import datetime

VIEW_STRUCTURE = "workforce.view_structure"
MANAGE_ASSIGNMENTS = "workforce.manage_assignments"
MANAGE_ROLES = "authorization.manage_roles"
REVOKE_AUTHORITY = "authorization.revoke"

_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_MAX_SOURCE_CHANNEL_LENGTH = 32
_ASSIGNABLE_EDITION_LIFECYCLES = frozenset(
    {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
    }
)
_CLEANUP_EDITION_LIFECYCLES = _ASSIGNABLE_EDITION_LIFECYCLES | {
    EventEdition.Lifecycle.CLOSING
}
_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_MAX_OPEN_ASSIGNMENTS = 1_024


class AssignmentCommandError(RuntimeError):
    """Base class for stable, disclosure-safe assignment command failures."""

    reason_code = "assignment_command_failed"

    def __init__(
        self,
        message: str = "The assignment action could not complete.",
    ) -> None:
        """Initialize the adapter-safe failure.

        Parameters
        ----------
        message : str, default="The assignment action could not complete."
            Disclosure-safe explanation suitable for an authorized adapter.
        """
        super().__init__(message)


class AssignmentAuthorizationDeniedError(AssignmentCommandError):
    """Signal missing current authority for an assignment action."""

    reason_code = "assignment_authorization_denied"


class AssignmentUnavailableError(AssignmentCommandError):
    """Signal a missing, mismatched, or undisclosable assignment target."""

    reason_code = "assignment_unavailable"


class AssignmentCandidateUnavailableError(AssignmentCommandError):
    """Signal a recipient outside the bounded known-person relationship set."""

    reason_code = "assignment_candidate_unavailable"


class AssignmentLifecycleConflictError(AssignmentCommandError):
    """Signal an edition lifecycle that does not permit the requested action."""

    reason_code = "assignment_lifecycle_conflict"


class AssignmentStateConflictError(AssignmentCommandError):
    """Signal a stale or incompatible assignment or Position state."""

    reason_code = "assignment_state_conflict"


class AssignmentVersionConflictError(AssignmentCommandError):
    """Signal an optimistic-concurrency mismatch."""

    reason_code = "assignment_version_conflict"


class AssignmentRetryConflictError(AssignmentCommandError):
    """Signal reuse of an idempotency key for a different command."""

    reason_code = "assignment_retry_conflict"


class AssignmentReadinessConflictError(AssignmentCommandError):
    """Signal incomplete Position onboarding requirements."""

    reason_code = "assignment_onboarding_incomplete"


class AssignmentHeadcountConflictError(AssignmentCommandError):
    """Signal exhaustion of the Position's approved headcount."""

    reason_code = "assignment_headcount_reached"


@dataclass(frozen=True, slots=True)
class AssignmentCommandResult:
    """Return minimized identifiers and version evidence for one command.

    Attributes
    ----------
    assignment_id
        Assignment changed by the command.
    receipt_id
        Immutable receipt proving the resulting command state.
    resulting_version
        Assignment version after the command.
    status
        Assignment lifecycle state after the command.
    replayed
        Whether an identical idempotent command returned prior evidence.
    """

    assignment_id: UUID
    receipt_id: UUID
    resulting_version: int
    status: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _AssignmentScope:
    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    target: object
    manage_decision: PolicyDecision
    evaluated_at: datetime
    write_scope: LockedWorkforceEditionWriteScope


def _validate_uuid(value: UUID, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationError(
            {
                field_name: ValidationError(
                    "Enter a valid UUID.",
                    code="assignment_identifier_invalid",
                )
            }
        )
    return value


def _validate_expected_version(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValidationError(
            {
                "expected_version": ValidationError(
                    "Enter an assignment version of one or greater.",
                    code="assignment_expected_version_invalid",
                )
            }
        )
    return value


def _validate_source_channel(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_SOURCE_CHANNEL_LENGTH
        or _SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        raise ValidationError(
            {
                "source_channel": ValidationError(
                    "Use a registered source channel.",
                    code="assignment_source_channel_invalid",
                )
            }
        )
    return value


def _route_target(
    *, organization_id: UUID, series_id: UUID, edition_id: UUID
) -> object:
    route_exists = EventEdition.objects.filter(
        id=edition_id,
        organization_id=organization_id,
        series_id=series_id,
        series__organization_id=organization_id,
    ).exists()
    if not route_exists:
        raise AssignmentAuthorizationDeniedError
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if target is None:
        raise AssignmentAuthorizationDeniedError
    return target


def _require_capabilities(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    capability_codes: tuple[str, ...],
    at: datetime | None = None,
) -> tuple[object, PolicyDecision]:
    if actor.pk is None:
        raise AssignmentAuthorizationDeniedError
    target = _route_target(
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
    )
    decisions = tuple(
        decide(
            principal=actor,
            capability_code=capability_code,
            resource=target,  # type: ignore[arg-type]
            at=at,
        )
        for capability_code in capability_codes
    )
    if any(not decision.allowed for decision in decisions):
        raise AssignmentAuthorizationDeniedError
    manage_index = capability_codes.index(MANAGE_ASSIGNMENTS)
    return target, decisions[manage_index]


def _lock_and_authorize_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    capability_codes: tuple[str, ...],
) -> _AssignmentScope:
    try:
        locked = lock_workforce_edition_write_scope(
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
    except ValidationError as error:
        raise AssignmentAuthorizationDeniedError from error
    persisted_actor = Account.objects.filter(pk=actor.pk, is_active=True).first()
    if persisted_actor is None:
        raise AssignmentAuthorizationDeniedError
    evaluated_at = timezone.now()
    target, manage_decision = _require_capabilities(
        actor=persisted_actor,
        organization_id=locked.organization_id,
        series_id=locked.series_id,
        edition_id=locked.edition_id,
        capability_codes=capability_codes,
        at=evaluated_at,
    )
    return _AssignmentScope(
        organization_id=locked.organization_id,
        series_id=locked.series_id,
        edition_id=locked.edition_id,
        target=target,
        manage_decision=manage_decision,
        evaluated_at=evaluated_at,
        write_scope=locked,
    )


def _require_lifecycle(
    *, scope: _AssignmentScope, permitted_editions: frozenset[str]
) -> None:
    lifecycle = (
        EventEdition.objects.filter(pk=scope.edition_id)
        .values_list("lifecycle", flat=True)
        .get()
    )
    organization_lifecycle = (
        Organization.objects.filter(pk=scope.organization_id)
        .values_list("lifecycle", flat=True)
        .get()
    )
    if (
        lifecycle not in permitted_editions
        or organization_lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
    ):
        raise AssignmentLifecycleConflictError


def _receipt_for_retry(
    *, scope: _AssignmentScope, actor_id: UUID, retry_key: UUID
) -> PositionAssignmentCommandReceipt | None:
    return (
        PositionAssignmentCommandReceipt.objects.filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            actor_id=actor_id,
            retry_key=retry_key,
        )
        .order_by("id")
        .first()
    )


def _replay_result(
    *,
    receipt: PositionAssignmentCommandReceipt,
    action: str,
    request_digest: str,
) -> AssignmentCommandResult:
    if receipt.action != action or receipt.request_digest != request_digest:
        raise AssignmentRetryConflictError
    return AssignmentCommandResult(
        assignment_id=receipt.assignment_id,
        receipt_id=receipt.id,
        resulting_version=receipt.resulting_version,
        status=receipt.assignment.status,
        replayed=True,
    )


def _create_receipt(
    *,
    assignment: PositionAssignment,
    actor: Account,
    action: str,
    resulting_version: int,
    reason: str,
    retry_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    source_channel: str,
) -> PositionAssignmentCommandReceipt:
    return PositionAssignmentCommandReceipt.objects.create(
        assignment=assignment,
        organization_id=assignment.organization_id,
        edition_id=assignment.edition_id,
        position_id=assignment.position_id,
        actor=actor,
        action=action,
        resulting_version=resulting_version,
        reason=reason,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def _append_assignment_audit(
    *,
    scope: _AssignmentScope,
    actor: Account,
    assignment: PositionAssignment,
    operation: str,
    reason_code: str,
    changed_fields: tuple[str, ...],
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
) -> AuditEvent:
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition_id,
            capability_code=MANAGE_ASSIGNMENTS,
            operation=operation,
            target_type="workforce.position_assignment",
            target_id=assignment.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.manage_decision.obligations)),
            changed_fields=changed_fields,
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="workforce-restricted",
        ),
        occurred_at=scope.evaluated_at,
    )


def _publish_assignment_event(
    *,
    assignment: PositionAssignment,
    actor: Account,
    event_name: str,
    audit_event: AuditEvent,
    correlation_id: UUID,
) -> None:
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=assignment.organization_id,
            event_edition_id=assignment.edition_id,
            aggregate_type="workforce.position_assignment",
            aggregate_id=assignment.id,
            aggregate_version=assignment.command_version or 1,
            payload={
                "position_code": assignment.position.code,
                "status": assignment.status,
            },
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="workforce-restricted",
        ),
        workload_pool="core",
    )


def _position_reference(
    *,
    organization_id: UUID,
    edition_id: UUID,
    position_id: UUID,
) -> tuple[UUID, UUID] | None:
    return (
        Position.objects.filter(
            id=position_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by()
        .values_list("department_id", "id")
        .first()
    )


def _assignment_reference(
    *,
    organization_id: UUID,
    edition_id: UUID,
    assignment_id: UUID,
) -> tuple[UUID, UUID] | None:
    return (
        PositionAssignment.objects.filter(
            id=assignment_id,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .order_by()
        .values_list("position_id", "position__department_id")
        .first()
    )


def _lock_position(
    *, scope: _AssignmentScope, position_id: UUID, department_id: UUID
) -> Position:
    lock_active_department_write_target(
        scope=scope.write_scope,
        department_id=department_id,
    )
    position = (
        Position.objects.select_for_update()
        .select_related("department", "edition", "edition__series", "role_bundle")
        .filter(
            id=position_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=department_id,
        )
        .order_by()
        .first()
    )
    if position is None:
        raise AssignmentUnavailableError
    return position


def _locked_open_assignments(position: Position) -> tuple[PositionAssignment, ...]:
    assignments = tuple(
        PositionAssignment.objects.select_for_update(of=("self",))
        .filter(
            position=position,
            status__in=(
                PositionAssignment.Status.PROPOSED,
                PositionAssignment.Status.ACTIVE,
            ),
        )
        .order_by("id")[: _MAX_OPEN_ASSIGNMENTS + 1]
    )
    if len(assignments) > _MAX_OPEN_ASSIGNMENTS:
        raise AssignmentStateConflictError
    return assignments


def propose_position_assignment(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    position_id: UUID,
    account_id: UUID,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> AssignmentCommandResult:
    """Propose one known person for a Position without issuing authority.

    Parameters
    ----------
    actor : Account
        Authenticated controller proposing the assignment.
    organization_id : UUID
        Organization that owns the Position.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Exact event edition receiving the proposal.
    position_id : UUID
        Current Position for the proposed responsibility.
    account_id : UUID
        Active known person proposed for the Position.
    effective_from : datetime
        Aware intended start of the responsibility.
    expires_at : datetime | None
        Optional aware intended ending.
    reason : str
        Required organizer rationale retained with the command.
    retry_key : UUID
        Caller-owned idempotency key.
    correlation_id : UUID
        Correlation identifier shared by command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default="service"
        Registered adapter channel for audit evidence.

    Returns
    -------
    AssignmentCommandResult
        Minimized assignment, receipt, version, status, and replay evidence.

    Raises
    ------
    AssignmentUnavailableError
        If the authorized Position is unavailable in the exact scope.
    AssignmentHeadcountConflictError
        If proposed and active assignments already reserve all headcount.
    AssignmentStateConflictError
        If Position state, an existing assignment, or the bounded candidate
        projection prevents the proposal.
    AssignmentCandidateUnavailableError
        If the submitted person is not an active known candidate.
    """
    position_id = _validate_uuid(position_id, field_name="position_id")
    account_id = _validate_uuid(account_id, field_name="account_id")
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_assignment_reason(reason)
    validate_assignment_interval(
        effective_from=effective_from,
        expires_at=expires_at,
    )
    source_channel = _validate_source_channel(source_channel)
    request_digest = assignment_command_digest(
        action=PositionAssignmentCommandReceipt.Action.PROPOSED,
        payload={
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "position_id": str(position_id),
            "account_id": str(account_id),
            "effective_from": effective_from.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "reason": normalized_reason,
        },
    )
    _require_capabilities(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        capability_codes=(VIEW_STRUCTURE, MANAGE_ASSIGNMENTS, MANAGE_ROLES),
    )
    with transaction.atomic():
        scope = _lock_and_authorize_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            capability_codes=(VIEW_STRUCTURE, MANAGE_ASSIGNMENTS, MANAGE_ROLES),
        )
        _require_lifecycle(
            scope=scope,
            permitted_editions=_ASSIGNABLE_EDITION_LIFECYCLES,
        )
        replay = _receipt_for_retry(
            scope=scope,
            actor_id=actor.id,
            retry_key=retry_key,
        )
        if replay is not None:
            return _replay_result(
                receipt=replay,
                action=PositionAssignmentCommandReceipt.Action.PROPOSED,
                request_digest=request_digest,
            )
        reference = _position_reference(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            position_id=position_id,
        )
        if reference is None:
            raise AssignmentUnavailableError
        position = _lock_position(
            scope=scope,
            position_id=position_id,
            department_id=reference[0],
        )
        if position.status == Position.Status.CLOSED:
            raise AssignmentStateConflictError(
                "A closed Position cannot receive assignments."
            )
        open_assignments = _locked_open_assignments(position)
        if len(open_assignments) >= position.headcount:
            raise AssignmentHeadcountConflictError
        if any(assignment.account_id == account_id for assignment in open_assignments):
            raise AssignmentStateConflictError(
                "That person already has an open assignment for this Position."
            )
        try:
            candidate_ids = {
                candidate.account_id
                for candidate in known_assignment_candidates(position=position)
            }
        except AssignmentReadLimitExceededError as error:
            raise AssignmentStateConflictError(
                "The candidate relationship set needs operator review."
            ) from error
        if account_id not in candidate_ids:
            raise AssignmentCandidateUnavailableError
        recipient = Account.objects.filter(
            id=account_id,
            account_kind=Account.Kind.PERSON,
            is_active=True,
        ).first()
        if recipient is None:
            raise AssignmentCandidateUnavailableError
        assignment = PositionAssignment.objects.create(
            position=position,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            account=recipient,
            status=PositionAssignment.Status.PROPOSED,
            effective_from=effective_from,
            expires_at=expires_at,
            proposed_by=actor,
            reason=normalized_reason,
            command_version=1,
        )
        receipt = _create_receipt(
            assignment=assignment,
            actor=actor,
            action=PositionAssignmentCommandReceipt.Action.PROPOSED,
            resulting_version=1,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        audit_event = _append_assignment_audit(
            scope=scope,
            actor=actor,
            assignment=assignment,
            operation="workforce.position_assignment.propose",
            reason_code="assignment_proposed",
            changed_fields=("proposal", "effective_interval"),
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        _publish_assignment_event(
            assignment=assignment,
            actor=actor,
            event_name="workforce.position_assignment.proposed.v1",
            audit_event=audit_event,
            correlation_id=correlation_id,
        )
        return AssignmentCommandResult(
            assignment_id=assignment.id,
            receipt_id=receipt.id,
            resulting_version=1,
            status=assignment.status,
            replayed=False,
        )


def _lock_assignment_for_decision(
    *,
    scope: _AssignmentScope,
    assignment_id: UUID,
) -> PositionAssignment:
    reference = _assignment_reference(
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        assignment_id=assignment_id,
    )
    if reference is None:
        raise AssignmentUnavailableError
    position = _lock_position(
        scope=scope,
        position_id=reference[0],
        department_id=reference[1],
    )
    _locked_open_assignments(position)
    assignment = (
        PositionAssignment.objects.select_for_update(of=("self",))
        .select_related(
            "account",
            "position",
            "position__department",
            "position__edition",
            "position__role_bundle",
            "role_assignment",
            "participation_capacity",
            "participation_capacity__participation",
        )
        .filter(
            id=assignment_id,
            position=position,
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
        )
        .order_by()
        .first()
    )
    if assignment is None:
        raise AssignmentUnavailableError
    return assignment


def approve_position_assignment(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    assignment_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> AssignmentCommandResult:
    """Approve a proposal as a distinct current controller and issue authority.

    Parameters
    ----------
    actor : Account
        Authenticated controller making the independent decision.
    organization_id : UUID
        Organization that owns the assignment.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Exact event edition containing the assignment.
    assignment_id : UUID
        Proposed assignment to approve.
    expected_version : int
        Optimistic assignment version expected by the approver.
    reason : str
        Required approval rationale retained with the command.
    retry_key : UUID
        Caller-owned idempotency key.
    correlation_id : UUID
        Correlation identifier shared by command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default="service"
        Registered adapter channel for audit evidence.

    Returns
    -------
    AssignmentCommandResult
        Minimized activated assignment and command evidence.

    Raises
    ------
    AssignmentVersionConflictError
        If the proposal has changed since the approver read it.
    AssignmentStateConflictError
        If the assignment or Position cannot be activated.
    AssignmentAuthorizationDeniedError
        If the actor is the proposer or either controller lacks current
        authority.
    AssignmentReadinessConflictError
        If a required onboarding document is not currently approved.
    AssignmentHeadcountConflictError
        If approved headcount is no longer available.
    """
    assignment_id = _validate_uuid(assignment_id, field_name="assignment_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_assignment_reason(reason)
    source_channel = _validate_source_channel(source_channel)
    request_digest = assignment_command_digest(
        action=PositionAssignmentCommandReceipt.Action.APPROVED,
        payload={
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "assignment_id": str(assignment_id),
            "expected_version": expected_version,
            "reason": normalized_reason,
        },
    )
    _require_capabilities(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        capability_codes=(VIEW_STRUCTURE, MANAGE_ASSIGNMENTS, MANAGE_ROLES),
    )
    with transaction.atomic():
        scope = _lock_and_authorize_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            capability_codes=(VIEW_STRUCTURE, MANAGE_ASSIGNMENTS, MANAGE_ROLES),
        )
        _require_lifecycle(
            scope=scope,
            permitted_editions=_ASSIGNABLE_EDITION_LIFECYCLES,
        )
        replay = _receipt_for_retry(
            scope=scope,
            actor_id=actor.id,
            retry_key=retry_key,
        )
        if replay is not None:
            return _replay_result(
                receipt=replay,
                action=PositionAssignmentCommandReceipt.Action.APPROVED,
                request_digest=request_digest,
            )
        assignment = _lock_assignment_for_decision(
            scope=scope,
            assignment_id=assignment_id,
        )
        if assignment.command_version != expected_version:
            raise AssignmentVersionConflictError
        if assignment.status != PositionAssignment.Status.PROPOSED:
            raise AssignmentStateConflictError
        if assignment.proposed_by_id == actor.id:
            raise AssignmentAuthorizationDeniedError(
                "A different current controller must decide this proposal."
            )
        if assignment.position.status == Position.Status.CLOSED:
            raise AssignmentStateConflictError
        if not assignment_readiness(
            position=assignment.position,
            account_id=assignment.account_id,
        ).ready:
            raise AssignmentReadinessConflictError
        try:
            activated = activate_position_assignment(
                position_id=assignment.position_id,
                account=assignment.account,
                actor=assignment.proposed_by,
                approver=actor,
                effective_from=assignment.effective_from,
                expires_at=assignment.expires_at,
                reason=normalized_reason,
                correlation_id=correlation_id,
                proposed_assignment_id=assignment.id,
                assignment_command_version=expected_version + 1,
                source_channel=source_channel,
                request_id=request_id,
            )
        except AuthorizationDenied as error:
            raise AssignmentAuthorizationDeniedError from error
        except ValidationError as error:
            code = getattr(error, "code", None)
            if code == "assignment_documents_incomplete":
                raise AssignmentReadinessConflictError from error
            if code == "position_headcount_reached":
                raise AssignmentHeadcountConflictError from error
            raise AssignmentStateConflictError(str(error)) from error
        receipt = _create_receipt(
            assignment=activated,
            actor=actor,
            action=PositionAssignmentCommandReceipt.Action.APPROVED,
            resulting_version=expected_version + 1,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        return AssignmentCommandResult(
            assignment_id=activated.id,
            receipt_id=receipt.id,
            resulting_version=expected_version + 1,
            status=activated.status,
            replayed=False,
        )


def reject_position_assignment(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    assignment_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> AssignmentCommandResult:
    """Reject a proposal as a distinct current controller.

    Parameters
    ----------
    actor : Account
        Authenticated controller making the independent decision.
    organization_id : UUID
        Organization that owns the assignment.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Exact event edition containing the assignment.
    assignment_id : UUID
        Proposed assignment to reject.
    expected_version : int
        Optimistic assignment version expected by the decision maker.
    reason : str
        Required rejection rationale retained with the command.
    retry_key : UUID
        Caller-owned idempotency key.
    correlation_id : UUID
        Correlation identifier shared by command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default="service"
        Registered adapter channel for audit evidence.

    Returns
    -------
    AssignmentCommandResult
        Minimized rejected assignment and command evidence.
    """
    return _decide_without_activation(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        assignment_id=assignment_id,
        expected_version=expected_version,
        reason=reason,
        retry_key=retry_key,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )


def _decide_without_activation(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    assignment_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
) -> AssignmentCommandResult:
    assignment_id = _validate_uuid(assignment_id, field_name="assignment_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_assignment_reason(reason)
    source_channel = _validate_source_channel(source_channel)
    action = PositionAssignmentCommandReceipt.Action.REJECTED
    request_digest = assignment_command_digest(
        action=action,
        payload={
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "assignment_id": str(assignment_id),
            "expected_version": expected_version,
            "reason": normalized_reason,
        },
    )
    _require_capabilities(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        capability_codes=(VIEW_STRUCTURE, MANAGE_ASSIGNMENTS, MANAGE_ROLES),
    )
    with transaction.atomic():
        scope = _lock_and_authorize_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            capability_codes=(VIEW_STRUCTURE, MANAGE_ASSIGNMENTS, MANAGE_ROLES),
        )
        _require_lifecycle(
            scope=scope,
            permitted_editions=_CLEANUP_EDITION_LIFECYCLES,
        )
        replay = _receipt_for_retry(
            scope=scope,
            actor_id=actor.id,
            retry_key=retry_key,
        )
        if replay is not None:
            return _replay_result(
                receipt=replay,
                action=action,
                request_digest=request_digest,
            )
        assignment = _lock_assignment_for_decision(
            scope=scope,
            assignment_id=assignment_id,
        )
        if assignment.command_version != expected_version:
            raise AssignmentVersionConflictError
        if assignment.status != PositionAssignment.Status.PROPOSED:
            raise AssignmentStateConflictError
        if assignment.proposed_by_id == actor.id:
            raise AssignmentAuthorizationDeniedError(
                "A different current controller must decide this proposal."
            )
        decided_at = timezone.now()
        assignment.status = PositionAssignment.Status.REJECTED
        assignment.command_version = expected_version + 1
        assignment.decision_by = actor
        assignment.decision_at = decided_at
        assignment.decision_reason = normalized_reason
        assignment.save(
            update_fields=(
                "status",
                "command_version",
                "decision_by",
                "decision_at",
                "decision_reason",
                "updated_at",
            )
        )
        receipt = _create_receipt(
            assignment=assignment,
            actor=actor,
            action=action,
            resulting_version=expected_version + 1,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        audit_event = _append_assignment_audit(
            scope=scope,
            actor=actor,
            assignment=assignment,
            operation="workforce.position_assignment.reject",
            reason_code="assignment_rejected",
            changed_fields=("status", "decision_evidence"),
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        _publish_assignment_event(
            assignment=assignment,
            actor=actor,
            event_name="workforce.position_assignment.rejected.v1",
            audit_event=audit_event,
            correlation_id=correlation_id,
        )
        return AssignmentCommandResult(
            assignment_id=assignment.id,
            receipt_id=receipt.id,
            resulting_version=expected_version + 1,
            status=assignment.status,
            replayed=False,
        )


def _complete_assignment_capacities(
    *, assignment: PositionAssignment, ended_at: datetime
) -> None:
    capacity = assignment.participation_capacity
    if capacity is None:
        if not profile_adopts_module(
            assignment.edition.adoption_profile_code,
            "participation",
        ):
            return
        raise AssignmentStateConflictError
    participation = capacity.participation
    capacities = tuple(
        ParticipationCapacity.objects.select_for_update()
        .filter(participation=participation)
        .order_by("id")
    )
    remaining_codes: set[str] = set()
    for capacity_codes in (
        PositionAssignment.objects.filter(
            organization_id=assignment.organization_id,
            edition_id=assignment.edition_id,
            account_id=assignment.account_id,
            status=PositionAssignment.Status.ACTIVE,
        )
        .exclude(pk=assignment.pk)
        .values_list("position__capacity_codes", flat=True)
    ):
        remaining_codes.update(capacity_codes)
    specific_code = f"position.{assignment.position.code}"
    ending_codes = set(assignment.position.capacity_codes) - remaining_codes
    ending_codes.add(specific_code)
    for item in capacities:
        if item.code not in ending_codes or item.status != item.Status.ACTIVE:
            continue
        item.status = item.Status.COMPLETED
        item.ended_at = ended_at
        item.save(update_fields=("status", "ended_at", "updated_at"))


def end_position_assignment(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    assignment_id: UUID,
    expected_version: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> AssignmentCommandResult:
    """End active responsibility, authority, and unused capacities.

    Parameters
    ----------
    actor : Account
        Authenticated controller ending the assignment.
    organization_id : UUID
        Organization that owns the assignment.
    series_id : UUID
        Convention series in the persisted route chain.
    edition_id : UUID
        Exact event edition containing the assignment.
    assignment_id : UUID
        Active assignment to end.
    expected_version : int
        Optimistic assignment version expected by the controller.
    reason : str
        Required ending rationale retained with the command.
    retry_key : UUID
        Caller-owned idempotency key.
    correlation_id : UUID
        Correlation identifier shared by command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default="service"
        Registered adapter channel for audit evidence.

    Returns
    -------
    AssignmentCommandResult
        Minimized ended assignment and command evidence.

    Raises
    ------
    AssignmentVersionConflictError
        If the assignment has changed since the controller read it.
    AssignmentStateConflictError
        If the assignment or linked authority cannot be ended consistently.
    AssignmentAuthorizationDeniedError
        If current revocation authority is unavailable.
    """
    assignment_id = _validate_uuid(assignment_id, field_name="assignment_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_assignment_reason(reason)
    source_channel = _validate_source_channel(source_channel)
    action = PositionAssignmentCommandReceipt.Action.ENDED
    request_digest = assignment_command_digest(
        action=action,
        payload={
            "organization_id": str(organization_id),
            "series_id": str(series_id),
            "edition_id": str(edition_id),
            "assignment_id": str(assignment_id),
            "expected_version": expected_version,
            "reason": normalized_reason,
        },
    )
    capabilities = (VIEW_STRUCTURE, MANAGE_ASSIGNMENTS, REVOKE_AUTHORITY)
    _require_capabilities(
        actor=actor,
        organization_id=organization_id,
        series_id=series_id,
        edition_id=edition_id,
        capability_codes=capabilities,
    )
    with transaction.atomic():
        scope = _lock_and_authorize_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
            capability_codes=capabilities,
        )
        _require_lifecycle(
            scope=scope,
            permitted_editions=_CLEANUP_EDITION_LIFECYCLES,
        )
        replay = _receipt_for_retry(
            scope=scope,
            actor_id=actor.id,
            retry_key=retry_key,
        )
        if replay is not None:
            return _replay_result(
                receipt=replay,
                action=action,
                request_digest=request_digest,
            )
        assignment = _lock_assignment_for_decision(
            scope=scope,
            assignment_id=assignment_id,
        )
        if assignment.command_version != expected_version:
            raise AssignmentVersionConflictError
        if assignment.status != PositionAssignment.Status.ACTIVE:
            raise AssignmentStateConflictError
        role_assignment = assignment.role_assignment
        if role_assignment is None:
            raise AssignmentStateConflictError
        ended_at = timezone.now()
        if role_assignment.revoked_at is None:
            try:
                revoke_role_assignment(
                    actor=actor,
                    target=scope.target,  # type: ignore[arg-type]
                    assignment_id=role_assignment.id,
                    reason=normalized_reason,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    revoked_at=ended_at,
                )
            except AuthorizationDenied as error:
                raise AssignmentAuthorizationDeniedError from error
            except ValidationError as error:
                raise AssignmentStateConflictError(str(error)) from error
        _complete_assignment_capacities(
            assignment=assignment,
            ended_at=ended_at,
        )
        assignment.status = PositionAssignment.Status.ENDED
        assignment.command_version = expected_version + 1
        assignment.ended_at = ended_at
        assignment.ended_by = actor
        assignment.end_reason = normalized_reason
        assignment.save(
            update_fields=(
                "status",
                "command_version",
                "ended_at",
                "ended_by",
                "end_reason",
                "updated_at",
            )
        )
        active_count = PositionAssignment.objects.filter(
            position=assignment.position,
            status=PositionAssignment.Status.ACTIVE,
        ).count()
        next_position_status = (
            Position.Status.FILLED
            if active_count >= assignment.position.headcount
            else Position.Status.OPEN
        )
        if assignment.position.status != next_position_status:
            assignment.position.status = next_position_status
            assignment.position.save(update_fields=("status", "updated_at"))
        receipt = _create_receipt(
            assignment=assignment,
            actor=actor,
            action=action,
            resulting_version=expected_version + 1,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        audit_event = _append_assignment_audit(
            scope=scope,
            actor=actor,
            assignment=assignment,
            operation="workforce.position_assignment.end",
            reason_code="assignment_ended",
            changed_fields=(
                "status",
                "end_evidence",
                *(
                    ("participation_capacity",)
                    if assignment.participation_capacity_id is not None
                    else ()
                ),
            ),
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        _publish_assignment_event(
            assignment=assignment,
            actor=actor,
            event_name="workforce.position_assignment.ended.v1",
            audit_event=audit_event,
            correlation_id=correlation_id,
        )
        return AssignmentCommandResult(
            assignment_id=assignment.id,
            receipt_id=receipt.id,
            resulting_version=expected_version + 1,
            status=assignment.status,
            replayed=False,
        )
