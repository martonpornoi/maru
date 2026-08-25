"""Person-owned availability commands shared by browser and API adapters."""

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
from maru.authorization.policy import PolicyDecision, decide, resolve_self_target
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.availability_inputs import (
    AvailabilityWindowInput,
    availability_window_set_digest,
    keyed_availability_digest,
    normalize_availability_windows,
)
from maru.workforce.edition_write_scope import lock_workforce_edition_write_scope
from maru.workforce.models import (
    PersonAvailabilityCommandReceipt,
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    PositionAssignment,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

MANAGE_SELF_AVAILABILITY = "workforce.manage_self_availability"
_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_MAX_SOURCE_CHANNEL_LENGTH = 32
_EDITABLE_EDITION_LIFECYCLES = frozenset(
    {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
    }
)
_WITHDRAWABLE_EDITION_LIFECYCLES = _EDITABLE_EDITION_LIFECYCLES | {
    EventEdition.Lifecycle.CLOSING
}
_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_MAX_OPEN_ASSIGNMENTS = 1_024


class AvailabilityCommandError(RuntimeError):
    """Base class for stable disclosure-safe availability failures."""

    reason_code = "availability_command_failed"


class AvailabilityAuthorizationDeniedError(AvailabilityCommandError):
    """Signal absent self authority or an invalid person principal."""

    reason_code = "availability_authorization_denied"


class AvailabilityRelationshipRequiredError(AvailabilityCommandError):
    """Signal that no proposed or active assignment permits a new statement."""

    reason_code = "availability_assignment_required"


class AvailabilityLifecycleConflictError(AvailabilityCommandError):
    """Signal an organization or edition lifecycle that is read-only."""

    reason_code = "availability_lifecycle_conflict"


class AvailabilityVersionConflictError(AvailabilityCommandError):
    """Signal an optimistic plan version mismatch."""

    reason_code = "availability_version_conflict"


class AvailabilityRetryConflictError(AvailabilityCommandError):
    """Signal reuse of an idempotency key for different availability input."""

    reason_code = "availability_retry_conflict"


class AvailabilityStateConflictError(AvailabilityCommandError):
    """Signal a missing or incompatible current availability state."""

    reason_code = "availability_state_conflict"


@dataclass(frozen=True, slots=True)
class AvailabilityCommandResult:
    """Return minimized evidence for one complete-plan command.

    Attributes
    ----------
    plan_id
        Person availability aggregate changed by the command.
    receipt_id
        Immutable minimized command receipt.
    resulting_version
        Optimistic plan version after the command.
    status
        Current owner-controlled disclosure state.
    window_count
        Number of current exact periods, without their values.
    replayed
        Whether an identical retry returned prior committed evidence.
    """

    plan_id: UUID
    receipt_id: UUID
    resulting_version: int
    status: str
    window_count: int
    replayed: bool


@dataclass(frozen=True, slots=True)
class _AvailabilityScope:
    organization_id: UUID
    series_id: UUID
    edition: EventEdition
    actor: Account
    decision: PolicyDecision
    evaluated_at: datetime


def _validate_uuid(value: UUID, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationError(
            {
                field_name: ValidationError(
                    "Enter a valid UUID.",
                    code="availability_identifier_invalid",
                )
            }
        )
    return value


def _validate_expected_version(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValidationError(
            {
                "expected_version": ValidationError(
                    "Enter the current availability version, starting with zero.",
                    code="availability_expected_version_invalid",
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
                    code="availability_source_channel_invalid",
                )
            }
        )
    return value


def _route_series_id(*, organization_id: UUID, edition_id: UUID) -> UUID:
    series_id = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .order_by()
        .values_list("series_id", flat=True)
        .first()
    )
    if series_id is None:
        raise AvailabilityAuthorizationDeniedError
    return series_id


def _require_self_decision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
) -> PolicyDecision:
    if actor.pk is None or not actor.is_active:
        raise AvailabilityAuthorizationDeniedError
    target = resolve_self_target(
        principal=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    decision = decide(
        principal=actor,
        capability_code=MANAGE_SELF_AVAILABILITY,
        resource=target,
        requested_fields=frozenset({"availability"}),
        at=at,
    )
    if not decision.allowed or decision.fields != frozenset({"availability"}):
        raise AvailabilityAuthorizationDeniedError
    return decision


def authorize_person_availability_command(  # noqa: DOC502 - delegated authorization
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> PolicyDecision:
    """Authorize a self route before an adapter parses command input.

    Parameters
    ----------
    actor : Account
        Authenticated person who can only target their own record.
    organization_id : UUID
        Persisted organization route identifier.
    edition_id : UUID
        Persisted exact-edition route identifier.

    Returns
    -------
    PolicyDecision
        Allowed relationship-derived self decision.

    Raises
    ------
    AvailabilityAuthorizationDeniedError
        If route scope or current self authority is unavailable.
    """
    _route_series_id(organization_id=organization_id, edition_id=edition_id)
    return _require_self_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )


def _lock_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> _AvailabilityScope:
    series_id = _route_series_id(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    try:
        locked = lock_workforce_edition_write_scope(
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
    except ValidationError as error:
        raise AvailabilityAuthorizationDeniedError from error
    persisted_actor = Account.objects.filter(
        pk=actor.pk,
        account_kind=Account.Kind.PERSON,
        is_active=True,
    ).first()
    if persisted_actor is None:
        raise AvailabilityAuthorizationDeniedError
    evaluated_at = timezone.now()
    decision = _require_self_decision(
        actor=persisted_actor,
        organization_id=locked.organization_id,
        edition_id=locked.edition_id,
        at=evaluated_at,
    )
    edition = (
        EventEdition.objects.select_related("organization")
        .filter(
            id=locked.edition_id,
            organization_id=locked.organization_id,
            series_id=locked.series_id,
        )
        .get()
    )
    return _AvailabilityScope(
        organization_id=locked.organization_id,
        series_id=locked.series_id,
        edition=edition,
        actor=persisted_actor,
        decision=decision,
        evaluated_at=evaluated_at,
    )


def _require_lifecycle(
    *, scope: _AvailabilityScope, permitted_editions: frozenset[str]
) -> None:
    if (
        scope.edition.lifecycle not in permitted_editions
        or scope.edition.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
    ):
        raise AvailabilityLifecycleConflictError


def _lock_open_assignments(*, scope: _AvailabilityScope) -> bool:
    assignments = tuple(
        PositionAssignment.objects.select_for_update(of=("self",))
        .filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
            account_id=scope.actor.id,
            status__in=(
                PositionAssignment.Status.PROPOSED,
                PositionAssignment.Status.ACTIVE,
            ),
        )
        .order_by("id")[: _MAX_OPEN_ASSIGNMENTS + 1]
    )
    if len(assignments) > _MAX_OPEN_ASSIGNMENTS:
        raise AvailabilityStateConflictError
    return bool(assignments)


def _receipt_for_retry(
    *, scope: _AvailabilityScope, retry_key: UUID
) -> PersonAvailabilityCommandReceipt | None:
    return (
        PersonAvailabilityCommandReceipt.objects.select_related("plan")
        .filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
            actor_id=scope.actor.id,
            retry_key=retry_key,
        )
        .order_by("id")
        .first()
    )


def _replay_result(
    *, receipt: PersonAvailabilityCommandReceipt, action: str, request_digest: str
) -> AvailabilityCommandResult:
    if receipt.action != action or receipt.request_digest != request_digest:
        raise AvailabilityRetryConflictError
    return AvailabilityCommandResult(
        plan_id=receipt.plan_id,
        receipt_id=receipt.id,
        resulting_version=receipt.resulting_version,
        status=receipt.resulting_status,
        window_count=receipt.window_count,
        replayed=True,
    )


def _append_availability_audit(
    *,
    scope: _AvailabilityScope,
    plan: PersonAvailabilityPlan,
    action: str,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
) -> AuditEvent:
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor.id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition.id,
            capability_code=MANAGE_SELF_AVAILABILITY,
            operation=f"workforce.person_availability.{action}",
            target_type="workforce.person_availability_plan",
            target_id=plan.id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=f"availability_{action}",
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=("status", "current_windows"),
            safe_metadata={
                "policy_version": POLICY_VERSION,
                "target_count": plan.window_count,
            },
            retention_class="workforce-personal",
        ),
        occurred_at=scope.evaluated_at,
    )


