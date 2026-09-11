"""Ordinary committed empty reversal and populated joint-graph recovery fences."""

from importlib import import_module

import pytest
from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.audit.models import AuditNativeMutationWitness
from maru.scheduling.models import SchedulingCandidate, SchedulingCandidateRevision
from maru.scheduling.readiness import scheduling_database_integrity_is_ready
from maru.venues.readiness import venues_database_integrity_is_ready
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414

pytestmark = [
    pytest.mark.integration,
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("restores_current_migration_graph"),
]


def test_empty_joint_graph_reverses_and_recovers_with_normal_migrations():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate([("scheduling", None)])
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.scheduling_schedulingcandidate'), "
                "to_regclass('public.venues_venueschedulingbinding'), "
                "to_regprocedure('public.maru_validate_venue_scheduling_graph()'), "
                "to_regprocedure('public.maru_guard_scheduling_row()')"
            )
            assert cursor.fetchone() == (None, None, None, None)
        assert not scheduling_database_integrity_is_ready()
        assert not venues_database_integrity_is_ready()
    finally:
        MigrationExecutor(connection).migrate(leaves)
    assert scheduling_database_integrity_is_ready()
    assert venues_database_integrity_is_ready()


@pytest.mark.parametrize(
    "target",
    [
        ("scheduling", "0004_conflict_vocabulary"),
        ("venues", "0003_scheduling_reservation_sources"),
    ],
)
def test_planning_history_fences_both_owners_before_any_guard_is_removed(world, target):
    before = set(MigrationRecorder(connection).applied_migrations())
    candidate = SchedulingCandidate.objects.values().get(id=world.candidate.object_id)
    revision = SchedulingCandidateRevision.objects.values().get(
        candidate_id=world.candidate.object_id, sequence=world.candidate.version
    )
    reference = (
        "maru.scheduling.migrations.0006_scheduling_downgrade_fence"
        if target[0] == "scheduling"
        else "maru.venues.migrations.0005_scheduling_downgrade_fence"
    )
    with (
        pytest.raises(RuntimeError, match="retain compatible code and fix forward"),
        connection.schema_editor() as editor,
    ):
        import_module(reference).refuse_used_scheduling_downgrade(apps, editor)
    assert AuditNativeMutationWitness.objects.exists()
    with pytest.raises(RuntimeError, match="retain its execution boundary"):
        MigrationExecutor(connection).migrate([target])
    # Native source evidence fences the current extension before any successor
    # can reverse, including successors with no direct staffing records yet.
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert SchedulingCandidate.objects.values().get(id=candidate["id"]) == candidate
    assert (
        SchedulingCandidateRevision.objects.values().get(id=revision["id"]) == revision
    )
    assert scheduling_database_integrity_is_ready()
    assert venues_database_integrity_is_ready()
    MigrationExecutor(connection).migrate(
        MigrationExecutor(connection).loader.graph.leaf_nodes()
    )
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert SchedulingCandidate.objects.values().get(id=candidate["id"]) == candidate
    assert (
        SchedulingCandidateRevision.objects.values().get(id=revision["id"]) == revision
    )
    assert scheduling_database_integrity_is_ready()
    assert venues_database_integrity_is_ready()
