"""Maintained real notice-schema recovery and negative metadata acceptance."""

import pytest
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.utils import timezone

from maru.scheduling.readiness import scheduling_database_integrity_is_ready
from tests.factories import (
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleBundleFactory,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("restores_current_migration_graph"),
]


def test_unused_notice_extension_reverses_and_recovers_with_real_migrations():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    assert scheduling_database_integrity_is_ready()
    try:
        executor.migrate([("scheduling", "0020_release_recovery_fence")])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.scheduling_schedulingchangenotice'), "
                "to_regclass('public.scheduling_schedulingchangenoticeevidence'), "
                "to_regprocedure('public.maru_scheduling_change_notice_graph()')"
            )
            assert cursor.fetchone() == (None, None, None)
        assert not scheduling_database_integrity_is_ready()
    finally:
        MigrationExecutor(connection).migrate(leaves)
    assert scheduling_database_integrity_is_ready()


@pytest.mark.parametrize("evidence", ["revoked_grant", "role_bundle"])
def test_notice_authority_blocks_downgrade_before_any_successor_recorder_changes(
    evidence,
):
    edition = EventEditionFactory()
    code = "scheduling.prepare_change_notices"
    if evidence == "revoked_grant":
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            capability_code=code,
            revoked_at=timezone.now(),
        )
    else:
        RoleBundleFactory(organization=edition.organization, capability_codes=[code])
    before = set(MigrationRecorder(connection).applied_migrations())
    with pytest.raises(RuntimeError, match="retain it and fix forward"):
        MigrationExecutor(connection).migrate(
            [("authorization", "0030_programme_operator_capabilities")]
        )
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert scheduling_database_integrity_is_ready()


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE public.scheduling_schedulingchangenotice "
        "DROP CONSTRAINT sch_change_notice_shape",
        "ALTER TABLE public.scheduling_schedulingchangenoticeevidence "
        "DROP CONSTRAINT sch_change_evidence_shape",
        "ALTER TABLE public.scheduling_schedulingchangenoticeevidence "
        "DISABLE TRIGGER sch_notice_1_graph_guard",
        "GRANT EXECUTE ON FUNCTION "
        "public.maru_scheduling_change_notice_source_valid(uuid) TO PUBLIC",
    ],
)
def test_weakened_notice_metadata_never_passes_readiness(mutation):
    assert scheduling_database_integrity_is_ready()
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(mutation)
        assert not scheduling_database_integrity_is_ready()
        transaction.set_rollback(True)
    assert scheduling_database_integrity_is_ready()
