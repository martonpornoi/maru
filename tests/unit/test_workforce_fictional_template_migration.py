from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.db import migrations

from maru.workforce.structure_templates import MARUCON_REFERENCE_V1

fictional_template_migration = import_module(
    "maru.workforce.migrations.0009_reconcile_fictional_structure_template"
)
structure_integrity_migration = import_module(
    "maru.workforce.migrations.0007_structure_write_integrity"
)


def _preflight_doubles(
    *,
    incompatible_count: int,
) -> tuple[Mock, Mock, Mock, Mock, list[str]]:
    events: list[str] = []
    apps = Mock()
    schema_editor = Mock(connection=SimpleNamespace(alias="migration"))
    receipt_model = Mock()
    manager = receipt_model.objects
    using_query = manager.using.return_value
    filtered_query = using_query.filter.return_value
    incompatible_query = filtered_query.exclude.return_value

    schema_editor.execute.side_effect = lambda _sql: events.append("lock")

    def count_incompatible_receipts() -> int:
        events.append("count")
        return incompatible_count

    incompatible_query.count.side_effect = count_incompatible_receipts
    apps.get_model.return_value = receipt_model
    return apps, schema_editor, manager, incompatible_query, events


def test_fictional_template_preflight_locks_then_accepts_current_evidence() -> None:
    apps, schema_editor, manager, incompatible_query, events = _preflight_doubles(
        incompatible_count=0
    )

    fictional_template_migration.refuse_incompatible_template_evidence(
        apps,
        schema_editor,
    )

    assert events == ["lock", "count"]
    schema_editor.execute.assert_called_once_with(
        "LOCK TABLE public.workforce_editionstructurecommandreceipt "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    apps.get_model.assert_called_once_with(
        "workforce",
        "EditionStructureCommandReceipt",
    )
    manager.using.assert_called_once_with("migration")
    manager.using.return_value.filter.assert_called_once_with(action="template_applied")
    manager.using.return_value.filter.return_value.exclude.assert_called_once_with(
        template_code="marucon-reference",
        template_version=1,
        template_digest=MARUCON_REFERENCE_V1.sha256_digest,
    )
    incompatible_query.count.assert_called_once_with()


def test_fictional_template_preflight_refuses_to_relabel_old_receipts() -> None:
    apps, schema_editor, _manager, incompatible_query, events = _preflight_doubles(
        incompatible_count=2
    )

    with pytest.raises(RuntimeError, match=r"the 2 existing receipt\(s\)"):
        fictional_template_migration.refuse_incompatible_template_evidence(
            apps,
            schema_editor,
        )

    assert events == ["lock", "count"]
    incompatible_query.count.assert_called_once_with()


def test_fictional_template_migration_orders_preflight_before_exact_sql_guard() -> None:
    migration_class = fictional_template_migration.Migration
    operations = tuple(migration_class.operations)

    assert tuple(migration_class.dependencies) == (
        ("workforce", "0008_department_fk_contract_successor"),
    )
    assert len(operations) == 2
    assert isinstance(operations[0], migrations.RunPython)
    assert operations[0].code is (
        fictional_template_migration.refuse_incompatible_template_evidence
    )
    assert operations[0].reverse_code is migrations.RunPython.noop
    assert isinstance(operations[1], migrations.RunSQL)
    assert operations[1].sql == (
        fictional_template_migration.INSTALL_FICTIONAL_TEMPLATE_RECEIPT_GUARDS_SQL
    )
    assert operations[1].reverse_sql is migrations.RunSQL.noop


def test_fictional_template_sql_pins_catalog_code_version_digest_and_size() -> None:
    sql = fictional_template_migration.INSTALL_FICTIONAL_TEMPLATE_RECEIPT_GUARDS_SQL
    digest = MARUCON_REFERENCE_V1.sha256_digest

    assert (
        MARUCON_REFERENCE_V1.code == fictional_template_migration.MARUCON_TEMPLATE_CODE
    )
    assert (
        MARUCON_REFERENCE_V1.version
        == fictional_template_migration.MARUCON_TEMPLATE_VERSION
    )
    assert digest == fictional_template_migration.MARUCON_TEMPLATE_DIGEST
    assert digest == structure_integrity_migration.PINNED_TEMPLATE_DIGEST
    assert sql.count("CREATE OR REPLACE FUNCTION") == 2
    assert "CREATE FUNCTION" not in sql
    assert "public.maru_validate_edition_structure_receipt()" in sql
    assert "public.maru_prevent_edition_structure_receipt_mutation()" in sql
    assert "NEW.template_code <> 'marucon-reference'" in sql
    assert "NEW.template_version <> 1" in sql
    assert f"'{digest}'" in sql
    assert "cardinality(NEW.affected_department_ids) <> 22" in sql
    assert len(MARUCON_REFERENCE_V1.departments) == 22
