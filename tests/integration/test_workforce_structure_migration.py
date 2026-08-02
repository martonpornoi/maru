from datetime import date

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_TARGET = (
    "authorization",
    "0009_runtime_executable_function_contract",
)
WORKFORCE_BEFORE = ("workforce", "0005_runtime_executable_function_hardening")
WORKFORCE_AFTER = ("workforce", "0006_edition_structure_schema")


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _apps(executor: MigrationExecutor, workforce: tuple[str, str]) -> object:
    return executor.loader.project_state([AUTHORIZATION_TARGET, workforce]).apps


def test_department_order_is_preserved_and_downgrade_fence_runs_first() -> None:
    executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    legacy_apps = _apps(executor, WORKFORCE_BEFORE)
    Organization = legacy_apps.get_model("organizations", "Organization")
    ConventionSeries = legacy_apps.get_model("organizations", "ConventionSeries")
    EventEdition = legacy_apps.get_model("events", "EventEdition")
    Department = legacy_apps.get_model("workforce", "Department")

    organization = Organization.objects.create(
        slug="structure-migration-organizer",
        name="Structure Migration Organizer",
        contact_email="migration@example.test",
        country_code="AT",
    )
    series = ConventionSeries.objects.create(
        organization_id=organization.id,
        slug="structure-migration-series",
        name="Structure Migration Series",
        contact_email="migration@example.test",
    )
    edition = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="structure-migration-edition",
        name="Structure Migration Edition",
        time_zone="Europe/Vienna",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2035, 8, 1),
        ends_on=date(2035, 8, 4),
    )
    department = Department.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        code="operations",
        name="Operations",
        position=37,
    )

    migrated_executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)
    # A migration-first deployment must leave the previous binary's physical
    # ``position`` mapping usable until the new binary takes traffic.
    assert Department.objects.get(pk=department.pk).position == 37
    Department.objects.filter(pk=department.pk).update(position=38)
    migrated_apps = _apps(migrated_executor, WORKFORCE_AFTER)
    migrated_department_model = migrated_apps.get_model("workforce", "Department")
    migrated_department = migrated_department_model.objects.get(pk=department.pk)
    assert migrated_department.display_order == 38
    assert migrated_department.created_in_structure_version is None
    assert migrated_department.last_changed_in_structure_version is None
    migrated_department_model.objects.filter(pk=department.pk).update(display_order=37)

    reversed_executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    reversed_apps = _apps(reversed_executor, WORKFORCE_BEFORE)
    reversed_department_model = reversed_apps.get_model("workforce", "Department")
    assert reversed_department_model.objects.get(pk=department.pk).position == 37

    remigrated_executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)
    remigrated_apps = _apps(remigrated_executor, WORKFORCE_AFTER)
    remigrated_department_model = remigrated_apps.get_model("workforce", "Department")
    structure_control_model = remigrated_apps.get_model(
        "workforce", "EditionStructureControl"
    )

    remigrated_department_model.objects.filter(pk=department.pk).update(
        display_order=65_535
    )
    with pytest.raises(RuntimeError, match="Cannot reverse the edition-structure"):
        _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    remigrated_department_model.objects.filter(pk=department.pk).update(
        display_order=37
    )

    control = structure_control_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        origin="legacy_existing",
        aggregate_version=1,
    )

    try:
        with pytest.raises(RuntimeError, match="Cannot reverse the edition-structure"):
            _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    finally:
        structure_control_model.objects.filter(pk=control.pk).delete()
        _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)
