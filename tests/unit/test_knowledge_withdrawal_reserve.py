"""Byte admission preserves one bounded withdrawal without increasing the cap."""

import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.knowledge import evidence_bound
from maru.knowledge.catalog import (
    MAX_NOTE,
    MAX_STORED_TEXT_BYTES,
    WITHDRAWAL_RECEIPT_RESERVE_BYTES,
)
from maru.knowledge.errors import GuidanceLimitError
from maru.knowledge.inputs import text
from maru.knowledge.models import GuidanceCommandReceipt


@pytest.mark.parametrize(
    "status", ["draft", "in_review", "changes_requested", "approved"]
)
@pytest.mark.parametrize("extra_byte", [False, True])
def test_available_or_unfinished_item_keeps_full_withdrawal_allowance(
    monkeypatch, status, extra_byte
):
    cursor = MagicMock()
    cursor.fetchone.return_value = (
        MAX_STORED_TEXT_BYTES - WITHDRAWAL_RECEIPT_RESERVE_BYTES + extra_byte,
        status,
    )
    database = MagicMock()
    database.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(evidence_bound, "connection", database)
    item_id = uuid4()
    if extra_byte:
        with pytest.raises(GuidanceLimitError):
            evidence_bound.require_complete_evidence_bound(item_id)
    else:
        evidence_bound.require_complete_evidence_bound(item_id)
    assert cursor.execute.call_args.args[1] == [item_id]


@pytest.mark.parametrize("extra_byte", [False, True])
def test_withdrawn_item_may_spend_reserve_but_never_exceed_total(
    monkeypatch, extra_byte
):
    database = MagicMock()
    database.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        MAX_STORED_TEXT_BYTES + extra_byte,
        "withdrawn",
    )
    monkeypatch.setattr(evidence_bound, "connection", database)
    if extra_byte:
        with pytest.raises(GuidanceLimitError):
            evidence_bound.require_complete_evidence_bound(uuid4())
    else:
        evidence_bound.require_complete_evidence_bound(uuid4())


def test_absent_item_never_counts_as_a_funded_withdrawal(monkeypatch):
    database = MagicMock()
    database.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        0,
        None,
    )
    monkeypatch.setattr(evidence_bound, "connection", database)
    with pytest.raises(GuidanceLimitError):
        evidence_bound.require_complete_evidence_bound(uuid4())


def test_edition_control_command_does_not_consume_an_item_reserve(monkeypatch):
    database = MagicMock()
    monkeypatch.setattr(evidence_bound, "connection", database)
    evidence_bound.require_complete_evidence_bound(None)
    database.cursor.assert_not_called()


@pytest.mark.parametrize("symbol", ["\U0001f43e", '"', "\\"])
def test_current_receipt_shape_and_maximum_legal_text_fit_reserved_bytes(symbol):
    reason = symbol * MAX_NOTE
    source = symbol * 80
    assert text(reason, maximum=MAX_NOTE) == reason
    assert text(source, maximum=80) == source
    identifier = str(uuid4())
    row = dict.fromkeys(
        (
            "id",
            "organization_id",
            "edition_id",
            "actor_id",
            "idempotency_key",
            "item_id",
            "object_id",
            "correlation_id",
        ),
        identifier,
    )
    row.update(
        operation="withdraw",
        request_digest="f" * 64,
        control_sequence=2**63 - 1,
        resulting_version=4096,
        created_at="9999-12-31T23:59:59.999999+00:00",
        updated_at="9999-12-31T23:59:59.999999+00:00",
        occurred_at="9999-12-31T23:59:59.999999+00:00",
        reason=reason,
        source_channel=source,
    )
    # A new retained field must trigger a fresh reserve review. This Python
    # encoding check is separate from the actual PostgreSQL byte assertion.
    assert set(row) == {
        field.attname for field in GuidanceCommandReceipt._meta.concrete_fields
    }
    assert len(json.dumps(row, ensure_ascii=False).encode()) < (
        WITHDRAWAL_RECEIPT_RESERVE_BYTES
    )
