"""Live PostgreSQL tamper evidence for bounded-domain integrity readiness."""

from __future__ import annotations

import re

import pytest
from django.db import DatabaseError, connection, transaction
from psycopg import sql

from maru.applications.readiness import (
    APPLICATIONS_INTEGRITY_CONTRACT,
    applications_database_integrity_is_ready,
    inspect_applications_schema_catalog,
)
from maru.catalog.readiness import CATALOG_INTEGRITY_CONTRACT
from maru.charities.readiness import CHARITIES_INTEGRITY_CONTRACT
from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    inspect_database_integrity_catalog,
)
from maru.programme.readiness import (
    PROGRAMME_INTEGRITY_CONTRACT,
    inspect_programme_schema_catalog,
    programme_database_integrity_is_ready,
)
from maru.venues.readiness import VENUES_INTEGRITY_CONTRACT

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]

CONTRACTS = (
    APPLICATIONS_INTEGRITY_CONTRACT,
    CHARITIES_INTEGRITY_CONTRACT,
    CATALOG_INTEGRITY_CONTRACT,
    VENUES_INTEGRITY_CONTRACT,
    PROGRAMME_INTEGRITY_CONTRACT,
)

PROGRAMME_RELATIONS = tuple(
    sorted(
        {trigger.table for trigger in PROGRAMME_INTEGRITY_CONTRACT.triggers.values()}
    )
)


def _truncate_programme_relation(relation: str) -> None:
    """Attempt one test-reset-disabled Programme truncate."""
    truncate = sql.SQL("TRUNCATE TABLE public.{} CASCADE").format(
        sql.Identifier(relation)
    )
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL maru.authority_provenance_test_reset = 'off'")
        cursor.execute(truncate)


def test_current_bounded_domain_integrity_catalogs_are_ready() -> None:
    catalogs = [inspect_database_integrity_catalog(contract) for contract in CONTRACTS]

    assert all(catalog.ready for catalog in catalogs)
    assert inspect_applications_schema_catalog().ready
    assert applications_database_integrity_is_ready()
    assert inspect_programme_schema_catalog().ready
    assert programme_database_integrity_is_ready()


def test_missing_applications_relation_blocks_readiness_transactionally() -> None:
    """Detect a missing expected relation without reading domain rows."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                RENAME TO applications_readiness_missing_relation
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.relations_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_extra_applications_relation_blocks_readiness_transactionally() -> None:
    """Detect an unexpected relation in the owned namespace."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE public.applications_readiness_extra_relation (
                    id uuid PRIMARY KEY
                )
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.relations_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_extra_applications_sequence_blocks_readiness_transactionally() -> None:
    """Detect an unexpected non-table relation in the owned namespace."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "CREATE SEQUENCE public.applications_readiness_extra_sequence"
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.relations_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_applications_relation_semantics_block_readiness_transactionally() -> (
    None
):
    """Detect security metadata drift on an otherwise intact table."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationdefinition
                ENABLE ROW LEVEL SECURITY
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.relations_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_missing_applications_column_blocks_readiness_transactionally() -> None:
    """Detect one removed generic Applications column."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                DROP COLUMN media_type
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_extra_applications_column_blocks_readiness_transactionally() -> None:
    """Detect one unmodeled Applications column."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                ADD COLUMN readiness_extra text
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_applications_column_type_blocks_readiness_transactionally() -> None:
    """Detect same-name column type drift."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                ALTER COLUMN media_type TYPE varchar(121)
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_applications_column_nullability_blocks_readiness() -> None:
    """Detect same-name column nullability drift."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                ALTER COLUMN media_type DROP NOT NULL
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_applications_column_default_blocks_readiness() -> None:
    """Detect an unexpected database-owned column default."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                ALTER COLUMN media_type SET DEFAULT ''
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_applications_column_identity_blocks_readiness() -> None:
    """Detect an unexpected identity generator on an integer column."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                ALTER COLUMN size_bytes ADD GENERATED ALWAYS AS IDENTITY
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_applications_column_generation_blocks_readiness() -> None:
    """Detect an unexpected stored-generation expression."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                DROP COLUMN media_type
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                ADD COLUMN media_type varchar(120)
                GENERATED ALWAYS AS ('generated'::varchar(120)) STORED
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_applications_column_collation_blocks_readiness_transactionally() -> (
    None
):
    """Detect a same-type text column switched away from database default."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationfilereceipt
                ALTER COLUMN media_type
                TYPE varchar(120) COLLATE "C"
                USING media_type::varchar(120)
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_missing_applications_constraint_blocks_readiness_transactionally() -> None:
    """Detect removal from the complete constraint catalog."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationdefinition
                DROP CONSTRAINT applications_definition_versions_positive
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.constraints_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_extra_applications_constraint_blocks_readiness_transactionally() -> None:
    """Detect an unexpected constraint even when every expected one remains."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationdefinition
                ADD CONSTRAINT applications_readiness_extra_check CHECK (TRUE)
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.constraints_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_same_name_applications_constraint_blocks_readiness() -> None:
    """Detect a same-named check whose definition was weakened."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationdefinition
                DROP CONSTRAINT applications_definition_versions_positive
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.applications_applicationdefinition
                ADD CONSTRAINT applications_definition_versions_positive CHECK (TRUE)
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.constraints_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_missing_applications_index_blocks_readiness_transactionally() -> None:
    """Detect removal from the complete index catalog."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX public.app_definition_scope_idx")
        catalog = inspect_applications_schema_catalog()
        assert not catalog.indexes_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_extra_applications_index_blocks_readiness_transactionally() -> None:
    """Detect an unexpected index even when every expected one remains."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE INDEX applications_readiness_extra_idx
                ON public.applications_applicationdefinition (name)
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.indexes_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


def test_changed_same_name_applications_index_blocks_readiness() -> None:
    """Detect a same-named index whose definition was changed."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("DROP INDEX public.app_definition_scope_idx")
            cursor.execute(
                """
                CREATE INDEX app_definition_scope_idx
                ON public.applications_applicationdefinition (name)
                """
            )
        catalog = inspect_applications_schema_catalog()
        assert not catalog.indexes_current
        assert not catalog.ready
        assert not applications_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_applications_schema_catalog().ready


