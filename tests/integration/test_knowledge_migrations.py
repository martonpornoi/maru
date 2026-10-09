"""Unused full reversal and refusal before retained joined evidence can be removed."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.knowledge.models import GuidanceCommandReceipt, GuidanceItem, GuidanceRevision
from maru.knowledge.readiness import knowledge_database_integrity_is_ready
from tests.integration.guidance_test_support import guidance_runtime
from tests.integration.test_knowledge_domain import approved, world
from tests.support.migrations import rollback_migration_case

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_unused_knowledge_fully_reverses_and_reapplies_native_contract(
    guidance_runtime,
):
    assert knowledge_database_integrity_is_ready()
    with rollback_migration_case():
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        executor.migrate([("knowledge", "0001_initial")])
        assert not knowledge_database_integrity_is_ready()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regprocedure('public.maru_knowledge_graph_guard()')"
            )
            assert cursor.fetchone()[0] is None
        MigrationExecutor(connection).migrate([("knowledge", None)])
        assert not any(
            name.startswith("knowledge_")
            for name in connection.introspection.table_names()
        )
        MigrationExecutor(connection).migrate(leaves)
        assert knowledge_database_integrity_is_ready()
    assert knowledge_database_integrity_is_ready()


def test_used_knowledge_refuses_before_any_migration_or_owner_evidence_changes(world):
    approved(world)

    def snapshot():
        return (
            list(GuidanceItem.objects.order_by("id").values()),
            list(GuidanceCommandReceipt.objects.order_by("id").values()),
            list(GuidanceRevision.objects.order_by("id").values()),
            set(MigrationRecorder(connection).applied_migrations()),
        )

    before = snapshot()
    with rollback_migration_case():
        with pytest.raises(RuntimeError):
            MigrationExecutor(connection).migrate([("knowledge", None)])
        # Check before the isolation fixture rolls back: a late refusal must not
        # hide earlier recorder or schema changes behind the outer rollback.
        assert snapshot() == before
        assert knowledge_database_integrity_is_ready()
    assert snapshot() == before
    assert knowledge_database_integrity_is_ready()


__all__ = ["guidance_runtime", "world"]


def test_unused_owner_still_fences_retained_foundation_before_successor_reversal(world):
    assert not GuidanceItem.objects.exists()
    before = set(MigrationRecorder(connection).applied_migrations())
    with rollback_migration_case():
        with pytest.raises(RuntimeError):
            MigrationExecutor(connection).migrate(
                [("events", "0021_announcements_setup_downgrade_fence")]
            )
        assert set(MigrationRecorder(connection).applied_migrations()) == before
        assert knowledge_database_integrity_is_ready()
    assert set(MigrationRecorder(connection).applied_migrations()) == before
