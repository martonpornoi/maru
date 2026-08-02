"""Migration and database-boundary evidence for ADR 0041 activation."""

from __future__ import annotations

from datetime import date, timedelta
from importlib import import_module
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.models import (
    AuthorizationScopeWriteFence,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.workforce.models import Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
    ScopedResourceBindingFactory,
)
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_for_test,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

AUTHORIZATION_BEFORE_ACTIVATION = ("authorization", "0004_scope_v2_schema")
AUTHORIZATION_AFTER_ACTIVATION = ("authorization", "0005_scope_v2_activation")
WORKFORCE_SCOPE_V2_INTEGRITY = ("workforce", "0004_scope_v2_integrity")

activation_migration = import_module(
    "maru.authorization.migrations.0005_scope_v2_activation"
)


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


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


def _delete_historical_scope(scope: SimpleNamespace) -> None:
    """Remove old-graph edition workforce rows before Page 9 restoration."""

    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE workforce_position DISABLE TRIGGER workforce_position_guard"
        )
        try:
            scope.position_model.objects.filter(edition_id=scope.edition.id).delete()
        finally:
            cursor.execute(
                "ALTER TABLE workforce_position ENABLE TRIGGER workforce_position_guard"
            )
    type(scope.template).objects.filter(pk=scope.template.id).delete()
    type(scope.department).objects.filter(pk=scope.department.id).delete()


def _create_runtime_scope(suffix: str) -> SimpleNamespace:
    edition = EventEditionFactory()
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(organization=edition.organization)
    department = create_department_for_test(
        edition=edition,
        name=f"Operations {suffix}",
        expected_code=f"operations-{suffix}",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code=f"operations-lead-{suffix}",
        name=f"Operations lead {suffix}",
        description="Synthetic activation-test template.",
        default_capacity_codes=["volunteer"],
        role_bundle=role_bundle,
        created_by=creator,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code=f"operations-lead-{suffix}",
            title=f"Operations lead {suffix}",
            description="Synthetic activation-test position.",
            capacity_codes=["volunteer"],
            created_by=creator,
        )
    )
    binding = ScopedResourceBindingFactory(
        department=department,
        resource_id=position.id,
    )
    return SimpleNamespace(
        edition=edition,
        organization=edition.organization,
        department=department,
        position=position,
        binding=binding,
        role_bundle=role_bundle,
    )


