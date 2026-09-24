"""The invitation cutover never becomes a flag-only readiness shortcut."""

from dataclasses import replace
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from django.core.exceptions import ValidationError

from maru.identity import invitation_readiness, invitation_writer_readiness, services


@pytest.mark.parametrize("purpose", ["account_invitation", "unknown", "", None, []])
@pytest.mark.parametrize("operation", ["issue", "consume"])
def test_generic_challenges_refuse_other_purposes_before_side_effects(
    monkeypatch, purpose, operation
):
    abuse = Mock(side_effect=AssertionError("must not write abuse state"))
    digest = Mock(side_effect=AssertionError("must not hash unsupported tokens"))
    raw = Mock(side_effect=AssertionError("must not create unsupported tokens"))
    monkeypatch.setattr(services, "enforce_abuse_limit", abuse)
    monkeypatch.setattr(services, "_digest", digest)
    monkeypatch.setattr(services, "_raw_challenge_token", raw)
    command, arguments = (
        (
            services.issue_identity_challenge,
            {
                "account": Mock(),
                "purpose": purpose,
                "fingerprint": "synthetic",
                "source_channel": "test",
            },
        )
        if operation == "issue"
        else (
            services.consume_identity_challenge,
            {"raw_token": "private", "purpose": purpose},
        )
    )
    with pytest.raises(ValidationError) as error:
        command(**arguments)
    assert error.value.code == "identity_challenge_purpose_invalid"
    abuse.assert_not_called()
    digest.assert_not_called()
    raw.assert_not_called()


def test_generation_declares_exact_native_evidence_not_a_boolean_override(monkeypatch):
    contract = invitation_writer_readiness.INVITATION_WRITER_INTEGRITY_CONTRACT
    assert contract.source_contract_current
    assert (
        contract.source_migration
        == contract.terminal_migration
        == (
            "identity",
            "0023_invitation_writer_cutover",
        )
    )
    assert set(contract.functions) == {"maru_identity_invitation_writer_guard()"}
    assert len(contract.triggers) == 1
    assert not contract.runtime_executable_functions
    assert not next(iter(contract.functions.values())).security_definer
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = []
    monkeypatch.setattr(
        invitation_writer_readiness.connection, "cursor", Mock(return_value=cursor)
    )
    assert not invitation_writer_readiness.invitation_writer_generation_is_ready()
    assert cursor.execute.call_args.args[1] == contract.source_migration


def test_operator_gate_observes_actual_generation_not_the_expected_label(monkeypatch):
    monkeypatch.setattr(
        invitation_readiness,
        "invitation_writer_generation_is_ready",
        Mock(return_value=False),
    )
    for name in (
        "_configured_runtime_database_role_is_safe",
        "invitation_encryption_is_ready",
        "invitation_token_keys_are_ready",
        "platform_invitation_digest_key_coverage_is_ready",
        "platform_invitation_delivery_heartbeat_is_ready",
        "platform_invitation_expiry_heartbeat_is_ready",
        "platform_invitation_retention_heartbeat_is_ready",
        "platform_account_prefix_query_plan_is_ready",
    ):
        monkeypatch.setattr(invitation_readiness, name, Mock(return_value=True))
    assert invitation_readiness.PAGE10_INVITATION_STOPPED_WRITER_GENERATION
    gates = invitation_readiness._platform_invitation_production_gates(
        SimpleNamespace(additive_contract_ready=True)
    )
    assert gates["stopped_writer_generation"] is False


@pytest.mark.parametrize("defect", ["source", "function", "shape", "connection"])
def test_invalid_writer_contract_or_catalog_fails_closed(monkeypatch, defect):
    contract = invitation_writer_readiness.INVITATION_WRITER_INTEGRITY_CONTRACT
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = [(True,)]
    if defect == "source":
        contract = replace(contract, source_contract_current=False)
    elif defect == "function":
        contract = replace(contract, functions={"unexpected()": Mock()})
    elif defect == "connection":
        cursor.execute.side_effect = invitation_writer_readiness.DatabaseError()
    monkeypatch.setattr(
        invitation_writer_readiness, "INVITATION_WRITER_INTEGRITY_CONTRACT", contract
    )
    monkeypatch.setattr(
        invitation_writer_readiness.connection, "cursor", Mock(return_value=cursor)
    )
    assert not invitation_writer_readiness.invitation_writer_generation_is_ready()


@pytest.mark.parametrize("index", range(30))
def test_every_observed_writer_attribute_is_required(monkeypatch, index):
    migration = import_module("maru.identity.migrations.0023_invitation_writer_cutover")
    row = [
        True,
        migration.FORWARD_SQL.split("$invitation_writer$")[1],
        "plpgsql",
        "v",
        "u",
        False,
        False,
        False,
        False,
        "f",
        ["search_path=pg_catalog, public, pg_temp"],
        "trigger",
        True,
        True,
        "public",
        "identity_identitychallenge",
        "r",
        "maru_identity_invitation_writer",
        23,
        "O",
        False,
        False,
        False,
        False,
        0,
        True,
        "",
        "public",
        "maru_identity_invitation_writer_guard",
        "",
    ]
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.fetchall.return_value = [row]
    monkeypatch.setattr(
        invitation_writer_readiness.connection, "cursor", Mock(return_value=cursor)
    )
    assert invitation_writer_readiness.invitation_writer_generation_is_ready()
    row[index] = None
    assert not invitation_writer_readiness.invitation_writer_generation_is_ready()
