"""Real retained-byte boundaries preserve withdrawal and atomic native evidence."""

import json
from contextlib import contextmanager
from dataclasses import replace

import pytest
from django.db import DatabaseError, connection, transaction

from maru.audit.models import (
    AuditEvent,
    AuditIntegrityBatch,
    AuditNativeMutationWitness,
)
from maru.effects.models import (
    DomainEvent,
    EffectAttempt,
    EffectReplayReceipt,
    OutboxMessage,
)
from maru.knowledge import command_support, commands, queries
from maru.knowledge.catalog import (
    MAX_BODY,
    MAX_EXPORT_BYTES,
    MAX_HISTORY,
    MAX_NOTE,
    MAX_REVISIONS,
    MAX_STORED_TEXT_BYTES,
    WITHDRAWAL_RECEIPT_RESERVE_BYTES,
)
from maru.knowledge.errors import GuidanceLimitError, GuidanceNotAvailableError
from maru.knowledge.models import (
    GuidanceCommandReceipt,
    GuidanceControl,
    GuidanceItem,
    GuidanceReview,
    GuidanceRevision,
    GuidanceSettingsRevision,
)
from tests.integration.guidance_test_support import guidance_runtime
from tests.integration.test_knowledge_domain import (
    approved,
    draft,
    native,
    read_request,
    request,
    world,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]
__all__ = ["guidance_runtime", "world"]

_SYMBOL = "\U0001f43e"
_REVISE_REASON = "Retain another complete synthetic replacement draft."
_RESERVE_DIAGNOSTIC = "Guidance must retain space for one reasoned withdrawal"


def _retained_bytes(item_id):
    """Measure actual stored JSONB bytes; never accept caller-supplied totals."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            WITH revisions AS (
                SELECT * FROM knowledge_guidancerevision WHERE item_id=%s
            ), rules AS (
                SELECT * FROM knowledge_guidancesettingsrevision
                WHERE id IN (SELECT settings_revision_id FROM revisions)
            ), records AS (
                SELECT to_jsonb(row) record FROM revisions row
                UNION ALL SELECT to_jsonb(row) FROM knowledge_guidancereview row
                    WHERE revision_id IN (SELECT id FROM revisions)
                UNION ALL SELECT to_jsonb(row) FROM rules row
                UNION ALL SELECT to_jsonb(row) FROM knowledge_guidancecommandreceipt row
                    WHERE item_id=%s OR id IN (SELECT command_receipt_id FROM rules)
            ) SELECT sum(octet_length(record::text)) FROM records
            """,
            [item_id, item_id],
        )
        return cursor.fetchone()[0]


def _state():
    """Keep complete owner, Audit witness and outbox row values."""
    return {
        model._meta.label: list(model.objects.order_by("pk").values())
        for model in (
            GuidanceControl,
            GuidanceSettingsRevision,
            GuidanceItem,
            GuidanceRevision,
            GuidanceReview,
            GuidanceCommandReceipt,
            AuditEvent,
            AuditIntegrityBatch,
            AuditNativeMutationWitness,
            DomainEvent,
            OutboxMessage,
            EffectAttempt,
            EffectReplayReceipt,
        )
    }


@contextmanager
def _refused_without_residue(error_type, *, diagnostic=None):
    before = _state()
    with transaction.atomic():
        try:
            with pytest.raises(error_type) as refused:
                yield
            if diagnostic is not None:
                cause = refused.value.__cause__
                assert cause.sqlstate == "23514"
                assert cause.diag.message_primary == diagnostic
            # native() has already unwound its inner savepoint. This assertion
            # proves the attempted command rolled back, before test cleanup can
            # hide residue from an unexpectedly admitted or partially saved write.
            assert _state() == before
        finally:
            transaction.set_rollback(True)
    assert _state() == before


