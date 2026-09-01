"""PostgreSQL coverage for the Programme-call Department FK successor."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection, migrations
from django.db.migrations.executor import MigrationExecutor

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

APPLICATIONS_SCHEMA = ("applications", "0004_programme_calls_and_proposals")
WORKFORCE_BEFORE = ("workforce", "0015_exact_assignment_adoption_profile")
WORKFORCE_AFTER = (
    "workforce",
    "0016_programme_call_department_fk_contract",
)
EXPECTED_DEPENDENCIES = [APPLICATIONS_SCHEMA, WORKFORCE_BEFORE]


def _migrate(targets: list[tuple[str, str]]) -> None:
    MigrationExecutor(connection).migrate(targets)


def _contract_state() -> tuple[str, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT procedure.prosrc,
                   public.maru_workforce_department_fk_contract_is_current()
              FROM pg_catalog.pg_proc AS procedure
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname = 'public'
               AND procedure.oid = pg_catalog.to_regprocedure(
                   'public.maru_workforce_department_fk_contract_is_current()'
               )
            """
        )
        source, is_current = cursor.fetchone()
    return str(source), bool(is_current)


def test_programme_successor_has_exact_dependencies_and_reversal() -> None:
    migration_module = import_module(
        "maru.workforce.migrations.0016_programme_call_department_fk_contract"
    )

    assert migration_module.Migration.dependencies == EXPECTED_DEPENDENCIES
    assert len(migration_module.Migration.operations) == 1
    operation = migration_module.Migration.operations[0]
    assert isinstance(operation, migrations.RunSQL)
    assert operation.sql == migration_module.FORWARD_SQL
    assert operation.reverse_sql == migration_module.REVERSE_SQL
    assert "applications_programmecall" in migration_module.FORWARD_SQL
    assert "owner_department_id" in migration_module.FORWARD_SQL
    assert "applications_programmecall" not in migration_module.REVERSE_SQL


def test_programme_successor_reverses_fail_closed_and_reapplies() -> None:
    _migrate([WORKFORCE_AFTER])
    forward_source, forward_is_current = _contract_state()
    assert forward_is_current
    assert "applications_programmecall" in forward_source
    assert "owner_department_id" in forward_source

    _migrate([APPLICATIONS_SCHEMA, WORKFORCE_BEFORE])
    reverse_source, reverse_is_current = _contract_state()
    assert not reverse_is_current
    assert "applications_programmecall" not in reverse_source

    _migrate([WORKFORCE_AFTER])
    restored_source, restored_is_current = _contract_state()
    assert restored_is_current
    assert restored_source == forward_source
