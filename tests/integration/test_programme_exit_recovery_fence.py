"""Real empty joined-fence reversal must refuse readiness until exact restoration."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from maru.events.programme_stop_readiness import programme_stop_command_is_ready

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.mark.usefixtures("restores_current_migration_graph")
def test_unused_exit_fence_reverses_and_restores_complete_readiness():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    assert programme_stop_command_is_ready()
    try:
        executor.migrate([("events", "0016_programme_stop_integrity")])
        assert not programme_stop_command_is_ready()
        assert ("events", "0017_programme_exit_recovery_fence") not in (
            MigrationExecutor(connection).loader.applied_migrations
        )
    finally:
        MigrationExecutor(connection).migrate(leaves)
    assert programme_stop_command_is_ready()
