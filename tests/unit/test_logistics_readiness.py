from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Never

from django.apps import apps
from django.db import migrations

from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
    RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
)
from maru.logistics import readiness


def test_logistics_readiness_derives_forward_reverse_contracts_from_migration() -> None:
    assert readiness.MIGRATION_CONTRACT_SYMMETRIC
    assert readiness.TRIGGER_CONTRACTS
    assert readiness.FUNCTION_CONTRACTS

    relation_names = set(readiness.logistics_relation_names())
    assert len(relation_names) == 25
    assert {contract.table for contract in readiness.TRIGGER_CONTRACTS.values()} <= (
        relation_names
    )
    for relation in relation_names:
        assert any(
            contract.table == relation and contract.trigger_type == 34
            for contract in readiness.TRIGGER_CONTRACTS.values()
        )

    projection = readiness.TRIGGER_CONTRACTS["log_event_projection_required"]
    assert projection.table == "logistics_logisticsevent"
    assert projection.trigger_type == 5
    assert projection.deferrable
    assert projection.initially_deferred


def test_logistics_readiness_requires_every_dependency_migration_record() -> None:
    assert readiness._REVIEWED_MIGRATIONS == (
        ("logistics", "0001_initial"),
        ("authorization", "0016_logistics_capabilities_and_resource_kind"),
        ("venues", "0001_initial"),
        ("logistics", "0002_logistics_write_integrity"),
    )


def test_trigger_catalog_includes_functions_from_every_schema() -> None:
    source = inspect.getsource(readiness.inspect_logistics_production_catalog)
    assert "procedure_namespace.nspname || '.'" in source
    assert "procedure_namespace.nspname = 'public'" not in source


def test_logistics_migration_symmetry_rejects_missing_drop_or_revoke() -> None:
    migration = readiness._migration
    trigger = next(iter(readiness.TRIGGER_CONTRACTS.values()))
    missing_trigger_drop = (
        f"DROP TRIGGER IF EXISTS {trigger.name} ON public.{trigger.table};"
    )
    assert missing_trigger_drop in migration.REVERSE_SQL
    assert not readiness._migration_contract_is_symmetric(
        migration.FORWARD_SQL,
        migration.REVERSE_SQL.replace(missing_trigger_drop, "", 1),
    )

    assert not readiness._migration_contract_is_symmetric(
        migration.FORWARD_SQL.replace("REVOKE ALL ON FUNCTION", "-- removed", 1),
        migration.REVERSE_SQL,
    )


def test_logistics_downgrade_fence_is_exact_and_locks_all_tables_first() -> None:
    migration = readiness._migration
    migration_class = migration.Migration
    operations = tuple(migration_class.operations)

    assert tuple(migration_class.dependencies) == (
        ("authorization", "0016_logistics_capabilities_and_resource_kind"),
        ("logistics", "0001_initial"),
        ("venues", "0001_initial"),
    )
    assert len(operations) == 2
    assert isinstance(operations[0], migrations.RunSQL)
    assert operations[0].sql == migration.FORWARD_SQL
    assert operations[0].reverse_sql == migration.REVERSE_SQL
    assert isinstance(operations[1], migrations.RunPython)
    assert operations[1].code is migrations.RunPython.noop
    assert operations[1].reverse_code is migration.refuse_logistics_integrity_downgrade

    model_names = tuple(migration.LOGISTICS_MODEL_NAMES)
    assert len(model_names) == len(set(model_names)) == 25
    source = (
        inspect.getsource(migration.refuse_logistics_integrity_downgrade)
        .replace("\r\n", "\n")
        .strip()
    )
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == (
        readiness._DOWNGRADE_FENCE_SOURCE_SHA256
    )
    assert source.index("LOCK TABLE") < source.index("objects.exists()")
    assert "IN ACCESS EXCLUSIVE MODE" in source
    assert "raise RuntimeError" in source
    assert readiness._migration_operations_are_reviewed()


def test_logistics_function_contract_covers_behavior_acl_and_owner_inputs() -> None:
    expected_search_path = ("search_path=pg_catalog, public, pg_temp",)
    assert all(
        contract.configuration == expected_search_path
        for contract in readiness.FUNCTION_CONTRACTS.values()
    )
    assert all(
        contract.language in {"plpgsql", "sql"}
        for contract in readiness.FUNCTION_CONTRACTS.values()
    )
    assert all(
        len(contract.definition_sha256) == 64
        for contract in readiness.FUNCTION_CONTRACTS.values()
    )

    identity, contract = next(iter(readiness.FUNCTION_CONTRACTS.items()))
    changed = replace(contract, source=contract.source + "\n-- weakened")
    assert identity == contract.identity
    assert changed.definition_sha256 != contract.definition_sha256


def test_nested_person_eligibility_calls_use_hardened_definer_callers() -> None:
    callers = tuple(
        contract
        for contract in readiness.FUNCTION_CONTRACTS.values()
        if "public.maru_logistics_person_is_eligible(" in contract.source
    )
    assert callers
    assert all(contract.security_definer for contract in callers)


