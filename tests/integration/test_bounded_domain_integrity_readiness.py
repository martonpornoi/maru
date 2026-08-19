"""Live PostgreSQL tamper evidence for bounded-domain integrity readiness."""

from __future__ import annotations

import re

import pytest
from django.db import connection
from psycopg import sql

from maru.applications.readiness import APPLICATIONS_INTEGRITY_CONTRACT
from maru.catalog.readiness import CATALOG_INTEGRITY_CONTRACT
from maru.charities.readiness import CHARITIES_INTEGRITY_CONTRACT
from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    inspect_database_integrity_catalog,
)
from maru.venues.readiness import VENUES_INTEGRITY_CONTRACT

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

CONTRACTS = (
    APPLICATIONS_INTEGRITY_CONTRACT,
    CHARITIES_INTEGRITY_CONTRACT,
    CATALOG_INTEGRITY_CONTRACT,
    VENUES_INTEGRITY_CONTRACT,
)


def test_current_bounded_domain_integrity_catalogs_are_ready() -> None:
    catalogs = [inspect_database_integrity_catalog(contract) for contract in CONTRACTS]

    assert all(catalog.ready for catalog in catalogs)


@pytest.mark.parametrize(
    "contract",
    list(CONTRACTS),
    ids=[contract.app_label for contract in CONTRACTS],
)
def test_disabled_expected_trigger_blocks_its_domain(
    contract: DatabaseIntegrityContract,
) -> None:
    trigger = next(iter(contract.triggers.values()))
    alter = sql.SQL("ALTER TABLE {}.{} {} TRIGGER {}").format(
        sql.Identifier("public"),
        sql.Identifier(trigger.table),
        sql.SQL("DISABLE"),
        sql.Identifier(trigger.name),
    )
    restore = sql.SQL("ALTER TABLE {}.{} {} TRIGGER {}").format(
        sql.Identifier("public"),
        sql.Identifier(trigger.table),
        sql.SQL("ENABLE"),
        sql.Identifier(trigger.name),
    )
    with connection.cursor() as cursor:
        cursor.execute(alter)
    try:
        catalog = inspect_database_integrity_catalog(contract)
        assert not catalog.trigger_contract_current
        assert not catalog.ready
    finally:
        with connection.cursor() as cursor:
            cursor.execute(restore)


def test_extra_trigger_on_an_owned_relation_blocks_the_domain() -> None:
    trigger = next(iter(CATALOG_INTEGRITY_CONTRACT.triggers.values()))
    create = sql.SQL(
        """
        CREATE TRIGGER bounded_integrity_test_extra
        BEFORE UPDATE ON {}.{}
        FOR EACH ROW EXECUTE FUNCTION {}()
        """
    ).format(
        sql.Identifier("public"),
        sql.Identifier(trigger.table),
        sql.SQL(trigger.function_identity.removesuffix("()")),
    )
    drop = sql.SQL("DROP TRIGGER bounded_integrity_test_extra ON {}.{}").format(
        sql.Identifier("public"),
        sql.Identifier(trigger.table),
    )
    with connection.cursor() as cursor:
        cursor.execute(create)
    try:
        catalog = inspect_database_integrity_catalog(CATALOG_INTEGRITY_CONTRACT)
        assert not catalog.trigger_contract_current
        assert not catalog.ready
    finally:
        with connection.cursor() as cursor:
            cursor.execute(drop)


def test_function_body_fingerprint_drift_blocks_the_domain() -> None:
    identity = next(iter(CATALOG_INTEGRITY_CONTRACT.functions))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_catalog.pg_get_functiondef(procedure.oid)
              FROM pg_catalog.pg_proc AS procedure
             WHERE procedure.oid = pg_catalog.to_regprocedure(%s)
            """,
            [f"public.{identity}"],
        )
        original = str(cursor.fetchone()[0])
    tampered = re.sub(
        r"(AS\s+\$[^$]*\$\s*)",
        r"\1\n-- bounded readiness tamper\n",
        original,
        count=1,
        flags=re.IGNORECASE,
    )
    assert tampered != original
    with connection.cursor() as cursor:
        cursor.execute(tampered)
    try:
        catalog = inspect_database_integrity_catalog(CATALOG_INTEGRITY_CONTRACT)
        assert not catalog.function_contract_current
        assert not catalog.ready
    finally:
        with connection.cursor() as cursor:
            cursor.execute(original)


def test_public_function_execute_grant_blocks_the_domain() -> None:
    identity = next(iter(VENUES_INTEGRITY_CONTRACT.functions))
    grant = sql.SQL("GRANT EXECUTE ON FUNCTION {} TO PUBLIC").format(
        sql.SQL(f"public.{identity}"),
    )
    revoke = sql.SQL("REVOKE ALL ON FUNCTION {} FROM PUBLIC").format(
        sql.SQL(f"public.{identity}"),
    )
    with connection.cursor() as cursor:
        cursor.execute(grant)
    try:
        catalog = inspect_database_integrity_catalog(VENUES_INTEGRITY_CONTRACT)
        assert not catalog.function_execute_owner_only
        assert not catalog.ready
    finally:
        with connection.cursor() as cursor:
            cursor.execute(revoke)


def test_missing_terminal_migration_recorder_blocks_the_domain() -> None:
    app_label, migration_name = APPLICATIONS_INTEGRITY_CONTRACT.terminal_migration
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT applied
              FROM public.django_migrations
             WHERE app = %s AND name = %s
            """,
            [app_label, migration_name],
        )
        applied = cursor.fetchone()
        assert applied is not None
        cursor.execute(
            "DELETE FROM public.django_migrations WHERE app = %s AND name = %s",
            [app_label, migration_name],
        )
    try:
        catalog = inspect_database_integrity_catalog(APPLICATIONS_INTEGRITY_CONTRACT)
        assert not catalog.required_migrations_applied
        assert not catalog.ready
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO public.django_migrations(app, name, applied)
                VALUES (%s, %s, %s)
                """,
                [app_label, migration_name, applied[0]],
            )
