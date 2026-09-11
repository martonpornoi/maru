from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import copy, deepcopy
from dataclasses import fields, replace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from maru.audit.models import AuditEvent, AuditNativeMutationWitness
from maru.audit.mutation_evidence import (
    AuditedMutation,
    MutationEvidenceUnavailableError,
    audited_mutation,
    require_audited_mutation,
)
from maru.audit.services import AuditRecord, append_audit

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _record(**changes: object) -> AuditRecord:
    return replace(
        AuditRecord(
            principal_kind="account",
            principal_id=uuid4(),
            principal_context_id=None,
            organization_id=uuid4(),
            event_edition_id=uuid4(),
            capability_code="events.transition",
            operation="events.edition.transition",
            target_type="events.event_edition",
            target_id=uuid4(),
            outcome="allow",
            reason_code="direct_grant",
            correlation_id=uuid4(),
            source_channel="api",
            changed_fields=("lifecycle",),
            safe_metadata={"policy_version": "synthetic-proof"},
        ),
        **changes,
    )


def test_native_append_lends_exact_minimized_evidence_then_expires() -> None:
    record = _record()
    occurred_at = timezone.now()
    with audited_mutation(record, occurred_at=occurred_at) as evidence:
        require_audited_mutation(evidence)
        assert AuditEvent.objects.count() == 1
        assert evidence.principal_id == record.principal_id
        assert evidence.organization_id == record.organization_id
        assert evidence.event_edition_id == record.event_edition_id
        assert evidence.target_type == record.target_type
        assert evidence.target_id == record.target_id
        assert evidence.changed_fields == ("lifecycle",)
        assert evidence.occurred_at == occurred_at
        assert evidence.correlation_id == record.correlation_id
        assert evidence.capability_code == record.capability_code
        assert evidence.operation == record.operation
        assert evidence.source_channel == record.source_channel
        assert evidence.principal_kind == record.principal_kind
        assert evidence.principal_context_id is None
        assert AuditNativeMutationWitness.objects.count() == 1
    assert AuditEvent.objects.filter(pk=evidence.audit_id).exists()
    with pytest.raises(MutationEvidenceUnavailableError):
        require_audited_mutation(evidence)
    append_audit(_record())
    assert AuditNativeMutationWitness.objects.count() == 1


def test_evidence_has_no_source_values_or_metadata_payload() -> None:
    assert {field.name for field in fields(AuditedMutation)} == {
        "audit_id",
        "principal_kind",
        "principal_id",
        "principal_context_id",
        "organization_id",
        "event_edition_id",
        "capability_code",
        "operation",
        "target_type",
        "target_id",
        "changed_fields",
        "correlation_id",
        "source_channel",
        "occurred_at",
    }


@pytest.mark.parametrize("clone", [copy, deepcopy, replace])
def test_identical_reconstructed_evidence_is_not_a_live_lease(clone) -> None:
    with audited_mutation(_record()) as evidence:
        with pytest.raises(MutationEvidenceUnavailableError):
            require_audited_mutation(clone(evidence))
        require_audited_mutation(evidence)


def test_old_audit_uuid_cannot_replace_native_append() -> None:
    old_event = append_audit(_record())
    with audited_mutation(_record()) as evidence:
        forged = replace(evidence, audit_id=old_event.id)
        with pytest.raises(MutationEvidenceUnavailableError):
            require_audited_mutation(forged)
        require_audited_mutation(evidence)


def test_copied_context_is_revoked_even_while_outer_transaction_remains() -> None:
    with audited_mutation(_record()) as evidence:
        captured = copy_context()
        captured.run(require_audited_mutation, evidence)
    with pytest.raises(MutationEvidenceUnavailableError):
        captured.run(require_audited_mutation, evidence)


def test_copied_live_context_cannot_cross_thread_or_connection() -> None:
    with audited_mutation(_record()) as evidence:
        captured = copy_context()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(captured.run, require_audited_mutation, evidence)
            with pytest.raises(MutationEvidenceUnavailableError):
                result.result(timeout=10)
        require_audited_mutation(evidence)


def test_nested_mutation_temporarily_supersedes_outer_evidence() -> None:
    with audited_mutation(_record()) as outer:
        with audited_mutation(_record()) as inner:
            require_audited_mutation(inner)
            with pytest.raises(MutationEvidenceUnavailableError):
                require_audited_mutation(outer)
        require_audited_mutation(outer)
        with pytest.raises(MutationEvidenceUnavailableError):
            require_audited_mutation(inner)
    assert AuditEvent.objects.count() == 2
    assert AuditNativeMutationWitness.objects.count() == 2


def test_nested_failure_restores_outer_and_rolls_back_derived_append() -> None:
    with audited_mutation(_record()) as outer:
        with (
            pytest.raises(RuntimeError, match="synthetic join failure"),
            audited_mutation(_record()) as inner,
        ):
            _fail_derived_join(inner)
        require_audited_mutation(outer)
        with pytest.raises(MutationEvidenceUnavailableError):
            require_audited_mutation(inner)
        assert AuditEvent.objects.count() == 1


def _fail_derived_join(evidence: AuditedMutation) -> None:
    require_audited_mutation(evidence)
    append_audit(_record())
    raise RuntimeError("synthetic join failure")


