"""Route only successful stopped-scope revocation to native Audit evidence."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.authorization import commands
from maru.authorization.services import AuthorizationDenied
from maru.events.programme_stop_queries import ProgrammeStopReference


def _audit_command(*, edition_id, operation="authorization.capability.revoke"):
    return commands._CommandAudit(
        capability_code="authorization.revoke",
        operation=operation,
        target_type="authorization.capability_grant",
        target_id=uuid4(),
        organization_id=uuid4(),
        edition_id=edition_id,
        correlation_id=uuid4(),
        request_id=None,
        source_channel="test",
        obligations=(),
        changed_fields=("revoked_at",),
    )


@pytest.mark.parametrize("stopped", [True, False])
@pytest.mark.parametrize(
    "operation", ["authorization.capability.revoke", "authorization.role.revoke"]
)
def test_only_stopped_revocation_lends_native_audit_evidence(
    monkeypatch, stopped, operation
):
    command = _audit_command(edition_id=uuid4(), operation=operation)
    query = MagicMock(
        return_value=ProgrammeStopReference(applies=True, is_stopped=stopped, version=4)
    )
    append = MagicMock(return_value=SimpleNamespace(id=uuid4()))
    native = MagicMock()
    native.return_value.__enter__.return_value = SimpleNamespace(audit_id=uuid4())
    monkeypatch.setattr(commands, "resolve_programme_stop_reference", query)
    monkeypatch.setattr(commands, "append_audit", append)
    monkeypatch.setattr(commands, "audited_mutation", native)
    result = commands._append_command_audit(
        principal=SimpleNamespace(id=uuid4()),
        command=command,
        outcome="allow",
        reason_code="permitted",
    )
    query.assert_called_once_with(
        organization_id=command.organization_id, edition_id=command.edition_id
    )
    assert native.call_count == int(stopped)
    assert append.call_count == int(not stopped)
    if stopped:
        assert result.id == native.return_value.__enter__.return_value.audit_id
        record = native.call_args.args[0]
        assert record.operation == operation
        assert record.target_id == command.target_id
        assert record.changed_fields == ("revoked_at",)
    else:
        assert result is append.return_value


@pytest.mark.parametrize("case", ["shared", "denied", "other_operation", "approval"])
def test_shared_denied_and_nonrevocation_audits_keep_existing_path(monkeypatch, case):
    command = _audit_command(
        edition_id=None if case == "shared" else uuid4(),
        operation="authorization.capability.grant"
        if case == "other_operation"
        else "authorization.capability.revoke",
    )
    query, append, native = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(commands, "resolve_programme_stop_reference", query)
    monkeypatch.setattr(commands, "append_audit", append)
    monkeypatch.setattr(commands, "audited_mutation", native)
    commands._append_command_audit(
        principal=SimpleNamespace(id=uuid4()),
        command=command,
        outcome="deny" if case == "denied" else "allow",
        reason_code="synthetic",
        approval=case == "approval",
    )
    append.assert_called_once()
    query.assert_not_called()
    native.assert_not_called()


def test_missing_current_scope_cannot_produce_success_or_native_witness(monkeypatch):
    monkeypatch.setattr(
        commands, "resolve_programme_stop_reference", lambda **_kwargs: None
    )
    append, native = MagicMock(), MagicMock()
    monkeypatch.setattr(commands, "append_audit", append)
    monkeypatch.setattr(commands, "audited_mutation", native)
    with pytest.raises(AuthorizationDenied, match="scope is unavailable"):
        commands._append_command_audit(
            principal=SimpleNamespace(id=uuid4()),
            command=_audit_command(edition_id=uuid4()),
            outcome="allow",
            reason_code="synthetic",
        )
    append.assert_not_called()
    native.assert_not_called()
