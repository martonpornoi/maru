import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.special import RunPython, RunSQL

from maru.authorization.provenance_readiness import (
    _FUNCTION_DEFINITION_SHA256,
    _function_definition_fingerprint,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_BEFORE = (
    "authorization",
    "0010_retired_department_authority_guards",
)
AUTHORIZATION_AFTER = (
    "authorization",
    "0011_registration_profile_extension_capabilities",
)


def _migrate(target: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def _minimum_scope(capability_code: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_authorization_capability_min_scope(%s)",
            [capability_code],
        )
        row = cursor.fetchone()
    assert row is not None
    return int(row[0])


def test_catalog_expansion_is_atomic_and_empty_reversal_is_exact() -> None:
    _migrate(AUTHORIZATION_BEFORE)
    assert _minimum_scope("registration.view_profile_extensions") == -1
    assert _minimum_scope("registration.update_profile_extensions") == -1

    _migrate(AUTHORIZATION_AFTER)
    assert _minimum_scope("registration.view_profile_extensions") == 1
    assert _minimum_scope("registration.update_profile_extensions") == 1
    assert _minimum_scope("registration.unknown_profile_extension") == -1

    _migrate(AUTHORIZATION_BEFORE)
    assert _minimum_scope("registration.view_profile_extensions") == -1
    assert _minimum_scope("registration.update_profile_extensions") == -1

    _migrate(AUTHORIZATION_AFTER)


def test_reverse_fence_precedes_catalog_contraction() -> None:
    executor = MigrationExecutor(connection)
    migration = executor.loader.disk_migrations[AUTHORIZATION_AFTER]

    assert isinstance(migration.operations[0], RunSQL)
    assert isinstance(migration.operations[1], RunPython)
    assert "registration.view_profile_extensions" in migration.operations[0].sql
    assert "registration.update_profile_extensions" in migration.operations[0].sql
    assert migration.operations[1].reverse_code is not RunPython.noop


def test_catalog_function_matches_the_reviewed_readiness_fingerprint() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT procedure.prosrc,
                   language.lanname::text,
                   procedure.provolatile::text,
                   procedure.proparallel::text,
                   procedure.prosecdef,
                   procedure.proleakproof,
                   procedure.proisstrict,
                   procedure.proretset,
                   procedure.prokind::text,
                   procedure.proconfig,
                   pg_get_function_result(procedure.oid)
              FROM pg_proc AS procedure
              JOIN pg_language AS language ON language.oid = procedure.prolang
             WHERE procedure.oid = to_regprocedure(
                 'public.maru_authorization_capability_min_scope(text)'
             )
            """
        )
        definition = cursor.fetchone()

    assert definition is not None
    fingerprint = _function_definition_fingerprint(definition)
    assert (
        fingerprint
        == _FUNCTION_DEFINITION_SHA256["maru_authorization_capability_min_scope(text)"]
    ), fingerprint
