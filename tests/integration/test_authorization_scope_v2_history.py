"""Historical scope activation with independent rollback-isolated cases."""

from __future__ import annotations

from datetime import date, timedelta
from importlib import import_module
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from tests.support.migrations import (
    flush_then_restore_current_migration_graph,
    migrate_test_targets,
    rollback_migration_case,
    workforce_migration_targets,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django.fixtures import DjangoDbBlocker

pytestmark = pytest.mark.integration

AUTHORIZATION_BEFORE_ACTIVATION = ("authorization", "0004_scope_v2_schema")
AUTHORIZATION_AFTER_ACTIVATION = ("authorization", "0005_scope_v2_activation")
WORKFORCE_SCOPE_V2_INTEGRITY = ("workforce", "0004_scope_v2_integrity")

activation_migration = import_module(
    "maru.authorization.migrations.0005_scope_v2_activation"
)


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    migrate_test_targets(
        executor, list(workforce_migration_targets(executor, *targets))
    )
    return executor


@pytest.fixture(scope="module")
def historical_baseline(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Traverse full history once; each case still runs the actual activation."""

    del django_db_setup
    with django_db_blocker.unblock():
        try:
            _migrate(AUTHORIZATION_BEFORE_ACTIVATION, WORKFORCE_SCOPE_V2_INTEGRITY)
            yield
        finally:
            flush_then_restore_current_migration_graph()


@pytest.fixture(autouse=True)
def isolated_historical_case(
    historical_baseline: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Roll back every case before another case uses the historical baseline."""

    del historical_baseline
    with django_db_blocker.unblock(), rollback_migration_case():
        yield


def _project_apps(
    executor: MigrationExecutor,
    authorization_target: tuple[str, str],
) -> Any:
    return executor.loader.project_state(
        [authorization_target, WORKFORCE_SCOPE_V2_INTEGRITY]
    ).apps


def _create_historical_scope(apps: Any, suffix: str) -> SimpleNamespace:
    Account = apps.get_model("identity", "Account")
    Organization = apps.get_model("organizations", "Organization")
    ConventionSeries = apps.get_model("organizations", "ConventionSeries")
    EventEdition = apps.get_model("events", "EventEdition")
    role_bundle_model = apps.get_model("authorization", "RoleBundle")
    department_model = apps.get_model("workforce", "Department")
    position_template_model = apps.get_model("workforce", "PositionTemplate")
    position_model = apps.get_model("workforce", "Position")

    account = Account.objects.create(
        email=f"scope-v2-{suffix}@example.invalid",
        login_handle=f"scope-v2-{suffix}",
        display_name=f"Scope V2 {suffix}",
        password="!",
    )
    organization = Organization.objects.create(
        slug=f"scope-v2-{suffix}",
        name=f"Scope V2 {suffix}",
    )
    series = ConventionSeries.objects.create(
        organization_id=organization.id,
        slug=f"scope-v2-series-{suffix}",
        name=f"Scope V2 Series {suffix}",
    )
    edition = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug=f"scope-v2-edition-{suffix}",
        name=f"Scope V2 Edition {suffix}",
        time_zone="UTC",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2033, 8, 1),
        ends_on=date(2033, 8, 4),
    )
    role_bundle = role_bundle_model.objects.create(
        organization_id=organization.id,
        code=f"scope-v2-reader-{suffix}",
        name=f"Scope V2 Reader {suffix}",
        version=1,
        capability_codes=["events.view_basic"],
    )
    department = department_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        code=f"operations-{suffix}",
        name=f"Operations {suffix}",
    )
    template = position_template_model.objects.create(
        organization_id=organization.id,
        code=f"operations-lead-{suffix}",
        name=f"Operations lead {suffix}",
        description="Synthetic scope-v2 position template.",
        default_capacity_codes=["volunteer"],
        role_bundle_id=role_bundle.id,
        created_by_id=account.id,
    )
    position = position_model.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        template_id=template.id,
        department_id=department.id,
        role_bundle_id=role_bundle.id,
        code=f"operations-lead-{suffix}",
        title=f"Operations lead {suffix}",
        description="Synthetic scope-v2 position.",
        capacity_codes=["volunteer"],
        created_by_id=account.id,
    )
    return SimpleNamespace(
        account=account,
        organization=organization,
        series=series,
        edition=edition,
        role_bundle=role_bundle,
        department=department,
        template=template,
        position=position,
        position_model=position_model,
    )