def test_required_join_failure_rolls_back_whole_native_transaction() -> None:
    captured = []

    def failed_owner() -> None:
        with transaction.atomic():
            append_audit(_record())
            with audited_mutation(_record()) as evidence:
                captured.append(evidence)
                _fail_derived_join(evidence)

    with pytest.raises(RuntimeError, match="synthetic join failure"):
        failed_owner()
    assert not AuditEvent.objects.exists()
    assert not AuditNativeMutationWitness.objects.exists()
    with pytest.raises(MutationEvidenceUnavailableError):
        require_audited_mutation(captured[0])


def test_missing_audit_evidence_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    with audited_mutation(_record()) as evidence:
        require_audited_mutation(evidence)
        # Inject absence at the Audit query seam, without disabling append-only
        # guards or pretending this is a real owner rollback acceptance test.
        with monkeypatch.context() as patch:
            query_type = type(AuditEvent.objects.all())
            patch.setattr(query_type, "exists", lambda _query: False)
            with pytest.raises(MutationEvidenceUnavailableError):
                require_audited_mutation(evidence)
        require_audited_mutation(evidence)


def test_rollback_marked_transaction_rejects_evidence_without_querying() -> None:
    with transaction.atomic(), audited_mutation(_record()) as evidence:
        transaction.set_rollback(True)
        with pytest.raises(MutationEvidenceUnavailableError):
            require_audited_mutation(evidence)
        with (
            pytest.raises(MutationEvidenceUnavailableError),
            audited_mutation(_record()),
        ):
            pytest.fail("A rollback-marked transaction accepted a lease")
    assert not AuditEvent.objects.exists()


def test_manual_commit_is_forbidden_while_lease_is_live() -> None:
    with audited_mutation(_record()) as evidence:
        with pytest.raises(TransactionManagementError):
            transaction.commit()
        require_audited_mutation(evidence)


@pytest.mark.parametrize("outcome", ["deny", "error", "unknown"])
def test_non_success_cannot_lend_mutation_evidence(outcome: str) -> None:
    with (
        pytest.raises(MutationEvidenceUnavailableError),
        audited_mutation(_record(outcome=outcome)),
    ):
        pytest.fail("Non-successful audit accepted")
    assert not AuditEvent.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_native_outer_transaction_is_required_and_commit_expires_evidence() -> None:
    with pytest.raises(MutationEvidenceUnavailableError), audited_mutation(_record()):
        pytest.fail("Autocommit audit accepted")
    assert not AuditEvent.objects.exists()
    with transaction.atomic(), audited_mutation(_record()) as evidence:
        require_audited_mutation(evidence)
    assert AuditEvent.objects.filter(pk=evidence.audit_id).exists()
    with transaction.atomic(), pytest.raises(MutationEvidenceUnavailableError):
        require_audited_mutation(evidence)


def test_ordinary_audit_append_does_not_create_native_witness_state() -> None:
    append_audit(_record())
    assert not AuditNativeMutationWitness.objects.exists()


def test_setting_an_old_audit_id_does_not_mint_database_evidence() -> None:
    old = append_audit(_record())
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('maru.audit_native_event_id', %s, TRUE)", [str(old.id)]
        )
        cursor.execute("SELECT public.maru_audit_current_native_transaction_stamp()")
        stamp = cursor.fetchone()[0]
    fabricated = AuditNativeMutationWitness(
        audit_event_id=old.id, transaction_stamp=stamp, created_at=timezone.now()
    )
    with pytest.raises(ValidationError, match="database-owned"):
        fabricated.save()
    with (
        transaction.atomic(),
        pytest.raises(IntegrityError, match="actual new audit insert"),
    ):
        AuditNativeMutationWitness.objects.bulk_create([fabricated])
    assert not AuditNativeMutationWitness.objects.exists()


def test_witness_cannot_be_rewritten_or_deleted_even_by_direct_dml() -> None:
    with audited_mutation(_record()) as evidence:
        witness = AuditNativeMutationWitness.objects.get(pk=evidence.audit_id)
        assert str(witness) == "Native audit mutation witness"
        with pytest.raises(ValidationError, match="retained"):
            witness.delete()
        with transaction.atomic(), pytest.raises(IntegrityError):
            AuditNativeMutationWitness.objects.filter(pk=witness.pk).update(
                transaction_stamp="a" * 64
            )
        with transaction.atomic(), pytest.raises(IntegrityError):
            AuditNativeMutationWitness.objects.filter(pk=witness.pk).delete()
        require_audited_mutation(evidence)


def test_capture_function_cannot_be_reused_on_an_unrelated_trigger_relation() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMPORARY TABLE issue96_forged_audit (id uuid) ON COMMIT DROP"
        )
        cursor.execute(
            "CREATE TRIGGER forged_capture AFTER INSERT ON issue96_forged_audit "
            "FOR EACH ROW EXECUTE FUNCTION public.maru_audit_capture_native_mutation()"
        )
    with (
        pytest.raises(IntegrityError, match="owning relation"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("INSERT INTO issue96_forged_audit VALUES (%s)", [uuid4()])
    assert not AuditNativeMutationWitness.objects.exists()


def test_reserved_native_event_setting_is_restored_across_success_and_failure() -> None:
    sentinel = str(uuid4())
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('maru.audit_native_event_id', %s, TRUE)", [sentinel]
        )
    with audited_mutation(_record()) as evidence, connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('maru.audit_native_event_id')")
        assert cursor.fetchone()[0] == str(evidence.audit_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('maru.audit_native_event_id')")
        assert cursor.fetchone()[0] == sentinel
    with pytest.raises(RuntimeError), audited_mutation(_record()) as evidence:
        _fail_derived_join(evidence)
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('maru.audit_native_event_id')")
        assert cursor.fetchone()[0] == sentinel
