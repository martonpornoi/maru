"""The native readiness proof must recognize every declared Guidance helper."""

from importlib import import_module

import pytest

from maru.announcements import readiness as announcements_readiness
from maru.authorization.provenance_readiness import (
    _GUIDANCE_REPLACED_FUNCTION_SHA256,
)
from maru.core.database_integrity_readiness import build_database_integrity_contract


def test_guidance_native_source_and_executable_identities_are_consistent():
    module = import_module(
        "maru.authorization.migrations.0046_guidance_authority_integrity"
    )
    contract = build_database_integrity_contract(
        status_key="guidance_authority_integrity",
        app_label="authorization",
        source_migration=("authorization", "0046_guidance_authority_integrity"),
        terminal_migration=("authorization", "0047_guidance_qualified_lineage"),
        source_migration_module=module.__name__,
    )
    assert contract.source_contract_current
    assert set(module.NEW_FUNCTION_IDENTITIES) <= contract.functions.keys()


def test_guidance_replaced_function_inventory_covers_both_lineage_successors():
    for name in (
        "0044_workspace_operator_lineage",
        "0046_guidance_authority_integrity",
    ):
        module = import_module(f"maru.authorization.migrations.{name}")
        assert set(module._IDENTITIES) <= _GUIDANCE_REPLACED_FUNCTION_SHA256.keys()


def test_guidance_announcements_successor_retains_exact_native_contract(monkeypatch):
    observed = []

    def inspect_contract(contract):
        observed.append(contract)
        return contract.source_contract_current

    monkeypatch.setattr(
        announcements_readiness,
        "database_integrity_contract_is_ready",
        inspect_contract,
    )
    monkeypatch.setattr(
        announcements_readiness, "relation_schema_is_current", lambda _: True
    )
    assert announcements_readiness.announcements_database_integrity_is_ready()
    assert len(observed) == 1
    contract = observed[0]
    assert ("announcements", "0004_guidance_combined_admission") in (
        contract.required_migrations
    )
    assert "announcements_guidance" in (
        contract.functions["maru_announcements_row_guard()"].source
    )
    assert contract.triggers
    assert not contract.runtime_executable_functions


@pytest.mark.parametrize("source_pin", ["", "0" * 64])
def test_guidance_announcements_missing_or_changed_source_stays_unready(
    monkeypatch, source_pin
):
    monkeypatch.setattr(
        announcements_readiness, "_GUIDANCE_SUCCESSOR_SHA256", source_pin
    )
    monkeypatch.setattr(
        announcements_readiness,
        "database_integrity_contract_is_ready",
        lambda contract: contract.source_contract_current,
    )
    monkeypatch.setattr(
        announcements_readiness, "relation_schema_is_current", lambda _: True
    )
    assert not announcements_readiness.announcements_database_integrity_is_ready()


@pytest.mark.parametrize(
    ("native_ready", "schema_ready"), [(False, True), (True, False)]
)
def test_guidance_announcements_source_pin_never_replaces_native_proof(
    monkeypatch, native_ready, schema_ready
):
    monkeypatch.setattr(
        announcements_readiness,
        "database_integrity_contract_is_ready",
        lambda contract: contract.source_contract_current and native_ready,
    )
    monkeypatch.setattr(
        announcements_readiness, "relation_schema_is_current", lambda _: schema_ready
    )
    assert not announcements_readiness.announcements_database_integrity_is_ready()
