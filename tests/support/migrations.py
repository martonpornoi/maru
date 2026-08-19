"""Helpers that keep migration integration tests from contaminating the suite."""

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

_REGISTRATION_DEPARTMENT_FK_MIGRATION = (
    "registration",
    "0039_profile_audiences_and_platform_starter",
)
_WORKFORCE_BEFORE_DEPARTMENT_FK_SUCCESSOR = (
    "workforce",
    "0007_structure_write_integrity",
)


def current_migration_leaves() -> tuple[tuple[str, str], ...]:
    """Return every current leaf from the migration graph on disk."""

    executor = MigrationExecutor(connection)
    return tuple(executor.loader.graph.leaf_nodes())


def registration_migration_targets(
    executor: MigrationExecutor,
    target: tuple[str, str],
) -> tuple[tuple[str, str], ...]:
    """Select a graph-consistent Workforce leaf for Registration history."""

    targets_by_app = {
        migration_key[0]: migration_key
        for migration_key in executor.loader.graph.leaf_nodes()
    }
    targets_by_app["registration"] = target
    if _REGISTRATION_DEPARTMENT_FK_MIGRATION not in (
        executor.loader.graph.forwards_plan(target)
    ):
        targets_by_app["workforce"] = _WORKFORCE_BEFORE_DEPARTMENT_FK_SUCCESSOR
    return tuple(sorted(targets_by_app.values()))


def restore_current_migration_graph() -> MigrationExecutor:
    """Bring every Django app back to its current migration leaf."""

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    return executor


def flush_then_restore_current_migration_graph() -> MigrationExecutor:
    """Discard historical test data before applying current forward fences."""

    try:
        call_command(
            "flush",
            verbosity=0,
            interactive=False,
            database=connection.alias,
            reset_sequences=False,
            allow_cascade=True,
            inhibit_post_migrate=True,
        )
    finally:
        executor = restore_current_migration_graph()
    return executor
