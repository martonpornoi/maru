"""Shared owner transaction, exact retries and atomic minimized command evidence."""

from __future__ import annotations

import hashlib
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.scheduling_queries import resolve_scheduling_edition_reference

from .authorization import (
    AuthorizedSchedulingScope,
    SchedulingAuthorizationDeniedError,
    SchedulingAuthorizer,
    authorize_scheduling_scope,
)
from .events import SCHEDULING_CHANGED_EVENT, SCHEDULING_CHANGED_SCHEMA_VERSION
from .inputs import SchedulingCommandRequest, scheduling_digest
from .models import SchedulingCommandReceipt, SchedulingEditionControl
from .writer_boundary import _command_receipt_scope, scheduling_writer

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from uuid import UUID

    from .catalogs import SchedulingOperation


class SchedulingCommandError(RuntimeError):
    """Base class for content-free stable Scheduling command failures."""

    reason_code = "scheduling_command_unavailable"


class SchedulingUnavailableError(SchedulingCommandError):
    """Hide an absent, foreign, retired or unavailable source selection."""

    reason_code = "scheduling_source_unavailable"


class SchedulingVersionConflictError(SchedulingCommandError):
    """Require a fresh snapshot after an optimistic version changes."""

    reason_code = "scheduling_version_conflict"


class SchedulingLifecycleConflictError(SchedulingCommandError):
    """Reject a new mutation after the current planning scope closes."""

    reason_code = "scheduling_lifecycle_conflict"


class SchedulingIdempotencyConflictError(SchedulingCommandError):
    """A retained actor/edition retry key cannot mean different intent."""

    reason_code = "scheduling_idempotency_conflict"


class SchedulingLimitError(SchedulingCommandError):
    """Reject complete-bound overflow rather than retaining partial success."""

    reason_code = "scheduling_limit_reached"


@dataclass(frozen=True, slots=True)
class SchedulingCommandResult:
    """Identifier-only receipt returned equally by first delivery and exact retry.

    Attributes
    ----------
    receipt_id
        Immutable Scheduling command evidence identifier.
    object_id
        Exact created or revised object, never a copied private field.
    version
        Resulting object version, including an immutable source revision version.
    control_version
        Resulting edition-local Scheduling command sequence.
    replayed
        Whether this response comes from an existing identical command receipt.
    """

    receipt_id: UUID
    object_id: UUID
    version: int
    control_version: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class _CommandTransaction:
    request: SchedulingCommandRequest
    scope: AuthorizedSchedulingScope
    prior_control_version: int
    occurred_at: datetime
    receipt_id: UUID = field(default_factory=uuid4)

    def evidence(self) -> dict[str, object]:
        return {
            "organization_id": self.request.organization_id,
            "edition_id": self.request.edition_id,
            "actor_id": self.request.actor_id,
            "occurred_at": self.occurred_at,
            "reason": self.request.reason,
        }

    def ownership(self) -> dict[str, object]:
        return {
            "organization_id": self.request.organization_id,
            "edition_id": self.request.edition_id,
        }


def _result(
    receipt: SchedulingCommandReceipt, *, replayed: bool
) -> SchedulingCommandResult:
    return SchedulingCommandResult(
        receipt.id,
        receipt.result_object_id,
        receipt.resulting_version,
        receipt.control_version,
        replayed=replayed,
    )


def _audit(
    request: SchedulingCommandRequest,
    *,
    operation: SchedulingOperation,
    capability: str,
    outcome: str,
    reason_code: str,
    target_id: UUID | None = None,
    obligations: tuple[str, ...] = ("audit",),
    occurred_at: datetime | None = None,
) -> UUID:
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=request.actor_id,
            principal_context_id=None,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            capability_code=capability,
            operation=f"scheduling.command.{operation.value}",
            target_type="scheduling.object",
            target_id=target_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=request.correlation_id,
            request_id=request.correlation_id,
            source_channel=request.source_channel,
            obligations=obligations,
            idempotency_key_hash=hashlib.sha256(
                str(request.idempotency_key).encode()
            ).hexdigest(),
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="programme-restricted",
        ),
        occurred_at=occurred_at,
    ).id


