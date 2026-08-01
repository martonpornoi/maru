from datetime import date

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from tests.support.migrations import (
    current_migration_leaves,
    restore_current_migration_graph,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

EVENTS_BEFORE_AGGREGATE = ("events", "0005_editionclosuremanifest_editionreadinessgate")
EVENTS_BEFORE_DOWNGRADE_FENCE = ("events", "0008_creation_receipt_digest_guard")
EVENTS_AFTER_GUARDS = ("events", "0009_edition_workspace_downgrade_fence")
ORGANIZATIONS_BEFORE_DOWNGRADE_FENCE = (
    "organizations",
    "0006_convention_series_profile_integrity_guard",
)
ORGANIZATIONS_AFTER_GUARD = (
    "organizations",
    "0007_convention_series_downgrade_fence",
)


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def test_aggregate_backfill_and_overlong_legacy_span_preflight() -> None:
    executor = _migrate(EVENTS_BEFORE_AGGREGATE, ORGANIZATIONS_AFTER_GUARD)
    legacy_apps = executor.loader.project_state(
        [EVENTS_BEFORE_AGGREGATE, ORGANIZATIONS_AFTER_GUARD]
    ).apps
    Organization = legacy_apps.get_model("organizations", "Organization")
    ConventionSeries = legacy_apps.get_model("organizations", "ConventionSeries")
    EventEdition = legacy_apps.get_model("events", "EventEdition")

    organization = Organization.objects.create(
        slug="migration-organizer",
        name="Migration Organizer",
    )
    series = ConventionSeries.objects.create(
        organization_id=organization.id,
        slug="migration-series",
        name="Migration Series",
    )
    draft = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="legacy-draft",
        name="Legacy Draft",
        time_zone="UTC",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2031, 8, 1),
        ends_on=date(2031, 8, 4),
    )
    transitioned = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="legacy-transitioned",
        name="Legacy Transitioned",
        time_zone="UTC",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2032, 8, 1),
        ends_on=date(2032, 8, 4),
    )
    EventEdition.objects.filter(pk=transitioned.pk).update(
        lifecycle="preparing",
        lifecycle_version=1,
    )
    EventEdition.objects.filter(pk=transitioned.pk).update(
        lifecycle="ready",
        lifecycle_version=2,
    )
    EventEdition.objects.filter(pk=transitioned.pk).update(
        lifecycle="live",
        lifecycle_version=3,
    )
    EventEdition.objects.filter(pk=transitioned.pk).update(
        lifecycle="closing",
        lifecycle_version=4,
    )
    EventEdition.objects.filter(pk=transitioned.pk).update(
        lifecycle="archived",
        lifecycle_version=5,
    )
    overlong = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="legacy-overlong",
        name="Legacy Overlong",
        time_zone="UTC",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2033, 1, 1),
        ends_on=date(2033, 2, 2),
    )
    unsupported_codes = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="legacy-unsupported-codes",
        name="Legacy Unsupported Codes",
        time_zone="UTC",
        language_codes=["en"] * 17,
        currency_codes=["ZZZ"],
        starts_on=date(2034, 1, 1),
        ends_on=date(2034, 1, 4),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match=r"1 existing edition record.*exceed it",
        ):
            _migrate(EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD)

        EventEdition.objects.filter(pk=overlong.pk).update(ends_on=date(2033, 2, 1))
        with pytest.raises(
            RuntimeError,
            match=r"1 edition record.*exceed 16 languages.*1 record.*unsupported",
        ):
            _migrate(EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD)

        EventEdition.objects.filter(pk=unsupported_codes.pk).update(
            language_codes=["en"],
            currency_codes=["EUR"],
        )
        migrated_executor = _migrate(
            EVENTS_AFTER_GUARDS,
            ORGANIZATIONS_AFTER_GUARD,
        )
        migrated_apps = migrated_executor.loader.project_state(
            [EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD]
        ).apps
        migrated_edition = migrated_apps.get_model("events", "EventEdition")

        assert migrated_edition.objects.get(pk=draft.pk).aggregate_version == 1
        assert migrated_edition.objects.get(pk=transitioned.pk).aggregate_version == 5
        assert migrated_edition.objects.get(pk=overlong.pk).aggregate_version == 1
        assert (
            migrated_edition.objects.get(pk=unsupported_codes.pk).aggregate_version == 1
        )
    finally:
        _migrate(EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD)


def test_downgrade_fences_refuse_to_drop_nonempty_workspace_history() -> None:
    executor = _migrate(EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD)
    current_apps = executor.loader.project_state(
        [EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD]
    ).apps
    Organization = current_apps.get_model("organizations", "Organization")
    ConventionSeries = current_apps.get_model("organizations", "ConventionSeries")
    EventEdition = current_apps.get_model("events", "EventEdition")

    organization = Organization.objects.create(
        slug="downgrade-fence-organizer",
        name="Downgrade Fence Organizer",
    )
    series = ConventionSeries.objects.create(
        organization_id=organization.id,
        slug="downgrade-fence-series",
        name="Downgrade Fence Series",
    )
    edition = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="downgrade-fence-edition",
        name="Downgrade Fence Edition",
        time_zone="UTC",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2035, 8, 1),
        ends_on=date(2035, 8, 4),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="Cannot reverse the edition-workspace migrations",
        ):
            _migrate(EVENTS_BEFORE_DOWNGRADE_FENCE, ORGANIZATIONS_AFTER_GUARD)

        EventEdition.objects.filter(pk=edition.pk).delete()
        _migrate(EVENTS_BEFORE_DOWNGRADE_FENCE, ORGANIZATIONS_AFTER_GUARD)

        with pytest.raises(
            RuntimeError,
            match="Cannot reverse the convention-series profile-version migrations",
        ):
            _migrate(
                EVENTS_BEFORE_DOWNGRADE_FENCE,
                ORGANIZATIONS_BEFORE_DOWNGRADE_FENCE,
            )
    finally:
        _migrate(EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD)


def test_historical_workspace_target_can_restore_the_complete_current_graph() -> None:
    _migrate(EVENTS_AFTER_GUARDS, ORGANIZATIONS_AFTER_GUARD)

    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('organizations_organizationrepresentation')")
        assert cursor.fetchone() == (None,)

    restore_current_migration_graph()

    executor = MigrationExecutor(connection)
    assert set(current_migration_leaves()).issubset(executor.loader.applied_migrations)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT tgname
              FROM pg_trigger
             WHERE NOT tgisinternal
               AND tgname IN (
                   'organizations_idn011_membership_subject_guard',
                   'organizations_idn011_appointment_subject_guard',
                   'identity_idn011_organizations_subject_guard'
               )
             ORDER BY tgname
            """
        )
        assert [row[0] for row in cursor.fetchall()] == [
            "identity_idn011_organizations_subject_guard",
            "organizations_idn011_appointment_subject_guard",
            "organizations_idn011_membership_subject_guard",
        ]
