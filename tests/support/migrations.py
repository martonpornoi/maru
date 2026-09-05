"""Helpers that keep migration integration tests from contaminating the suite."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.core.management import call_command
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

_REGISTRATION_DEPARTMENT_FK_MIGRATION = (
    "registration",
    "0039_profile_audiences_and_platform_starter",
)
_WORKFORCE_BEFORE_DEPARTMENT_FK_SUCCESSOR = (
    "workforce",
    "0007_structure_write_integrity",
)
_IDENTITY_PROGRAMME_PROPOSAL_PERSON_GUARD = (
    "identity",
    "0020_programme_proposal_person_guard",
)
_APPLICATIONS_BEFORE_IDENTITY_PROGRAMME_GUARD = (
    "applications",
    "0004_programme_calls_and_proposals",
)
_WORKFORCE_PROGRAMME_CALL_FK_CONTRACT = (
    "workforce",
    "0016_programme_call_department_fk_contract",
)
_WORKFORCE_PROGRAMME_IMPORT_FK_CONTRACT = (
    "workforce",
    "0017_programme_import_department_fk_contract",
)
_WORKFORCE_PROGRAMME_OWNERSHIP_FK_CONTRACT = (
    "workforce",
    "0018_programme_department_ownership_contract",
)
_WORKFORCE_CROSS_MODULE_DEPARTMENT_FK_CONTRACT = (
    "workforce",
    "0008_department_fk_contract_successor",
)
_APPLICATIONS_BEFORE_PROGRAMME_IMPORT = (
    "applications",
    "0006_programme_populated_downgrade_fence",
)
_APPLICATIONS_BEFORE_PROGRAMME_OWNERSHIP = (
    "applications",
    "0009_programme_import_populated_downgrade_fence",
)
_APPLICATIONS_BEFORE_PROGRAMME_CALLS = (
    "applications",
    "0003_integrity_function_execute_boundary",
)
_APPLICATIONS_ZERO: tuple[str, None] = ("applications", None)


@contextmanager
def rollback_migration_case() -> Iterator[None]:
    """Isolate a serial historical case using real PostgreSQL DDL rollback.

    The caller owns a committed historical baseline and restores current leaves
    after its last case. Only single-connection, transactional migrations belong
    here: commit visibility, concurrent connections, and non-atomic migrations
    must retain the ordinary full-graph fixtures. Deferred constraints are checked
    before discarding a successful case; failed cases also roll back completely.
    """

    if (
        connection.vendor != "postgresql"
        or not str(connection.settings_dict["NAME"]).startswith("test_")
        or not connection.features.can_rollback_ddl
        or not connection.get_autocommit()
    ):
        msg = "Historical case isolation requires an idle PostgreSQL test database."
        raise RuntimeError(msg)
    with transaction.atomic():
        try:
            yield
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        finally:
            transaction.set_rollback(True)


def migrate_test_targets(
    executor: MigrationExecutor,
    targets: list[tuple[str, str | None]],
) -> None:
    """Run Django's unchanged plan, rejecting non-atomic sandbox transitions."""

    plan = executor.migration_plan(targets)
    if connection.in_atomic_block and any(
        not migration.atomic for migration, _ in plan
    ):
        msg = "Non-atomic migrations require ordinary committed migration tests."
        raise RuntimeError(msg)
    executor.migrate(targets, plan=plan)


def current_migration_leaves() -> tuple[tuple[str, str], ...]:
    """Return every current leaf from the migration graph on disk."""

    executor = MigrationExecutor(connection)
    return tuple(executor.loader.graph.leaf_nodes())


def registration_migration_targets(
    executor: MigrationExecutor,
    target: tuple[str, str],
) -> tuple[tuple[str, str], ...]:
    """Select compatible Workforce and Applications leaves for Registration history."""

    targets_by_app = {
        migration_key[0]: migration_key
        for migration_key in executor.loader.graph.leaf_nodes()
    }
    targets_by_app["registration"] = target
    if _REGISTRATION_DEPARTMENT_FK_MIGRATION not in (
        executor.loader.graph.forwards_plan(target)
    ):
        targets_by_app["workforce"] = _WORKFORCE_BEFORE_DEPARTMENT_FK_SUCCESSOR
        if "applications" in targets_by_app:
            targets_by_app["applications"] = _APPLICATIONS_BEFORE_PROGRAMME_OWNERSHIP
    return tuple(sorted(targets_by_app.values()))


def identity_migration_targets(
    executor: MigrationExecutor,
    target: tuple[str, str],
) -> tuple[tuple[str, str], ...]:
    """Select Applications and Workforce leaves compatible with Identity history."""

    targets_by_app = {
        migration_key[0]: migration_key
        for migration_key in executor.loader.graph.leaf_nodes()
    }
    targets_by_app["identity"] = target
    if _IDENTITY_PROGRAMME_PROPOSAL_PERSON_GUARD not in (
        executor.loader.graph.forwards_plan(target)
    ):
        targets_by_app["applications"] = _APPLICATIONS_BEFORE_IDENTITY_PROGRAMME_GUARD
        targets_by_app["workforce"] = _WORKFORCE_PROGRAMME_CALL_FK_CONTRACT
    return tuple(sorted(targets_by_app.values()))


def workforce_migration_targets(
    executor: MigrationExecutor,
    *targets: tuple[str, str | None],
) -> tuple[tuple[str, str | None], ...]:
    """Remove later Applications schema from historical Workforce states."""

    workforce_target = next(
        (target for target in targets if target[0] == "workforce"),
        None,
    )
    if workforce_target is None or workforce_target[1] is None:
        return targets
    forward_plan = executor.loader.graph.forwards_plan(workforce_target)
    if _WORKFORCE_PROGRAMME_OWNERSHIP_FK_CONTRACT in forward_plan:
        return targets
    applications_target: tuple[str, str | None] = _APPLICATIONS_ZERO
    if _WORKFORCE_PROGRAMME_IMPORT_FK_CONTRACT in forward_plan:
        applications_target = _APPLICATIONS_BEFORE_PROGRAMME_OWNERSHIP
    elif _WORKFORCE_PROGRAMME_CALL_FK_CONTRACT in forward_plan:
        applications_target = _APPLICATIONS_BEFORE_PROGRAMME_IMPORT
    elif _WORKFORCE_CROSS_MODULE_DEPARTMENT_FK_CONTRACT in forward_plan:
        applications_target = _APPLICATIONS_BEFORE_PROGRAMME_CALLS
    compatible = [target for target in targets if target[0] != "applications"]
    compatible.append(applications_target)
    return tuple(sorted(compatible, key=lambda target: target[0]))


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
