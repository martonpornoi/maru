from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor

from tests.support.migrations import workforce_migration_targets

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_TARGET = (
    "authorization",
    "0010_retired_department_authority_guards",
)
WORKFORCE_BEFORE = ("workforce", "0006_edition_structure_schema")
WORKFORCE_AFTER = ("workforce", "0007_structure_write_integrity")


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(workforce_migration_targets(executor, *targets))
    return executor


def _apps(executor: MigrationExecutor, workforce: tuple[str, str]) -> object:
    return executor.loader.project_state([AUTHORIZATION_TARGET, workforce]).apps


def _legacy_edition(apps: object, *, suffix: str) -> tuple[object, object]:
    organization_model = apps.get_model("organizations", "Organization")  # type: ignore[attr-defined]
    series_model = apps.get_model("organizations", "ConventionSeries")  # type: ignore[attr-defined]
    edition_model = apps.get_model("events", "EventEdition")  # type: ignore[attr-defined]
    organization = organization_model.objects.create(
        slug=f"page9-integrity-{suffix}",
        name=f"Page 9 Integrity {suffix}",
        lifecycle="active",
        default_language_codes=["en"],
        default_time_zone="Europe/Budapest",
    )
    series = series_model.objects.create(
        organization_id=organization.id,
        slug=f"page9-series-{suffix}",
        name=f"Page 9 Series {suffix}",
    )
    edition = edition_model.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug=f"page9-edition-{suffix}",
        name=f"Page 9 Edition {suffix}",
        lifecycle="draft",
        time_zone="Europe/Budapest",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2038, 8, 1),
        ends_on=date(2038, 8, 4),
    )
    return organization, edition


def test_empty_forward_and_reverse_install_and_remove_the_guard_graph() -> None:
    _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
              FROM pg_catalog.pg_trigger
             WHERE NOT tgisinternal
               AND tgname LIKE '%workforce_page9%'
            """
        )
        assert cursor.fetchone() == (28,)

    _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
              FROM pg_catalog.pg_trigger
             WHERE NOT tgisinternal
               AND tgname LIKE '%workforce_page9%'
            """
        )
        assert cursor.fetchone() == (0,)


def test_populated_legacy_scope_gets_one_control_without_receipt_or_inference() -> None:
    executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    legacy_apps = _apps(executor, WORKFORCE_BEFORE)
    department_model = legacy_apps.get_model("workforce", "Department")
    organization, edition = _legacy_edition(legacy_apps, suffix="backfill")
    parent = department_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        code="executive-board",
        name="Executive Board",
        description="A legacy operational label, not governance inference.",
        display_order=7,
    )
    child = department_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        parent_id=parent.id,
        code="helper-board",
        name="Helper Board",
        description="A legacy child edge that must remain exact.",
        display_order=8,
    )

    migrated = _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)
    current_apps = _apps(migrated, WORKFORCE_AFTER)
    control_model = current_apps.get_model("workforce", "EditionStructureControl")
    receipt_model = current_apps.get_model(
        "workforce", "EditionStructureCommandReceipt"
    )
    current_department_model = current_apps.get_model("workforce", "Department")
    control = control_model.objects.get(edition_id=edition.id)

    assert control.organization_id == organization.id
    assert control.origin == "legacy_existing"
    assert control.aggregate_version == 1
    assert not receipt_model.objects.filter(structure_id=control.id).exists()
    assert current_department_model.objects.get(pk=parent.id).parent_id is None
    preserved_child = current_department_model.objects.get(pk=child.id)
    assert preserved_child.parent_id == parent.id
    assert preserved_child.display_order == 8
    assert preserved_child.created_in_structure_version is None
    assert preserved_child.last_changed_in_structure_version is None

    with pytest.raises(RuntimeError, match="Cannot remove Page 9"):
        _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)


def test_empty_edition_remains_control_free_at_conceptual_version_zero() -> None:
    executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    legacy_apps = _apps(executor, WORKFORCE_BEFORE)
    _organization, edition = _legacy_edition(legacy_apps, suffix="empty")

    migrated = _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)
    current_apps = _apps(migrated, WORKFORCE_AFTER)
    control_model = current_apps.get_model("workforce", "EditionStructureControl")

    assert not control_model.objects.filter(edition_id=edition.id).exists()


def test_preflight_rejects_unapproved_gap_evidence_then_recovers() -> None:
    executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    legacy_apps = _apps(executor, WORKFORCE_BEFORE)
    control_model = legacy_apps.get_model("workforce", "EditionStructureControl")
    organization, edition = _legacy_edition(legacy_apps, suffix="gap-evidence")
    control = control_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        origin="manual",
        aggregate_version=1,
    )

    with pytest.raises(IntegrityError, match="Page 9 structure preflight"):
        _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)

    control_model.objects.filter(pk=control.pk).delete()
    _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)


def test_preflight_rejects_unknown_cascading_department_reference() -> None:
    _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE public.page9_unknown_department_reference (
                id uuid PRIMARY KEY,
                department_id uuid NOT NULL REFERENCES
                    public.workforce_department(id) ON DELETE CASCADE
            )
            """
        )
    try:
        with pytest.raises(IntegrityError, match="Page 9 structure preflight"):
            _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP TABLE IF EXISTS public.page9_unknown_department_reference"
            )
    _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)


def test_preflight_rejects_department_count_and_depth_bounds() -> None:
    executor = _migrate(AUTHORIZATION_TARGET, WORKFORCE_BEFORE)
    legacy_apps = _apps(executor, WORKFORCE_BEFORE)
    department_model = legacy_apps.get_model("workforce", "Department")
    organization, edition = _legacy_edition(legacy_apps, suffix="bounds")
    department_model.objects.bulk_create(
        [
            department_model(
                organization_id=organization.id,
                edition_id=edition.id,
                code=f"department-{number}",
                name=f"Department {number}",
                display_order=number,
            )
            for number in range(257)
        ]
    )

    with pytest.raises(IntegrityError, match="Page 9 structure preflight"):
        _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)

    department_model.objects.filter(edition_id=edition.id).delete()
    parent = None
    for number in range(33):
        parent = department_model.objects.create(
            organization_id=organization.id,
            edition_id=edition.id,
            parent_id=parent.id if parent is not None else None,
            code=f"depth-{number}",
            name=f"Depth {number}",
            display_order=number,
        )
    with pytest.raises(IntegrityError, match="Page 9 structure preflight"):
        _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)

    department_model.objects.filter(edition_id=edition.id).update(parent_id=None)
    department_model.objects.filter(edition_id=edition.id).delete()
    _migrate(AUTHORIZATION_TARGET, WORKFORCE_AFTER)
