"""Readiness evidence for the retired-Department authority fence."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from psycopg import sql

from maru.authorization import provenance_readiness
from tests.support.migrations import workforce_migration_targets

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

_AUTHORIZATION_BEFORE = (
    "authorization",
    "0009_runtime_executable_function_contract",
)
_WORKFORCE_BEFORE_PAGE9_INTEGRITY = (
    "workforce",
    "0006_edition_structure_schema",
)
_RETIRED_AUTHORITY_TRIGGER_TABLES = {
    "authorization_retired_binding_guard": "authorization_scopedresourcebinding",
    "authorization_retired_capability_guard": "authorization_capabilitygrant",
    "authorization_retired_role_guard": "authorization_roleassignment",
    "authorization_retired_department_authority_guard": "workforce_department",
    "authorization_retired_binding_writer_lock": (
        "authorization_scopedresourcebinding"
    ),
    "authorization_retired_capability_writer_lock": ("authorization_capabilitygrant"),
    "authorization_retired_role_writer_lock": "authorization_roleassignment",
    "authorization_retired_department_writer_lock": "workforce_department",
}
_RETIRED_AUTHORITY_FUNCTIONS = frozenset(
    {
        "maru_lock_retired_department_authority_writer()",
        "maru_reject_retired_authority_target()",
        "maru_guard_department_retirement_authority()",
    }
)


def test_retired_authority_contract_is_installed_and_inside_downgrade_fence() -> None:
    declared_triggers = {
        contract.name for contract in provenance_readiness._TRIGGER_CONTRACTS
    }

    assert set(_RETIRED_AUTHORITY_TRIGGER_TABLES) <= declared_triggers
    assert set(_RETIRED_AUTHORITY_TRIGGER_TABLES) <= (
        provenance_readiness._DOWNGRADE_FENCE_TRIGGER_NAMES
    )
    assert _RETIRED_AUTHORITY_FUNCTIONS <= (
        provenance_readiness._DOWNGRADE_FENCE_FUNCTIONS
    )
    assert set(provenance_readiness._CORE_FUNCTIONS) >= _RETIRED_AUTHORITY_FUNCTIONS

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert catalog.migration_applied
    assert catalog.guards_installed
    assert catalog.downgrade_fence_installed


@pytest.mark.parametrize(
    ("trigger_name", "table"),
    _RETIRED_AUTHORITY_TRIGGER_TABLES.items(),
)
def test_each_disabled_retired_authority_trigger_blocks_both_catalog_gates(
    trigger_name: str,
    table: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER TABLE public.{} DISABLE TRIGGER {}").format(
                sql.Identifier(table),
                sql.Identifier(trigger_name),
            )
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


@pytest.mark.parametrize("identity", _RETIRED_AUTHORITY_FUNCTIONS)
def test_each_tampered_retired_authority_function_blocks_both_catalog_gates(
    identity: str,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("ALTER FUNCTION public.")
            + sql.SQL(identity)
            + sql.SQL(" SECURITY DEFINER")
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


def test_missing_retired_authority_migration_record_blocks_both_catalog_gates() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            DELETE FROM public.django_migrations
             WHERE app = 'authorization'
               AND name = '0010_retired_department_authority_guards'
            """
        )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.migration_applied
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed


@pytest.mark.usefixtures("restores_current_migration_graph")
@pytest.mark.django_db(transaction=True)
def test_clean_full_reverse_blocks_both_catalog_gates() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate(
        workforce_migration_targets(
            executor,
            _AUTHORIZATION_BEFORE,
            _WORKFORCE_BEFORE_PAGE9_INTEGRITY,
        )
    )

    catalog = provenance_readiness._inspect_cutover_catalog()
    assert not catalog.migration_applied
    assert not catalog.guards_installed
    assert not catalog.downgrade_fence_installed