@pytest.mark.parametrize(
    ("relation", "constraint_name"),
    [
        (
            "programme_programmecommandreceipt",
            "programme_command_retry_uq",
        ),
        (
            "programme_programmeworkingrevision",
            "programme_working_item_version_uq",
        ),
    ],
)
def test_missing_critical_programme_unique_blocks_readiness_transactionally(
    relation: str,
    constraint_name: str,
) -> None:
    """Detect idempotency or aggregate-version uniqueness drift immediately."""
    drop = sql.SQL("ALTER TABLE public.{} DROP CONSTRAINT {}").format(
        sql.Identifier(relation),
        sql.Identifier(constraint_name),
    )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(drop)
        catalog = inspect_programme_schema_catalog()
        assert not catalog.constraints_current
        assert not catalog.ready
        assert not programme_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_programme_schema_catalog().ready


def test_missing_critical_programme_foreign_key_blocks_readiness_transactionally() -> (
    None
):
    """Detect removal of the item-to-edition tenant boundary without row reads."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT constraint_record.conname
                  FROM pg_catalog.pg_constraint AS constraint_record
                  JOIN pg_catalog.pg_class AS relation
                    ON relation.oid = constraint_record.conrelid
                  JOIN pg_catalog.pg_attribute AS attribute
                    ON attribute.attrelid = relation.oid
                   AND attribute.attnum = ANY(constraint_record.conkey)
                 WHERE relation.oid = pg_catalog.to_regclass(
                           'public.programme_programmeitem'
                       )
                   AND constraint_record.contype = 'f'
                   AND attribute.attname = 'edition_id'
                """
            )
            row = cursor.fetchone()
            assert row is not None
            cursor.execute(
                sql.SQL(
                    "ALTER TABLE public.programme_programmeitem DROP CONSTRAINT {}"
                ).format(sql.Identifier(str(row[0])))
            )
        catalog = inspect_programme_schema_catalog()
        assert not catalog.constraints_current
        assert not catalog.ready
        assert not programme_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_programme_schema_catalog().ready


def test_weakened_same_name_programme_check_blocks_readiness_transactionally() -> None:
    """Detect a same-named CHECK whose expression no longer protects data."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.programme_programmeitem
                DROP CONSTRAINT programme_item_version_pos
                """
            )
            cursor.execute(
                """
                ALTER TABLE public.programme_programmeitem
                ADD CONSTRAINT programme_item_version_pos CHECK (TRUE)
                """
            )
        catalog = inspect_programme_schema_catalog()
        assert not catalog.constraints_current
        assert not catalog.ready
        assert not programme_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_programme_schema_catalog().ready


def test_changed_same_name_partial_unique_blocks_readiness_transactionally() -> None:
    """Detect a same-named partial unique whose predicate was weakened."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DROP INDEX public.programme_command_item_version_uq
                """
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX programme_command_item_version_uq
                ON public.programme_programmecommandreceipt (
                    item_id,
                    resulting_item_version
                )
                WHERE operation <> 'item_create'
                """
            )
        catalog = inspect_programme_schema_catalog()
        assert not catalog.indexes_current
        assert not catalog.ready
        assert not programme_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_programme_schema_catalog().ready


def test_changed_programme_column_collation_blocks_readiness_transactionally() -> None:
    """Detect a same-type text column switched away from database default."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                """
                ALTER TABLE public.programme_programmeworkingrevision
                ALTER COLUMN internal_title
                TYPE varchar(240) COLLATE "C"
                USING internal_title::varchar(240)
                """
            )
        catalog = inspect_programme_schema_catalog()
        assert not catalog.columns_current
        assert not catalog.ready
        assert not programme_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_programme_schema_catalog().ready


@pytest.mark.parametrize(
    "statement",
    [
        ("ALTER TABLE public.programme_programmeitem ENABLE ROW LEVEL SECURITY"),
        ("ALTER TABLE public.programme_programmeitem FORCE ROW LEVEL SECURITY"),
        ("ALTER TABLE public.programme_programmeitem REPLICA IDENTITY NOTHING"),
    ],
    ids=["enable-rls", "force-rls", "replica-identity"],
)
def test_changed_programme_relation_semantics_block_readiness_transactionally(
    statement: str,
) -> None:
    """Detect security and replication flags on an otherwise intact table."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(statement)
        catalog = inspect_programme_schema_catalog()
        assert not catalog.relations_current
        assert not catalog.ready
        assert not programme_database_integrity_is_ready()
        transaction.set_rollback(True)

    assert inspect_programme_schema_catalog().ready


@pytest.mark.parametrize("relation", PROGRAMME_RELATIONS)
def test_every_programme_relation_refuses_truncate(relation: str) -> None:
    """Keep retained Programme rows protected from statement-level deletion."""
    with pytest.raises(DatabaseError, match="cannot be truncated"):
        _truncate_programme_relation(relation)


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