def _raw_grant(
    *,
    scope: SimpleNamespace,
    capability_code: str = "events.view_basic",
    edition_id: UUID | None = None,
    department_id: UUID | None = None,
    resource_binding_id: UUID | None = None,
    principal: Any | None = None,
    granted_by: Any | None = None,
    effective_from: Any | None = None,
    expires_at: Any | None = None,
    delegated_from: CapabilityGrant | None = None,
) -> CapabilityGrant:
    return CapabilityGrant(
        organization=scope.organization,
        edition_id=edition_id,
        department_id=department_id,
        resource_binding_id=resource_binding_id,
        principal=principal or AccountFactory(),
        capability_code=capability_code,
        effective_from=effective_from or timezone.now(),
        expires_at=expires_at,
        granted_by=granted_by or AccountFactory(),
        delegated_from=delegated_from,
        reason="Synthetic database-boundary grant.",
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
    invalid_grant = grant_before.objects.create(
        organization_id=scope.organization.id,
        principal_id=scope.account.id,
        capability_code=capability_code,
        effective_from=timezone.now(),
        granted_by_id=scope.account.id,
        reason="Synthetic migration blocker.",
    )

    try:
        with pytest.raises(IntegrityError, match=expected_fragment):
            _migrate(
                AUTHORIZATION_AFTER_ACTIVATION,
                WORKFORCE_SCOPE_V2_INTEGRITY,
            )
    finally:
        grant_before.objects.filter(pk=invalid_grant.id).delete()
        _delete_historical_scope(scope)


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

    try:
        with pytest.raises(IntegrityError, match=r"ADR 0041 blockers:.*Y 2"):
            _migrate(
                AUTHORIZATION_AFTER_ACTIVATION,
                WORKFORCE_SCOPE_V2_INTEGRITY,
            )
    finally:
        grant_model.objects.filter(pk=parent.id).update(delegated_from_id=None)
        grant_model.objects.filter(pk=child.id).delete()
        grant_model.objects.filter(pk=parent.id).delete()
        _delete_historical_scope(scope)


def test_active_guards_reject_scope_forgery_mutation_and_catalog_bypass() -> None:
    first = _create_runtime_scope("first")
    second = _create_runtime_scope("second")

    with (
        pytest.raises(IntegrityError, match="department scope mismatch"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=first,
                    edition_id=first.edition.id,
                    department_id=second.department.id,
                )
            ]
        )

    with (
        pytest.raises(IntegrityError, match="resource scope mismatch"),
        transaction.atomic(),
    ):
        RoleAssignment.objects.bulk_create(
            [
                RoleAssignment(
                    organization=first.organization,
                    edition=first.edition,
                    department=first.department,
                    resource_binding=second.binding,
                    principal=AccountFactory(),
                    role_bundle=first.role_bundle,
                    effective_from=timezone.now(),
                    granted_by=AccountFactory(),
                    reason="Synthetic forged role scope.",
                )
            ]
        )

    valid_grant = CapabilityGrantFactory(
        organization=first.organization,
        edition=first.edition,
        department=first.department,
    )
    other_department = create_department_for_test(
        edition=first.edition,
        name="Registration first",
        expected_code="registration-first",
    )
    with (
        pytest.raises(IntegrityError, match="immutable"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.filter(pk=valid_grant.pk).update(
            department=other_department
        )

    valid_assignment = RoleAssignmentFactory(
        organization=first.organization,
        edition=first.edition,
        department=first.department,
        role_bundle=first.role_bundle,
    )
    with (
        pytest.raises(IntegrityError, match="immutable"),
        transaction.atomic(),
    ):
        RoleAssignment.objects.filter(pk=valid_assignment.pk).update(
            resource_binding=first.binding
        )

    with (
        pytest.raises(IntegrityError, match="cannot be persisted"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=first,
                    capability_code="workforce.view_self",
                    edition_id=first.edition.id,
                    department_id=first.department.id,
                    resource_binding_id=first.binding.id,
                )
            ]
        )

    with pytest.raises(IntegrityError, match="non-persistable"), transaction.atomic():
        RoleBundle.objects.bulk_create(
            [
                RoleBundle(
                    organization=first.organization,
                    code="forged-self-role",
                    name="Forged self role",
                    version=1,
                    capability_codes=["workforce.view_self"],
                )
            ]
        )

    edition_only_bundle = RoleBundleFactory(
        organization=first.organization,
        capability_codes=["events.change_profile"],
    )
    with (
        pytest.raises(IntegrityError, match="cannot be persisted at this scope"),
        transaction.atomic(),
    ):
        RoleAssignment.objects.bulk_create(
            [
                RoleAssignment(
                    organization=first.organization,
                    principal=AccountFactory(),
                    role_bundle=edition_only_bundle,
                    effective_from=timezone.now(),
                    granted_by=AccountFactory(),
                    reason="Synthetic too-broad role assignment.",
                )
            ]
        )


def test_revocation_requires_complete_evidence_and_is_one_way() -> None:
    scope = _create_runtime_scope("revocation")
    grant = CapabilityGrantFactory(organization=scope.organization)
    assignment = RoleAssignmentFactory(
        organization=scope.organization,
        role_bundle=scope.role_bundle,
    )
    revoker = AccountFactory()
    revoked_at = timezone.now()

    for authority, label in (
        (grant, "capability grant"),
        (assignment, "role assignment"),
    ):
        queryset = type(authority).objects.filter(pk=authority.pk)
        with (
            pytest.raises(IntegrityError, match=f"{label} revocation evidence"),
            transaction.atomic(),
        ):
            queryset.update(revoked_at=revoked_at)

        assert (
            queryset.update(
                revoked_at=revoked_at,
                revoked_by=revoker,
                revocation_reason="Synthetic complete revocation evidence.",
            )
            == 1
        )
        with (
            pytest.raises(IntegrityError, match=f"{label} revocation is immutable"),
            transaction.atomic(),
        ):
            queryset.update(revocation_reason="Rewritten revocation evidence.")
        with (
            pytest.raises(IntegrityError, match="must be revoked, not deleted"),
            transaction.atomic(),
        ):
            queryset.delete()


def test_delegation_guard_enforces_ancestry_scope_and_horizon() -> None:
    scope = _create_runtime_scope("delegation")
    sibling_department = create_department_for_test(
        edition=scope.edition,
        name="Registration delegation",
        expected_code="registration-delegation",
    )
    now = timezone.now()
    parent_principal = AccountFactory()
    parent = CapabilityGrantFactory(
        organization=scope.organization,
        edition=scope.edition,
        department=scope.department,
        principal=parent_principal,
        effective_from=now,
        expires_at=now + timedelta(days=10),
    )

    with (
        pytest.raises(IntegrityError, match="delegation containment"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=scope,
                    edition_id=scope.edition.id,
                    department_id=sibling_department.id,
                    granted_by=parent_principal,
                    effective_from=now,
                    expires_at=now + timedelta(days=5),
                    delegated_from=parent,
                )
            ]
        )

    with (
        pytest.raises(IntegrityError, match="delegation containment"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=scope,
                    edition_id=scope.edition.id,
                    department_id=scope.department.id,
                    granted_by=parent_principal,
                    effective_from=now - timedelta(seconds=1),
                    expires_at=now + timedelta(days=5),
                    delegated_from=parent,
                )
            ]
        )

    with (
        pytest.raises(IntegrityError, match="delegation containment"),
        transaction.atomic(),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                _raw_grant(
                    scope=scope,
                    edition_id=scope.edition.id,
                    department_id=scope.department.id,
                    granted_by=parent_principal,
                    effective_from=now,
                    expires_at=now + timedelta(days=11),
                    delegated_from=parent,
                )
            ]
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