def test_all_logistics_relations_have_one_declared_runtime_privilege_profile() -> None:
    assert readiness.relation_privilege_profiles_are_declared()
    expected = {
        f"public.{relation}" for relation in readiness.logistics_relation_names()
    }
    declared = {
        relation
        for profile in (
            RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
            RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
        )
        for relation in profile
        if relation.startswith("public.logistics_")
    }
    assert declared == expected


def test_schema_contract_tracks_every_named_model_constraint_and_field_unique() -> None:
    schema_contracts = readiness.declared_schema_object_contracts()
    expected_names: set[str] = set()
    expected_implicit_uniques: set[tuple[str, tuple[str, ...]]] = set()
    for model in apps.get_app_config("logistics").get_models():
        expected_names.update(constraint.name for constraint in model._meta.constraints)
        expected_implicit_uniques.update(
            (model._meta.db_table, (field.column,))
            for field in model._meta.local_fields
            if field.unique and not field.primary_key
        )

    assert {contract.name for contract in schema_contracts.values()} == expected_names
    assert {
        (contract.table, contract.columns)
        for contract in readiness.declared_implicit_unique_contracts()
    } == expected_implicit_uniques
    assert {
        "log_node_venue_shape",
        "log_keyholder_no_overlap",
        "log_agree_asset_no_overlap",
        "log_agree_lot_no_overlap",
        "log_agree_key_no_overlap",
        "log_agree_node_no_overlap",
        "log_kit_line_count_bound",
        "log_manifest_line_count_bound",
        "log_manifest_event_line_type_uq",
        "log_offline_operation_bound",
        "log_asset_event_seq_uq",
        "log_lot_event_seq_uq",
        "log_key_event_seq_uq",
        "log_node_event_seq_uq",
    } <= expected_names
    assert {
        contract.name
        for contract in schema_contracts.values()
        if contract.constraint_type == "x"
    } == {
        "log_keyholder_no_overlap",
        "log_agree_asset_no_overlap",
        "log_agree_lot_no_overlap",
        "log_agree_key_no_overlap",
        "log_agree_node_no_overlap",
    }
    assert {
        contract.columns
        for contract in readiness.declared_implicit_unique_contracts()
        if contract.table == "logistics_logisticscurrentstate"
    } == {
        ("node_id",),
        ("asset_id",),
        ("stock_lot_id",),
        ("physical_key_id",),
        ("last_event_id",),
    }


def test_schema_definition_catalog_cannot_be_partially_finalized() -> None:
    contracts = readiness.declared_schema_object_contracts()
    fingerprints = readiness.SCHEMA_DEFINITION_SHA256
    assert not fingerprints or set(fingerprints) == set(contracts)
    if not fingerprints:
        assert not readiness._schema_definitions_are_current({}, contracts)


def test_current_session_readiness_rejects_owner_session(
    monkeypatch,
    settings,
) -> None:
    settings.RUNTIME_DATABASE_ROLE = "maru_runtime"
    monkeypatch.setattr(
        readiness,
        "inspect_logistics_production_catalog",
        lambda: SimpleNamespace(ready=True),
    )
    monkeypatch.setattr(
        readiness,
        "probe_runtime_database_role_safety",
        lambda **_kwargs: SimpleNamespace(current_session_is_safe=False),
    )

    assert not readiness.logistics_current_session_is_ready()


def test_current_session_readiness_accepts_proved_runtime_session(
    monkeypatch,
    settings,
) -> None:
    settings.RUNTIME_DATABASE_ROLE = "maru_runtime"
    monkeypatch.setattr(
        readiness,
        "inspect_logistics_production_catalog",
        lambda: SimpleNamespace(ready=True),
    )
    monkeypatch.setattr(
        readiness,
        "probe_runtime_database_role_safety",
        lambda **_kwargs: SimpleNamespace(current_session_is_safe=True),
    )

    assert readiness.logistics_current_session_is_ready()


def test_current_session_readiness_fails_closed_on_probe_error(
    monkeypatch,
    settings,
) -> None:
    settings.RUNTIME_DATABASE_ROLE = "maru_runtime"
    monkeypatch.setattr(
        readiness,
        "inspect_logistics_production_catalog",
        lambda: SimpleNamespace(ready=True),
    )

    def fail_probe(**_kwargs) -> Never:
        raise readiness.RuntimeDatabaseRoleProbeError("invalid probe shape")

    monkeypatch.setattr(readiness, "probe_runtime_database_role_safety", fail_probe)

    assert not readiness.logistics_current_session_is_ready()


def test_readiness_report_minimizes_catalog_contract_errors(monkeypatch) -> None:
    def fail_catalog() -> Never:
        raise RuntimeError("private catalog detail")

    monkeypatch.setattr(readiness, "inspect_logistics_production_catalog", fail_catalog)

    assert not readiness.logistics_production_contract_is_ready()
    assert readiness.build_logistics_readiness_report() == {
        "status": "blocked",
        "gates": {"catalog_inspection": "unresolved"},
    }


def test_stage_receiving_templates_remain_utf8_clean() -> None:
    templates = Path(__file__).resolve().parents[2] / "src/maru/logistics/templates"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            templates / "logistics/stage_receiving.html",
            templates / "logistics/manifest_detail.html",
        )
    )
    assert not {"â", "Ã", "Â", "�"}.intersection(source)
    assert " — " in source
    assert f" {chr(0xD7)} " in source