def _record_success(
    context: _CommandTransaction,
    *,
    operation: SchedulingOperation,
    capability: str,
    digest: str,
    object_id: UUID,
    version: int,
) -> SchedulingCommandResult:
    request, scope = context.request, context.scope
    control_version = context.prior_control_version + 1
    receipt = SchedulingCommandReceipt.objects.create(
        id=context.receipt_id,
        **context.evidence(),
        operation=operation.value,
        idempotency_key=request.idempotency_key,
        request_digest=digest,
        control_version=control_version,
        result_object_id=object_id,
        resulting_version=version,
        correlation_id=request.correlation_id,
        source_channel=request.source_channel,
    )
    audit_id = _audit(
        request,
        operation=operation,
        capability=capability,
        outcome="allow",
        reason_code=scope.decision.reason_code,
        target_id=object_id,
        obligations=tuple(sorted(scope.decision.obligations | {"audit"})),
        occurred_at=context.occurred_at,
    )
    publish_domain_event(
        DomainEventRecord(
            event_name=SCHEDULING_CHANGED_EVENT,
            schema_version=SCHEDULING_CHANGED_SCHEMA_VERSION,
            organization_id=request.organization_id,
            event_edition_id=request.edition_id,
            aggregate_type="scheduling.edition",
            aggregate_id=request.edition_id,
            aggregate_version=control_version,
            payload={"operation": operation.value},
            correlation_id=request.correlation_id,
            causation_id=audit_id,
            actor_kind="account",
            actor_id=request.actor_id,
            retention_class="programme-restricted",
        ),
        occurred_at=context.occurred_at,
    )
    return _result(receipt, replayed=False)


def _require_current_version(actual: int, expected: int) -> None:
    if actual != expected:
        raise SchedulingVersionConflictError


def _execute[IntentT, PreparedT](
    request: SchedulingCommandRequest,
    *,
    operation: SchedulingOperation,
    capability: str,
    normalize: Callable[[], IntentT],
    payload: Callable[[IntentT], dict[str, object]],
    prepare: Callable[[IntentT], PreparedT],
    write: Callable[[_CommandTransaction, IntentT, PreparedT], tuple[UUID, int]],
    authorizer: SchedulingAuthorizer,
) -> SchedulingCommandResult:
    request = request.normalized()

    def authorize(*, lock: bool = False) -> AuthorizedSchedulingScope:
        return authorize_scheduling_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=capability,
            authorizer=authorizer,
            lock=lock,
        )

    def action() -> SchedulingCommandResult:
        authorize()
        intent = normalize()
        digest = scheduling_digest(
            {
                "operation": operation.value,
                "reason": request.reason,
                "source_channel": request.source_channel,
                "intent": payload(intent),
            }
        )
        with transaction.atomic(), scheduling_writer():
            edition = resolve_scheduling_edition_reference(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                lock=True,
            )
            if edition is None:
                raise SchedulingAuthorizationDeniedError
            scope = authorize()
            receipt = SchedulingCommandReceipt.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                actor_id=request.actor_id,
                idempotency_key=request.idempotency_key,
            ).first()
            if receipt is not None:
                if receipt.request_digest != digest:
                    raise SchedulingIdempotencyConflictError
                authorize(lock=True)
                return _result(receipt, replayed=True)
            if not scope.accepts_writes:
                raise SchedulingLifecycleConflictError
            # Owner preparation locks the complete canonical subject set before
            # the actor-only recheck and Scheduling control lock below.
            prepared = prepare(intent)
            scope = authorize(lock=True)
            if not scope.accepts_writes:
                raise SchedulingLifecycleConflictError
            control = (
                SchedulingEditionControl.objects.select_for_update()
                .filter(
                    organization_id=request.organization_id,
                    edition_id=request.edition_id,
                )
                .first()
            )
            prior = control.aggregate_version if control else 0
            if prior >= 2**63 - 2:
                raise SchedulingLimitError
            context = _CommandTransaction(request, scope, prior, timezone.now())
            if control is None:
                SchedulingEditionControl.objects.create(
                    **context.ownership(), aggregate_version=1
                )
            else:
                control.aggregate_version += 1
                control.save(update_fields=("aggregate_version", "updated_at"))
            with _command_receipt_scope(context.receipt_id):
                object_id, version = write(context, intent, prepared)
                current_scope = authorize()
                context = replace(context, scope=current_scope)
                return _record_success(
                    context,
                    operation=operation,
                    capability=capability,
                    digest=digest,
                    object_id=object_id,
                    version=version,
                )

    try:
        return action()
    except SchedulingAuthorizationDeniedError:
        _audit(
            request,
            operation=operation,
            capability=capability,
            outcome="deny",
            reason_code=SchedulingAuthorizationDeniedError.reason_code,
        )
        raise
    except Exception as error:
        # Preserve the original rollback/error if the evidence sink is unavailable.
        with suppress(Exception):
            _audit(
                request,
                operation=operation,
                capability=capability,
                outcome="error",
                reason_code=(
                    error.reason_code
                    if isinstance(error, SchedulingCommandError)
                    else "scheduling_input_invalid"
                    if isinstance(error, ValidationError)
                    else "scheduling_dependency_error"
                ),
            )
        raise
