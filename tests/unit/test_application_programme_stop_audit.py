"""Native witness routing is restricted to stopped, successful cleanup intents."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.applications import programme_stop_audit as boundary
from maru.audit.services import AuditRecord
from maru.events.programme_stop_queries import ProgrammeStopReference


def record(operation, **overrides):
    return AuditRecord(
        **{
            "principal_kind": "account",
            "principal_id": uuid4(),
            "principal_context_id": None,
            "organization_id": uuid4(),
            "event_edition_id": uuid4(),
            "capability_code": "applications.manage_programme_calls",
            "operation": operation,
            "target_type": "applications.programme_call",
            "target_id": uuid4(),
            "outcome": "allow",
            "reason_code": "allowed",
            "correlation_id": uuid4(),
            "source_channel": "test",
            **overrides,
        }
    )


@pytest.mark.parametrize("operation", sorted(boundary._CLEANUP_OPERATIONS))
@pytest.mark.parametrize("stopped", [True, False])
def test_successful_cleanup_uses_native_witness_only_for_exact_stopped_scope(
    monkeypatch,
    operation,
    stopped,
):
    query = MagicMock(
        return_value=ProgrammeStopReference(applies=True, is_stopped=stopped, version=4)
    )
    append = MagicMock(return_value=SimpleNamespace(id=uuid4()))
    native = MagicMock()
    native.return_value.__enter__.return_value = SimpleNamespace(audit_id=uuid4())
    monkeypatch.setattr(boundary, "resolve_programme_stop_reference", query)
    monkeypatch.setattr(boundary, "append_audit", append)
    monkeypatch.setattr(boundary, "audited_mutation", native)
    event = record(operation)
    key, when = uuid4(), datetime.now(UTC)
    result = boundary._append_cleanup_audit(event, occurred_at=when, retry_key=key)
    query.assert_called_once_with(
        organization_id=event.organization_id, edition_id=event.event_edition_id
    )
    assert native.call_count == int(stopped)
    assert append.call_count == int(not stopped)
    if stopped:
        retained = native.call_args.args[0]
        assert (
            retained.idempotency_key_hash
            == hashlib.sha256(str(key).encode()).hexdigest()
        )
        assert retained.correlation_id == event.correlation_id
        assert result.id == native.return_value.__enter__.return_value.audit_id
    else:
        append.assert_called_once_with(event, occurred_at=when)
        assert result.id == append.return_value.id


@pytest.mark.parametrize("denied", [True, False])
def test_ordinary_or_denied_audit_does_not_consult_stop_scope(monkeypatch, denied):
    query, append, native = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(boundary, "resolve_programme_stop_reference", query)
    monkeypatch.setattr(boundary, "append_audit", append)
    monkeypatch.setattr(boundary, "audited_mutation", native)
    event = record(
        "applications.programme.command.call_retired"
        if denied
        else "applications.programme.command.call_created",
        outcome="deny" if denied else "allow",
    )
    boundary._append_cleanup_audit(
        event, occurred_at=datetime.now(UTC), retry_key=uuid4()
    )
    query.assert_not_called()
    native.assert_not_called()
    append.assert_called_once()


def test_missing_stop_scope_refuses_before_any_success_evidence(monkeypatch):
    monkeypatch.setattr(boundary, "resolve_programme_stop_reference", lambda **_: None)
    append, native = MagicMock(), MagicMock()
    monkeypatch.setattr(boundary, "append_audit", append)
    monkeypatch.setattr(boundary, "audited_mutation", native)
    with pytest.raises(boundary.ProgrammeCleanupUnavailableError):
        boundary._append_cleanup_audit(
            record("applications.programme.command.call_retired"),
            occurred_at=datetime.now(UTC),
            retry_key=uuid4(),
        )
    append.assert_not_called()
    native.assert_not_called()
