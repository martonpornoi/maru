"""Static contract coverage for Programme integrity and recovery migrations."""

from __future__ import annotations

import inspect
from importlib import import_module

from django.db import migrations

import maru.programme.readiness as programme_readiness
from maru.programme.readiness import PROGRAMME_INTEGRITY_CONTRACT


def test_integrity_migration_is_one_exact_reversible_sql_contract() -> None:
    """Keep the runtime fingerprint derived from one app-owned SQL operation."""
    migration = import_module("maru.programme.migrations.0002_integrity_guards")

    assert tuple(migration.Migration.dependencies) == (("programme", "0001_initial"),)
    assert len(migration.Migration.operations) == 1
    operation = migration.Migration.operations[0]
    assert isinstance(operation, migrations.RunSQL)
    assert operation.sql == migration.FORWARD_SQL
    assert operation.reverse_sql == migration.REVERSE_SQL
    assert PROGRAMME_INTEGRITY_CONTRACT.source_contract_current
    assert len(PROGRAMME_INTEGRITY_CONTRACT.triggers) == 38
    assert len(PROGRAMME_INTEGRITY_CONTRACT.functions) == 15
    assert migration.FORWARD_SQL.count("REVOKE ALL ON FUNCTION") == 15
    no_truncate = {
        trigger.table
        for trigger in PROGRAMME_INTEGRITY_CONTRACT.triggers.values()
        if trigger.name.endswith("_no_truncate")
    }
    assert no_truncate == {
        "programme_programmeeditioncontrol",
        "programme_programmeitem",
        "programme_programmeitemsourcebinding",
        "programme_programmeworkingrevision",
        "programme_programmedeliveryrevision",
        "programme_programmedepartmentdiscussionentry",
        "programme_programmereadinessrequirement",
        "programme_programmereadinessrequirementrevision",
        "programme_programmereadinessevidence",
        "programme_programmepublicrendition",
        "programme_programmecommandreceipt",
    }


def test_schema_fingerprint_covers_exact_columns_and_catalog_definitions() -> None:
    """Keep column and complete definition semantics inside readiness."""
    columns = programme_readiness._expected_programme_columns()
    assert any(
        column[:7]
        == (
            "programme_programmecommandreceipt",
            "idempotency_key",
            "uuid",
            True,
            False,
            "",
            "",
        )
        and column[7:] == programme_readiness._NO_COLLATION_IDENTITY
        for column in columns
    )
    internal_title = next(
        column
        for column in columns
        if column[:2]
        == (
            "programme_programmeworkingrevision",
            "internal_title",
        )
    )
    assert internal_title[7:] == programme_readiness._DEFAULT_COLLATION_IDENTITY
    assert {
        ("constraint:programme_programmecommandreceipt:programme_command_retry_uq"),
        (
            "constraint:programme_programmeworkingrevision:"
            "programme_working_item_version_uq"
        ),
        "constraint:programme_programmeitem:programme_item_version_pos",
        ("index:programme_programmecommandreceipt:programme_command_item_version_uq"),
    } == programme_readiness._REQUIRED_SCHEMA_OBJECT_KEYS
    source = inspect.getsource(programme_readiness._schema_definition_rows)
    assert "pg_get_constraintdef" in source
    assert "pg_get_indexdef" in source
    assert "convalidated" in source
    assert "confupdtype" in source
    assert "confdeltype" in source
    assert "confmatchtype" in source
    assert "indisvalid" in source
    assert "indisready" in source
    assert "indislive" in source
    assert "indnkeyatts" in source
    assert "indnatts" in source
    inspection_source = inspect.getsource(
        programme_readiness.inspect_programme_schema_catalog
    )
    assert "collprovider" in inspection_source
    assert "collisdeterministic" in inspection_source
    assert "colllocale" in inspection_source
    assert "collversion" in inspection_source
    assert "relkind" in inspection_source
    assert "relpersistence" in inspection_source
    assert "relrowsecurity" in inspection_source
    assert "relforcerowsecurity" in inspection_source
    assert "relispartition" in inspection_source
    assert "relreplident" in inspection_source


def test_relation_semantics_catalog_is_complete_and_fail_closed() -> None:
    """Pin all Programme relations to permanent non-RLS ordinary tables."""
    relations = programme_readiness.PROGRAMME_RELATION_SEMANTICS

    assert set(relations) == {
        "programme_programmecommandreceipt",
        "programme_programmedeliveryrevision",
        "programme_programmedepartmentdiscussionentry",
        "programme_programmeeditioncontrol",
        "programme_programmeitem",
        "programme_programmeitemsourcebinding",
        "programme_programmepublicrendition",
        "programme_programmereadinessevidence",
        "programme_programmereadinessrequirement",
        "programme_programmereadinessrequirementrevision",
        "programme_programmeworkingrevision",
    }
    assert set(relations.values()) == {("r", "p", False, False, False, "d")}


