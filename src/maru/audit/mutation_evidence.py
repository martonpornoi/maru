"""Lexically scoped native mutation attribution, not an authorization grant.

Owners use this instead of their existing audit append when a derived owner
must join the same transaction. The lease cannot be reconstructed from an old
audit identifier. Database source guards and consumer-specific operation/scope
validation remain independently necessary; this is not a raw-SQL boundary.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import get_ident
from typing import TYPE_CHECKING
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.expressions import RawSQL

from .models import AuditEvent, AuditNativeMutationWitness
from .services import AuditRecord, append_audit

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from uuid import UUID


class MutationEvidenceUnavailableError(ValidationError):
    """Reject evidence outside its live, successful native transaction."""

    def __init__(self) -> None:
        """Initialize a stable, content-free evidence failure."""
        super().__init__(
            "Native mutation evidence is unavailable.",
            code="audit_mutation_evidence_unavailable",
        )


@dataclass(frozen=True, slots=True, eq=False)
class AuditedMutation:
    """Minimized attribution whose identity is valid only inside its owner lease.

    Attributes
    ----------
    audit_id
        Newly appended native audit event, never caller-selected prior evidence.
    principal_kind
        Native principal discriminator; consumers must check supported kinds.
    principal_id
        Native actor identifier, not permission to impersonate that actor.
    principal_context_id
        Native principal context, where applicable.
    organization_id
        Exact native organization scope, or none for a platform operation.
    event_edition_id
        Exact native edition scope, or none for a broader operation.
    capability_code
        Capability retained by the native command, not a new capability grant.
    operation
        Native operation code for closed consumer-side classification.
    target_type
        Native target discriminator for owner-side reference validation.
    target_id
        Exact native target identifier.
    changed_fields
        Field names only; no source values or private human reason.
    correlation_id
        Correlation to preserve in derived transaction evidence.
    source_channel
        Native command origin.
    occurred_at
        Time retained by the native audit event.
    """

    audit_id: UUID
    principal_kind: str
    principal_id: UUID | None
    principal_context_id: UUID | None
    organization_id: UUID | None
    event_edition_id: UUID | None
    capability_code: str
    operation: str
    target_type: str
    target_id: UUID | None
    changed_fields: tuple[str, ...]
    correlation_id: UUID
    source_channel: str
    occurred_at: datetime


@dataclass(slots=True)
class _MutationLease:
    evidence: AuditedMutation
    native_connection: object
    thread_id: int
    active: bool = True


_ACTIVE_MUTATION: ContextVar[_MutationLease | None] = ContextVar(
    "maru_audited_mutation", default=None
)


def _projection(event: AuditEvent) -> AuditedMutation:
    return AuditedMutation(
        audit_id=event.id,
        principal_kind=event.principal_kind,
        principal_id=event.principal_id,
        principal_context_id=event.principal_context_id,
        organization_id=event.organization_id,
        event_edition_id=event.event_edition_id,
        capability_code=event.capability_code,
        operation=event.operation,
        target_type=event.target_type,
        target_id=event.target_id,
        changed_fields=tuple(event.changed_fields),
        correlation_id=event.correlation_id,
        source_channel=event.source_channel,
        occurred_at=event.occurred_at,
    )


@contextmanager
def audited_mutation(
    record: AuditRecord,
    *,
    occurred_at: datetime | None = None,
) -> Iterator[AuditedMutation]:
    """Append one successful native audit and lend same-transaction evidence.

    Parameters
    ----------
    record : AuditRecord
        Audit the already authorized owner would otherwise append directly.
    occurred_at : datetime | None, default=None
        Native command time, or the normal Audit append time.

    Yields
    ------
    AuditedMutation
        Evidence usable by a derived owner only while this scope is active.

    Raises
    ------
    MutationEvidenceUnavailableError
        If no owner transaction is active or the record is not a success.

    Notes
    -----
    The additional atomic scope prohibits committing while evidence is live.
    Exceptions roll back this append and derived work; the native owner must
    propagate a required derived-join failure to roll back its earlier mutation.
    Nested scopes temporarily supersede the outer lease. Existing append_audit
    validation and persistence failures propagate unchanged. No transaction-ID
    arithmetic or 32-bit epoch assumptions is used. The Audit INSERT trigger
    independently stamps the actual backend transaction for SQL validation.
    """
    connection = transaction.get_connection()
    if (
        not connection.in_atomic_block
        or connection.needs_rollback
        or record.outcome != AuditEvent.Outcome.ALLOW
    ):
        raise MutationEvidenceUnavailableError
    with transaction.atomic():
        event_id = uuid4()
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('maru.audit_native_event_id', TRUE)")
            previous_event_id = cursor.fetchone()[0] or ""
            cursor.execute(
                "SELECT set_config('maru.audit_native_event_id', %s, TRUE)",
                [str(event_id)],
            )
        event = append_audit(record, occurred_at=occurred_at, event_id=event_id)
        evidence = _projection(event)
        lease = _MutationLease(evidence, connection.connection, get_ident())
        token = _ACTIVE_MUTATION.set(lease)
        try:
            yield evidence
        finally:
            # Revoke the shared lease too: resetting a ContextVar alone would
            # leave a copy_context() snapshot holding usable historical evidence.
            lease.active = False
            _ACTIVE_MUTATION.reset(token)
        # On failure or rollback the enclosing savepoint restores the setting.
        # Only successful, usable scopes need an explicit restoration here.
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('maru.audit_native_event_id', %s, TRUE)",
                    [previous_event_id],
                )


def require_audited_mutation(evidence: AuditedMutation) -> None:
    """Require exact live evidence before a consumer validates its owner contract.

    Parameters
    ----------
    evidence : AuditedMutation
        Exact object supplied by the innermost native mutation scope.

    Raises
    ------
    MutationEvidenceUnavailableError
        If copied, forged, expired, cross-thread, rolled-back or disconnected.

    Notes
    -----
    This establishes attribution only. Consumers still validate closed operation,
    field and target contracts through documented owner seams, and retain their
    own database invariants. Old audit UUIDs cannot reopen an expired lease.
    """
    lease = _ACTIVE_MUTATION.get()
    connection = transaction.get_connection()
    if (
        lease is None
        or not lease.active
        or lease.evidence is not evidence
        or lease.thread_id != get_ident()
        or lease.native_connection is not connection.connection
        or not connection.in_atomic_block
        or connection.needs_rollback
    ):
        raise MutationEvidenceUnavailableError
    if not AuditNativeMutationWitness.objects.filter(
        audit_event_id=evidence.audit_id,
        audit_event__outcome=AuditEvent.Outcome.ALLOW,
        transaction_stamp=RawSQL(
            "public.maru_audit_current_native_transaction_stamp()", ()
        ),
    ).exists():
        raise MutationEvidenceUnavailableError
