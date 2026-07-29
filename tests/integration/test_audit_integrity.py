from dataclasses import replace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from maru.audit.models import AuditEvent, AuditIntegrityBatch
from maru.audit.services import (
    GENESIS_DIGEST,
    AuditRecord,
    append_audit,
    seal_pending_audit_events,
    verify_audit_integrity,
)
from tests.factories import AccountFactory, EventEditionFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _record(**changes: object) -> AuditRecord:
    edition = EventEditionFactory()
    actor = AccountFactory()
    record = AuditRecord(
        principal_kind="account",
        principal_id=actor.id,
        principal_context_id=uuid4(),
        organization_id=edition.organization_id,
        event_edition_id=edition.id,
        capability_code="events.transition",
        operation="events.edition.transition",
        target_type="events.event_edition",
        target_id=edition.id,
        outcome=AuditEvent.Outcome.ALLOW,
        reason_code="direct_grant",
        correlation_id=uuid4(),
        request_id=uuid4(),
        source_channel="api",
        obligations=("reason",),
        changed_fields=("lifecycle",),
        safe_metadata={
            "client_kind": "staff-console",
            "policy_version": "2026-07-26.1",
        },
    )
    return replace(record, **changes)


def test_append_records_safe_control_evidence() -> None:
    record = _record()

    event = append_audit(record)

    assert event.principal_id == record.principal_id
    assert event.correlation_id == record.correlation_id
    assert event.changed_fields == ["lifecycle"]
    assert event.safe_metadata["client_kind"] == "staff-console"
    assert event.integrity_batch_id is None


def test_append_rejects_protected_payload_field() -> None:
    with pytest.raises(ValidationError, match="allowlisted"):
        append_audit(_record(safe_metadata={"message_body": "do not retain"}))

    assert not AuditEvent.objects.exists()


def test_model_and_database_reject_audit_event_mutation_or_deletion() -> None:
    event = append_audit(_record())
    event.reason_code = "rewritten"

    with pytest.raises(ValidationError, match="append-only"):
        event.save()
    with pytest.raises(ValidationError, match="append-only"):
        event.delete()

    with transaction.atomic(), pytest.raises(IntegrityError):
        AuditEvent.objects.filter(pk=event.pk).update(reason_code="raw-rewrite")
    with transaction.atomic(), pytest.raises(IntegrityError):
        AuditEvent.objects.filter(pk=event.pk).delete()

    event.refresh_from_db()
    assert event.reason_code == "direct_grant"


def test_seal_builds_a_verifiable_chain_and_is_idempotent_when_empty() -> None:
    first = append_audit(_record(operation="events.edition.transition"))
    second = append_audit(_record(operation="authorization.grant.create"))

    batch = seal_pending_audit_events()

    assert batch is not None
    assert batch.sequence == 1
    assert batch.previous_digest == GENESIS_DIGEST
    assert batch.event_count == 2
    assert len(batch.digest) == 64
    assert verify_audit_integrity()
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.integrity_batch_id == batch.id
    assert second.integrity_batch_id == batch.id
    assert seal_pending_audit_events() is None


def test_multiple_batches_chain_and_batch_rows_are_immutable() -> None:
    append_audit(_record())
    first = seal_pending_audit_events()
    append_audit(_record())
    second = seal_pending_audit_events()

    assert first is not None
    assert second is not None
    assert second.sequence == 2
    assert second.previous_digest == first.digest
    assert verify_audit_integrity()

    first.event_count = 99
    with pytest.raises(ValidationError, match="immutable"):
        first.save()
    with pytest.raises(ValidationError, match="immutable"):
        first.delete()
    with transaction.atomic(), pytest.raises(IntegrityError):
        AuditIntegrityBatch.objects.filter(pk=first.pk).update(event_count=99)


@pytest.mark.parametrize(
    ("sequence", "previous_digest", "digest", "event_count"),
    [
        (2, GENESIS_DIGEST, GENESIS_DIGEST, 0),
        (1, "1" * 64, GENESIS_DIGEST, 0),
        (1, GENESIS_DIGEST, "1" * 64, 0),
        (1, GENESIS_DIGEST, GENESIS_DIGEST, 1),
    ],
)
def test_gapped_or_modified_integrity_batch_fails_verification(
    sequence: int,
    previous_digest: str,
    digest: str,
    event_count: int,
) -> None:
    AuditIntegrityBatch.objects.create(
        sequence=sequence,
        previous_digest=previous_digest,
        digest=digest,
        event_count=event_count,
    )

    assert not verify_audit_integrity()


@pytest.mark.parametrize("limit", [0, 10_001])
def test_seal_rejects_unbounded_batch_size(limit: int) -> None:
    with pytest.raises(ValidationError, match="batch size"):
        seal_pending_audit_events(limit=limit)
