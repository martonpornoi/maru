"""Focused schema evidence for ADR 0041's additive scope-v2 phase."""

from datetime import date
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.models import (
    CapabilityGrant,
    RoleAssignment,
    ScopedResourceBinding,
)
from maru.workforce.models import Department, Position, PositionTemplate
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

pytestmark = [pytest.mark.django_db, pytest.mark.integration]

AUTHORIZATION_BEFORE_SCOPE_V2 = (
    "authorization",
    "0003_capabilitygrant_approved_by_and_more",
)
AUTHORIZATION_SCOPE_V2_SCHEMA = ("authorization", "0004_scope_v2_schema")
SCHEMA_DEPENDENCIES = (
    ("events", "0009_edition_workspace_downgrade_fence"),
    ("organizations", "0012_idn011_convention_subject_guards"),
    ("workforce", "0003_idn011_convention_subject_guards"),
)


def _workforce_position() -> tuple[Department, Position]:
    edition = EventEditionFactory()
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(organization=edition.organization)
    department = create_department_for_test(
        edition=edition,
        name="Operations",
        expected_code="operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code="operations-lead",
        name="Operations lead",
        description="Synthetic scope-v2 position template.",
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
            code="operations-lead",
            title="Operations lead",
            description="Synthetic scope-v2 position.",
            capacity_codes=["volunteer"],
            created_by=creator,
        )
    )
    return department, position


def _binding_for_position(
    department: Department,
    position: Position,
) -> ScopedResourceBinding:
    return ScopedResourceBindingFactory(
        department=department,
        resource_id=position.id,
    )


def test_existing_and_narrower_scope_shapes_are_model_valid() -> None:
    department, position = _workforce_position()
    binding = _binding_for_position(department, position)
    organization = department.organization
    edition = department.edition

    organization_grant = CapabilityGrantFactory(
        organization=organization,
        capability_code="organizations.view_basic",
    )
    edition_grant = CapabilityGrantFactory(
        organization=organization,
        edition=edition,
    )
    department_grant = CapabilityGrantFactory(
        organization=organization,
        edition=edition,
        department=department,
    )
    resource_grant = CapabilityGrantFactory(
        organization=organization,
        edition=edition,
        department=department,
        resource_binding=binding,
    )

    assert organization_grant.edition_id is None
    assert edition_grant.department_id is None
    assert department_grant.resource_binding_id is None
    assert resource_grant.resource_binding_id == binding.id

    bundle = RoleBundleFactory(organization=organization)
    assignment = RoleAssignmentFactory(
        organization=organization,
        edition=edition,
        department=department,
        resource_binding=binding,
        role_bundle=bundle,
    )
    assert assignment.resource_binding_id == binding.id


def test_model_rejects_partial_foreign_and_relationship_only_scope() -> None:
    department, position = _workforce_position()
    binding = _binding_for_position(department, position)
    organization = department.organization
    edition = department.edition
    principal = AccountFactory()
    grantor = AccountFactory()

    with pytest.raises(ValidationError, match="requires an edition"):
        CapabilityGrant(
            organization=organization,
            department=department,
            principal=principal,
            capability_code="organizations.view_basic",
            effective_from=timezone.now(),
            granted_by=grantor,
            reason="Invalid partial scope.",
        ).full_clean()

    with pytest.raises(ValidationError, match="requires a department"):
        CapabilityGrant(
            organization=organization,
            edition=edition,
            resource_binding=binding,
            principal=principal,
            capability_code="events.view_basic",
            effective_from=timezone.now(),
            granted_by=grantor,
            reason="Invalid partial scope.",
        ).full_clean()

    other_department = create_department_for_test(
        edition=edition,
        name="Registration",
        expected_code="registration",
    )
    with pytest.raises(ValidationError, match="exact department scope"):
        CapabilityGrant(
            organization=organization,
            edition=edition,
            department=other_department,
            resource_binding=binding,
            principal=principal,
            capability_code="events.view_basic",
            effective_from=timezone.now(),
            granted_by=grantor,
            reason="Mismatched exact resource.",
        ).full_clean()

    with pytest.raises(ValidationError, match="cannot be stored"):
        CapabilityGrant(
            organization=organization,
            edition=edition,
            department=department,
            resource_binding=binding,
            principal=principal,
            capability_code="workforce.view_self",
            effective_from=timezone.now(),
            granted_by=grantor,
            reason="Relationship authority cannot be persisted.",
        ).full_clean()

    foreign_edition = EventEditionFactory()
    with pytest.raises(ValidationError, match="resource edition"):
        ScopedResourceBinding(
            organization=organization,
            edition=foreign_edition,
            department=department,
            resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
            resource_id=position.id,
        ).full_clean()

    with pytest.raises(ValidationError, match="Relationship-derived"):
        RoleBundleFactory(
            organization=organization,
            capability_codes=["workforce.view_self"],
        )


def test_binding_chain_and_identity_are_immutable_and_unique() -> None:
    department, position = _workforce_position()
    binding = _binding_for_position(department, position)

    binding.resource_id = uuid4()
    with pytest.raises(ValidationError, match="immutable"):
        binding.save()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        binding.delete()

    with pytest.raises(IntegrityError, match="immutable"), transaction.atomic():
        ScopedResourceBinding.objects.filter(pk=binding.pk).update(resource_id=uuid4())

    with pytest.raises(IntegrityError), transaction.atomic():
        ScopedResourceBinding.objects.bulk_create(
            [
                ScopedResourceBinding(
                    organization=department.organization,
                    edition=department.edition,
                    department=department,
                    resource_kind=(
                        ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION
                    ),
                    resource_id=position.id,
                )
            ]
        )

    with pytest.raises(IntegrityError), transaction.atomic():
        ScopedResourceBinding.objects.bulk_create(
            [
                ScopedResourceBinding(
                    organization=department.organization,
                    edition=department.edition,
                    department=department,
                    resource_kind="unregistered.resource",
                    resource_id=uuid4(),
                )
            ]
        )


