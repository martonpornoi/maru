"""Real reversible empty migrations and retained-evidence downgrade fences."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

from maru.announcements.models import AnnouncementCommandReceipt, AnnouncementRevision
from maru.announcements.readiness import announcements_database_integrity_is_ready
from tests.factories import OrganizationRepresentationFactory, RoleBundleFactory
from tests.integration.test_announcements_domain import approved, world
from tests.support.migrations import rollback_migration_case

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_unused_announcements_reverse_and_reapply_exact_native_contract():
    assert announcements_database_integrity_is_ready()
    with rollback_migration_case():
        executor = MigrationExecutor(connection)
        leaves = executor.loader.graph.leaf_nodes()
        executor.migrate([("announcements", "0001_initial")])
        assert not announcements_database_integrity_is_ready()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regprocedure('public.maru_announcements_graph_guard()')"
            )
            assert cursor.fetchone()[0] is None
        MigrationExecutor(connection).migrate([("announcements", None)])
        assert not any(
            name.startswith("announcements_")
            for name in connection.introspection.table_names()
        )
        MigrationExecutor(connection).migrate(leaves)
        assert announcements_database_integrity_is_ready()
    assert announcements_database_integrity_is_ready()


def test_used_announcements_refuses_downgrade_before_removing_guards(world):
    approved(world)
    before = (
        list(AnnouncementCommandReceipt.objects.order_by("id").values()),
        list(AnnouncementRevision.objects.order_by("id").values()),
        set(MigrationRecorder(connection).applied_migrations()),
    )
    with (
        pytest.raises(RuntimeError, match="retain it and fix forward"),
        rollback_migration_case(),
    ):
        MigrationExecutor(connection).migrate([("announcements", "0001_initial")])
    assert (
        list(AnnouncementCommandReceipt.objects.order_by("id").values()),
        list(AnnouncementRevision.objects.order_by("id").values()),
        set(MigrationRecorder(connection).applied_migrations()),
    ) == before
    assert announcements_database_integrity_is_ready()


@pytest.mark.parametrize(
    ("retained", "target"),
    [
        ("representation", ("organizations", "0014_purpose_bounded_representation")),
        ("capability", ("authorization", "0040_programme_stop_boundary")),
    ],
)
def test_retained_foundation_without_edition_refuses_before_successor_removal(
    retained, target, restores_current_migration_graph
):
    del restores_current_migration_graph
    if retained == "representation":
        OrganizationRepresentationFactory(
            code="announcements_operators", name="Announcements operators"
        )
    else:
        RoleBundleFactory(capability_codes=["announcements.compose"])
    before = set(MigrationRecorder(connection).applied_migrations())
    assert announcements_database_integrity_is_ready()
    # No outer rollback: each earlier successful migration reversal would remain
    # committed, so recorder equality detects a late refusal rather than hiding it.
    with pytest.raises(RuntimeError, match=r"Announcements .*fix forward"):
        MigrationExecutor(connection).migrate([target])
    assert set(MigrationRecorder(connection).applied_migrations()) == before
    assert announcements_database_integrity_is_ready()


__all__ = ["world"]
