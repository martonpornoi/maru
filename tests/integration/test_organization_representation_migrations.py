from __future__ import annotations

from uuid import uuid4

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.authorization.models import CapabilityGrant
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
)
from maru.organizations.representation import (
    activate_executive_board,
    emergency_remove_executive_board_controller,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    OrganizationFactory,
    RoleAssignmentFactory,
)
from tests.support.migrations import restore_current_migration_graph

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
    pytest.mark.usefixtures("restores_current_migration_graph"),
]

ORGANIZATIONS_BEFORE_HARDENING = (
    "organizations",
    "0008_organization_representation",
)
ORGANIZATIONS_AFTER_HARDENING = (
    "organizations",
    "0011_emergency_controller_removal_integrity",
)
ORGANIZATIONS_BEFORE_EMERGENCY_HARDENING = (
    "organizations",
    "0010_executive_board_authority_hardening",
)
ORGANIZATIONS_BEFORE_FIX_FORWARD = (
    "organizations",
    "0009_executive_board_integrity_guards",
)
AUDIT_CURRENT = ("audit", "0004_alter_auditevent_safe_metadata")
EFFECTS_CURRENT = ("effects", "0002_integrity_guards")
IDENTITY_CURRENT = ("identity", "0010_account_kind")


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _restore_current_graph() -> MigrationExecutor:
    """Restore all leaves before current-model assertions or test handoff."""

    return restore_current_migration_graph()


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

    try:
        _migrate(ORGANIZATIONS_AFTER_HARDENING)
        with pytest.raises(
            RuntimeError,
            match="Cannot reverse hardened Executive Board governance",
        ):
            _migrate(ORGANIZATIONS_BEFORE_HARDENING)
    finally:
        _restore_current_graph()


def test_hardened_downgrade_fence_allows_clean_reverse_plan() -> None:
    _migrate(ORGANIZATIONS_BEFORE_HARDENING)
    try:
        _migrate(ORGANIZATIONS_AFTER_HARDENING)
        _migrate(ORGANIZATIONS_BEFORE_HARDENING)
    finally:
        _restore_current_graph()


def test_emergency_integrity_downgrade_fence_rejects_surviving_evidence() -> None:
    _restore_current_graph()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish synthetic governance before the downgrade exercise.",
        correlation_id=uuid4(),
    )
    controllers = [AccountFactory(), AccountFactory()]
    appointments = []
    for controller in controllers:
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic controller for downgrade-fence coverage.",
            correlation_id=uuid4(),
        )
        respond_to_representation_invitation(
            actor=controller,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
        )
        appointments.append(appointment)
    representation.refresh_from_db()
    activation = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate synthetic governance for downgrade-fence coverage.",
        correlation_id=uuid4(),
    )
    emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=activation.representation.id,
        appointment_id=appointments[0].id,
        expected_version=activation.representation.aggregate_version,
        reason="Synthetic platform emergency used only to verify the fence.",
        correlation_id=uuid4(),
    )

    try:
        with pytest.raises(
            RuntimeError,
            match="Cannot reverse emergency Executive Board integrity",
        ):
            _migrate(ORGANIZATIONS_BEFORE_EMERGENCY_HARDENING)
    finally:
        _restore_current_graph()


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
        _restore_current_graph()


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
        _restore_current_graph()


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
        _restore_current_graph()


def test_fix_forward_rejects_raw_platform_capability_grants() -> None:
    _restore_current_graph()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match="platform accounts cannot receive convention capability grants",
        ),
    ):
        CapabilityGrant.objects.bulk_create(
            [
                CapabilityGrant(
                    organization=organization,
                    principal=administrator,
                    capability_code="events.view_basic",
                    effective_from=timezone.now(),
                    granted_by=administrator,
                    reason="Forbidden raw platform authority.",
                )
            ]
        )


@pytest.mark.parametrize("authority_kind", ["grant", "assignment"])
def test_fix_forward_blocks_reclassification_while_authority_remains(
    authority_kind: str,
) -> None:
    _restore_current_graph()
    person = AccountFactory()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    if authority_kind == "grant":
        CapabilityGrantFactory(
            organization=organization,
            principal=person,
            capability_code="events.view_basic",
        )
    else:
        RoleAssignmentFactory(
            principal=person,
            edition=None,
        )

    def reclassify_with_authority() -> None:
        with transaction.atomic():
            Account.objects.filter(pk=person.pk).update(
                account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
                is_staff=True,
                is_superuser=True,
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET CONSTRAINTS identity_platform_authority_principal_guard "
                    "IMMEDIATE"
                )

    with pytest.raises(
        IntegrityError,
        match="platform account cannot retain convention authority",
    ):
        reclassify_with_authority()

    person.refresh_from_db()
    assert person.account_kind == Account.Kind.PERSON


@pytest.mark.parametrize(
    "membership_changes",
    [
        {"relationship_label": "Unrelated relationship"},
        {"started_at": None},
        {"ended_at": "now"},
    ],
)
def test_fix_forward_freezes_active_board_membership_provenance(
    membership_changes: dict[str, object],
) -> None:
    _restore_current_graph()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish synthetic governance.",
        correlation_id=uuid4(),
    )
    controllers = [AccountFactory(), AccountFactory()]
    for controller in controllers:
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic controller.",
            correlation_id=uuid4(),
        )
        respond_to_representation_invitation(
            actor=controller,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
        )
    representation.refresh_from_db()
    activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate synthetic governance.",
        correlation_id=uuid4(),
    )
    changes = dict(membership_changes)
    if changes.get("ended_at") == "now":
        changes["ended_at"] = timezone.now()
    membership = OrganizationMembership.objects.get(
        organization=organization,
        account=controllers[0],
    )

    def tamper_with_membership() -> None:
        with transaction.atomic():
            OrganizationMembership.objects.filter(pk=membership.pk).update(**changes)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET CONSTRAINTS organizations_membership_board_provenance "
                    "IMMEDIATE"
                )

    with pytest.raises(
        IntegrityError,
        match="active Executive Board membership evidence is incomplete",
    ):
        tamper_with_membership()