def test_schema_object_fingerprint_requires_complete_exact_object_sets() -> None:
    """Reject missing, extra, or changed same-named catalog objects."""
    expected = {"constraint:programme_table:programme_check": ("a" * 64, "b" * 64)}

    assert programme_readiness._schema_object_rows_are_current(
        expected,
        expected,
        prefix="constraint:",
    )
    assert not programme_readiness._schema_object_rows_are_current(
        {
            **expected,
            "constraint:programme_table:unexpected": ("c" * 64, "d" * 64),
        },
        expected,
        prefix="constraint:",
    )
    assert not programme_readiness._schema_object_rows_are_current(
        {"constraint:programme_table:programme_check": ("a" * 64, "c" * 64)},
        expected,
        prefix="constraint:",
    )


def test_schema_definition_catalog_cannot_be_partially_finalized() -> None:
    """Keep an absent or incomplete immutable digest catalog fail-closed."""
    fingerprints = programme_readiness.PROGRAMME_SCHEMA_OBJECT_SHA256

    assert not fingerprints or (
        fingerprints.keys() >= programme_readiness._REQUIRED_SCHEMA_OBJECT_KEYS
        and all(
            len(metadata_sha256) == len(definition_sha256) == 64
            for metadata_sha256, definition_sha256 in fingerprints.values()
        )
    )


def test_reverse_preflights_lock_and_refuse_before_destructive_operations() -> None:
    """Fence both guard removal and later table removal in their transactions."""
    initial = import_module("maru.programme.migrations.0001_initial")
    guards = import_module("maru.programme.migrations.0002_integrity_guards")

    assert "IN ACCESS EXCLUSIVE MODE" in guards.REVERSE_SQL
    assert guards.REVERSE_SQL.index("IN ACCESS EXCLUSIVE MODE") < (
        guards.REVERSE_SQL.index("DROP TRIGGER")
    )
    assert "Cannot remove Programme integrity guards" in guards.REVERSE_SQL
    final_operation = initial.Migration.operations[-1]
    assert isinstance(final_operation, migrations.RunSQL)
    assert final_operation.sql == migrations.RunSQL.noop
    assert final_operation.reverse_sql == initial.REVERSE_PREFLIGHT_SQL
    assert "IN ACCESS EXCLUSIVE MODE" in initial.REVERSE_PREFLIGHT_SQL
    assert "Cannot remove Programme tables" in initial.REVERSE_PREFLIGHT_SQL


def test_integrity_sql_keeps_dependency_and_public_version_semantics_exact() -> None:
    """Pin dependency-only invalidation and non-mutating public approval."""
    migration = import_module("maru.programme.migrations.0002_integrity_guards")
    sql = migration.FORWARD_SQL

    assert "NEW.requirement_version = OLD.requirement_version" in sql
    assert "NEW.dependency_version <> NEW.item_version" in sql
    assert "NEW.dependency_version <= OLD.dependency_version" in sql
    assert "NEW.operation = 'public_rendition_record'" in sql
    assert "NEW.expected_version <> NEW.resulting_item_version" in sql
    assert "Programme public-copy receipt changed item state" in sql
    assert "programme_requirement_dependency_cursor_guard" in sql
    assert "programme_receipt_dependency_cursor_guard" in sql


def test_integrity_sql_binds_mutating_receipts_to_the_item_actor() -> None:
    """Pin creator/modifier attribution while exempting public-only approval."""
    migration = import_module("maru.programme.migrations.0002_integrity_guards")
    sql = migration.FORWARD_SQL

    create_branch = sql[
        sql.index("IF item_row.aggregate_version <> 1") : sql.index(
            "RAISE EXCEPTION 'Programme creation receipt"
        )
    ]
    public_branch = sql[
        sql.index(
            "ELSIF NEW.operation = 'public_rendition_record' THEN",
            sql.index("Programme creation receipt"),
        ) : sql.index("RAISE EXCEPTION 'Programme public-copy receipt")
    ]
    mutation_branch = sql[
        sql.index("ELSIF NEW.resulting_control_version IS NOT NULL") : sql.index(
            "RAISE EXCEPTION 'Programme item mutation receipt"
        )
    ]

    assert "item_row.created_by_id IS DISTINCT FROM NEW.actor_id" in create_branch
    assert "item_row.last_modified_by_id IS DISTINCT FROM NEW.actor_id" in create_branch
    assert (
        "item_row.last_modified_by_id IS DISTINCT FROM NEW.actor_id" in mutation_branch
    )
    assert "item_row.last_modified_by_id IS DISTINCT FROM NEW.actor_id" not in (
        public_branch
    )