def _create_second_historical_position(
    scope: SimpleNamespace,
    suffix: str,
) -> Any:
    return scope.position_model.objects.create(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        template_id=scope.template.id,
        department_id=scope.department.id,
        role_bundle_id=scope.role_bundle.id,
        code=f"deputy-{suffix}",
        title=f"Deputy {suffix}",
        description="Synthetic second scope-v2 position.",
        capacity_codes=["volunteer"],
        created_by_id=scope.account.id,
    )


def test_fresh_activation_installs_helpers_and_creates_no_authority() -> None:
    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    before_apps = _project_apps(executor, AUTHORIZATION_BEFORE_ACTIVATION)
    assert not before_apps.get_model(
        "authorization", "ScopedResourceBinding"
    ).objects.exists()

    executor = _migrate(
        AUTHORIZATION_AFTER_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    after_apps = _project_apps(executor, AUTHORIZATION_AFTER_ACTIVATION)
    assert not after_apps.get_model(
        "authorization", "ScopedResourceBinding"
    ).objects.exists()
    assert not after_apps.get_model("authorization", "CapabilityGrant").objects.exists()
    assert not after_apps.get_model("authorization", "RoleAssignment").objects.exists()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM pg_proc "
            "WHERE proname IN ("
            "'maru_authorization_capability_min_scope', "
            "'maru_authorization_scope_rank', "
            "'maru_authorization_scope_contains')"
        )
        assert cursor.fetchone()[0] == 3
        cursor.execute(
            "SELECT COUNT(*) FROM pg_trigger "
            "WHERE tgname IN ("
            "'authorization_scoped_resource_binding_guard', "
            "'authorization_role_bundle_catalog_guard') "
            "AND NOT tgisinternal"
        )
        assert cursor.fetchone()[0] == 2


