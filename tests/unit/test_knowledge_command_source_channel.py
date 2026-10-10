"""Guides adapter attribution fits Audit before writes and exact retry lookup."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db.backends.base.base import BaseDatabaseWrapper

from maru.audit.models import AuditEvent
from maru.knowledge import command_support, commands
from maru.knowledge.contracts import GuidanceCommandRequest, GuidanceDraftInput
from maru.knowledge.errors import (
    GuidanceDeniedError,
    GuidanceIdempotencyConflictError,
)
from maru.knowledge.models import GuidanceCommandReceipt


def request(source="knowledge-html"):
    return GuidanceCommandRequest(uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), source)


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("This source-boundary test must not open a database.")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", forbidden)


@pytest.mark.parametrize(
    ("source", "error", "code"),
    [
        ("s" * 41, ValidationError, "invalid_text"),
        ("s" * 80, ValidationError, "invalid_text"),
        ("🐾" * 41, ValidationError, "invalid_text"),
        ("", ValidationError, "invalid_text"),
        (None, ValidationError, "invalid_text"),
        (True, ValidationError, "invalid_text"),
        (" padded", GuidanceIdempotencyConflictError, None),
        ("padded ", GuidanceIdempotencyConflictError, None),
        ("line\r\nend", GuidanceIdempotencyConflictError, None),
        ("e\u0301", GuidanceIdempotencyConflictError, None),
        ("hidden\x00", ValidationError, "invalid_text"),
    ],
)
def test_public_create_rejects_bad_attribution_before_any_write_or_retry(
    monkeypatch, source, error, code
):
    # Source normalization is downstream of actual public purpose admission.
    admit = Mock()
    monkeypatch.setattr(commands, "authorize_guidance_scope", admit)
    forbidden = Mock(side_effect=AssertionError("No command or audit work allowed"))
    for name in (
        "authorize_guidance_scope",
        "require_knowledge_integrity",
        "append_audit",
        "publish_domain_event",
        "audited_mutation",
    ):
        monkeypatch.setattr(command_support, name, forbidden)
    monkeypatch.setattr(command_support.transaction, "atomic", forbidden)
    monkeypatch.setattr(
        command_support.GuidanceCommandReceipt.objects, "filter", forbidden
    )
    with pytest.raises(error) as caught:
        commands.create_guidance(
            request(source),
            draft=GuidanceDraftInput("Synthetic title", "Synthetic body", "en"),
            expected_settings_version=1,
        )
    if code is not None:
        assert caught.value.code == code
    admit.assert_called_once()
    forbidden.assert_not_called()


@pytest.fixture
def admitted_executor(monkeypatch):
    scope = SimpleNamespace(decision=SimpleNamespace(reason_code="allowed"))
    authorize = Mock(return_value=scope)
    monkeypatch.setattr(command_support, "authorize_guidance_scope", authorize)
    monkeypatch.setattr(command_support, "require_knowledge_integrity", lambda: None)
    monkeypatch.setattr(command_support.transaction, "atomic", nullcontext)
    monkeypatch.setattr(
        command_support, "resolve_knowledge_edition_scope", lambda **_kwargs: object()
    )
    monkeypatch.setattr(
        command_support, "lock_account_references_for_evidence", lambda **_kwargs: ()
    )
    receipts = Mock()
    receipts.filter.return_value.first.return_value = None
    receipts.create.side_effect = SimpleNamespace
    monkeypatch.setattr(
        command_support, "GuidanceCommandReceipt", SimpleNamespace(objects=receipts)
    )
    control = SimpleNamespace(sequence=0, save=Mock())
    controls = Mock()
    controls.select_for_update.return_value.filter.return_value.first.return_value = (
        control
    )
    monkeypatch.setattr(
        command_support, "GuidanceControl", SimpleNamespace(objects=controls)
    )
    audits = Mock(
        side_effect=lambda *_args, **_kwargs: nullcontext(
            SimpleNamespace(audit_id=uuid4())
        )
    )
    monkeypatch.setattr(command_support, "audited_mutation", audits)
    errors = Mock()
    monkeypatch.setattr(command_support, "append_audit", errors)
    monkeypatch.setattr(command_support, "publish_domain_event", Mock())
    monkeypatch.setattr(
        command_support, "require_complete_evidence_bound", lambda _item: None
    )
    write = Mock(return_value=(uuid4(), uuid4(), 1))
    return SimpleNamespace(
        receipts=receipts,
        control=control,
        audits=audits,
        errors=errors,
        write=write,
        authorize=authorize,
    )


def execute(value, env):
    return command_support.execute(
        value, operation="create", intent={"synthetic": True}, write=env.write
    )


@pytest.mark.parametrize("source", ["s" * 40, "🐾" * 40, "knowledge-html"])
def test_exact_source_reaches_receipt_audit_and_replay_without_truncation(
    admitted_executor, source
):
    env = admitted_executor
    value = request(source)
    first = execute(value, env)
    retained = env.receipts.create.call_args.kwargs
    audit = env.audits.call_args.args[0]
    assert retained["source_channel"] == audit.source_channel == source
    assert AuditEvent._meta.get_field("source_channel").clean(source, None) == source
    env.receipts.filter.return_value.first.return_value = SimpleNamespace(**retained)
    replay = execute(value, env)
    assert replay == replace(first, replayed=True)
    env.write.assert_called_once()
    env.receipts.create.assert_called_once()
    env.audits.assert_called_once()
    env.errors.assert_not_called()


def test_retry_rejects_invalid_source_before_lookup_and_changed_valid_source_conflicts(
    admitted_executor,
):
    env = admitted_executor
    value = request("s" * 40)
    execute(value, env)
    env.receipts.filter.return_value.first.return_value = SimpleNamespace(
        **env.receipts.create.call_args.kwargs
    )
    reads = env.receipts.filter.call_count
    with pytest.raises(ValidationError):
        execute(replace(value, source_channel="s" * 41), env)
    assert env.receipts.filter.call_count == reads
    with pytest.raises(GuidanceIdempotencyConflictError):
        execute(replace(value, source_channel="t" * 40), env)
    env.write.assert_called_once()
    env.audits.assert_called_once()
    assert env.errors.call_args.args[0].source_channel == "t" * 40


def test_original_retry_still_requires_current_authority(admitted_executor):
    env = admitted_executor
    value = request()
    execute(value, env)
    env.receipts.filter.return_value.first.return_value = SimpleNamespace(
        **env.receipts.create.call_args.kwargs
    )
    env.authorize.side_effect = GuidanceDeniedError
    reads = env.receipts.filter.call_count
    with pytest.raises(GuidanceDeniedError):
        execute(value, env)
    assert env.receipts.filter.call_count == reads
    env.write.assert_called_once()


def test_producer_limit_tracks_audit_without_narrowing_historical_receipt_schema():
    assert (
        AuditEvent._meta.get_field("source_channel").max_length
        == command_support._MAX_AUDIT_SOURCE_CHANNEL
    )
    assert GuidanceCommandReceipt._meta.get_field("source_channel").max_length == 80