def _publish_availability_event(
    *,
    scope: _AvailabilityScope,
    plan: PersonAvailabilityPlan,
    audit_event: AuditEvent,
    correlation_id: UUID,
) -> None:
    publish_domain_event(
        DomainEventRecord(
            event_name="workforce.person_availability.changed.v1",
            schema_version=1,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition.id,
            aggregate_type="workforce.person_availability_plan",
            aggregate_id=plan.id,
            aggregate_version=plan.command_version,
            payload={
                "status": plan.status,
                "window_count": str(plan.window_count),
            },
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=scope.actor.id,
            retention_class="workforce-personal",
        ),
        workload_pool="core",
    )


def _create_receipt(
    *,
    scope: _AvailabilityScope,
    plan: PersonAvailabilityPlan,
    action: str,
    retry_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    source_channel: str,
) -> PersonAvailabilityCommandReceipt:
    return PersonAvailabilityCommandReceipt.objects.create(
        plan=plan,
        organization_id=scope.organization_id,
        edition_id=scope.edition.id,
        actor=scope.actor,
        action=action,
        resulting_version=plan.command_version,
        resulting_status=plan.status,
        window_count=plan.window_count,
        window_set_digest=plan.window_set_digest,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def save_person_availability(  # noqa: DOC503 - composed command boundary
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    expected_version: int,
    status: str,
    windows: Sequence[AvailabilityWindowInput],
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> AvailabilityCommandResult:
    """Replace the owner's complete plan as a private draft or shared statement.

    Parameters
    ----------
    actor : Account
        Authenticated person who owns the plan.
    organization_id : UUID
        Organization that owns the exact edition.
    edition_id : UUID
        Edition receiving the availability statement.
    expected_version : int
        Current plan version, or zero when no plan exists.
    status : str
        ``draft`` or ``submitted``.
    windows : Sequence[AvailabilityWindowInput]
        Complete replacement set of aware availability periods.
    retry_key : UUID
        Caller-owned idempotency UUID.
    correlation_id : UUID
        Correlation identifier shared by command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default="service"
        Registered trusted adapter channel.

    Returns
    -------
    AvailabilityCommandResult
        Minimized resulting plan and retry evidence.

    Raises
    ------
    AvailabilityAuthorizationDeniedError
        If the actor cannot own a plan in the exact scope.
    AvailabilityRelationshipRequiredError
        If no proposed or active assignment permits writing.
    AvailabilityLifecycleConflictError
        If the organization or edition is read-only.
    AvailabilityVersionConflictError
        If the supplied plan version is stale.
    AvailabilityRetryConflictError
        If a retry key was used for different input.
    ValidationError
        If state, interval, identifier, or source input is invalid.
    """
    organization_id = _validate_uuid(organization_id, field_name="organization_id")
    edition_id = _validate_uuid(edition_id, field_name="edition_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    if status not in {
        PersonAvailabilityPlan.Status.DRAFT,
        PersonAvailabilityPlan.Status.SUBMITTED,
    }:
        raise ValidationError(
            {
                "status": ValidationError(
                    "Choose private draft or shared availability.",
                    code="availability_status_invalid",
                )
            }
        )
    authorize_person_availability_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        _require_lifecycle(
            scope=scope,
            permitted_editions=_EDITABLE_EDITION_LIFECYCLES,
        )
        if not _lock_open_assignments(scope=scope):
            raise AvailabilityRelationshipRequiredError
        normalized_windows = normalize_availability_windows(
            windows,
            starts_on=scope.edition.starts_on,
            ends_on=scope.edition.ends_on,
            time_zone=scope.edition.time_zone,
        )
        action = (
            PersonAvailabilityCommandReceipt.Action.DRAFT_SAVED
            if status == PersonAvailabilityPlan.Status.DRAFT
            else PersonAvailabilityCommandReceipt.Action.SUBMITTED
        )
        window_set_digest = availability_window_set_digest(normalized_windows)
        request_digest = keyed_availability_digest(
            {
                "action": action,
                "organization_id": str(scope.organization_id),
                "edition_id": str(scope.edition.id),
                "expected_version": expected_version,
                "status": status,
                "time_zone": scope.edition.time_zone,
                "window_set_digest": window_set_digest,
                "window_count": len(normalized_windows),
            }
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _replay_result(
                receipt=replay,
                action=action,
                request_digest=request_digest,
            )
        plan = (
            PersonAvailabilityPlan.objects.select_for_update()
            .filter(
                organization_id=scope.organization_id,
                edition_id=scope.edition.id,
                account_id=scope.actor.id,
            )
            .first()
        )
        current_version = plan.command_version if plan is not None else 0
        if current_version != expected_version:
            raise AvailabilityVersionConflictError
        resulting_version = current_version + 1
        submitted_at = (
            scope.evaluated_at
            if status == PersonAvailabilityPlan.Status.SUBMITTED
            else None
        )
        if plan is None:
            plan = PersonAvailabilityPlan.objects.create(
                organization_id=scope.organization_id,
                edition=scope.edition,
                account=scope.actor,
                status=status,
                time_zone=scope.edition.time_zone,
                command_version=resulting_version,
                window_count=len(normalized_windows),
                window_set_digest=window_set_digest,
                submitted_at=submitted_at,
                withdrawn_at=None,
            )
        else:
            plan.status = status
            plan.time_zone = scope.edition.time_zone
            plan.command_version = resulting_version
            plan.window_count = len(normalized_windows)
            plan.window_set_digest = window_set_digest
            plan.submitted_at = submitted_at
            plan.withdrawn_at = None
            plan.save()
        PersonAvailabilityWindow.objects.filter(plan=plan).delete()
        PersonAvailabilityWindow.objects.bulk_create(
            [
                PersonAvailabilityWindow(
                    plan=plan,
                    starts_at=window.starts_at,
                    ends_at=window.ends_at,
                    preference=window.preference,
                    created_by_version=resulting_version,
                )
                for window in normalized_windows
            ]
        )
        receipt = _create_receipt(
            scope=scope,
            plan=plan,
            action=action,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        audit_event = _append_availability_audit(
            scope=scope,
            plan=plan,
            action=action,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        _publish_availability_event(
            scope=scope,
            plan=plan,
            audit_event=audit_event,
            correlation_id=correlation_id,
        )
        return AvailabilityCommandResult(
            plan_id=plan.id,
            receipt_id=receipt.id,
            resulting_version=resulting_version,
            status=plan.status,
            window_count=plan.window_count,
            replayed=False,
        )


def withdraw_person_availability(  # noqa: DOC503 - composed command boundary
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    expected_version: int,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> AvailabilityCommandResult:
    """Withdraw a plan and immediately remove every current exact period.

    Parameters
    ----------
    actor : Account
        Authenticated person who owns the plan.
    organization_id : UUID
        Organization that owns the exact edition.
    edition_id : UUID
        Exact edition containing the plan.
    expected_version : int
        Current optimistic plan version.
    retry_key : UUID
        Caller-owned idempotency UUID.
    correlation_id : UUID
        Correlation identifier shared by command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default="service"
        Registered trusted adapter channel.

    Returns
    -------
    AvailabilityCommandResult
        Minimized withdrawn-plan evidence.

    Raises
    ------
    AvailabilityAuthorizationDeniedError
        If the actor cannot own the exact plan scope.
    AvailabilityLifecycleConflictError
        If the edition can no longer accept withdrawal.
    AvailabilityStateConflictError
        If no current plan exists or it was already withdrawn.
    AvailabilityVersionConflictError
        If the supplied plan version is stale.
    AvailabilityRetryConflictError
        If a retry key was used for different input.
    ValidationError
        If identifier, version, or source input is invalid.
    """
    organization_id = _validate_uuid(organization_id, field_name="organization_id")
    edition_id = _validate_uuid(edition_id, field_name="edition_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    authorize_person_availability_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        _require_lifecycle(
            scope=scope,
            permitted_editions=_WITHDRAWABLE_EDITION_LIFECYCLES,
        )
        _lock_open_assignments(scope=scope)
        action = PersonAvailabilityCommandReceipt.Action.WITHDRAWN
        empty_digest = availability_window_set_digest(())
        request_digest = keyed_availability_digest(
            {
                "action": action,
                "organization_id": str(scope.organization_id),
                "edition_id": str(scope.edition.id),
                "expected_version": expected_version,
            }
        )
        replay = _receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            return _replay_result(
                receipt=replay,
                action=action,
                request_digest=request_digest,
            )
        plan = (
            PersonAvailabilityPlan.objects.select_for_update()
            .filter(
                organization_id=scope.organization_id,
                edition_id=scope.edition.id,
                account_id=scope.actor.id,
            )
            .first()
        )
        if plan is None or plan.status == PersonAvailabilityPlan.Status.WITHDRAWN:
            raise AvailabilityStateConflictError
        if plan.command_version != expected_version:
            raise AvailabilityVersionConflictError
        resulting_version = plan.command_version + 1
        plan.status = PersonAvailabilityPlan.Status.WITHDRAWN
        plan.time_zone = scope.edition.time_zone
        plan.command_version = resulting_version
        plan.window_count = 0
        plan.window_set_digest = empty_digest
        plan.submitted_at = None
        plan.withdrawn_at = scope.evaluated_at
        plan.save()
        PersonAvailabilityWindow.objects.filter(plan=plan).delete()
        receipt = _create_receipt(
            scope=scope,
            plan=plan,
            action=action,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            source_channel=source_channel,
        )
        audit_event = _append_availability_audit(
            scope=scope,
            plan=plan,
            action=action,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )
        _publish_availability_event(
            scope=scope,
            plan=plan,
            audit_event=audit_event,
            correlation_id=correlation_id,
        )
        return AvailabilityCommandResult(
            plan_id=plan.id,
            receipt_id=receipt.id,
            resulting_version=resulting_version,
            status=plan.status,
            window_count=0,
            replayed=False,
        )