def _revise(world, current, body):
    return native(
        commands.revise_guidance,
        request(world),
        item_id=current.item_id,
        expected_version=current.version,
        expected_settings_version=1,
        draft=draft(body=body),
        reason=_REVISE_REASON,
    )


def _full_history_before_tail(world):
    """Use only normal owning commands to approach the real eight-MiB budget."""
    current = approved(world)
    old_copy = queries.load_current_guidance(
        read_request(world), item_id=current.item_id
    )
    limit = MAX_STORED_TEXT_BYTES - WITHDRAWAL_RECEIPT_RESERVE_BYTES
    full_body = _SYMBOL * MAX_BODY
    body_bytes = len(full_body.encode())
    previous = _retained_bytes(current.item_id)
    current = _revise(world, current, full_body)
    measured = _retained_bytes(current.item_id)
    overhead = measured - previous - body_bytes
    assert 0 < overhead < 8192
    # Leave 128 bytes for timestamp-width/counter changes in the final revision.
    # The final assertions fail if this engineering margin ever stops sufficing.
    while limit - measured >= body_bytes + overhead + 128:
        previous = measured
        current = _revise(world, current, full_body)
        measured = _retained_bytes(current.item_id)
        overhead = measured - previous - body_bytes
        assert GuidanceRevision.objects.filter(item_id=current.item_id).count() < (
            MAX_REVISIONS - 1
        )
    available = limit - measured - overhead - 128
    assert 0 < available < body_bytes
    final_body = _SYMBOL * (available // len(_SYMBOL.encode()))
    assert 0 < len(final_body) <= MAX_BODY
    return current, final_body, old_copy


def _assert_near_reserve(current):
    measured = _retained_bytes(current.item_id)
    limit = MAX_STORED_TEXT_BYTES - WITHDRAWAL_RECEIPT_RESERVE_BYTES
    assert 0 <= limit - measured <= 256
    assert (
        GuidanceRevision.objects.filter(item_id=current.item_id).count() < MAX_REVISIONS
    )
    assert current.version < MAX_HISTORY - 1
    return measured


def _assert_withdrawal(world, result, reason):
    receipt = GuidanceCommandReceipt.objects.get(id=result.receipt_id)
    assert receipt.reason == reason
    assert len(receipt.reason) == MAX_NOTE
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT octet_length(to_jsonb(row)::text) "
            "FROM knowledge_guidancecommandreceipt row WHERE id=%s",
            [result.receipt_id],
        )
        assert cursor.fetchone()[0] <= WITHDRAWAL_RECEIPT_RESERVE_BYTES
    total = _retained_bytes(result.item_id)
    assert total > MAX_STORED_TEXT_BYTES - WITHDRAWAL_RECEIPT_RESERVE_BYTES
    assert total <= MAX_STORED_TEXT_BYTES
    item = GuidanceItem.objects.get(id=result.item_id)
    assert (item.status, item.withdrawn, item.published_revision_id) == (
        "withdrawn",
        True,
        None,
    )
    assert item.approved_revision_id is not None
    audit = AuditEvent.objects.get(
        event_edition_id=world[1].id,
        correlation_id=receipt.correlation_id,
        operation="knowledge.command.withdraw",
        outcome="allow",
    )
    event = DomainEvent.objects.get(
        event_name="knowledge.changed.v1",
        event_edition_id=world[1].id,
        aggregate_version=receipt.control_sequence,
    )
    assert event.causation_id == audit.id
    assert event.payload == {"operation": "withdraw"}
    assert OutboxMessage.objects.filter(event_id=event.id).count() == 1
    with pytest.raises(GuidanceNotAvailableError):
        queries.load_current_guidance(read_request(world), item_id=result.item_id)
    assert not queries.load_context_guidance(
        read_request(world), context="knowledge.compose"
    ).items


