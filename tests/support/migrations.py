"""Helpers that keep migration integration tests from contaminating the suite."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def current_migration_leaves() -> tuple[tuple[str, str], ...]:
    """Return every current leaf from the migration graph on disk."""

    executor = MigrationExecutor(connection)
    return tuple(executor.loader.graph.leaf_nodes())


def restore_current_migration_graph() -> MigrationExecutor:
    """Bring every Django app back to its current migration leaf."""

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    return executor