def test_populated_activation_backfills_deterministically_and_is_idempotent() -> None:
    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    before_apps = _project_apps(executor, AUTHORIZATION_BEFORE_ACTIVATION)
    scope = _create_historical_scope(before_apps, "populated")
    second_position = _create_second_historical_position(scope, "populated")
    binding_before = before_apps.get_model("authorization", "ScopedResourceBinding")
    capability_grant_before = before_apps.get_model("authorization", "CapabilityGrant")
    role_assignment_before = before_apps.get_model("authorization", "RoleAssignment")
    preserved_binding_id = uuid4()
    binding_before.objects.create(
        id=preserved_binding_id,
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
        resource_kind="workforce.position",
        resource_id=second_position.id,
    )
    broad_grant = capability_grant_before.objects.create(
        organization_id=scope.organization.id,
        principal_id=scope.account.id,
        capability_code="organizations.view_basic",
        effective_from=timezone.now(),
        granted_by_id=scope.account.id,
        reason="Existing organization authority.",
    )
    broad_assignment = role_assignment_before.objects.create(
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        principal_id=scope.account.id,
        role_bundle_id=scope.role_bundle.id,
        effective_from=timezone.now(),
        granted_by_id=scope.account.id,
        reason="Existing edition authority.",
    )

    executor = _migrate(
        AUTHORIZATION_AFTER_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    after_apps = _project_apps(executor, AUTHORIZATION_AFTER_ACTIVATION)
    binding_after = after_apps.get_model("authorization", "ScopedResourceBinding")
    expected_id = activation_migration.workforce_position_binding_id(scope.position.id)
    assert binding_after.objects.get(resource_id=scope.position.id).id == expected_id
    assert (
        binding_after.objects.get(resource_id=second_position.id).id
        == preserved_binding_id
    )
    assert binding_after.objects.count() == 2

    activation_migration.backfill_workforce_position_bindings(
        after_apps,
        SimpleNamespace(connection=connection),
    )
    assert binding_after.objects.count() == 2
    assert (
        after_apps.get_model("authorization", "CapabilityGrant")
        .objects.get(pk=broad_grant.id)
        .department_id
        is None
    )
    migrated_assignment = after_apps.get_model(
        "authorization", "RoleAssignment"
    ).objects.get(pk=broad_assignment.id)
    assert migrated_assignment.edition_id == scope.edition.id
    assert migrated_assignment.department_id is None
    assert migrated_assignment.resource_binding_id is None


@pytest.mark.parametrize(
    ("capability_code", "expected_fragment"),
    [
        ("workforce.view_self", "ADR 0041 blockers"),
        ("events.change_profile", "ADR 0041 blockers"),
    ],
)
def test_populated_preflight_rejects_nonpersistable_or_too_broad_grant(
    capability_code: str,
    expected_fragment: str,
) -> None:
    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    before_apps = _project_apps(executor, AUTHORIZATION_BEFORE_ACTIVATION)
    scope = _create_historical_scope(before_apps, capability_code.replace(".", "-"))
    grant_before = before_apps.get_model("authorization", "CapabilityGrant")
    grant_before.objects.create(
        organization_id=scope.organization.id,
        principal_id=scope.account.id,
        capability_code=capability_code,
        effective_from=timezone.now(),
        granted_by_id=scope.account.id,
        reason="Synthetic migration blocker.",
    )

    with pytest.raises(IntegrityError, match=expected_fragment):
        _migrate(
            AUTHORIZATION_AFTER_ACTIVATION,
            WORKFORCE_SCOPE_V2_INTEGRITY,
        )


def test_populated_preflight_rejects_a_delegation_cycle() -> None:
    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    before_apps = _project_apps(executor, AUTHORIZATION_BEFORE_ACTIVATION)
    scope = _create_historical_scope(before_apps, "cycle")
    account_model = before_apps.get_model("identity", "Account")
    grant_model = before_apps.get_model("authorization", "CapabilityGrant")
    second_account = account_model.objects.create(
        email="scope-v2-cycle-second@example.invalid",
        login_handle="scope-v2-cycle-second",
        display_name="Scope V2 Cycle Second",
        password="!",
    )
    now = timezone.now()
    parent = grant_model.objects.create(
        organization_id=scope.organization.id,
        principal_id=scope.account.id,
        capability_code="events.view_basic",
        effective_from=now,
        expires_at=now + timedelta(days=5),
        granted_by_id=second_account.id,
        reason="Synthetic cycle parent.",
    )
    child = grant_model.objects.create(
        organization_id=scope.organization.id,
        principal_id=second_account.id,
        capability_code="events.view_basic",
        effective_from=now,
        expires_at=now + timedelta(days=5),
        granted_by_id=scope.account.id,
        delegated_from_id=parent.id,
        reason="Synthetic cycle child.",
    )
    grant_model.objects.filter(pk=parent.id).update(delegated_from_id=child.id)

    with pytest.raises(IntegrityError, match=r"ADR 0041 blockers:.*Y 2"):
        _migrate(
            AUTHORIZATION_AFTER_ACTIVATION,
            WORKFORCE_SCOPE_V2_INTEGRITY,
        )


def test_reverse_removes_only_reproducible_bindings() -> None:
    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    before_apps = _project_apps(executor, AUTHORIZATION_BEFORE_ACTIVATION)
    scope = _create_historical_scope(before_apps, "reverse")
    preserved_position = _create_second_historical_position(scope, "reverse")
    binding_before = before_apps.get_model("authorization", "ScopedResourceBinding")
    preserved_binding_id = uuid4()
    binding_before.objects.create(
        id=preserved_binding_id,
        organization_id=scope.organization.id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
        resource_kind="workforce.position",
        resource_id=preserved_position.id,
    )

    executor = _migrate(
        AUTHORIZATION_AFTER_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    after_apps = _project_apps(executor, AUTHORIZATION_AFTER_ACTIVATION)
    binding_after = after_apps.get_model("authorization", "ScopedResourceBinding")
    deterministic_id = activation_migration.workforce_position_binding_id(
        scope.position.id
    )
    assert binding_after.objects.filter(pk=deterministic_id).exists()

    executor = _migrate(
        AUTHORIZATION_BEFORE_ACTIVATION,
        WORKFORCE_SCOPE_V2_INTEGRITY,
    )
    reversed_apps = _project_apps(executor, AUTHORIZATION_BEFORE_ACTIVATION)
    binding_reversed = reversed_apps.get_model("authorization", "ScopedResourceBinding")
    assert not binding_reversed.objects.filter(pk=deterministic_id).exists()
    assert binding_reversed.objects.filter(pk=preserved_binding_id).exists()