def test_database_rejects_partial_persistent_scope_when_model_is_bypassed() -> None:
    department, position = _workforce_position()
    binding = _binding_for_position(department, position)
    grant = CapabilityGrantFactory(
        organization=department.organization,
        capability_code="organizations.view_basic",
    )
    assignment = RoleAssignmentFactory(
        organization=department.organization,
        role_bundle=RoleBundleFactory(organization=department.organization),
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        CapabilityGrant.objects.filter(pk=grant.pk).update(resource_binding=binding)

    with pytest.raises(IntegrityError), transaction.atomic():
        RoleAssignment.objects.filter(pk=assignment.pk).update(department=department)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("restores_current_migration_graph")
def test_scope_v2_migration_preserves_existing_authority_without_inference() -> None:
    executor = MigrationExecutor(connection)
    executor.migrate([AUTHORIZATION_BEFORE_SCOPE_V2, *SCHEMA_DEPENDENCIES])
    legacy_apps = executor.loader.project_state(
        [AUTHORIZATION_BEFORE_SCOPE_V2, *SCHEMA_DEPENDENCIES]
    ).apps
    Account = legacy_apps.get_model("identity", "Account")
    Organization = legacy_apps.get_model("organizations", "Organization")
    ConventionSeries = legacy_apps.get_model("organizations", "ConventionSeries")
    EventEdition = legacy_apps.get_model("events", "EventEdition")
    legacy_capability_grant = legacy_apps.get_model("authorization", "CapabilityGrant")
    legacy_role_bundle = legacy_apps.get_model("authorization", "RoleBundle")
    legacy_role_assignment = legacy_apps.get_model("authorization", "RoleAssignment")

    account = Account.objects.create(
        email="scope-v2-migration@example.invalid",
        login_handle="scope-v2-migration",
        display_name="Scope migration",
        password="!",
    )
    organization = Organization.objects.create(
        slug="scope-v2-migration",
        name="Scope V2 Migration",
    )
    series = ConventionSeries.objects.create(
        organization_id=organization.id,
        slug="scope-v2-series",
        name="Scope V2 Series",
    )
    edition = EventEdition.objects.create(
        organization_id=organization.id,
        series_id=series.id,
        slug="scope-v2-edition",
        name="Scope V2 Edition",
        time_zone="UTC",
        language_codes=["en"],
        currency_codes=["EUR"],
        starts_on=date(2032, 8, 1),
        ends_on=date(2032, 8, 4),
    )
    grant = legacy_capability_grant.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        principal_id=account.id,
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        granted_by_id=account.id,
        reason="Existing edition-wide authority.",
    )
    organization_grant = legacy_capability_grant.objects.create(
        organization_id=organization.id,
        principal_id=account.id,
        capability_code="organizations.view_basic",
        effective_from=timezone.now(),
        granted_by_id=account.id,
        reason="Existing organization-wide authority.",
    )
    bundle = legacy_role_bundle.objects.create(
        organization_id=organization.id,
        code="migration-reader",
        name="Migration reader",
        version=1,
        capability_codes=["events.view_basic"],
    )
    assignment = legacy_role_assignment.objects.create(
        organization_id=organization.id,
        edition_id=edition.id,
        principal_id=account.id,
        role_bundle_id=bundle.id,
        effective_from=timezone.now(),
        granted_by_id=account.id,
        reason="Existing edition-wide role.",
    )

    executor = MigrationExecutor(connection)
    executor.migrate([AUTHORIZATION_SCOPE_V2_SCHEMA, *SCHEMA_DEPENDENCIES])
    scope_v2_apps = executor.loader.project_state(
        [AUTHORIZATION_SCOPE_V2_SCHEMA, *SCHEMA_DEPENDENCIES]
    ).apps
    scope_v2_capability_grant = scope_v2_apps.get_model(
        "authorization", "CapabilityGrant"
    )
    scope_v2_role_assignment = scope_v2_apps.get_model(
        "authorization", "RoleAssignment"
    )
    scope_v2_resource_binding = scope_v2_apps.get_model(
        "authorization", "ScopedResourceBinding"
    )

    migrated_grant = scope_v2_capability_grant.objects.get(pk=grant.id)
    migrated_organization_grant = scope_v2_capability_grant.objects.get(
        pk=organization_grant.id
    )
    migrated_assignment = scope_v2_role_assignment.objects.get(pk=assignment.id)
    assert migrated_grant.edition_id == edition.id
    assert migrated_grant.department_id is None
    assert migrated_grant.resource_binding_id is None
    assert migrated_organization_grant.edition_id is None
    assert migrated_organization_grant.department_id is None
    assert migrated_organization_grant.resource_binding_id is None
    assert migrated_assignment.edition_id == edition.id
    assert migrated_assignment.department_id is None
    assert migrated_assignment.resource_binding_id is None
    assert not scope_v2_resource_binding.objects.exists()