def test_integrity_sql_requires_complete_creation_and_readiness_attribution() -> None:
    """Pin child completeness and mutable readiness state to each receipt."""
    migration = import_module("maru.programme.migrations.0002_integrity_guards")
    sql = migration.FORWARD_SQL
    create_result = sql[
        sql.index("IF NEW.operation = 'item_create' THEN") : sql.index(
            "ELSIF NEW.operation = 'working_revise' THEN"
        )
    ]
    readiness_result = sql[
        sql.index("ELSIF NEW.operation = 'readiness_configure' THEN") : sql.index(
            "ELSIF NEW.operation = 'readiness_record' THEN"
        )
    ]

    assert "FROM public.programme_programmeworkingrevision AS result" in create_result
    assert "SELECT COUNT(*) = 1" in create_result
    assert "result.sequence = 1" in create_result
    assert "result.item_version = 1" in create_result
    assert "result.actor_id = NEW.actor_id" in create_result
    assert "result.reason = NEW.reason" in create_result
    assert "JOIN public.programme_programmereadinessrequirement AS requirement" in (
        readiness_result
    )
    assert "requirement.requirement_version = result.sequence" in readiness_result
    assert "requirement.item_version = result.item_version" in readiness_result
    assert "requirement.disposition = result.disposition" in readiness_result
    assert "requirement.last_modified_by_id = NEW.actor_id" in readiness_result


def test_integrity_sql_requires_latest_working_source_for_public_copy() -> None:
    """Pin public approval to the deterministic current working revision."""
    migration = import_module("maru.programme.migrations.0002_integrity_guards")
    sql = migration.FORWARD_SQL
    public_guard = sql[
        sql.index(
            "CREATE FUNCTION public.maru_guard_programme_public_rendition"
        ) : sql.index("CREATE FUNCTION public.maru_guard_programme_receipt")
    ]

    assert "ORDER BY sequence DESC, id DESC" in public_guard
    assert "latest_working_id IS DISTINCT FROM NEW.source_working_revision_id" in (
        public_guard
    )


def test_deferred_evidence_checks_each_transition_version_not_final_state() -> None:
    """Prevent one final receipt from satisfying earlier deferred transitions."""
    migration = import_module("maru.programme.migrations.0002_integrity_guards")
    sql = migration.FORWARD_SQL
    item_evidence = sql[
        sql.index(
            "CREATE FUNCTION public.maru_validate_programme_item_evidence"
        ) : sql.index("CREATE FUNCTION public.maru_validate_programme_control_evidence")
    ]
    control_evidence = sql[
        sql.index(
            "CREATE FUNCTION public.maru_validate_programme_control_evidence"
        ) : sql.index("CREATE FUNCTION public.maru_validate_programme_source_shape")
    ]

    assert "current_version := NEW.aggregate_version" in item_evidence
    assert "current_version := NEW.resulting_item_version" in item_evidence
    assert "SELECT aggregate_version INTO current_version" not in item_evidence
    assert "current_version := NEW.aggregate_version" in control_evidence
    assert "current_version := NEW.resulting_control_version" in control_evidence
    assert "SELECT aggregate_version INTO current_version" not in control_evidence


def test_writers_stabilize_and_enforce_the_edition_lifecycle() -> None:
    """Lock lifecycle rows against races and cover non-item public writes."""
    migration = import_module("maru.programme.migrations.0002_integrity_guards")
    sql = migration.FORWARD_SQL
    control_guard = sql[
        sql.index("CREATE FUNCTION public.maru_guard_programme_control") : sql.index(
            "CREATE FUNCTION public.maru_guard_programme_item"
        )
    ]
    item_guard = sql[
        sql.index("CREATE FUNCTION public.maru_guard_programme_item") : sql.index(
            "CREATE FUNCTION public.maru_guard_programme_source_binding"
        )
    ]
    public_guard = sql[
        sql.index(
            "CREATE FUNCTION public.maru_guard_programme_public_rendition"
        ) : sql.index("CREATE FUNCTION public.maru_guard_programme_receipt")
    ]

    for guard in (control_guard, item_guard, public_guard):
        assert "FROM public.events_eventedition" in guard
        assert "FOR SHARE;" in guard
        assert (
            "FOR KEY SHARE;"
            not in guard.split(
                "FROM public.events_eventedition",
                maxsplit=1,
            )[1].split(";", maxsplit=1)[0]
        )
    assert "edition_lifecycle NOT IN ('draft', 'preparing')" in public_guard


def test_downgrade_fence_covers_every_programme_relation() -> None:
    """Keep empty reversal possible and populated reversal fix-forward only."""
    migration = import_module("maru.programme.migrations.0003_downgrade_fence")

    assert tuple(migration.Migration.dependencies) == (
        ("programme", "0002_integrity_guards"),
    )
    assert len(migration.Migration.operations) == 1
    operation = migration.Migration.operations[0]
    assert isinstance(operation, migrations.RunPython)
    assert operation.code is migrations.RunPython.noop
    assert operation.reverse_code is migration.refuse_used_programme_downgrade
    assert len(migration.PROGRAMME_MODEL_NAMES) == 11
    assert len(set(migration.PROGRAMME_MODEL_NAMES)) == 11
