"""Historical governance migrations with independent rollback-isolated cases."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from tests.support.migrations import (
    flush_then_restore_current_migration_graph,
    migrate_test_targets,
    rollback_migration_case,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django.fixtures import DjangoDbBlocker

pytestmark = pytest.mark.integration

ORGANIZATIONS_BEFORE_HARDENING = (
    "organizations",
    "0008_organization_representation",
)
ORGANIZATIONS_AFTER_HARDENING = (
    "organizations",
    "0011_emergency_controller_removal_integrity",
)
ORGANIZATIONS_BEFORE_FIX_FORWARD = (
    "organizations",
    "0009_executive_board_integrity_guards",
)
AUDIT_CURRENT = ("audit", "0004_alter_auditevent_safe_metadata")
EFFECTS_CURRENT = ("effects", "0002_integrity_guards")
IDENTITY_CURRENT = ("identity", "0010_account_kind")


@pytest.fixture(scope="module")
def historical_baseline(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Run full-graph setup and restoration once for this historical boundary."""

    del django_db_setup
    with django_db_blocker.unblock():
        try:
            _migrate(ORGANIZATIONS_BEFORE_HARDENING)
            yield
        finally:
            flush_then_restore_current_migration_graph()


@pytest.fixture(autouse=True)
def isolated_historical_case(
    historical_baseline: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Preserve independent schema, data, and recorder state for every case."""

    del historical_baseline
    with django_db_blocker.unblock(), rollback_migration_case():
        yield


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    migrate_test_targets(executor, list(targets))
    return executor


def _historical_objects(executor: MigrationExecutor):  # type: ignore[no-untyped-def]
    historical_apps = executor.loader.project_state(
        [
            ORGANIZATIONS_BEFORE_HARDENING,
            AUDIT_CURRENT,
            EFFECTS_CURRENT,
            IDENTITY_CURRENT,
        ]
    ).apps
    organization_model = historical_apps.get_model("organizations", "Organization")
    account_model = historical_apps.get_model("identity", "Account")
    organization = organization_model.objects.create(
        slug=f"downgrade-{uuid4().hex[:12]}",
        name="Synthetic downgrade fence organization",
    )
    account = account_model.objects.create(
        email=f"downgrade-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name="Synthetic fence person",
        email_verified_at=timezone.now(),
    )
    return historical_apps, organization, account


@pytest.mark.parametrize("artifact", ["role", "membership", "audit", "event"])
def test_hardened_downgrade_fence_detects_surviving_governance_artifacts(
    artifact: str,
) -> None:
    executor = _migrate(ORGANIZATIONS_BEFORE_HARDENING)
    historical_apps, organization, account = _historical_objects(executor)

    if artifact == "role":
        role_bundle = historical_apps.get_model("authorization", "RoleBundle")
        role_bundle.objects.create(
            organization_id=organization.id,
            code="executive-board",
            name="Executive Board",
            version=1,
            capability_codes=["events.view_basic"],
        )
    elif artifact == "membership":
        membership = historical_apps.get_model(
            "organizations",
            "OrganizationMembership",
        )
        membership.objects.create(
            organization_id=organization.id,
            account_id=account.id,
            state="active",
            relationship_label="Executive Board controller",
        )
    elif artifact == "audit":
        audit_event = historical_apps.get_model("audit", "AuditEvent")
        audit_event.objects.create(
            occurred_at=timezone.now(),
            principal_kind="account",
            principal_id=account.id,
            organization_id=organization.id,
            capability_code="organizations.manage_representation",
            operation="organizations.representation.activate",
            target_type="organizations.organization_representation",
            target_id=uuid4(),
            outcome="allow",
            reason_code="synthetic_fence_evidence",
            obligations=[],
            changed_fields=[],
            correlation_id=uuid4(),
            source_channel="test",
        )
    else:
        domain_event = historical_apps.get_model("effects", "DomainEvent")
        domain_event.objects.create(
            event_name="organizations.representation.changed.v1",
            schema_version=1,
            occurred_at=timezone.now(),
            organization_id=organization.id,
            aggregate_type="organizations.organization_representation",
            aggregate_id=uuid4(),
            aggregate_version=1,
            payload={"action": "activated"},
            correlation_id=uuid4(),
            actor_kind="account",
            actor_id=account.id,
        )

    _migrate(ORGANIZATIONS_AFTER_HARDENING)
    with pytest.raises(
        RuntimeError,
        match="Cannot reverse hardened Executive Board governance",
    ):
        _migrate(ORGANIZATIONS_BEFORE_HARDENING)


def test_hardened_downgrade_fence_allows_clean_reverse_plan() -> None:
    _migrate(ORGANIZATIONS_BEFORE_HARDENING)
    _migrate(ORGANIZATIONS_AFTER_HARDENING)
    _migrate(ORGANIZATIONS_BEFORE_HARDENING)


def test_hardening_preflight_rejects_existing_platform_role_assignment() -> None:
    executor = _migrate(ORGANIZATIONS_BEFORE_HARDENING)
    historical_apps, organization, account = _historical_objects(executor)
    account_model = historical_apps.get_model("identity", "Account")
    role_bundle_model = historical_apps.get_model("authorization", "RoleBundle")
    role_assignment_model = historical_apps.get_model(
        "authorization",
        "RoleAssignment",
    )
    administrator = account_model.objects.create(
        email=f"platform-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name="Synthetic platform administrator",
        account_kind="platform_administrator",
        is_staff=True,
        is_superuser=True,
        email_verified_at=timezone.now(),
    )
    role = role_bundle_model.objects.create(
        organization_id=organization.id,
        code="synthetic-preflight-role",
        name="Synthetic preflight role",
        version=1,
        capability_codes=["events.view_basic"],
    )
    assignment = role_assignment_model.objects.create(
        organization_id=organization.id,
        principal_id=administrator.id,
        role_bundle_id=role.id,
        effective_from=timezone.now(),
        granted_by_id=account.id,
        reason="Synthetic pre-existing invalid platform authority.",
    )

    try:
        with pytest.raises(
            IntegrityError,
            match="1 platform role assignments exist",
        ):
            _migrate(ORGANIZATIONS_AFTER_HARDENING)
    finally:
        role_assignment_model.objects.filter(pk=assignment.pk).delete()


def test_fix_forward_preflight_rejects_existing_platform_capability_grant() -> None:
    executor = _migrate(ORGANIZATIONS_BEFORE_FIX_FORWARD)
    historical_apps = executor.loader.project_state(
        [
            ORGANIZATIONS_BEFORE_FIX_FORWARD,
            AUDIT_CURRENT,
            EFFECTS_CURRENT,
            IDENTITY_CURRENT,
        ]
    ).apps
    organization_model = historical_apps.get_model("organizations", "Organization")
    account_model = historical_apps.get_model("identity", "Account")
    capability_grant_model = historical_apps.get_model(
        "authorization",
        "CapabilityGrant",
    )
    organization = organization_model.objects.create(
        slug=f"platform-grant-{uuid4().hex[:12]}",
        name="Synthetic platform grant preflight",
    )
    administrator = account_model.objects.create(
        email=f"platform-grant-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name="Synthetic platform grant administrator",
        account_kind="platform_administrator",
        is_staff=True,
        is_superuser=True,
        email_verified_at=timezone.now(),
    )
    grant = capability_grant_model.objects.create(
        organization_id=organization.id,
        principal_id=administrator.id,
        capability_code="events.view_basic",
        effective_from=timezone.now(),
        granted_by_id=administrator.id,
        reason="Synthetic pre-existing invalid platform grant.",
    )

    try:
        with pytest.raises(IntegrityError, match="1 platform grants"):
            _migrate(ORGANIZATIONS_AFTER_HARDENING)
    finally:
        capability_grant_model.objects.filter(pk=grant.pk).delete()


def test_fix_forward_preflight_rejects_ineligible_provisioning_subjects() -> None:
    executor = _migrate(ORGANIZATIONS_BEFORE_HARDENING)
    historical_apps = executor.loader.project_state(
        [
            ORGANIZATIONS_BEFORE_HARDENING,
            AUDIT_CURRENT,
            EFFECTS_CURRENT,
            IDENTITY_CURRENT,
        ]
    ).apps
    organization_model = historical_apps.get_model("organizations", "Organization")
    representation_model = historical_apps.get_model(
        "organizations",
        "OrganizationRepresentation",
    )
    appointment_model = historical_apps.get_model(
        "organizations",
        "RepresentationAppointment",
    )
    account_model = historical_apps.get_model("identity", "Account")
    administrator = account_model.objects.create(
        email=f"provisioning-admin-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name="Synthetic provisioning administrator",
        account_kind="platform_administrator",
        is_staff=True,
        is_superuser=True,
        email_verified_at=timezone.now(),
    )
    subjects = []
    for label, active, verified_at in (
        ("inactive", False, timezone.now()),
        ("unverified", True, None),
    ):
        organization = organization_model.objects.create(
            slug=f"{label}-appointment-{uuid4().hex[:10]}",
            name=f"Synthetic {label} provisioning appointment",
        )
        subject = account_model.objects.create(
            email=f"{label}-subject-{uuid4().hex}@example.invalid",
            password="!synthetic-unusable",
            display_name=f"Synthetic {label} subject",
            account_kind="person",
            is_active=active,
            email_verified_at=verified_at,
        )
        representation = representation_model.objects.create(
            organization_id=organization.id,
            state="provisioning",
            aggregate_version=1,
            provisioning_reason="Synthetic provisioning preflight.",
            provisioned_by_id=administrator.id,
        )
        appointment_model.objects.create(
            representation_id=representation.id,
            account_id=subject.id,
            role="controller",
            state="invited",
            invitation_version=1,
            invited_by_id=administrator.id,
            invited_at=timezone.now(),
            reason="Synthetic ineligible provisioning appointment.",
        )
        subjects.append(subject)

    _migrate(ORGANIZATIONS_BEFORE_FIX_FORWARD)
    try:
        with pytest.raises(
            IntegrityError,
            match="2 ineligible provisioning appointments exist",
        ):
            _migrate(ORGANIZATIONS_AFTER_HARDENING)
    finally:
        account_model.objects.filter(
            id__in=[subject.id for subject in subjects]
        ).update(
            is_active=True,
            email_verified_at=timezone.now(),
        )
