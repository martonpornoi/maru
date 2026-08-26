"""Audited Shift-demand and commitment commands shared by every adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide,
    resolve_edition_target,
    resolve_self_target,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.edition_write_scope import (
    LockedWorkforceEditionWriteScope,
    lock_active_department_write_target,
    lock_workforce_edition_write_scope,
)
from maru.workforce.models import (
    PersonAvailabilityPlan,
    PersonAvailabilityWindow,
    Position,
    PositionAssignment,
    ShiftCommitment,
    ShiftCommitmentCommandReceipt,
    ShiftDemand,
    ShiftDemandCommandReceipt,
)
from maru.workforce.shift_inputs import (
    MAX_SHIFT_BRIEFING_LENGTH,
    MAX_SHIFT_LOCATION_LENGTH,
    MAX_SHIFT_SUPERVISION_LENGTH,
    MAX_SHIFT_TITLE_LENGTH,
    normalize_shift_interval,
    normalize_shift_reason,
    normalize_shift_text,
    shift_command_digest,
    validate_shift_numbers,
)

if TYPE_CHECKING:
    from datetime import datetime

VIEW_SHIFTS = "workforce.view_shifts"
MANAGE_SHIFTS = "workforce.manage_shifts"
MANAGE_SELF_SHIFTS = "workforce.manage_self_shifts"
_SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
_MAX_SOURCE_CHANNEL_LENGTH = 32
_PLANNING_EDITION_LIFECYCLES = frozenset(
    {
        EventEdition.Lifecycle.DRAFT,
        EventEdition.Lifecycle.PREPARING,
        EventEdition.Lifecycle.READY,
        EventEdition.Lifecycle.LIVE,
    }
)
_CLEANUP_EDITION_LIFECYCLES = _PLANNING_EDITION_LIFECYCLES | {
    EventEdition.Lifecycle.CLOSING
}
_EDITABLE_ORGANIZATION_LIFECYCLES = frozenset(
    {Organization.Lifecycle.DRAFT, Organization.Lifecycle.ACTIVE}
)
_ACTIVE_COMMITMENT_STATES = (
    ShiftCommitment.Status.CLAIMED,
    ShiftCommitment.Status.CONFIRMED,
)
_MAX_SHIFT_COMMITMENTS = 1_024
_SELF_CLAIM_REASON = "The person claimed this published suitable Shift."
_SELF_WITHDRAW_REASON = "The person withdrew their own open Shift commitment."


class ShiftCommandError(RuntimeError):
    """Base class for stable, disclosure-safe Shift command failures."""

    reason_code = "shift_command_failed"


class ShiftAuthorizationDeniedError(ShiftCommandError):
    """Signal absent current organizer or person-owned authority."""

    reason_code = "shift_authorization_denied"


class ShiftUnavailableError(ShiftCommandError):
    """Signal a missing, mismatched, or undisclosable Shift target."""

    reason_code = "shift_unavailable"


class ShiftLifecycleConflictError(ShiftCommandError):
    """Signal an organization or edition lifecycle that is read-only."""

    reason_code = "shift_lifecycle_conflict"


class ShiftStateConflictError(ShiftCommandError):
    """Signal an incompatible demand or commitment lifecycle state."""

    reason_code = "shift_state_conflict"


class ShiftVersionConflictError(ShiftCommandError):
    """Signal an optimistic Shift command-version mismatch."""

    reason_code = "shift_version_conflict"


class ShiftRetryConflictError(ShiftCommandError):
    """Signal reuse of an idempotency key for different Shift input."""

    reason_code = "shift_retry_conflict"


class ShiftQualificationConflictError(ShiftCommandError):
    """Signal absence of a current exact Position assignment."""

    reason_code = "shift_qualification_conflict"


class ShiftAvailabilityConflictError(ShiftCommandError):
    """Signal that current shared Availability does not cover the Shift."""

    reason_code = "shift_availability_conflict"


class ShiftCapacityConflictError(ShiftCommandError):
    """Signal exhaustion or underfill of required Shift coverage."""

    reason_code = "shift_capacity_conflict"


class ShiftOverlapConflictError(ShiftCommandError):
    """Signal overlap with work or required post-shift rest."""

    reason_code = "shift_overlap_conflict"


@dataclass(frozen=True, slots=True)
class ShiftDemandCommandResult:
    """Return minimized evidence for one demand command.

    Attributes
    ----------
    demand_id : UUID
        Governed Shift demand changed by the command.
    receipt_id : UUID
        Immutable command receipt written atomically with the demand.
    resulting_version : int
        Optimistic demand version after the command.
    status : str
        Demand lifecycle state after the command.
    replayed : bool
        Whether an identical idempotent retry returned existing evidence.
    """

    demand_id: UUID
    receipt_id: UUID
    resulting_version: int
    status: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class ShiftCommitmentCommandResult:
    """Return minimized evidence for one commitment command.

    Attributes
    ----------
    commitment_id : UUID
        Governed person commitment changed by the command.
    demand_id : UUID
        Shift demand that owns the commitment.
    receipt_id : UUID
        Immutable command receipt written atomically with the commitment.
    resulting_version : int
        Optimistic commitment version after the command.
    status : str
        Commitment lifecycle state after the command.
    replayed : bool
        Whether an identical idempotent retry returned existing evidence.
    """

    commitment_id: UUID
    demand_id: UUID
    receipt_id: UUID
    resulting_version: int
    status: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class _OrganizerScope:
    """Current, locked, exact-edition organizer command scope."""

    organization_id: UUID
    series_id: UUID
    edition: EventEdition
    actor: Account
    decision: PolicyDecision
    evaluated_at: datetime
    write_scope: LockedWorkforceEditionWriteScope


@dataclass(frozen=True, slots=True)
class _SelfScope:
    """Current, locked, exact-edition person-owned command scope."""

    organization_id: UUID
    series_id: UUID
    edition: EventEdition
    actor: Account
    decision: PolicyDecision
    evaluated_at: datetime
    write_scope: LockedWorkforceEditionWriteScope


def _validate_uuid(value: UUID, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise ValidationError(
            {
                field_name: ValidationError(
                    "Enter a valid UUID.",
                    code="shift_identifier_invalid",
                )
            }
        )
    return value


def _validate_expected_version(value: int, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or value < minimum:
        raise ValidationError(
            {
                "expected_version": ValidationError(
                    f"Enter a Shift version of {minimum} or greater.",
                    code="shift_expected_version_invalid",
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
                    code="shift_source_channel_invalid",
                )
            }
        )
    return value


def _edition_series_id(*, organization_id: UUID, edition_id: UUID) -> UUID:
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
        raise ShiftAuthorizationDeniedError
    return series_id


def _require_organizer_decision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
    manage: bool,
) -> PolicyDecision:
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if actor.pk is None or not actor.is_active or target is None:
        raise ShiftAuthorizationDeniedError
    view_decision = decide(
        principal=actor,
        capability_code=VIEW_SHIFTS,
        resource=target,
        at=at,
    )
    if not view_decision.allowed:
        raise ShiftAuthorizationDeniedError
    if not manage:
        return view_decision
    manage_decision = decide(
        principal=actor,
        capability_code=MANAGE_SHIFTS,
        resource=target,
        at=at,
    )
    if not manage_decision.allowed:
        raise ShiftAuthorizationDeniedError
    return manage_decision


def _require_self_decision(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    at: datetime | None = None,
) -> PolicyDecision:
    target = resolve_self_target(
        principal=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    if actor.pk is None or not actor.is_active or target is None:
        raise ShiftAuthorizationDeniedError
    decision = decide(
        principal=actor,
        capability_code=MANAGE_SELF_SHIFTS,
        resource=target,
        requested_fields=frozenset({"shifts"}),
        at=at,
    )
    if not decision.allowed or decision.fields != frozenset({"shifts"}):
        raise ShiftAuthorizationDeniedError
    return decision


def authorize_shift_organizer_command(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    """Authorize an organizer route before its adapter parses private input.

    Parameters
    ----------
    actor : Account
        Authenticated organizer candidate.
    organization_id : UUID
        Exact organization scope from the route.
    edition_id : UUID
        Exact edition scope from the route.

    Returns
    -------
    PolicyDecision
        Fresh allowed Shift-management decision.
    """
    _edition_series_id(organization_id=organization_id, edition_id=edition_id)
    return _require_organizer_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        manage=True,
    )


def authorize_shift_self_command(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> PolicyDecision:
    """Authorize a person-owned route before its adapter parses command input.

    Parameters
    ----------
    actor : Account
        Authenticated person candidate.
    organization_id : UUID
        Exact organization scope from the route.
    edition_id : UUID
        Exact edition scope from the route.

    Returns
    -------
    PolicyDecision
        Fresh allowed self-service Shift decision.
    """
    _edition_series_id(organization_id=organization_id, edition_id=edition_id)
    return _require_self_decision(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )


def _lock_organizer_scope(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> _OrganizerScope:
    try:
        locked = lock_workforce_edition_write_scope(
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
    except ValidationError as error:
        raise ShiftAuthorizationDeniedError from error
    persisted_actor = Account.objects.filter(pk=actor.pk, is_active=True).first()
    if persisted_actor is None:
        raise ShiftAuthorizationDeniedError
    evaluated_at = timezone.now()
    decision = _require_organizer_decision(
        actor=persisted_actor,
        organization_id=locked.organization_id,
        edition_id=locked.edition_id,
        at=evaluated_at,
        manage=True,
    )
    edition = EventEdition.objects.select_related("organization").get(
        id=locked.edition_id,
        organization_id=locked.organization_id,
        series_id=locked.series_id,
    )
    return _OrganizerScope(
        organization_id=locked.organization_id,
        series_id=locked.series_id,
        edition=edition,
        actor=persisted_actor,
        decision=decision,
        evaluated_at=evaluated_at,
        write_scope=locked,
    )


def _lock_self_scope(
    *, actor: Account, organization_id: UUID, edition_id: UUID
) -> _SelfScope:
    series_id = _edition_series_id(
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
        raise ShiftAuthorizationDeniedError from error
    persisted_actor = Account.objects.filter(
        pk=actor.pk,
        account_kind=Account.Kind.PERSON,
        is_active=True,
    ).first()
    if persisted_actor is None:
        raise ShiftAuthorizationDeniedError
    evaluated_at = timezone.now()
    decision = _require_self_decision(
        actor=persisted_actor,
        organization_id=locked.organization_id,
        edition_id=locked.edition_id,
        at=evaluated_at,
    )
    edition = EventEdition.objects.select_related("organization").get(
        id=locked.edition_id,
        organization_id=locked.organization_id,
        series_id=locked.series_id,
    )
    return _SelfScope(
        organization_id=locked.organization_id,
        series_id=locked.series_id,
        edition=edition,
        actor=persisted_actor,
        decision=decision,
        evaluated_at=evaluated_at,
        write_scope=locked,
    )


def _require_lifecycle(
    *, edition: EventEdition, permitted_editions: frozenset[str]
) -> None:
    if (
        edition.lifecycle not in permitted_editions
        or edition.organization.lifecycle not in _EDITABLE_ORGANIZATION_LIFECYCLES
    ):
        raise ShiftLifecycleConflictError


def _lock_position(*, scope: _OrganizerScope, position_id: UUID) -> Position:
    reference = (
        Position.objects.filter(
            id=position_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
        )
        .order_by()
        .values_list("department_id", flat=True)
        .first()
    )
    if reference is None:
        raise ShiftUnavailableError
    lock_active_department_write_target(
        scope=scope.write_scope,
        department_id=reference,
    )
    position = (
        Position.objects.select_for_update()
        .select_related("department")
        .filter(
            id=position_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
        )
        .order_by()
        .first()
    )
    if position is None or position.status == Position.Status.CLOSED:
        raise ShiftStateConflictError
    return position


def _lock_demand(
    *, scope: _OrganizerScope | _SelfScope, demand_id: UUID
) -> ShiftDemand:
    department_id = (
        ShiftDemand.objects.filter(
            id=demand_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
        )
        .order_by()
        .values_list("position__department_id", flat=True)
        .first()
    )
    if department_id is None:
        raise ShiftUnavailableError
    lock_active_department_write_target(
        scope=scope.write_scope,
        department_id=department_id,
    )
    demand = (
        ShiftDemand.objects.select_for_update()
        .select_related("position", "position__department")
        .filter(
            id=demand_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
        )
        .order_by()
        .first()
    )
    if demand is None:
        raise ShiftUnavailableError
    return demand


def _demand_receipt_for_retry(
    *, scope: _OrganizerScope, retry_key: UUID
) -> ShiftDemandCommandReceipt | None:
    return (
        ShiftDemandCommandReceipt.objects.select_related("demand")
        .filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
            actor_id=scope.actor.id,
            retry_key=retry_key,
        )
        .order_by("id")
        .first()
    )


def _commitment_receipt_for_retry(
    *, scope: _OrganizerScope | _SelfScope, retry_key: UUID
) -> ShiftCommitmentCommandReceipt | None:
    return (
        ShiftCommitmentCommandReceipt.objects.select_related("commitment")
        .filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
            actor_id=scope.actor.id,
            retry_key=retry_key,
        )
        .order_by("id")
        .first()
    )


def _demand_result(
    *, receipt: ShiftDemandCommandReceipt, replayed: bool
) -> ShiftDemandCommandResult:
    return ShiftDemandCommandResult(
        demand_id=receipt.demand_id,
        receipt_id=receipt.id,
        resulting_version=receipt.resulting_version,
        status=receipt.resulting_status,
        replayed=replayed,
    )


def _commitment_result(
    *, receipt: ShiftCommitmentCommandReceipt, replayed: bool
) -> ShiftCommitmentCommandResult:
    return ShiftCommitmentCommandResult(
        commitment_id=receipt.commitment_id,
        demand_id=receipt.demand_id,
        receipt_id=receipt.id,
        resulting_version=receipt.resulting_version,
        status=receipt.resulting_status,
        replayed=replayed,
    )


def _create_demand_receipt(
    *,
    scope: _OrganizerScope,
    demand: ShiftDemand,
    action: str,
    reason: str,
    retry_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    source_channel: str,
) -> ShiftDemandCommandReceipt:
    return ShiftDemandCommandReceipt.objects.create(
        demand=demand,
        organization_id=scope.organization_id,
        edition=scope.edition,
        actor=scope.actor,
        action=action,
        resulting_version=demand.command_version,
        resulting_status=demand.status,
        reason=reason,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def _create_commitment_receipt(
    *,
    scope: _OrganizerScope | _SelfScope,
    commitment: ShiftCommitment,
    action: str,
    reason: str,
    retry_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    source_channel: str,
) -> ShiftCommitmentCommandReceipt:
    return ShiftCommitmentCommandReceipt.objects.create(
        commitment=commitment,
        demand_id=commitment.demand_id,
        organization_id=scope.organization_id,
        edition=scope.edition,
        actor=scope.actor,
        action=action,
        resulting_version=commitment.command_version,
        resulting_status=commitment.status,
        reason=reason,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )


def _append_shift_audit(
    *,
    scope: _OrganizerScope | _SelfScope,
    target_type: str,
    target_id: UUID,
    capability_code: str,
    operation: str,
    reason_code: str,
    changed_fields: tuple[str, ...],
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    target_count: int | None = None,
) -> AuditEvent:
    safe_metadata: dict[str, object] = {"policy_version": POLICY_VERSION}
    if target_count is not None:
        safe_metadata["target_count"] = target_count
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=scope.actor.id,
            principal_context_id=None,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition.id,
            capability_code=capability_code,
            operation=operation,
            target_type=target_type,
            target_id=target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=request_id or correlation_id,
            source_channel=source_channel,
            obligations=tuple(sorted(scope.decision.obligations)),
            changed_fields=changed_fields,
            safe_metadata=safe_metadata,
            retention_class=(
                "workforce-personal"
                if capability_code == MANAGE_SELF_SHIFTS
                else "workforce-restricted"
            ),
        ),
        occurred_at=scope.evaluated_at,
    )


def _publish_shift_event(
    *,
    scope: _OrganizerScope | _SelfScope,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    event_name: str,
    status: str,
    audit_event: AuditEvent,
    correlation_id: UUID,
) -> None:
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=scope.organization_id,
            event_edition_id=scope.edition.id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            payload={"status": status},
            correlation_id=correlation_id,
            causation_id=audit_event.id,
            actor_kind="account",
            actor_id=scope.actor.id,
            retention_class="workforce-restricted",
        ),
        workload_pool="core",
    )


def _record_demand_change(
    *,
    scope: _OrganizerScope,
    demand: ShiftDemand,
    action: str,
    reason: str,
    retry_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    changed_fields: tuple[str, ...],
) -> ShiftDemandCommandResult:
    receipt = _create_demand_receipt(
        scope=scope,
        demand=demand,
        action=action,
        reason=reason,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    audit_event = _append_shift_audit(
        scope=scope,
        target_type="workforce.shift_demand",
        target_id=demand.id,
        capability_code=MANAGE_SHIFTS,
        operation=f"workforce.shift_demand.{action}",
        reason_code=f"shift_demand_{action}",
        changed_fields=changed_fields,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )
    _publish_shift_event(
        scope=scope,
        aggregate_type="workforce.shift_demand",
        aggregate_id=demand.id,
        aggregate_version=demand.command_version,
        event_name="workforce.shift_demand.changed.v1",
        status=demand.status,
        audit_event=audit_event,
        correlation_id=correlation_id,
    )
    return _demand_result(receipt=receipt, replayed=False)


def _record_commitment_change(
    *,
    scope: _OrganizerScope | _SelfScope,
    commitment: ShiftCommitment,
    action: str,
    reason: str,
    retry_key: UUID,
    request_digest: str,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    changed_fields: tuple[str, ...],
    capability_code: str,
) -> ShiftCommitmentCommandResult:
    receipt = _create_commitment_receipt(
        scope=scope,
        commitment=commitment,
        action=action,
        reason=reason,
        retry_key=retry_key,
        request_digest=request_digest,
        correlation_id=correlation_id,
        source_channel=source_channel,
    )
    audit_event = _append_shift_audit(
        scope=scope,
        target_type="workforce.shift_commitment",
        target_id=commitment.id,
        capability_code=capability_code,
        operation=f"workforce.shift_commitment.{action}",
        reason_code=f"shift_commitment_{action}",
        changed_fields=changed_fields,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
    )
    _publish_shift_event(
        scope=scope,
        aggregate_type="workforce.shift_commitment",
        aggregate_id=commitment.id,
        aggregate_version=commitment.command_version,
        event_name="workforce.shift_commitment.changed.v1",
        status=commitment.status,
        audit_event=audit_event,
        correlation_id=correlation_id,
    )
    return _commitment_result(receipt=receipt, replayed=False)


def _normalize_demand_fields(
    *,
    scope: _OrganizerScope,
    title: str,
    location_label: str,
    briefing: str,
    supervision_note: str,
    starts_at: datetime,
    ends_at: datetime,
    required_headcount: int,
    break_minutes: int,
    minimum_rest_minutes: int,
) -> dict[str, object]:
    normalized_start, normalized_end = normalize_shift_interval(
        starts_at=starts_at,
        ends_at=ends_at,
        starts_on=scope.edition.starts_on,
        ends_on=scope.edition.ends_on,
        zone=ZoneInfo(scope.edition.time_zone),
    )
    validate_shift_numbers(
        required_headcount=required_headcount,
        break_minutes=break_minutes,
        minimum_rest_minutes=minimum_rest_minutes,
        starts_at=normalized_start,
        ends_at=normalized_end,
    )
    return {
        "title": normalize_shift_text(
            title,
            field_name="title",
            maximum_length=MAX_SHIFT_TITLE_LENGTH,
        ),
        "location_label": normalize_shift_text(
            location_label,
            field_name="location_label",
            maximum_length=MAX_SHIFT_LOCATION_LENGTH,
        ),
        "briefing": normalize_shift_text(
            briefing,
            field_name="briefing",
            maximum_length=MAX_SHIFT_BRIEFING_LENGTH,
        ),
        "supervision_note": normalize_shift_text(
            supervision_note,
            field_name="supervision_note",
            maximum_length=MAX_SHIFT_SUPERVISION_LENGTH,
            required=False,
        ),
        "starts_at": normalized_start,
        "ends_at": normalized_end,
        "required_headcount": required_headcount,
        "break_minutes": break_minutes,
        "minimum_rest_minutes": minimum_rest_minutes,
    }


def create_shift_demand(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    position_id: UUID,
    title: str,
    location_label: str,
    briefing: str,
    supervision_note: str,
    starts_at: datetime,
    ends_at: datetime,
    required_headcount: int,
    break_minutes: int,
    minimum_rest_minutes: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> ShiftDemandCommandResult:
    """Create a reasoned draft Shift for one current Position.

    Parameters
    ----------
    actor : Account
        Authenticated organizer performing the command.
    organization_id : UUID
        Exact owning organization.
    series_id : UUID
        Exact owning convention series.
    edition_id : UUID
        Exact edition planning scope.
    position_id : UUID
        Active Position for which work is required.
    title : str
        Person-facing Shift name.
    location_label : str
        Person-facing reporting place.
    briefing : str
        Operational work instructions.
    supervision_note : str
        Optional supervision or handover instructions.
    starts_at : datetime
        Inclusive aware work start.
    ends_at : datetime
        Exclusive aware work end.
    required_headcount : int
        Requested accountable coverage.
    break_minutes : int
        Planned break within the work interval.
    minimum_rest_minutes : int
        Required blocked rest after the work interval.
    reason : str
        Retained organizer planning rationale.
    retry_key : UUID
        Actor-and-edition idempotency key.
    correlation_id : UUID
        Correlation identifier for command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default='service'
        Registered trusted adapter channel.

    Returns
    -------
    ShiftDemandCommandResult
        Created demand identity, version, state, receipt, and replay marker.

    Raises
    ------
    ShiftRetryConflictError
        If the retry key was already used for different command input.
    """
    position_id = _validate_uuid(position_id, field_name="position_id")
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_shift_reason(reason)
    source_channel = _validate_source_channel(source_channel)
    authorize_shift_organizer_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_organizer_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_lifecycle(
            edition=scope.edition,
            permitted_editions=_PLANNING_EDITION_LIFECYCLES,
        )
        fields = _normalize_demand_fields(
            scope=scope,
            title=title,
            location_label=location_label,
            briefing=briefing,
            supervision_note=supervision_note,
            starts_at=starts_at,
            ends_at=ends_at,
            required_headcount=required_headcount,
            break_minutes=break_minutes,
            minimum_rest_minutes=minimum_rest_minutes,
        )
        request_digest = shift_command_digest(
            action=ShiftDemandCommandReceipt.Action.CREATED,
            payload={
                "organization_id": str(scope.organization_id),
                "edition_id": str(scope.edition.id),
                "position_id": str(position_id),
                **{
                    key: value.isoformat() if hasattr(value, "isoformat") else value
                    for key, value in fields.items()
                },
                "reason": normalized_reason,
            },
        )
        replay = _demand_receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            if (
                replay.action != ShiftDemandCommandReceipt.Action.CREATED
                or replay.request_digest != request_digest
            ):
                raise ShiftRetryConflictError
            return _demand_result(receipt=replay, replayed=True)
        position = _lock_position(scope=scope, position_id=position_id)
        demand = ShiftDemand.objects.create(
            organization_id=scope.organization_id,
            edition=scope.edition,
            position=position,
            status=ShiftDemand.Status.DRAFT,
            command_version=1,
            created_by=scope.actor,
            **fields,
        )
        return _record_demand_change(
            scope=scope,
            demand=demand,
            action=ShiftDemandCommandReceipt.Action.CREATED,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            changed_fields=("demand", "status"),
        )


def update_shift_demand(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    demand_id: UUID,
    expected_version: int,
    title: str,
    location_label: str,
    briefing: str,
    supervision_note: str,
    starts_at: datetime,
    ends_at: datetime,
    required_headcount: int,
    break_minutes: int,
    minimum_rest_minutes: int,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> ShiftDemandCommandResult:
    """Replace editable fields on an unpublished Shift draft.

    Parameters
    ----------
    actor : Account
        Authenticated organizer performing the command.
    organization_id : UUID
        Exact owning organization.
    series_id : UUID
        Exact owning convention series.
    edition_id : UUID
        Exact edition planning scope.
    demand_id : UUID
        Draft demand to replace.
    expected_version : int
        Optimistic current demand version.
    title : str
        Person-facing Shift name.
    location_label : str
        Person-facing reporting place.
    briefing : str
        Operational work instructions.
    supervision_note : str
        Optional supervision or handover instructions.
    starts_at : datetime
        Inclusive aware work start.
    ends_at : datetime
        Exclusive aware work end.
    required_headcount : int
        Requested accountable coverage.
    break_minutes : int
        Planned break within the work interval.
    minimum_rest_minutes : int
        Required blocked rest after the work interval.
    reason : str
        Retained organizer change rationale.
    retry_key : UUID
        Actor-and-edition idempotency key.
    correlation_id : UUID
        Correlation identifier for command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default='service'
        Registered trusted adapter channel.

    Returns
    -------
    ShiftDemandCommandResult
        Updated demand identity, version, state, receipt, and replay marker.

    Raises
    ------
    ShiftRetryConflictError
        If the retry key was already used for different command input.
    ShiftStateConflictError
        If the demand is no longer an editable draft.
    ShiftVersionConflictError
        If the optimistic version is stale.
    """
    demand_id = _validate_uuid(demand_id, field_name="demand_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_shift_reason(reason)
    source_channel = _validate_source_channel(source_channel)
    authorize_shift_organizer_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_organizer_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_lifecycle(
            edition=scope.edition,
            permitted_editions=_PLANNING_EDITION_LIFECYCLES,
        )
        fields = _normalize_demand_fields(
            scope=scope,
            title=title,
            location_label=location_label,
            briefing=briefing,
            supervision_note=supervision_note,
            starts_at=starts_at,
            ends_at=ends_at,
            required_headcount=required_headcount,
            break_minutes=break_minutes,
            minimum_rest_minutes=minimum_rest_minutes,
        )
        request_digest = shift_command_digest(
            action=ShiftDemandCommandReceipt.Action.UPDATED,
            payload={
                "demand_id": str(demand_id),
                "expected_version": expected_version,
                **{
                    key: value.isoformat() if hasattr(value, "isoformat") else value
                    for key, value in fields.items()
                },
                "reason": normalized_reason,
            },
        )
        replay = _demand_receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            if (
                replay.action != ShiftDemandCommandReceipt.Action.UPDATED
                or replay.request_digest != request_digest
            ):
                raise ShiftRetryConflictError
            return _demand_result(receipt=replay, replayed=True)
        demand = _lock_demand(scope=scope, demand_id=demand_id)
        if demand.command_version != expected_version:
            raise ShiftVersionConflictError
        if demand.status != ShiftDemand.Status.DRAFT:
            raise ShiftStateConflictError
        if demand.commitments.exists():
            raise ShiftStateConflictError
        for field_name, value in fields.items():
            setattr(demand, field_name, value)
        demand.command_version += 1
        demand.save()
        return _record_demand_change(
            scope=scope,
            demand=demand,
            action=ShiftDemandCommandReceipt.Action.UPDATED,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            changed_fields=("demand",),
        )


def _locked_commitments(demand: ShiftDemand) -> tuple[ShiftCommitment, ...]:
    commitments = tuple(
        ShiftCommitment.objects.select_for_update()
        .select_related("position_assignment", "availability_plan")
        .filter(demand=demand)
        .order_by("id")[: _MAX_SHIFT_COMMITMENTS + 1]
    )
    if len(commitments) > _MAX_SHIFT_COMMITMENTS:
        raise ShiftStateConflictError
    return commitments


def _current_availability(
    *, scope: _OrganizerScope | _SelfScope, demand: ShiftDemand, account_id: UUID
) -> tuple[PersonAvailabilityPlan, str]:
    plan = (
        PersonAvailabilityPlan.objects.select_for_update()
        .filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
            account_id=account_id,
            status=PersonAvailabilityPlan.Status.SUBMITTED,
        )
        .order_by()
        .first()
    )
    if plan is None:
        raise ShiftAvailabilityConflictError
    covering = tuple(
        PersonAvailabilityWindow.objects.select_for_update()
        .filter(
            plan=plan,
            created_by_version=plan.command_version,
            starts_at__lte=demand.starts_at,
            ends_at__gte=demand.ends_at,
        )
        .order_by("preference", "id")[:2]
    )
    if len(covering) != 1:
        raise ShiftAvailabilityConflictError
    return plan, covering[0].preference


def _active_assignment(
    *, scope: _OrganizerScope | _SelfScope, demand: ShiftDemand, account_id: UUID
) -> PositionAssignment:
    assignments = tuple(
        PositionAssignment.objects.select_for_update()
        .filter(
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
            position_id=demand.position_id,
            account_id=account_id,
            status=PositionAssignment.Status.ACTIVE,
            effective_from__lte=demand.starts_at,
        )
        .filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gte=demand.ends_at)
        )
        .order_by("id")[:2]
    )
    if len(assignments) != 1:
        raise ShiftQualificationConflictError
    return assignments[0]


def _require_no_overlap(
    *, account_id: UUID, demand: ShiftDemand, exclude_id: UUID | None = None
) -> None:
    rest_end = demand.ends_at + timedelta(minutes=demand.minimum_rest_minutes)
    conflicts = ShiftCommitment.objects.filter(
        account_id=account_id,
        status__in=_ACTIVE_COMMITMENT_STATES,
        starts_at__lt=rest_end,
        rest_ends_at__gt=demand.starts_at,
    )
    if exclude_id is not None:
        conflicts = conflicts.exclude(id=exclude_id)
    if conflicts.exists():
        raise ShiftOverlapConflictError


def _transition_shift_demand(  # noqa: PLR0912,PLR0915
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    demand_id: UUID,
    expected_version: int,
    action: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
    allow_understaffed: bool = False,
) -> ShiftDemandCommandResult:
    demand_id = _validate_uuid(demand_id, field_name="demand_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_shift_reason(reason)
    source_channel = _validate_source_channel(source_channel)
    if type(allow_understaffed) is not bool:
        raise ValidationError(
            {"allow_understaffed": "Choose whether underfilled coverage is accepted."}
        )
    request_digest = shift_command_digest(
        action=action,
        payload={
            "demand_id": str(demand_id),
            "expected_version": expected_version,
            "reason": normalized_reason,
            "allow_understaffed": allow_understaffed,
        },
    )
    authorize_shift_organizer_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_organizer_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        permitted = (
            _CLEANUP_EDITION_LIFECYCLES
            if action
            in {
                ShiftDemandCommandReceipt.Action.REOPENED,
                ShiftDemandCommandReceipt.Action.COMPLETED,
                ShiftDemandCommandReceipt.Action.CANCELLED,
            }
            else _PLANNING_EDITION_LIFECYCLES
        )
        _require_lifecycle(edition=scope.edition, permitted_editions=permitted)
        replay = _demand_receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            if replay.action != action or replay.request_digest != request_digest:
                raise ShiftRetryConflictError
            return _demand_result(receipt=replay, replayed=True)
        demand = _lock_demand(scope=scope, demand_id=demand_id)
        commitments = _locked_commitments(demand)
        if demand.command_version != expected_version:
            raise ShiftVersionConflictError
        changed_fields: tuple[str, ...]
        if action == ShiftDemandCommandReceipt.Action.OPENED:
            if demand.status != ShiftDemand.Status.DRAFT:
                raise ShiftStateConflictError
            if scope.evaluated_at >= demand.ends_at:
                raise ShiftStateConflictError(
                    "An ended Shift cannot be opened for claims."
                )
            demand.status = ShiftDemand.Status.OPEN
            demand.published_at = scope.evaluated_at
            demand.published_by = scope.actor
            changed_fields = ("status", "publication_evidence")
        elif action == ShiftDemandCommandReceipt.Action.LOCKED:
            if demand.status != ShiftDemand.Status.OPEN:
                raise ShiftStateConflictError
            active = tuple(
                item for item in commitments if item.status in _ACTIVE_COMMITMENT_STATES
            )
            if any(item.status != ShiftCommitment.Status.CONFIRMED for item in active):
                raise ShiftStateConflictError(
                    "Resolve every unconfirmed claim before locking coverage."
                )
            for item in active:
                _active_assignment(
                    scope=scope,
                    demand=demand,
                    account_id=item.account_id,
                )
                plan, _preference = _current_availability(
                    scope=scope,
                    demand=demand,
                    account_id=item.account_id,
                )
                if plan.id != item.availability_plan_id or (
                    plan.command_version != item.availability_version
                ):
                    raise ShiftAvailabilityConflictError(
                        "Availability changed after confirmation; review it again."
                    )
                _require_no_overlap(
                    account_id=item.account_id,
                    demand=demand,
                    exclude_id=item.id,
                )
            if len(active) < demand.required_headcount and not allow_understaffed:
                raise ShiftCapacityConflictError(
                    "Coverage is below demand. Explicitly accept underfill to lock it."
                )
            demand.status = ShiftDemand.Status.LOCKED
            demand.locked_at = scope.evaluated_at
            demand.locked_by = scope.actor
            demand.locked_headcount = len(active)
            demand.lock_reason = normalized_reason
            changed_fields = ("status", "coverage_lock")
        elif action == ShiftDemandCommandReceipt.Action.REOPENED:
            if demand.status != ShiftDemand.Status.LOCKED:
                raise ShiftStateConflictError
            demand.status = ShiftDemand.Status.OPEN
            demand.locked_at = None
            demand.locked_by = None
            demand.locked_headcount = None
            demand.lock_reason = ""
            changed_fields = ("status", "coverage_lock")
        elif action == ShiftDemandCommandReceipt.Action.COMPLETED:
            if demand.status != ShiftDemand.Status.LOCKED:
                raise ShiftStateConflictError
            if scope.evaluated_at < demand.ends_at:
                raise ShiftStateConflictError("A Shift cannot complete before it ends.")
            active = tuple(
                item for item in commitments if item.status in _ACTIVE_COMMITMENT_STATES
            )
            if any(item.status != ShiftCommitment.Status.CONFIRMED for item in active):
                raise ShiftStateConflictError
            for item in active:
                item.status = ShiftCommitment.Status.COMPLETED
                item.command_version += 1
                item.completed_at = scope.evaluated_at
                item.completed_by = scope.actor
                item.completion_reason = normalized_reason
                item.save()
                child_retry = uuid5(retry_key, f"complete:{item.id}")
                child_digest = shift_command_digest(
                    action=ShiftCommitmentCommandReceipt.Action.COMPLETED,
                    payload={
                        "commitment_id": str(item.id),
                        "demand_id": str(demand.id),
                        "reason": normalized_reason,
                    },
                )
                _record_commitment_change(
                    scope=scope,
                    commitment=item,
                    action=ShiftCommitmentCommandReceipt.Action.COMPLETED,
                    reason=normalized_reason,
                    retry_key=child_retry,
                    request_digest=child_digest,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    changed_fields=("status", "completion_evidence"),
                    capability_code=MANAGE_SHIFTS,
                )
            demand.status = ShiftDemand.Status.COMPLETED
            demand.completed_at = scope.evaluated_at
            demand.completed_by = scope.actor
            demand.completion_reason = normalized_reason
            changed_fields = ("status", "completion_evidence")
        elif action == ShiftDemandCommandReceipt.Action.CANCELLED:
            if demand.status in {
                ShiftDemand.Status.COMPLETED,
                ShiftDemand.Status.CANCELLED,
            }:
                raise ShiftStateConflictError
            for item in commitments:
                if item.status not in _ACTIVE_COMMITMENT_STATES:
                    continue
                item.status = ShiftCommitment.Status.REMOVED
                item.command_version += 1
                item.removed_at = scope.evaluated_at
                item.removed_by = scope.actor
                item.removal_kind = ShiftCommitment.RemovalKind.CANCELLED
                item.removal_reason = normalized_reason
                item.save()
                child_retry = uuid5(retry_key, f"cancel:{item.id}")
                child_digest = shift_command_digest(
                    action=ShiftCommitmentCommandReceipt.Action.CANCELLED,
                    payload={
                        "commitment_id": str(item.id),
                        "demand_id": str(demand.id),
                        "reason": normalized_reason,
                    },
                )
                _record_commitment_change(
                    scope=scope,
                    commitment=item,
                    action=ShiftCommitmentCommandReceipt.Action.CANCELLED,
                    reason=normalized_reason,
                    retry_key=child_retry,
                    request_digest=child_digest,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    changed_fields=("status", "removal_evidence"),
                    capability_code=MANAGE_SHIFTS,
                )
            demand.status = ShiftDemand.Status.CANCELLED
            demand.cancelled_at = scope.evaluated_at
            demand.cancelled_by = scope.actor
            demand.cancellation_reason = normalized_reason
            changed_fields = ("status", "cancellation_evidence")
        else:
            raise ValidationError({"action": "Choose a supported Shift action."})
        demand.command_version += 1
        demand.save()
        return _record_demand_change(
            scope=scope,
            demand=demand,
            action=action,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            changed_fields=changed_fields,
        )


def open_shift_demand(**kwargs: object) -> ShiftDemandCommandResult:
    """Publish a draft Shift so qualified people may claim it.

    Parameters
    ----------
    **kwargs : object
        Organizer transition command arguments.

    Returns
    -------
    ShiftDemandCommandResult
        Published demand result and immutable receipt identity.
    """
    return _transition_shift_demand(
        action=ShiftDemandCommandReceipt.Action.OPENED,
        allow_understaffed=False,
        **kwargs,  # type: ignore[arg-type]
    )


def lock_shift_demand(
    *, allow_understaffed: bool, **kwargs: object
) -> ShiftDemandCommandResult:
    """Freeze confirmed, current coverage with an explicit underfill choice.

    Parameters
    ----------
    allow_understaffed : bool
        Whether the organizer explicitly accepts below-target coverage.
    **kwargs : object
        Organizer transition command arguments.

    Returns
    -------
    ShiftDemandCommandResult
        Locked demand result and immutable receipt identity.
    """
    return _transition_shift_demand(
        action=ShiftDemandCommandReceipt.Action.LOCKED,
        allow_understaffed=allow_understaffed,
        **kwargs,  # type: ignore[arg-type]
    )


def reopen_shift_demand(**kwargs: object) -> ShiftDemandCommandResult:
    """Return locked coverage to the open planning state.

    Parameters
    ----------
    **kwargs : object
        Organizer transition command arguments.

    Returns
    -------
    ShiftDemandCommandResult
        Reopened demand result and immutable receipt identity.
    """
    return _transition_shift_demand(
        action=ShiftDemandCommandReceipt.Action.REOPENED,
        allow_understaffed=False,
        **kwargs,  # type: ignore[arg-type]
    )


def complete_shift_demand(**kwargs: object) -> ShiftDemandCommandResult:
    """Complete ended locked work and all confirmed commitments atomically.

    Parameters
    ----------
    **kwargs : object
        Organizer transition command arguments.

    Returns
    -------
    ShiftDemandCommandResult
        Completed demand result and immutable receipt identity.
    """
    return _transition_shift_demand(
        action=ShiftDemandCommandReceipt.Action.COMPLETED,
        allow_understaffed=False,
        **kwargs,  # type: ignore[arg-type]
    )


def cancel_shift_demand(**kwargs: object) -> ShiftDemandCommandResult:
    """Cancel unfinished demand and retain removal evidence for active claims.

    Parameters
    ----------
    **kwargs : object
        Organizer transition command arguments.

    Returns
    -------
    ShiftDemandCommandResult
        Cancelled demand result and immutable receipt identity.
    """
    return _transition_shift_demand(
        action=ShiftDemandCommandReceipt.Action.CANCELLED,
        allow_understaffed=False,
        **kwargs,  # type: ignore[arg-type]
    )


def claim_shift(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    demand_id: UUID,
    expected_version: int,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> ShiftCommitmentCommandResult:
    """Claim one currently suitable open Shift as the authenticated person.

    Parameters
    ----------
    actor : Account
        Authenticated person claiming the work.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact edition planning scope.
    demand_id : UUID
        Open demand being claimed.
    expected_version : int
        Optimistic current demand version.
    retry_key : UUID
        Person-and-edition idempotency key.
    correlation_id : UUID
        Correlation identifier for command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default='service'
        Registered trusted adapter channel.

    Returns
    -------
    ShiftCommitmentCommandResult
        Claim identity, version, state, receipt, and replay marker.

    Raises
    ------
    ShiftCapacityConflictError
        If transactional demand capacity is already full.
    ShiftRetryConflictError
        If the retry key was already used for different command input.
    ShiftStateConflictError
        If the demand is no longer open and claimable.
    ShiftVersionConflictError
        If the optimistic demand version is stale.
    """
    demand_id = _validate_uuid(demand_id, field_name="demand_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    request_digest = shift_command_digest(
        action=ShiftCommitmentCommandReceipt.Action.CLAIMED,
        payload={"demand_id": str(demand_id), "expected_version": expected_version},
    )
    authorize_shift_self_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_self_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        _require_lifecycle(
            edition=scope.edition,
            permitted_editions=_PLANNING_EDITION_LIFECYCLES,
        )
        replay = _commitment_receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            if (
                replay.action != ShiftCommitmentCommandReceipt.Action.CLAIMED
                or replay.request_digest != request_digest
            ):
                raise ShiftRetryConflictError
            return _commitment_result(receipt=replay, replayed=True)
        demand = _lock_demand(scope=scope, demand_id=demand_id)
        if demand.command_version != expected_version:
            raise ShiftVersionConflictError
        if demand.status != ShiftDemand.Status.OPEN:
            raise ShiftStateConflictError
        if scope.evaluated_at >= demand.ends_at:
            raise ShiftStateConflictError("An ended Shift can no longer be claimed.")
        commitments = _locked_commitments(demand)
        active = tuple(
            item for item in commitments if item.status in _ACTIVE_COMMITMENT_STATES
        )
        if len(active) >= demand.required_headcount:
            raise ShiftCapacityConflictError
        if any(item.account_id == scope.actor.id for item in active):
            raise ShiftStateConflictError
        assignment = _active_assignment(
            scope=scope,
            demand=demand,
            account_id=scope.actor.id,
        )
        plan, _preference = _current_availability(
            scope=scope,
            demand=demand,
            account_id=scope.actor.id,
        )
        _require_no_overlap(account_id=scope.actor.id, demand=demand)
        commitment = ShiftCommitment.objects.create(
            demand=demand,
            organization_id=scope.organization_id,
            edition=scope.edition,
            position_assignment=assignment,
            account=scope.actor,
            status=ShiftCommitment.Status.CLAIMED,
            starts_at=demand.starts_at,
            ends_at=demand.ends_at,
            rest_ends_at=demand.ends_at
            + timedelta(minutes=demand.minimum_rest_minutes),
            availability_plan=plan,
            availability_version=plan.command_version,
            command_version=1,
            claimed_at=scope.evaluated_at,
        )
        return _record_commitment_change(
            scope=scope,
            commitment=commitment,
            action=ShiftCommitmentCommandReceipt.Action.CLAIMED,
            reason=_SELF_CLAIM_REASON,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            changed_fields=("status", "availability_evidence"),
            capability_code=MANAGE_SELF_SHIFTS,
        )


def _lock_commitment(
    *, scope: _OrganizerScope | _SelfScope, commitment_id: UUID
) -> ShiftCommitment:
    demand_id = (
        ShiftCommitment.objects.filter(
            id=commitment_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
        )
        .order_by()
        .values_list("demand_id", flat=True)
        .first()
    )
    if demand_id is None:
        raise ShiftUnavailableError
    _lock_demand(scope=scope, demand_id=demand_id)
    commitment = (
        ShiftCommitment.objects.select_for_update()
        .select_related("demand", "demand__position", "position_assignment")
        .filter(
            id=commitment_id,
            organization_id=scope.organization_id,
            edition_id=scope.edition.id,
        )
        .order_by()
        .first()
    )
    if commitment is None:
        raise ShiftUnavailableError
    return commitment


def withdraw_shift_claim(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    commitment_id: UUID,
    expected_version: int,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> ShiftCommitmentCommandResult:
    """Withdraw the authenticated person's claimed or confirmed open Shift.

    Parameters
    ----------
    actor : Account
        Authenticated commitment owner.
    organization_id : UUID
        Exact owning organization.
    edition_id : UUID
        Exact edition planning scope.
    commitment_id : UUID
        Person-owned active commitment to remove.
    expected_version : int
        Optimistic current commitment version.
    retry_key : UUID
        Person-and-edition idempotency key.
    correlation_id : UUID
        Correlation identifier for command evidence.
    request_id : UUID | None, default=None
        Optional originating request identifier.
    source_channel : str, default='service'
        Registered trusted adapter channel.

    Returns
    -------
    ShiftCommitmentCommandResult
        Removed commitment identity, version, receipt, and replay marker.

    Raises
    ------
    ShiftAuthorizationDeniedError
        If the commitment does not belong to the authenticated person.
    ShiftRetryConflictError
        If the retry key was already used for different command input.
    ShiftStateConflictError
        If planning is not open or the commitment is not active.
    ShiftVersionConflictError
        If the optimistic commitment version is stale.
    """
    commitment_id = _validate_uuid(commitment_id, field_name="commitment_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    source_channel = _validate_source_channel(source_channel)
    request_digest = shift_command_digest(
        action=ShiftCommitmentCommandReceipt.Action.WITHDRAWN,
        payload={
            "commitment_id": str(commitment_id),
            "expected_version": expected_version,
        },
    )
    authorize_shift_self_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_self_scope(
            actor=actor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        _require_lifecycle(
            edition=scope.edition,
            permitted_editions=_CLEANUP_EDITION_LIFECYCLES,
        )
        replay = _commitment_receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            if (
                replay.action != ShiftCommitmentCommandReceipt.Action.WITHDRAWN
                or replay.request_digest != request_digest
            ):
                raise ShiftRetryConflictError
            return _commitment_result(receipt=replay, replayed=True)
        commitment = _lock_commitment(scope=scope, commitment_id=commitment_id)
        if commitment.account_id != scope.actor.id:
            raise ShiftAuthorizationDeniedError
        if commitment.command_version != expected_version:
            raise ShiftVersionConflictError
        if commitment.demand.status != ShiftDemand.Status.OPEN or (
            commitment.status not in _ACTIVE_COMMITMENT_STATES
        ):
            raise ShiftStateConflictError
        commitment.status = ShiftCommitment.Status.REMOVED
        commitment.command_version += 1
        commitment.removed_at = scope.evaluated_at
        commitment.removed_by = scope.actor
        commitment.removal_kind = ShiftCommitment.RemovalKind.WITHDRAWN
        commitment.removal_reason = _SELF_WITHDRAW_REASON
        commitment.save()
        return _record_commitment_change(
            scope=scope,
            commitment=commitment,
            action=ShiftCommitmentCommandReceipt.Action.WITHDRAWN,
            reason=_SELF_WITHDRAW_REASON,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            changed_fields=("status", "removal_evidence"),
            capability_code=MANAGE_SELF_SHIFTS,
        )


def _organizer_commitment_change(
    *,
    actor: Account,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
    commitment_id: UUID,
    expected_version: int,
    action: str,
    reason: str,
    retry_key: UUID,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> ShiftCommitmentCommandResult:
    commitment_id = _validate_uuid(commitment_id, field_name="commitment_id")
    expected_version = _validate_expected_version(expected_version)
    retry_key = _validate_uuid(retry_key, field_name="retry_key")
    correlation_id = _validate_uuid(correlation_id, field_name="correlation_id")
    normalized_reason = normalize_shift_reason(reason)
    source_channel = _validate_source_channel(source_channel)
    request_digest = shift_command_digest(
        action=action,
        payload={
            "commitment_id": str(commitment_id),
            "expected_version": expected_version,
            "reason": normalized_reason,
        },
    )
    authorize_shift_organizer_command(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    with transaction.atomic():
        scope = _lock_organizer_scope(
            actor=actor,
            organization_id=organization_id,
            series_id=series_id,
            edition_id=edition_id,
        )
        _require_lifecycle(
            edition=scope.edition,
            permitted_editions=_CLEANUP_EDITION_LIFECYCLES,
        )
        replay = _commitment_receipt_for_retry(scope=scope, retry_key=retry_key)
        if replay is not None:
            if replay.action != action or replay.request_digest != request_digest:
                raise ShiftRetryConflictError
            return _commitment_result(receipt=replay, replayed=True)
        commitment = _lock_commitment(scope=scope, commitment_id=commitment_id)
        if commitment.command_version != expected_version:
            raise ShiftVersionConflictError
        if commitment.demand.status != ShiftDemand.Status.OPEN:
            raise ShiftStateConflictError
        changed_fields: tuple[str, ...]
        if action == ShiftCommitmentCommandReceipt.Action.CONFIRMED:
            if commitment.status not in {
                ShiftCommitment.Status.CLAIMED,
                ShiftCommitment.Status.CONFIRMED,
            }:
                raise ShiftStateConflictError
            if commitment.account_id == scope.actor.id:
                raise ShiftAuthorizationDeniedError(
                    "A person cannot confirm their own Shift claim."
                )
            _active_assignment(
                scope=scope,
                demand=commitment.demand,
                account_id=commitment.account_id,
            )
            plan, _preference = _current_availability(
                scope=scope,
                demand=commitment.demand,
                account_id=commitment.account_id,
            )
            _require_no_overlap(
                account_id=commitment.account_id,
                demand=commitment.demand,
                exclude_id=commitment.id,
            )
            commitment.status = ShiftCommitment.Status.CONFIRMED
            commitment.command_version += 1
            commitment.availability_plan = plan
            commitment.availability_version = plan.command_version
            commitment.confirmed_at = scope.evaluated_at
            commitment.confirmed_by = scope.actor
            commitment.confirmation_reason = normalized_reason
            changed_fields = (
                "status",
                "confirmation_evidence",
                "availability_evidence",
            )
        elif action == ShiftCommitmentCommandReceipt.Action.REMOVED:
            if commitment.status not in _ACTIVE_COMMITMENT_STATES:
                raise ShiftStateConflictError
            commitment.status = ShiftCommitment.Status.REMOVED
            commitment.command_version += 1
            commitment.removed_at = scope.evaluated_at
            commitment.removed_by = scope.actor
            commitment.removal_kind = ShiftCommitment.RemovalKind.ORGANIZER
            commitment.removal_reason = normalized_reason
            changed_fields = ("status", "removal_evidence")
        else:
            raise ValidationError({"action": "Choose a supported commitment action."})
        commitment.save()
        return _record_commitment_change(
            scope=scope,
            commitment=commitment,
            action=action,
            reason=normalized_reason,
            retry_key=retry_key,
            request_digest=request_digest,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            changed_fields=changed_fields,
            capability_code=MANAGE_SHIFTS,
        )


def confirm_shift_commitment(**kwargs: object) -> ShiftCommitmentCommandResult:
    """Confirm a person's claim after a fresh organizer suitability check.

    Parameters
    ----------
    **kwargs : object
        Organizer commitment-command arguments.

    Returns
    -------
    ShiftCommitmentCommandResult
        Confirmed commitment result and immutable receipt identity.
    """
    return _organizer_commitment_change(
        action=ShiftCommitmentCommandReceipt.Action.CONFIRMED,
        **kwargs,  # type: ignore[arg-type]
    )


def remove_shift_commitment(**kwargs: object) -> ShiftCommitmentCommandResult:
    """Remove active open coverage while retaining organizer rationale.

    Parameters
    ----------
    **kwargs : object
        Organizer commitment-command arguments.

    Returns
    -------
    ShiftCommitmentCommandResult
        Removed commitment result and immutable receipt identity.
    """
    return _organizer_commitment_change(
        action=ShiftCommitmentCommandReceipt.Action.REMOVED,
        **kwargs,  # type: ignore[arg-type]
    )
