"""Unit decision coverage for Programme replay and optimistic versions."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

import maru.programme.commands as programme_commands


def _receipt(*, request_digest: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        item_id=uuid4(),
        result_object_id=uuid4(),
        expected_version=4,
        resulting_item_version=5,
        resulting_control_version=None,
        request_digest=request_digest,
    )


def _set_receipt_lookup(
    monkeypatch: pytest.MonkeyPatch,
    receipt: SimpleNamespace | None,
) -> None:
    lookup = SimpleNamespace(
        filter=lambda **_kwargs: SimpleNamespace(first=lambda: receipt)
    )
    monkeypatch.setattr(
        programme_commands.ProgrammeCommandReceipt.objects,
        "select_for_update",
        lambda: lookup,
    )


def test_replay_returns_the_canonical_receipt_before_version_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return an exact prior result even when its expected version is old."""
    digest = "a" * 64
    receipt = _receipt(request_digest=digest)
    _set_receipt_lookup(monkeypatch, receipt)

    result = programme_commands._replay(
        actor_id=uuid4(),
        edition_id=uuid4(),
        idempotency_key=uuid4(),
        request_digest=digest,
    )

    assert result is not None
    assert result.replayed
    assert result.receipt_id == receipt.id
    assert result.resulting_item_version == 5


def test_replay_rejects_key_reuse_with_a_different_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject semantic key reuse before an optimistic-version decision."""
    _set_receipt_lookup(monkeypatch, _receipt(request_digest="a" * 64))

    with pytest.raises(programme_commands.ProgrammeIdempotencyConflictError):
        programme_commands._replay(
            actor_id=uuid4(),
            edition_id=uuid4(),
            idempotency_key=uuid4(),
            request_digest="b" * 64,
        )


def test_missing_replay_and_optimistic_version_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Continue on a missing receipt and reject only a mismatched version."""
    _set_receipt_lookup(monkeypatch, None)

    assert (
        programme_commands._replay(
            actor_id=uuid4(),
            edition_id=uuid4(),
            idempotency_key=uuid4(),
            request_digest="a" * 64,
        )
        is None
    )
    assert programme_commands._require_version(actual=7, expected=7) is None
    with pytest.raises(programme_commands.ProgrammeVersionConflictError):
        programme_commands._require_version(actual=7, expected=6)


def test_unknown_evidence_source_preserves_input_code_and_audit_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Classify an unregistered caller source as invalid input."""
    audit_append = MagicMock()
    monkeypatch.setattr(programme_commands, "append_audit", audit_append)
    monkeypatch.setattr(
        programme_commands,
        "_preauthorize",
        lambda **_kwargs: None,
    )

    with pytest.raises(ValidationError) as raised:
        programme_commands.record_programme_readiness_evidence(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            item_id=uuid4(),
            concern="public_copy",
            state="satisfied",
            source_code="programme.evidence.unregistered@1",
            expected_version=1,
            reason="Reject an unregistered evidence source.",
            idempotency_key=uuid4(),
            correlation_id=uuid4(),
            source_channel="service",
        )

    assert programme_commands._validation_error_codes(raised.value) == frozenset(
        {"programme_closed_value_invalid"}
    )
    audit_append.assert_called_once()
    audit = audit_append.call_args.args[0]
    assert audit.operation == "programme.command.readiness_record"
    assert audit.outcome == "error"
    assert audit.reason_code == "programme_input_invalid"


def test_error_audit_rejects_non_ascii_source_channel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace a Unicode confusable with the registered fallback channel."""
    audit_append = MagicMock()
    monkeypatch.setattr(programme_commands, "append_audit", audit_append)

    programme_commands._append_error_audit_best_effort(
        error=ValidationError("Invalid source channel."),
        actor_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        capability_code="programme.manage_items",
        operation="item_create",
        correlation_id=uuid4(),
        source_channel="é",
    )

    audit_append.assert_called_once()
    assert audit_append.call_args.args[0].source_channel == "service"
