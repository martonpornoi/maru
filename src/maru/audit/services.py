"""Safe audit append, seal, and verification commands."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent, AuditIntegrityBatch

GENESIS_DIGEST = "0" * 64
AUDIT_SEAL_ADVISORY_LOCK = 6_844_781_305_381_117_204
MAX_BATCH_SIZE = 10_000


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Describe audit record.

    Attributes
    ----------
    principal_kind
        The closed principal kind discriminator defined by the domain catalog.
    principal_id
        The principal identifier within the requested scope.
    principal_context_id
        The principal context identifier within the requested scope.
    organization_id
        The organization identifier that owns the requested resource.
    event_edition_id
        The event edition identifier within the requested scope.
    capability_code
        The stable capability code required by the operation.
    operation
        The stable operation code recorded in audit evidence.
    target_type
        The closed target type discriminator defined by the domain catalog.
    target_id
        The target identifier within the requested scope.
    outcome
        The outcome retained in this immutable projection.
    reason_code
        The stable reason code from the relevant closed catalog.
    correlation_id
        The request correlation identifier used for audit tracing.
    source_channel
        The closed channel code identifying where the request originated.
    obligations
        The obligations retained in this immutable projection.
    changed_fields
        The canonical field names changed by the operation.
    causation_id
        The causation identifier within the requested scope.
    request_id
        The correlation identifier attached to the incoming request.
    idempotency_key_hash
        The idempotency key hash retained in this immutable projection.
    delegated
        The delegated retained in this immutable projection.
    elevated
        The elevated retained in this immutable projection.
    break_glass
        The break glass retained in this immutable projection.
    safe_metadata
        The safe metadata mapping to validate or transform.
    retention_class
        The retention class retained in this immutable projection.
    """

    principal_kind: str
    principal_id: UUID | None
    principal_context_id: UUID | None
    organization_id: UUID | None
    event_edition_id: UUID | None
    capability_code: str
    operation: str
    target_type: str
    target_id: UUID | None
    outcome: str
    reason_code: str
    correlation_id: UUID
    source_channel: str
    obligations: tuple[str, ...] = ()
    changed_fields: tuple[str, ...] = ()
    causation_id: UUID | None = None
    request_id: UUID | None = None
    idempotency_key_hash: str = ""
    delegated: bool = False
    elevated: bool = False
    break_glass: bool = False
    safe_metadata: dict[str, object] | None = None
    retention_class: str = "security-standard"


def append_audit(
    record: AuditRecord,
    *,
    occurred_at: datetime | None = None,
) -> AuditEvent:
    """Append audit.

    Parameters
    ----------
    record : AuditRecord
        The domain record to validate, persist, or project.
    occurred_at : datetime | None, default=None
        The time at which the event occurred.

    Returns
    -------
    AuditEvent
        The AuditEvent established after append audit completes.
    """
    values = asdict(record)
    values["obligations"] = list(record.obligations)
    values["changed_fields"] = list(record.changed_fields)
    values["safe_metadata"] = record.safe_metadata or {}
    return AuditEvent.objects.create(
        occurred_at=occurred_at or timezone.now(),
        **values,
    )


def _canonical_event(event: AuditEvent) -> dict[str, object]:
    return {
        "id": str(event.id),
        "schema_version": event.schema_version,
        "occurred_at": event.occurred_at.isoformat(),
        "principal_kind": event.principal_kind,
        "principal_id": str(event.principal_id) if event.principal_id else None,
        "principal_context_id": (
            str(event.principal_context_id) if event.principal_context_id else None
        ),
        "organization_id": (
            str(event.organization_id) if event.organization_id else None
        ),
        "event_edition_id": (
            str(event.event_edition_id) if event.event_edition_id else None
        ),
        "capability_code": event.capability_code,
        "operation": event.operation,
        "target_type": event.target_type,
        "target_id": str(event.target_id) if event.target_id else None,
        "outcome": event.outcome,
        "reason_code": event.reason_code,
        "obligations": event.obligations,
        "changed_fields": event.changed_fields,
        "correlation_id": str(event.correlation_id),
        "causation_id": str(event.causation_id) if event.causation_id else None,
        "request_id": str(event.request_id) if event.request_id else None,
        "idempotency_key_hash": event.idempotency_key_hash,
        "source_channel": event.source_channel,
        "delegated": event.delegated,
        "elevated": event.elevated,
        "break_glass": event.break_glass,
        "safe_metadata": event.safe_metadata,
        "retention_class": event.retention_class,
    }


def _digest(previous_digest: str, events: Iterable[AuditEvent]) -> str:
    payload = {
        "previous_digest": previous_digest,
        "events": [_canonical_event(event) for event in events],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


@transaction.atomic
def seal_pending_audit_events(*, limit: int = 1_000) -> AuditIntegrityBatch | None:
    """Seal pending audit events.

    Parameters
    ----------
    limit : int, default=1000
        The maximum number of records to process.

    Returns
    -------
    AuditIntegrityBatch | None
        The matching AuditIntegrityBatch, or `None` when no authorized record exists.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if limit < 1 or limit > MAX_BATCH_SIZE:
        raise ValidationError(
            f"Audit batch size must be between 1 and {MAX_BATCH_SIZE}.",
            code="invalid_audit_batch_size",
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [AUDIT_SEAL_ADVISORY_LOCK])

    last_batch = (
        AuditIntegrityBatch.objects.select_for_update().order_by("-sequence").first()
    )
    events = list(
        AuditEvent.objects.select_for_update(skip_locked=True)
        .filter(integrity_batch__isnull=True)
        .order_by("occurred_at", "id")[:limit]
    )
    if not events:
        return None

    previous_digest = last_batch.digest if last_batch else GENESIS_DIGEST
    batch = AuditIntegrityBatch.objects.create(
        sequence=(last_batch.sequence + 1) if last_batch else 1,
        previous_digest=previous_digest,
        digest=_digest(previous_digest, events),
        event_count=len(events),
    )
    AuditEvent.objects.filter(id__in=[event.id for event in events]).update(
        integrity_batch=batch
    )
    return batch


def verify_audit_integrity() -> bool:
    """Verify audit integrity.

    Returns
    -------
    bool
        Whether the requested condition is satisfied.
    """
    expected_previous = GENESIS_DIGEST
    expected_sequence = 1
    for batch in AuditIntegrityBatch.objects.order_by("sequence"):
        events = list(batch.events.order_by("occurred_at", "id"))
        if batch.sequence != expected_sequence:
            return False
        if batch.previous_digest != expected_previous:
            return False
        if batch.event_count != len(events):
            return False
        if batch.digest != _digest(expected_previous, events):
            return False
        expected_previous = batch.digest
        expected_sequence += 1
    return True
