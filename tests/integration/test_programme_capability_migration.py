"""PostgreSQL scope and downgrade coverage for Programme capabilities."""

from uuid import UUID

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.special import RunPython, RunSQL

from maru.authorization.provenance_readiness import (
    _FUNCTION_DEFINITION_SHA256,
    _function_definition_fingerprint,
)
from tests.factories import (
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleBundleFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_BEFORE = ("authorization", "0019_progressive_adoption_authority")
AUTHORIZATION_AFTER = ("authorization", "0020_programme_capabilities")
PROGRAMME_CAPABILITIES = (
    "programme.view_private",
    "programme.manage_items",
    "programme.view_readiness",
    "programme.manage_readiness",
    "programme.view_delivery",
    "programme.manage_delivery",
    "programme.view_discussion",
    "programme.view_public_copy",
    "programme.approve_public_copy",
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


def _scope_function_is_installed() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regprocedure(
                'public.maru_authorization_capability_min_scope(text)'
            ) IS NOT NULL
            """
        )
        row = cursor.fetchone()
    assert row is not None
    return bool(row[0])


def _installed_scope_function_fingerprint() -> str:
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
    return _function_definition_fingerprint(definition)


def _assert_used_capability_refuses_reverse(
    *,
    relation: str,
    object_id: UUID,
) -> None:
    with pytest.raises(RuntimeError, match="Cannot remove Programme authority"):
        _migrate(AUTHORIZATION_BEFORE)

    executor = MigrationExecutor(connection)
    assert AUTHORIZATION_AFTER in executor.loader.applied_migrations
    assert _scope_function_is_installed()
    assert _minimum_scope("programme.manage_items") == 1
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT 1 FROM public.{relation} WHERE id = %s",  # noqa: S608
            [object_id],
        )
        assert cursor.fetchone() == (1,)


def test_programme_capability_expansion_and_empty_reversal_are_exact() -> None:
    _migrate(AUTHORIZATION_BEFORE)
    before_fingerprint = _installed_scope_function_fingerprint()
    assert all(_minimum_scope(code) == -1 for code in PROGRAMME_CAPABILITIES)

    _migrate(AUTHORIZATION_AFTER)
    assert _installed_scope_function_fingerprint() != before_fingerprint
    assert all(_minimum_scope(code) == 1 for code in PROGRAMME_CAPABILITIES)
    assert _minimum_scope("programme.future_unregistered") == -1

    _migrate(AUTHORIZATION_BEFORE)
    assert all(_minimum_scope(code) == -1 for code in PROGRAMME_CAPABILITIES)
    assert _installed_scope_function_fingerprint() == before_fingerprint

    _migrate(AUTHORIZATION_AFTER)


def test_programme_capability_reverse_fence_precedes_catalog_contraction() -> None:
    executor = MigrationExecutor(connection)
    migration = executor.loader.disk_migrations[AUTHORIZATION_AFTER]

    assert isinstance(migration.operations[0], RunSQL)
    assert isinstance(migration.operations[1], RunPython)
    assert all(code in migration.operations[0].sql for code in PROGRAMME_CAPABILITIES)
    assert migration.operations[1].reverse_code is not RunPython.noop


def test_durable_programme_grant_refuses_capability_contraction() -> None:
    """Keep exact-edition direct authority and its scope catalog installed."""
    edition = EventEditionFactory()
    grant = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        capability_code="programme.manage_items",
    )

    _assert_used_capability_refuses_reverse(
        relation="authorization_capabilitygrant",
        object_id=grant.id,
    )


def test_durable_programme_role_refuses_capability_contraction() -> None:
    """Keep a reusable Programme role and its scope catalog installed."""
    role = RoleBundleFactory(capability_codes=["programme.manage_items"])

    _assert_used_capability_refuses_reverse(
        relation="authorization_rolebundle",
        object_id=role.id,
    )


def test_programme_capabilities_match_the_readiness_function_fingerprint() -> None:
    """Pin the installed catalog expansion to the readiness contract."""
    fingerprint = _installed_scope_function_fingerprint()
    assert (
        fingerprint
        == _FUNCTION_DEFINITION_SHA256["maru_authorization_capability_min_scope(text)"]
    ), fingerprint