def test_full_history_refuses_growth_but_maximum_reason_withdrawal_and_retry_work(
    world, monkeypatch
):
    current, tail, old_copy = _full_history_before_tail(world)
    current = _revise(world, current, tail)
    before_bytes = _assert_near_reserve(current)
    assert (
        queries.load_current_guidance(read_request(world), item_id=current.item_id)
        == old_copy
    )
    with _refused_without_residue(GuidanceLimitError):
        _revise(world, current, "A further complete private draft.")
    assert (
        queries.load_current_guidance(read_request(world), item_id=current.item_id)
        == old_copy
    )
    # Isolate the native reserve by fault-injecting only the application byte
    # callback. Authority, evidence writers and every native guard stay active.
    with monkeypatch.context() as patch:
        patch.setattr(
            command_support, "require_complete_evidence_bound", lambda _: None
        )
        with _refused_without_residue(DatabaseError, diagnostic=_RESERVE_DIAGNOSTIC):
            _revise(world, current, "A further complete private draft.")
    assert _retained_bytes(current.item_id) == before_bytes
    assert (
        queries.load_current_guidance(read_request(world), item_id=current.item_id)
        == old_copy
    )
    reason = _SYMBOL * MAX_NOTE
    # Audit is the narrower shared boundary (40 characters); Guidance's stored
    # receipt permits 80. Exercise the actual public command, not that mismatch.
    intent = replace(request(world), source_channel=_SYMBOL * 40)
    withdrawn = native(
        commands.withdraw_guidance,
        intent,
        item_id=current.item_id,
        expected_version=current.version,
        reason=reason,
    )
    _assert_withdrawal(world, withdrawn, reason)
    artifact = queries.export_guidance_evidence(
        read_request(world), item_id=current.item_id
    )
    assert len(artifact.content) <= MAX_EXPORT_BYTES
    evidence = json.loads(artifact.content)["content"]
    assert sorted(row["id"] for row in evidence["revisions"]) == sorted(
        str(value)
        for value in GuidanceRevision.objects.filter(
            item_id=current.item_id
        ).values_list("id", flat=True)
    )
    exported_receipts = sorted(
        row["id"]
        for row in evidence["receipts"]
        if row["item_id"] == str(current.item_id)
    )
    assert exported_receipts == sorted(
        str(value)
        for value in GuidanceCommandReceipt.objects.filter(
            item_id=current.item_id
        ).values_list("id", flat=True)
    )
    assert str(withdrawn.receipt_id) in exported_receipts
    # The protected export may audit; the retry snapshot starts after that read.
    before_retry = _state()
    replay = native(
        commands.withdraw_guidance,
        intent,
        item_id=current.item_id,
        expected_version=current.version,
        reason=reason,
    )
    assert replay.receipt_id == withdrawn.receipt_id
    assert replay.replayed
    assert _state() == before_retry
    # Withdrawing spends the reserve; it is not a permanent exemption for new work.
    with _refused_without_residue(GuidanceLimitError):
        _revise(world, withdrawn, "New work needs a new withdrawal allowance.")


def test_final_withdrawal_head_releases_reserve_for_earlier_command_in_same_transaction(
    world,
):
    current, tail, _old_copy = _full_history_before_tail(world)
    reason = _SYMBOL * MAX_NOTE
    with transaction.atomic():
        revised = commands.revise_guidance(
            request(world),
            item_id=current.item_id,
            expected_version=current.version,
            expected_settings_version=1,
            draft=draft(body=tail),
            reason=_REVISE_REASON,
        )
        _assert_near_reserve(revised)
        withdrawn = commands.withdraw_guidance(
            request(world),
            item_id=current.item_id,
            expected_version=revised.version,
            reason=reason,
        )
        # The final bytes consume the reserve before either deferred receipt
        # trigger runs. NEW.operation='revise' must not demand another reserve.
        assert _retained_bytes(current.item_id) > (
            MAX_STORED_TEXT_BYTES - WITHDRAWAL_RECEIPT_RESERVE_BYTES
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    assert withdrawn.version == current.version + 2
    _assert_withdrawal(world, withdrawn, reason)
