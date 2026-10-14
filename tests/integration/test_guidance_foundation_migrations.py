"""Early joined downgrade refusal for bare Guides editions and Workspace roots."""

from importlib import import_module

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.events.guidance_setup_readiness import (
    guidance_setup_database_integrity_is_ready,
)
from tests.factories import EventEditionFactory, OrganizationRepresentationFactory
from tests.support.migrations import rollback_migration_case

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


@pytest.mark.parametrize("retained", ["edition", "workspace"])
def test_bare_used_foundation_refuses_before_any_successor_recorder_changes(
    retained, restores_current_migration_graph
):
    if retained == "edition":
        EventEditionFactory(
            adoption_profile_code="guidance_only",
            adoption_profile_version=1,
            currency_codes=["XXX"],
        )
    else:
        OrganizationRepresentationFactory(
            code="workspace_operators", name="Workspace operators"
        )
    before = set(MigrationRecorder(connection).applied_migrations())
    # No outer rollback: a late refusal must expose any already reversed successor.
    with pytest.raises(RuntimeError, match="fix forward"):
        MigrationExecutor(connection).migrate(
            [("authorization", "0042_announcements_operator_lineage")]
        )
    assert set(MigrationRecorder(connection).applied_migrations()) == before


def _aggregate_guard_state():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.oid, p.proowner, p.prosrc, p.proacl::text,
                   p.prolang, p.provolatile, p.proparallel, p.prosecdef,
                   p.proleakproof, p.proisstrict, p.proretset, p.prokind,
                   p.proconfig, pg_catalog.pg_get_function_result(p.oid)
              FROM pg_catalog.pg_proc AS p
             WHERE p.oid =
                 'public.maru_validate_edition_aggregate_version()'::regprocedure
            """
        )
        state = cursor.fetchone()
    assert state is not None
    return state


def _assert_aggregate_execute_is_owner_only():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proowner, acl.grantor, acl.grantee
              FROM pg_catalog.pg_proc AS p
              CROSS JOIN LATERAL pg_catalog.aclexplode(
                  COALESCE(p.proacl, pg_catalog.acldefault('f', p.proowner))
              ) AS acl
             WHERE p.oid =
                 'public.maru_validate_edition_aggregate_version()'::regprocedure
               AND acl.privilege_type = 'EXECUTE'
            """
        )
        rows = cursor.fetchall()
    assert len(rows) == 1
    owner, grantor, grantee = rows[0]
    assert owner == grantor == grantee


def test_fresh_guidance_migration_hardens_aggregate_before_any_setup():
    # No runtime provisioning or readiness doubles: fresh migrations themselves
    # must close the inherited trigger ACL before the public setup command runs.
    _assert_aggregate_execute_is_owner_only()
    assert guidance_setup_database_integrity_is_ready()


def test_aggregate_public_execute_drift_denies_guidance_setup():
    assert guidance_setup_database_integrity_is_ready()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "GRANT EXECUTE ON FUNCTION "
                "public.maru_validate_edition_aggregate_version() TO PUBLIC"
            )
        assert not guidance_setup_database_integrity_is_ready()
        transaction.set_rollback(True)
    _assert_aggregate_execute_is_owner_only()
    assert guidance_setup_database_integrity_is_ready()


def test_unused_guidance_reverse_reapply_preserves_hardened_predecessor():
    migration = import_module("maru.events.migrations.0023_guidance_adoption_integrity")
    before = _aggregate_guard_state()
    assert before[2] == migration.next_source()
    _assert_aggregate_execute_is_owner_only()
    with rollback_migration_case():
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        executor.migrate([("events", "0022_guidance_adoption_profiles")])
        restored = _aggregate_guard_state()
        assert restored[2] == migration.previous_source()
        assert restored[:2] == before[:2]
        assert restored[3:] == before[3:]
        _assert_aggregate_execute_is_owner_only()
        assert not guidance_setup_database_integrity_is_ready()
        MigrationExecutor(connection).migrate(leaves)
        assert _aggregate_guard_state() == before
        _assert_aggregate_execute_is_owner_only()
        assert guidance_setup_database_integrity_is_ready()
    assert _aggregate_guard_state() == before
    assert guidance_setup_database_integrity_is_ready()
