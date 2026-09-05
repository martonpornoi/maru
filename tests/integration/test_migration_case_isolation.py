"""Prove historical-case isolation against real PostgreSQL, not mocked DDL."""

from contextlib import nullcontext

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.recorder import MigrationRecorder

from tests.support.migrations import rollback_migration_case

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.mark.parametrize("fail", [False, True])
def test_case_restores_schema_data_recorder_and_callbacks(fail: bool) -> None:
    callbacks: list[str] = []
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE migration_case_sentinel (value integer)")
    try:
        with (
            pytest.raises(ValueError, match="synthetic") if fail else nullcontext(),
            rollback_migration_case(),
        ):
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO migration_case_sentinel VALUES (1)")
                cursor.execute("ALTER TABLE migration_case_sentinel ADD extra text")
            MigrationRecorder(connection).record_applied("synthetic", "0001_case")
            transaction.on_commit(lambda: callbacks.append("committed"))
            if fail:
                raise ValueError("synthetic case failure")
        assert callbacks == []
        assert ("synthetic", "0001_case") not in MigrationRecorder(
            connection
        ).applied_migrations()
        # A second independent case must see neither rows nor the added column.
        with rollback_migration_case(), connection.cursor() as cursor:
            cursor.execute("SELECT * FROM migration_case_sentinel")
            assert cursor.fetchall() == []
            assert [column.name for column in cursor.description] == ["value"]
    finally:
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE migration_case_sentinel")


def test_deferred_constraint_violation_is_not_hidden_by_rollback() -> None:
    def violate_deferred_constraint() -> None:
        with rollback_migration_case(), connection.cursor() as cursor:
            cursor.execute(
                "CREATE TABLE migration_case_deferred "
                "(value integer UNIQUE DEFERRABLE INITIALLY DEFERRED)"
            )
            cursor.execute("INSERT INTO migration_case_deferred VALUES (1), (1)")

    with pytest.raises(IntegrityError):
        violate_deferred_constraint()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('migration_case_deferred')")
        assert cursor.fetchone() == (None,)


def test_nested_transaction_cannot_masquerade_as_a_committed_baseline() -> None:
    with (
        transaction.atomic(),
        pytest.raises(RuntimeError, match="idle PostgreSQL"),
        rollback_migration_case(),
    ):
        pytest.fail("Nested historical baseline was accepted.")
