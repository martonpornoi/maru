"""Shared exact replay validation for Registration setup command evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from maru.audit.models import AuditEvent
from maru.effects.models import DomainEvent
from maru.registration.setup_commands import RegistrationSetupStateConflictError
from maru.registration.setup_content import canonical_digest

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.registration.models import (
        RegistrationSetupCommandReceipt,
        RegistrationSetupCommandTarget,
    )

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_POLICY_VERSION_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\.[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class SetupCommandTargetExpectation:
    """One exact immutable target row expected beneath a command receipt.

    Attributes
    ----------
    target_kind
        The closed target kind discriminator defined by the domain catalog.
    target_id
        The target identifier within the requested scope.
    change_kind
        The closed change kind discriminator defined by the domain catalog.
    target_schema_version
        The expected target schema version used to reject stale updates.
    content_digest
        The canonical digest used to verify content.
    """

    target_kind: str
    target_id: UUID
    change_kind: str
    target_schema_version: int | None
    content_digest: str


def require_setup_command_evidence_graph(
    *,
    scope: Any,
    receipt: RegistrationSetupCommandReceipt,
    primary_target_id: UUID,
    operation_segment: str,
    expected_targets: tuple[SetupCommandTargetExpectation, ...],
    expected_changed_fields: tuple[str, ...],
    expected_event_payload: dict[str, object],
    expected_occurred_at: datetime | None = None,
    expected_audit_operation: str | None = None,
    expected_audit_target_type: str | None = None,
    expected_contract_version: str = "registration-definition-command-v1",
    expected_event_name: str = "registration.configuration.draft_changed.v1",
) -> AuditEvent:
    """Lock and prove one receipt's exact target/audit/event/outbox graph.

    Parameters
    ----------
    scope : Any
        The exact tenant and resource scope of the operation.
    receipt : RegistrationSetupCommandReceipt
        The immutable command receipt proving the accepted transition.
    primary_target_id : UUID
        The primary target identifier within the requested scope.
    operation_segment : str
        The operation segment evaluated while require setup command evidence graph.
    expected_targets : tuple[SetupCommandTargetExpectation, ...]
        The expected targets evaluated while require setup command evidence graph.
    expected_changed_fields : tuple[str, ...]
        The canonical expected changed fields included in the projection or mutation.
    expected_event_payload : dict[str, object]
        The expected event payload mapping to validate or transform.
    expected_occurred_at : datetime | None, default=None
        The timezone-aware timestamp for expected occurred.
    expected_audit_operation : str | None, default=None
        The audit operation required in the evidence graph.
    expected_audit_target_type : str | None, default=None
        The closed target type required on the audit event.
    expected_contract_version : str, default='registration-definition-command-v1'
        The expected expected contract version used to reject stale updates.
    expected_event_name : str, default='registration.configuration.draft_changed.v1'
        The human-readable expected event name shown to authorized readers.

    Returns
    -------
    AuditEvent
        The resolved AuditEvent for require setup command evidence graph.

    Raises
    ------
    RegistrationSetupStateConflictError
        If the target lifecycle state does not permit the transition.
    """
    retry_key = receipt.retry_key
    request_digest = receipt.request_digest
    if (
        retry_key is None
        or _SHA256_PATTERN.fullmatch(request_digest) is None
        or receipt.setup_id != scope.control.id
        or receipt.organization_id != scope.organization.id
        or receipt.edition_id != scope.edition.id
        or receipt.resulting_version <= 0
        or not expected_targets
        or any(
            _SHA256_PATTERN.fullmatch(target.content_digest) is None
            or (
                target.target_schema_version is not None
                and target.target_schema_version <= 0
            )
            for target in expected_targets
        )
    ):
        raise RegistrationSetupStateConflictError

    persisted_targets = tuple(
        receipt.targets.select_for_update().order_by(
            "target_kind",
            "target_id",
            "id",
        )
    )
    expected_target_rows = tuple(
        sorted(
            (
                target.target_kind,
                target.target_id,
                target.change_kind,
                target.target_schema_version,
                target.content_digest,
            )
            for target in expected_targets
        )
    )
    persisted_target_rows = tuple(
        (
            target.target_kind,
            target.target_id,
            target.change_kind,
            target.target_schema_version,
            target.content_digest,
        )
        for target in persisted_targets
    )
    if persisted_target_rows != expected_target_rows:
        raise RegistrationSetupStateConflictError

    audit_operation = expected_audit_operation or (
        f"registration.setup.{operation_segment}.changed"
    )
    audit_target_type = expected_audit_target_type or (
        f"registration.{operation_segment}"
    )
    audits = tuple(
        AuditEvent.objects.select_for_update().filter(
            schema_version=1,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            principal_kind="account",
            principal_id=receipt.actor_id,
            capability_code="registration.manage_configuration",
            operation=audit_operation,
            target_type=audit_target_type,
            target_id=primary_target_id,
            outcome=AuditEvent.Outcome.ALLOW,
            correlation_id=receipt.correlation_id,
            source_channel=receipt.source_channel,
            changed_fields=list(expected_changed_fields),
            idempotency_key_hash=canonical_digest({"retry_key": str(retry_key)}),
            retention_class="registration-restricted",
        )[:2]
    )
    if len(audits) != 1:
        raise RegistrationSetupStateConflictError
    audit = audits[0]
    policy_version = audit.safe_metadata.get("policy_version")
    if (
        (expected_occurred_at is not None and audit.occurred_at != expected_occurred_at)
        or not audit.reason_code
        or audit.request_id is None
        or not isinstance(audit.obligations, list)
        or audit.obligations != sorted(set(audit.obligations))
        or any(
            not isinstance(obligation, str) or not obligation
            for obligation in audit.obligations
        )
        or set(audit.safe_metadata)
        != {"policy_version", "contract_version", "target_count"}
        or not isinstance(policy_version, str)
        or _POLICY_VERSION_PATTERN.fullmatch(policy_version) is None
        or audit.safe_metadata.get("contract_version") != expected_contract_version
        or audit.safe_metadata.get("target_count") != len(expected_targets)
    ):
        raise RegistrationSetupStateConflictError

    events = tuple(
        DomainEvent.objects.select_for_update().filter(
            event_name=expected_event_name,
            schema_version=1,
            occurred_at=audit.occurred_at,
            organization_id=scope.organization.id,
            event_edition_id=scope.edition.id,
            aggregate_type="registration.setup",
            aggregate_id=scope.control.id,
            aggregate_version=receipt.resulting_version,
            payload=expected_event_payload,
            correlation_id=receipt.correlation_id,
            causation_id=audit.id,
            actor_kind="account",
            actor_id=receipt.actor_id,
            retention_class="registration-restricted",
        )[:2]
    )
    if len(events) != 1:
        raise RegistrationSetupStateConflictError
    outbox = tuple(
        events[0]
        .outbox_messages.select_for_update()
        .filter(
            organization_id=scope.organization.id,
            destination="internal",
            workload_pool="default",
        )[:2]
    )
    if len(outbox) != 1:
        raise RegistrationSetupStateConflictError
    return audit


def target_expectation(
    target: RegistrationSetupCommandTarget,
) -> SetupCommandTargetExpectation:
    """Copy a locked immutable target into an exact comparison value.

    Parameters
    ----------
    target : RegistrationSetupCommandTarget
        The exact domain resource targeted by the operation.

    Returns
    -------
    SetupCommandTargetExpectation
        The resolved SetupCommandTargetExpectation for target expectation.
    """
    return SetupCommandTargetExpectation(
        target_kind=target.target_kind,
        target_id=target.target_id,
        change_kind=target.change_kind,
        target_schema_version=target.target_schema_version,
        content_digest=target.content_digest,
    )


__all__ = [
    "SetupCommandTargetExpectation",
    "require_setup_command_evidence_graph",
    "target_expectation",
]
