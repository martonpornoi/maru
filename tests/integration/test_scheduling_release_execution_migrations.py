"""Real unused ACL reversal and populated native-evidence recovery fences."""

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.audit.mutation_evidence import audited_mutation
from maru.core.database_integrity_readiness import inspect_database_integrity_catalog
from maru.scheduling.models import SchedulingReleaseDependencyKey
from maru.scheduling.readiness import SCHEDULING_INTEGRITY_CONTRACT
from maru.scheduling.writer_boundary import scheduling_writer
from tests.factories import AccountFactory
from tests.integration.test_audit_mutation_evidence import _record

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("restores_current_migration_graph"),
]
_BEFORE_EXECUTION_BOUNDARY = ("scheduling", "0011_release_source_baseline")


def test_unused_native_execution_boundary_really_reverses_and_recovers():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    assert inspect_database_integrity_catalog(SCHEDULING_INTEGRITY_CONTRACT).ready
    try:
        executor.migrate([_BEFORE_EXECUTION_BOUNDARY])
        catalog = inspect_database_integrity_catalog(SCHEDULING_INTEGRITY_CONTRACT)
        assert not catalog.required_migrations_applied
        assert not catalog.function_execute_boundary_closed
        assert not catalog.ready
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_proc p, "
                "LATERAL pg_catalog.aclexplode(p.proacl) acl "
                "WHERE p.oid = "
                "'public.maru_audit_current_native_transaction_stamp()'::regprocedure "
                "AND acl.grantee=0 AND acl.privilege_type='EXECUTE')"
            )
            assert cursor.fetchone() == (True,)
    finally:
        MigrationExecutor(connection).migrate(leaves)
    assert inspect_database_integrity_catalog(SCHEDULING_INTEGRITY_CONTRACT).ready


@pytest.mark.parametrize("evidence", ["witness", "key"])
def test_native_evidence_fences_acl_reopening_before_any_migration_is_removed(evidence):
    with transaction.atomic():
        if evidence == "witness":
            with audited_mutation(_record()):
                pass
        else:
            person = AccountFactory()
            with scheduling_writer():
                SchedulingReleaseDependencyKey.objects.create(
                    kind="identity_account",
                    source_id=person.id,
                )
    before = set(MigrationRecorder(connection).applied_migrations())
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
        MigrationExecutor(connection).migrate([_BEFORE_EXECUTION_BOUNDARY])
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert inspect_database_integrity_catalog(SCHEDULING_INTEGRITY_CONTRACT).ready
