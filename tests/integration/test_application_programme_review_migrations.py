"""Fresh review install, empty reversal, and retained-evidence downgrade fences."""

from importlib import import_module

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from maru.applications.models import ProgrammeReviewPolicy
from maru.applications.readiness import (
    APPLICATIONS_INTEGRITY_CONTRACT,
    applications_database_integrity_is_ready,
)
from maru.core.database_integrity_readiness import (
    inspect_database_integrity_catalog,
    parse_database_integrity_sql_contracts,
)
from tests.factories import RoleBundleFactory
from tests.integration.test_application_programme_services import (
    _admit_future_programme_effects,
)
from tests.support.programme_review import create_review_world

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures(
        "restores_current_migration_graph", _admit_future_programme_effects.__name__
    ),
]
_BEFORE = ("applications", "0012_programme_department_ownership_downgrade_fence")
_AFTER = ("applications", "0015_programme_review_downgrade_fence")


def test_empty_review_schema_reverses_and_installs_the_actual_final_guards():
    MigrationExecutor(connection).migrate([_BEFORE])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.to_regclass('public.applications_programmereviewpolicy')"
        )
        assert cursor.fetchone() == (None,)
    MigrationExecutor(connection).migrate([_AFTER])
    migration = import_module(
        "maru.applications.migrations.0014_programme_review_integrity"
    )
    with connection.cursor() as cursor:
        for _suffix, table in migration.REVIEW_TABLES:
            cursor.execute(
                "SELECT pg_catalog.to_regclass(%s) IS NOT NULL", ["public." + table]
            )
            assert cursor.fetchone() == (True,)
        triggers, _functions = parse_database_integrity_sql_contracts(
            migration.FORWARD_SQL
        )
        cursor.execute(
            "SELECT t.tgname, r.relname FROM pg_catalog.pg_trigger t "
            "JOIN pg_catalog.pg_class r ON r.oid = t.tgrelid "
            "WHERE t.tgname = ANY(%s) AND NOT t.tgisinternal",
            [list(triggers)],
        )
        assert set(cursor.fetchall()) == {
            (name, contract.table) for name, contract in triggers.items()
        }
    # Prove execution, not only the presence of newly installed SQL text.
    world = create_review_world()
    assert world.version == 1
    assert applications_database_integrity_is_ready()


def test_retained_review_fences_downgrade_before_any_guard_or_table_is_removed():
    world = create_review_world()
    with pytest.raises(RuntimeError, match="durable evidence exists"):
        MigrationExecutor(connection).migrate([_BEFORE])
    assert ProgrammeReviewPolicy.objects.filter(id=world.policy_id).exists()
    assert _AFTER in MigrationExecutor(connection).loader.applied_migrations
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.to_regprocedure("
            "'public.maru_applications_validate_programme_review()') IS NOT NULL"
        )
        assert cursor.fetchone() == (True,)


def test_retained_review_role_fences_authorization_vocabulary_downgrade():
    RoleBundleFactory(
        capability_codes=[
            "applications.manage_programme_review",
            "applications.review_programme",
            "applications.moderate_programme_review",
            "applications.decide_programme",
        ]
    )
    with pytest.raises(RuntimeError, match="durable authority evidence"):
        MigrationExecutor(connection).migrate(
            [("authorization", "0023_programme_department_ownership_recovery")]
        )
    assert ("authorization", "0024_programme_review_capabilities") in (
        MigrationExecutor(connection).loader.applied_migrations
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT public.maru_authorization_capability_min_scope(%s)",
            ["applications.decide_programme"],
        )
        assert cursor.fetchone() == (2,)


@pytest.mark.parametrize("mutation", ["volatility", "public_execute"])
def test_review_helper_drift_fails_readiness_and_transactional_restore_recovers(
    mutation,
):
    assert inspect_database_integrity_catalog(APPLICATIONS_INTEGRITY_CONTRACT).ready
    with transaction.atomic(), connection.cursor() as cursor:
        if mutation == "volatility":
            cursor.execute(
                "ALTER FUNCTION public.maru_applications_review_stage_ready("
                "uuid, integer, bigint) IMMUTABLE"
            )
        else:
            cursor.execute(
                "GRANT EXECUTE ON FUNCTION public.maru_applications_review_stage_ready("
                "uuid, integer, bigint) TO PUBLIC"
            )
        assert not inspect_database_integrity_catalog(
            APPLICATIONS_INTEGRITY_CONTRACT
        ).ready
        transaction.set_rollback(True)
    assert inspect_database_integrity_catalog(APPLICATIONS_INTEGRITY_CONTRACT).ready
