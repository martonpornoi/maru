"""Atomic owning commands, current authorization and immutable exact retries."""

import hashlib
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from django.db import transaction
from django.utils import timezone

from maru.audit.mutation_evidence import audited_mutation
from maru.audit.services import AuditRecord, append_audit
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.knowledge_scope import resolve_knowledge_edition_scope
from maru.identity.queries import lock_account_references_for_evidence

from .authorization import AuthorizedGuidanceScope, authorize_guidance_scope
from .catalog import EVENT_NAME, OPERATION_CAPABILITIES, RETENTION_CLASS
from .contracts import GuidanceCommandRequest, GuidanceCommandResult
from .errors import (
    GuidanceDeniedError,
    GuidanceIdempotencyConflictError,
    GuidanceLimitError,
)
from .evidence_bound import require_complete_evidence_bound
from .inputs import digest, identifier, text
from .models import GuidanceCommandReceipt, GuidanceControl
from .readiness import require_knowledge_integrity
from .writer_boundary import guidance_writer


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Same-transaction immutable actor evidence and the locked owner control.

    Attributes
    ----------
    request : GuidanceCommandRequest
        Authenticated actor, tenant scope and retry identity for this command.
    scope : AuthorizedGuidanceScope
        Current Events facts and capability admission after ownership locking.
    control : GuidanceControl
        Locked edition cursor advanced with the receipt and domain evidence.
    receipt_id : UUID
        Shared immutable evidence reference allocated before domain rows exist.
    occurred_at : datetime
        One timestamp retained by the domain rows, receipt, audit and event.
    """

    request: GuidanceCommandRequest
    scope: AuthorizedGuidanceScope
    control: GuidanceControl
    receipt_id: UUID
    occurred_at: datetime

    def evidence(self) -> dict[str, object]:
        """Return only exact owner and attribution fields for immutable rows.

        Returns
        -------
        dict[str, object]
            The complete validated result; failures do not return partial evidence.
        """
        return {
            "organization_id": self.request.organization_id,
            "edition_id": self.request.edition_id,
            "actor_id": self.request.actor_id,
            "occurred_at": self.occurred_at,
            "command_receipt_id": self.receipt_id,
        }


def _result(
    receipt: GuidanceCommandReceipt, *, replayed: bool
) -> GuidanceCommandResult:
    return GuidanceCommandResult(
        receipt.id,
        receipt.object_id,
        receipt.resulting_version,
        receipt.item_id,
        replayed,
    )


def _audit_record(
    request: GuidanceCommandRequest,
    operation: str,
    *,
    outcome: str,
    reason_code: str,
    target_id: UUID | None = None,
) -> AuditRecord:
    return AuditRecord(
        principal_kind="account",
        principal_id=request.actor_id,
        principal_context_id=None,
        organization_id=request.organization_id,
        event_edition_id=request.edition_id,
        capability_code=OPERATION_CAPABILITIES[operation],
        operation=f"knowledge.command.{operation}",
        target_type="knowledge.record",
        target_id=target_id,
        outcome=outcome,
        reason_code=reason_code,
        correlation_id=request.correlation_id,
        request_id=request.correlation_id,
        source_channel=request.source_channel,
        obligations=("audit",),
        idempotency_key_hash=hashlib.sha256(
            str(request.idempotency_key).encode()
        ).hexdigest(),
        retention_class=RETENTION_CLASS,
    )


def execute(
    request: GuidanceCommandRequest,
    *,
    operation: str,
    intent: dict[str, object],
    write: Callable[[CommandContext], tuple[UUID, UUID | None, int]],
    reason: str = "",
) -> GuidanceCommandResult:
    """Commit one versioned fact, receipt, native audit witness and outbox together.

    Parameters
    ----------
    request : GuidanceCommandRequest
        Actual authenticated actor and exact organization/edition context.
    operation : str
        Closed command operation code for audit and event evidence.
    intent : dict[str, object]
        Normalized command intent bound to the exact retry receipt.
    write : Callable[[CommandContext], tuple[UUID, UUID | None, int]]
        Owning mutation evaluated inside the locked atomic transaction.
    reason : str, default=''
        Bounded operational explanation retained with this command.

    Returns
    -------
    GuidanceCommandResult
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    GuidanceIdempotencyConflictError
        If scope, input, state or retained evidence fails the owning contract.
    Exception
        If a transactional dependency fails; the complete write is rolled back.
    """
    capability = OPERATION_CAPABILITIES[operation]
    identifier(request.idempotency_key)
    source = text(request.source_channel, maximum=80)
    if source != request.source_channel:
        raise GuidanceIdempotencyConflictError
    request_digest = digest(
        {
            "operation": operation,
            "intent": intent,
            "reason": reason,
            "source_channel": source,
        }
    )

    def apply() -> GuidanceCommandResult:
        authorize_guidance_scope(request, capability=capability)
        require_knowledge_integrity()
        with transaction.atomic(), guidance_writer():
            edition = resolve_knowledge_edition_scope(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                for_update=True,
            )
            if (
                edition is None
                or lock_account_references_for_evidence(account_ids=(request.actor_id,))
                is None
            ):
                raise GuidanceDeniedError
            scope = authorize_guidance_scope(request, capability=capability)
            receipt = GuidanceCommandReceipt.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                actor_id=request.actor_id,
                idempotency_key=request.idempotency_key,
            ).first()
            if receipt:
                if (
                    receipt.request_digest != request_digest
                    or receipt.operation != operation
                ):
                    raise GuidanceIdempotencyConflictError
                return _result(receipt, replayed=True)
            control = (
                GuidanceControl.objects.select_for_update()
                .filter(
                    organization_id=request.organization_id,
                    edition_id=request.edition_id,
                )
                .first()
            )
            if control is None:
                control = GuidanceControl.objects.create(
                    organization_id=request.organization_id,
                    edition_id=request.edition_id,
                )
            if control.sequence >= 2**63 - 2:
                raise GuidanceLimitError
            context = CommandContext(request, scope, control, uuid4(), timezone.now())
            object_id, item_id, result_version = write(context)
            control.sequence += 1
            control.save()
            scope = authorize_guidance_scope(request, capability=capability)
            receipt = GuidanceCommandReceipt.objects.create(
                id=context.receipt_id,
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                actor_id=request.actor_id,
                operation=operation,
                idempotency_key=request.idempotency_key,
                request_digest=request_digest,
                control_sequence=control.sequence,
                item_id=item_id,
                object_id=object_id,
                resulting_version=result_version,
                occurred_at=context.occurred_at,
                reason=reason,
                correlation_id=request.correlation_id,
                source_channel=source,
            )
            require_complete_evidence_bound(item_id)
            with audited_mutation(
                _audit_record(
                    request,
                    operation,
                    outcome="allow",
                    reason_code=scope.decision.reason_code,
                    target_id=object_id,
                ),
                occurred_at=context.occurred_at,
            ) as evidence:
                publish_domain_event(
                    DomainEventRecord(
                        event_name=EVENT_NAME,
                        schema_version=1,
                        organization_id=request.organization_id,
                        event_edition_id=request.edition_id,
                        aggregate_type="knowledge.edition",
                        aggregate_id=request.edition_id,
                        aggregate_version=control.sequence,
                        payload={"operation": operation},
                        correlation_id=request.correlation_id,
                        causation_id=evidence.audit_id,
                        actor_kind="account",
                        actor_id=request.actor_id,
                        retention_class=RETENTION_CLASS,
                    ),
                    occurred_at=context.occurred_at,
                )
            return _result(receipt, replayed=False)

    try:
        return apply()
    except Exception as error:
        with suppress(Exception):
            append_audit(
                _audit_record(
                    request,
                    operation,
                    outcome="deny"
                    if isinstance(error, GuidanceDeniedError)
                    else "error",
                    reason_code=getattr(
                        error, "reason_code", "guidance_command_failed"
                    ),
                )
            )
        raise
