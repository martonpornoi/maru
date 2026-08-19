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

WORKFORCE_BEFORE = ("workforce", "0007_structure_write_integrity")
WORKFORCE_AFTER = ("workforce", "0008_department_fk_contract_successor")
EXPECTED_DEPENDENCIES = [
    ("applications", "0001_initial"),
    ("charities", "0001_initial"),
    ("logistics", "0001_initial"),
    ("registration", "0039_profile_audiences_and_platform_starter"),
    ("venues", "0001_initial"),
    WORKFORCE_BEFORE,
]
EXPECTED_SUCCESSOR_RELATIONS = (
    "applications_applicationownerdepartment",
    "charities_charityselection",
    "logistics_equipmentoffer",
    "logistics_logisticsmanifest",
    "registration_registrationprofileextensionfield",
    "venues_editionspaceselection",
    "venues_editionvenueselection",
    "venues_venuebooking",
)


def _migrate(target: tuple[str, str]) -> None:
    MigrationExecutor(connection).migrate([target])


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


def test_successor_migration_has_exact_creator_dependencies_and_reversal() -> None:
    migration_module = import_module(
        "maru.workforce.migrations.0008_department_fk_contract_successor"
    )

    assert migration_module.Migration.dependencies == EXPECTED_DEPENDENCIES
    assert len(migration_module.Migration.operations) == 1
    operation = migration_module.Migration.operations[0]
    assert isinstance(operation, migrations.RunSQL)
    assert operation.sql == migration_module.FORWARD_SQL
    assert operation.reverse_sql == migration_module.REVERSE_SQL
    assert all(
        relation in migration_module.FORWARD_SQL
        for relation in EXPECTED_SUCCESSOR_RELATIONS
    )


def test_successor_reverses_fail_closed_and_reapplies_current_contract() -> None:
    _migrate(WORKFORCE_AFTER)
    forward_source, forward_is_current = _contract_state()
    assert forward_is_current
    assert all(relation in forward_source for relation in EXPECTED_SUCCESSOR_RELATIONS)

    _migrate(WORKFORCE_BEFORE)
    reverse_source, reverse_is_current = _contract_state()
    assert not reverse_is_current
    assert all(
        relation not in reverse_source for relation in EXPECTED_SUCCESSOR_RELATIONS
    )

    _migrate(WORKFORCE_AFTER)
    restored_source, restored_is_current = _contract_state()
    assert restored_is_current
    assert restored_source == forward_source