@pytest.mark.parametrize("authority_kind", ["grant", "role"])
def test_downgrade_fence_refuses_any_scoped_authority(authority_kind: str) -> None:
    scope = _create_runtime_scope(f"fence-{authority_kind}")
    if authority_kind == "grant":
        authority = CapabilityGrantFactory(
            organization=scope.organization,
            edition=scope.edition,
            department=scope.department,
        )
    else:
        authority = RoleAssignmentFactory(
            organization=scope.organization,
            edition=scope.edition,
            department=scope.department,
            role_bundle=scope.role_bundle,
        )

    if authority_kind == "grant":
        disable_sql = (
            "ALTER TABLE authorization_capabilitygrant DISABLE TRIGGER "
            "authorization_capability_grant_no_delete"
        )
        delete_sql = "DELETE FROM authorization_capabilitygrant WHERE id = %s"
        enable_sql = (
            "ALTER TABLE authorization_capabilitygrant ENABLE TRIGGER "
            "authorization_capability_grant_no_delete"
        )
    else:
        disable_sql = (
            "ALTER TABLE authorization_roleassignment DISABLE TRIGGER "
            "authorization_role_assignment_no_delete"
        )
        delete_sql = "DELETE FROM authorization_roleassignment WHERE id = %s"
        enable_sql = (
            "ALTER TABLE authorization_roleassignment ENABLE TRIGGER "
            "authorization_role_assignment_no_delete"
        )
    with connection.cursor() as cursor:
        cursor.execute(disable_sql)
        try:
            cursor.execute(delete_sql, [authority.id])
        finally:
            cursor.execute(enable_sql)
    assert not type(authority).objects.filter(pk=authority.pk).exists()
    assert AuthorizationScopeWriteFence.objects.filter(singleton=True).exists()

    with pytest.raises(RuntimeError, match="Cannot remove Page 9 structure integrity"):
        _migrate(
            AUTHORIZATION_BEFORE_ACTIVATION,
            WORKFORCE_SCOPE_V2_INTEGRITY,
        )
