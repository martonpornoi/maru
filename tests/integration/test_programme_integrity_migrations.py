"""PostgreSQL reversal and fix-forward coverage for Programme schema."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from tests.factories import EventEditionFactory

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

PROGRAMME_ZERO: tuple[str, str | None] = ("programme", None)
PROGRAMME_SCHEMA: tuple[str, str | None] = ("programme", "0001_initial")
PROGRAMME_CURRENT: tuple[str, str | None] = (
    "programme",
    "0003_downgrade_fence",
)
PROGRAMME_RELATIONS = (
    "programme_programmeeditioncontrol",
    "programme_programmeitem",
    "programme_programmeitemsourcebinding",
    "programme_programmeworkingrevision",
    "programme_programmedeliveryrevision",
    "programme_programmedepartmentdiscussionentry",
    "programme_programmereadinessrequirement",
    "programme_programmereadinessrequirementrevision",
    "programme_programmereadinessevidence",
    "programme_programmepublicrendition",
    "programme_programmecommandreceipt",
)


def _migrate(target: tuple[str, str | None]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate([target])
    return executor


def _function_is_installed() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_regprocedure('public.maru_guard_programme_item()') IS NOT NULL"
        )
        row = cursor.fetchone()
    assert row is not None
    return bool(row[0])


def _programme_relations_are_installed() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT bool_and(to_regclass('public.' || relation_name) IS NOT NULL)
              FROM unnest(%s::text[]) AS relation_name
            """,
            [list(PROGRAMME_RELATIONS)],
        )
        row = cursor.fetchone()
    assert row is not None
    return bool(row[0])


def test_empty_programme_integrity_reverses_and_reapplies_exactly() -> None:
    """Allow an unused additive schema to reverse without residue."""
    _migrate(PROGRAMME_ZERO)
    assert not _function_is_installed()
    assert not _programme_relations_are_installed()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM django_migrations WHERE app = 'programme'",
        )
        assert cursor.fetchone() is None

    _migrate(PROGRAMME_CURRENT)
    assert _function_is_installed()
    assert _programme_relations_are_installed()


def test_populated_programme_downgrade_refuses_before_removing_guards() -> None:
    """Preserve durable state, recorder, and integrity functions on refusal."""
    edition = EventEditionFactory()
    executor = _migrate(PROGRAMME_SCHEMA)
    historical_apps = executor.loader.project_state([PROGRAMME_SCHEMA]).apps
    control = historical_apps.get_model(
        "programme",
        "ProgrammeEditionControl",
    ).objects.create(
        organization_id=edition.organization_id,
        edition_id=edition.id,
        aggregate_version=1,
    )
    _migrate(PROGRAMME_CURRENT)

    with pytest.raises(
        RuntimeError,
        match="Cannot remove Programme database integrity",
    ):
        _migrate(PROGRAMME_SCHEMA)

    executor = MigrationExecutor(connection)
    assert PROGRAMME_CURRENT in executor.loader.applied_migrations
    assert _function_is_installed()
    current_apps = executor.loader.project_state([PROGRAMME_CURRENT]).apps
    current_control = current_apps.get_model(
        "programme",
        "ProgrammeEditionControl",
    )
    assert current_control.objects.filter(id=control.id).exists()
