"""Native evidence for the closed retained Applications cleanup purposes."""

import hashlib
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from maru.audit.mutation_evidence import audited_mutation
from maru.audit.services import AuditRecord, append_audit
from maru.events.programme_stop_queries import resolve_programme_stop_reference

_CLEANUP_OPERATIONS = frozenset(
    {
        "applications.programme.command.call_retired",
        "applications.programme.command.recovery_call_retired",
        "applications.programme.command.recovery_call_reassigned",
        "applications.programme.command.proposal_withdrawn",
        "applications.programme_import.command.batch_discarded",
    }
)


class ProgrammeCleanupUnavailableError(RuntimeError):
    """Refuse cleanup when its exact Events stop consequence is unavailable."""


@dataclass(frozen=True, slots=True)
class _AuditReference:
    id: UUID


def _append_cleanup_audit(
    record: AuditRecord,
    *,
    occurred_at: datetime,
    retry_key: UUID,
) -> _AuditReference:
    """Bind stopped cleanup under existing owner locks to its original retry intent."""
    if record.outcome == "allow" and record.operation in _CLEANUP_OPERATIONS:
        if record.organization_id is None or record.event_edition_id is None:
            raise ProgrammeCleanupUnavailableError
        reference = resolve_programme_stop_reference(
            organization_id=record.organization_id,
            edition_id=record.event_edition_id,
        )
        if reference is None:
            raise ProgrammeCleanupUnavailableError
        if reference.applies and reference.is_stopped:
            digest = hashlib.sha256(str(retry_key).encode("ascii")).hexdigest()
            with audited_mutation(
                replace(record, idempotency_key_hash=digest),
                occurred_at=occurred_at,
            ) as mutation:
                return _AuditReference(mutation.audit_id)
    return _AuditReference(append_audit(record, occurred_at=occurred_at).id)
