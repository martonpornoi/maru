"""Deployment preflight coverage for organization representation readiness."""

from __future__ import annotations

import json
from copy import copy
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.identity.models import Account
from maru.organizations.management.commands import (
    check_representation_readiness as readiness,
)
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    EXECUTIVE_BOARD_CAPABILITIES,
    EXECUTIVE_BOARD_ROLE_CODE,
    activate_executive_board,
    emergency_remove_executive_board_controller,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from tests.factories import (
    AccountFactory,
    OrganizationFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

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
    "0012_idn011_convention_subject_guards",
)
AUDIT_CURRENT = ("audit", "0004_alter_auditevent_safe_metadata")
EFFECTS_CURRENT = ("effects", "0002_integrity_guards")
IDENTITY_CURRENT = ("identity", "0010_account_kind")

EXPECTED_BLOCKER_KEYS = {
    "active_board_appointment_mismatch",
    "active_board_insufficient_controllers",
    "active_board_pending_appointments",
    "active_representation_organization_not_active",
    "emergency_board_evidence_mismatch",
    "governed_board_activation_evidence_mismatch",
    "governed_representation_activation_provenance_mismatch",
    "non_draft_without_active_representation",
    "platform_principal_capability_grants",
    "platform_principal_role_assignments",
    "provisioning_appointment_subject_ineligible",
    "reserved_executive_board_bundle_mismatch",
    "reserved_executive_board_cardinality",
    "stray_active_executive_board_membership",
    "suspended_representation_organization_not_suspended",
    "unlinked_live_executive_board_assignments",
}


def _migrate(*targets: tuple[str, str]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(list(targets))
    return executor


def _legacy_person(historical_apps: Any, label: str) -> Any:
    account_model = historical_apps.get_model("identity", "Account")
    return account_model.objects.create(
        email=f"{label}-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name=f"Sensitive {label}",
        account_kind="person",
        is_active=True,
        email_verified_at=timezone.now(),
    )


def _legacy_platform_administrator(historical_apps: Any, label: str) -> Any:
    account_model = historical_apps.get_model("identity", "Account")
    return account_model.objects.create(
        email=f"{label}-{uuid4().hex}@example.invalid",
        password="!synthetic-unusable",
        display_name=f"Sensitive {label}",
        account_kind="platform_administrator",
        is_staff=True,
        is_superuser=True,
        is_active=True,
        email_verified_at=timezone.now(),
    )


def _legacy_organization(
    historical_apps: Any,
    *,
    slug: str,
    lifecycle: str = "draft",
) -> Any:
    organization_model = historical_apps.get_model(
        "organizations",
        "Organization",
    )
    return organization_model.objects.create(
        slug=slug,
        name=f"Sensitive {slug}",
        lifecycle=lifecycle,
    )


def _legacy_active_board(
    historical_apps: Any,
    slug: str,
    *,
    bundle_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    representation_model = historical_apps.get_model(
        "organizations",
        "OrganizationRepresentation",
    )
    appointment_model = historical_apps.get_model(
        "organizations",
        "RepresentationAppointment",
    )
    membership_model = historical_apps.get_model(
        "organizations",
        "OrganizationMembership",
    )
    role_bundle_model = historical_apps.get_model("authorization", "RoleBundle")
    role_assignment_model = historical_apps.get_model(
        "authorization",
        "RoleAssignment",
    )
    audit_model = historical_apps.get_model("audit", "AuditEvent")
    event_model = historical_apps.get_model("effects", "DomainEvent")
    outbox_model = historical_apps.get_model("effects", "OutboxMessage")
    now = timezone.now()
    correlation_id = uuid4()
    activation_reason = "Synthetic canonical activation reason."
    administrator = _legacy_platform_administrator(
        historical_apps,
        f"{slug}-administrator",
    )
    controllers = [
        _legacy_person(historical_apps, f"{slug}-controller-{number}")
        for number in range(2)
    ]
    organization = _legacy_organization(historical_apps, slug=slug)
    representation = representation_model.objects.create(
        organization_id=organization.id,
        state="provisioning",
        aggregate_version=1,
        provisioning_reason="Sensitive provisioning reason.",
        provisioned_by_id=administrator.id,
    )
    bundle_values: dict[str, Any] = {
        "organization_id": organization.id,
        "code": EXECUTIVE_BOARD_ROLE_CODE,
        "name": "Executive Board",
        "version": 1,
        "capability_codes": list(EXECUTIVE_BOARD_CAPABILITIES),
        "created_by_id": administrator.id,
        "approved_by_id": controllers[0].id,
        "reason": activation_reason,
    }
    bundle_values.update(bundle_overrides or {})
    bundle = role_bundle_model.objects.create(
        **bundle_values,
    )
    assignments = []
    memberships = []
    appointments = []
    for number, controller in enumerate(controllers):
        assignment = role_assignment_model.objects.create(
            organization_id=organization.id,
            principal_id=controller.id,
            role_bundle_id=bundle.id,
            effective_from=now,
            granted_by_id=administrator.id,
            approved_by_id=controllers[1 - number].id,
            reason=activation_reason,
        )
        membership = membership_model.objects.create(
            organization_id=organization.id,
            account_id=controller.id,
            state="active",
            relationship_label="Executive Board controller",
            started_at=now,
        )
        appointment = appointment_model.objects.create(
            representation_id=representation.id,
            account_id=controller.id,
            role="controller",
            state="active",
            invitation_version=3,
            invited_by_id=administrator.id,
            invited_at=now,
            responded_at=now,
            activated_at=now,
            reason="Sensitive appointment reason.",
            role_assignment_id=assignment.id,
        )
        assignments.append(assignment)
        memberships.append(membership)
        appointments.append(appointment)
        audit_model.objects.create(
            schema_version=1,
            occurred_at=now,
            principal_kind="account",
            principal_id=administrator.id,
            organization_id=organization.id,
            capability_code="organizations.manage_representation",
            operation="organizations.representation.authority_assign",
            target_type="authorization.role_assignment",
            target_id=assignment.id,
            outcome="allow",
            reason_code="initial_representation_bootstrap",
            obligations=["reason", "audit", "approval"],
            changed_fields=["role_assignment"],
            correlation_id=correlation_id,
            source_channel="test",
            retention_class="security-extended",
        )

    representation_model.objects.filter(id=representation.id).update(
        state="active",
        aggregate_version=2,
        activation_reason=activation_reason,
        activated_by_id=administrator.id,
        activated_at=now,
    )
    historical_apps.get_model("organizations", "Organization").objects.filter(
        id=organization.id
    ).update(lifecycle="active")
    activation_audit = audit_model.objects.create(
        schema_version=1,
        occurred_at=now,
        principal_kind="account",
        principal_id=administrator.id,
        organization_id=organization.id,
        capability_code="organizations.manage_representation",
        operation="organizations.representation.activate",
        target_type="organizations.organization_representation",
        target_id=representation.id,
        outcome="allow",
        reason_code="independent_controller_acceptance",
        obligations=["reason", "audit", "approval"],
        changed_fields=[
            "representation_state",
            "organization_lifecycle",
            "memberships",
            "role_assignments",
        ],
        correlation_id=correlation_id,
        source_channel="test",
        retention_class="security-extended",
    )
    event = event_model.objects.create(
        event_name="organizations.representation.changed.v1",
        schema_version=1,
        occurred_at=now,
        organization_id=organization.id,
        aggregate_type="organizations.organization_representation",
        aggregate_id=representation.id,
        aggregate_version=2,
        payload={
            "action": "activated",
            "representation_code": "executive_board",
            "state": "active",
        },
        correlation_id=correlation_id,
        causation_id=activation_audit.id,
        actor_kind="account",
        actor_id=administrator.id,
        retention_class="security-extended",
    )
    outbox_model.objects.create(
        event_id=event.id,
        organization_id=organization.id,
        destination="internal",
        workload_pool="core",
        available_at=now,
    )
    organization.refresh_from_db()
    representation.refresh_from_db()
    return {
        "activation_audit": activation_audit,
        "activation_correlation_id": correlation_id,
        "activation_reason": activation_reason,
        "administrator": administrator,
        "appointments": appointments,
        "assignments": assignments,
        "bundle": bundle,
        "controllers": controllers,
        "memberships": memberships,
        "organization": organization,
        "representation": representation,
    }


def _remove_legacy_readiness_fixtures(historical_apps: Any) -> None:
    """Empty only isolated migration-test records before restoring current guards."""

    historical_apps.get_model(
        "organizations",
        "RepresentationAppointment",
    ).objects.all().delete()
    historical_apps.get_model(
        "organizations",
        "OrganizationMembership",
    ).objects.all().delete()
    historical_apps.get_model(
        "authorization",
        "CapabilityGrant",
    ).objects.all().delete()
    historical_apps.get_model(
        "authorization",
        "RoleAssignment",
    ).objects.all().delete()
    historical_apps.get_model(
        "organizations",
        "OrganizationRepresentation",
    ).objects.all().delete()
    # Role bundle versions are deliberately DELETE-immutable. TRUNCATE is safe
    # here because the transaction-capable test database started empty and all
    # referencing synthetic rows were removed above.
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE TABLE authorization_rolebundle CASCADE")
    historical_apps.get_model(
        "organizations",
        "Organization",
    ).objects.all().delete()
    historical_apps.get_model("identity", "Account").objects.all().delete()


def _run_readiness_command(*, no_fail: bool = True) -> tuple[str, dict[str, Any]]:
    output = StringIO()
    arguments = ["--no-fail"] if no_fail else []
    call_command(
        "check_representation_readiness",
        *arguments,
        stdout=output,
    )
    rendered = output.getvalue()
    return rendered, json.loads(rendered)


def _active_board(
    slug: str,
    *,
    controller_count: int = 2,
) -> tuple[
    Organization,
    OrganizationRepresentation,
    Account,
    list[RepresentationAppointment],
]:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(
        slug=slug,
        name=f"Synthetic {slug}",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Synthetic representation preflight setup.",
        correlation_id=uuid4(),
    )
    appointments: list[RepresentationAppointment] = []
    for _ in range(controller_count):
        controller = AccountFactory()
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Synthetic controller invitation.",
            correlation_id=uuid4(),
        )
        appointment = respond_to_representation_invitation(
            actor=controller,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
        )
        appointments.append(appointment)
    representation.refresh_from_db()
    activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Synthetic representation activation.",
        correlation_id=uuid4(),
    )
    organization.refresh_from_db()
    representation.refresh_from_db()
    appointments = list(representation.appointments.order_by("created_at", "id"))
    return organization, representation, administrator, appointments


def test_ready_report_is_deterministic_and_read_only() -> None:
    _active_board("ready-board")
    OrganizationFactory(
        slug="unprovisioned-draft",
        lifecycle=Organization.Lifecycle.DRAFT,
    )
    counts_before = (
        Organization.objects.count(),
        OrganizationRepresentation.objects.count(),
        RepresentationAppointment.objects.count(),
        OrganizationMembership.objects.count(),
        RoleAssignment.objects.count(),
        CapabilityGrant.objects.count(),
        AuditEvent.objects.count(),
    )

    first_rendered, first = _run_readiness_command()
    second_rendered, second = _run_readiness_command()

    assert first_rendered == second_rendered
    assert first == second
    assert first == {
        "status": "ready",
        "blocker_counts": dict.fromkeys(sorted(EXPECTED_BLOCKER_KEYS), 0),
        "blocked_organization_count": 0,
        "organization_slugs": [],
        "organization_slugs_truncated": False,
    }
    assert counts_before == (
        Organization.objects.count(),
        OrganizationRepresentation.objects.count(),
        RepresentationAppointment.objects.count(),
        OrganizationMembership.objects.count(),
        RoleAssignment.objects.count(),
        CapabilityGrant.objects.count(),
        AuditEvent.objects.count(),
    )


def test_valid_emergency_suspension_remains_governed_and_ready() -> None:
    organization, representation, administrator, appointments = _active_board(
        "ready-suspended-board"
    )

    emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=representation.id,
        appointment_id=appointments[0].id,
        expected_version=representation.aggregate_version,
        reason="Synthetic emergency readiness verification.",
        correlation_id=uuid4(),
    )

    organization.refresh_from_db()
    representation.refresh_from_db()
    _, report = _run_readiness_command()

    assert organization.lifecycle == Organization.Lifecycle.SUSPENDED
    assert representation.state == OrganizationRepresentation.State.SUSPENDED
    assert report == {
        "status": "ready",
        "blocker_counts": dict.fromkeys(sorted(EXPECTED_BLOCKER_KEYS), 0),
        "blocked_organization_count": 0,
        "organization_slugs": [],
        "organization_slugs_truncated": False,
    }


def test_valid_emergency_removal_with_remaining_quorum_is_ready() -> None:
    organization, representation, administrator, appointments = _active_board(
        "ready-board-after-removal",
        controller_count=3,
    )

    emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=representation.id,
        appointment_id=appointments[0].id,
        expected_version=representation.aggregate_version,
        reason="Synthetic emergency removal with remaining quorum.",
        correlation_id=uuid4(),
    )

    organization.refresh_from_db()
    representation.refresh_from_db()
    _, report = _run_readiness_command()

    assert organization.lifecycle == Organization.Lifecycle.ACTIVE
    assert representation.state == OrganizationRepresentation.State.ACTIVE
    assert report["status"] == "ready"
    assert report["blocked_organization_count"] == 0


def test_readiness_defensive_evidence_checks_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, representation, administrator, appointments = _active_board(
        "readiness-defensive-evidence"
    )
    bundle = RoleBundle.objects.get(
        organization=organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    )
    appointment = RepresentationAppointment.objects.select_related(
        "account",
        "representation",
    ).get(id=appointments[0].id)

    assert not readiness._has_controller_approver(
        representation=representation,
        account_id=None,
        emergency_state=False,
    )

    missing_assignment = copy(appointment)
    missing_assignment.role_assignment_id = uuid4()
    assert not readiness._active_appointment_is_exact(
        appointment=missing_assignment,
        representation=representation,
        bundle=bundle,
        emergency_state=False,
    )

    activation_audit = readiness._latest_activation_audit(representation)
    assert activation_audit is not None
    with monkeypatch.context() as patch:
        patch.setattr(
            RepresentationAppointment.objects,
            "filter",
            lambda **_kwargs: [SimpleNamespace(role_assignment_id=None)],
        )
        assert not readiness._has_assignment_audits(
            representation=representation,
            activation_audit=activation_audit,
        )

    with monkeypatch.context() as patch:
        patch.setattr(
            RepresentationAppointment.objects,
            "filter",
            lambda **_kwargs: [SimpleNamespace(account_id=uuid4())],
        )
        assert not readiness._ended_appointments_have_memberships(representation)

    malformed_event = SimpleNamespace(
        payload={"action": "activated", "state": "active"},
        causation_id=uuid4(),
        actor_id=administrator.id,
        correlation_id=uuid4(),
    )
    assert not readiness._emergency_evidence_is_exact(  # type: ignore[arg-type]
        representation=representation,
        current_event=malformed_event,
        bundle=bundle,
    )

    auditless_event = SimpleNamespace(
        payload={"action": "controller_ended", "state": "active"},
        causation_id=uuid4(),
        actor_id=administrator.id,
        correlation_id=uuid4(),
    )
    assert not readiness._emergency_evidence_is_exact(  # type: ignore[arg-type]
        representation=representation,
        current_event=auditless_event,
        bundle=bundle,
    )

    ordinary_bundle = RoleBundleFactory(organization=organization)
    RoleAssignmentFactory(
        organization=organization,
        role_bundle=ordinary_bundle,
        revoked_at=timezone.now(),
        revoked_by=administrator,
        revocation_reason="Synthetic revoked authority without audit evidence.",
    )
    assert not readiness._revoked_assignments_have_audits(
        representation=representation,
        bundle=ordinary_bundle,
    )


def test_no_fail_report_detects_all_required_blocker_classes_privately() -> None:  # noqa: PLR0915
    historical_apps = None
    try:
        executor = _migrate(ORGANIZATIONS_BEFORE_HARDENING)
        historical_apps = executor.loader.project_state(
            [
                ORGANIZATIONS_BEFORE_HARDENING,
                AUDIT_CURRENT,
                EFFECTS_CURRENT,
                IDENTITY_CURRENT,
            ]
        ).apps
        organization_model = historical_apps.get_model(
            "organizations",
            "Organization",
        )
        appointment_model = historical_apps.get_model(
            "organizations",
            "RepresentationAppointment",
        )
        membership_model = historical_apps.get_model(
            "organizations",
            "OrganizationMembership",
        )
        account_model = historical_apps.get_model("identity", "Account")
        capability_grant_model = historical_apps.get_model(
            "authorization",
            "CapabilityGrant",
        )
        role_bundle_model = historical_apps.get_model(
            "authorization",
            "RoleBundle",
        )
        role_assignment_model = historical_apps.get_model(
            "authorization",
            "RoleAssignment",
        )

        non_draft = _legacy_organization(
            historical_apps,
            slug="non-draft-no-board",
            lifecycle="suspended",
        )

        inactive_parent = _legacy_active_board(historical_apps, "inactive-parent")
        organization_model.objects.filter(id=inactive_parent["organization"].id).update(
            lifecycle="suspended"
        )

        insufficient = _legacy_active_board(historical_apps, "insufficient-board")
        appointment_model.objects.filter(id=insufficient["appointments"][0].id).update(
            state="ended",
            ended_at=timezone.now(),
            invitation_version=4,
        )

        pending = _legacy_active_board(historical_apps, "pending-board")
        pending_subject = _legacy_person(historical_apps, "pending-subject")
        appointment_model.objects.create(
            representation_id=pending["representation"].id,
            account_id=pending_subject.id,
            role="controller",
            state="invited",
            invitation_version=1,
            invited_by_id=pending["administrator"].id,
            invited_at=timezone.now(),
            reason="Sensitive pending invitation reason.",
        )

        orphan_bundle = _legacy_organization(
            historical_apps,
            slug="orphan-board-bundle",
        )
        role_bundle_model.objects.create(
            organization_id=orphan_bundle.id,
            code=EXECUTIVE_BOARD_ROLE_CODE,
            name="Executive Board",
            version=1,
            capability_codes=["events.view_basic"],
            reason="Sensitive orphan bundle reason.",
        )

        assignment_mismatch = _legacy_active_board(
            historical_apps,
            "assignment-mismatch",
        )
        role_assignment_model.objects.filter(
            id=assignment_mismatch["assignments"][0].id
        ).update(
            revoked_at=timezone.now(),
            revoked_by_id=assignment_mismatch["administrator"].id,
            revocation_reason="Sensitive revocation reason.",
        )

        membership_mismatch = _legacy_active_board(
            historical_apps,
            "membership-mismatch",
        )
        membership_model.objects.filter(
            id=membership_mismatch["memberships"][0].id
        ).update(
            relationship_label="Unrelated historical relationship",
            started_at=None,
            ended_at=timezone.now(),
        )

        subject_mismatch = _legacy_active_board(
            historical_apps,
            "subject-mismatch",
        )
        account_model.objects.filter(id=subject_mismatch["controllers"][0].id).update(
            is_active=False
        )

        platform_principal = _legacy_platform_administrator(
            historical_apps,
            "private-platform-principal",
        )
        grant_organization = _legacy_organization(
            historical_apps,
            slug="platform-grant",
        )
        capability_grant_model.objects.create(
            organization_id=grant_organization.id,
            principal_id=platform_principal.id,
            capability_code="events.view_basic",
            effective_from=timezone.now(),
            granted_by_id=platform_principal.id,
            reason="Sensitive grant reason.",
        )

        assignment_organization = _legacy_organization(
            historical_apps,
            slug="platform-assignment",
        )
        ordinary_bundle = role_bundle_model.objects.create(
            organization_id=assignment_organization.id,
            code="ordinary-reader",
            name="Ordinary reader",
            version=1,
            capability_codes=["events.view_basic"],
            reason="Sensitive ordinary bundle reason.",
        )
        platform_assignment = role_assignment_model.objects.create(
            organization_id=assignment_organization.id,
            principal_id=platform_principal.id,
            role_bundle_id=ordinary_bundle.id,
            effective_from=timezone.now(),
            granted_by_id=platform_principal.id,
            reason="Sensitive platform assignment reason.",
        )

        ineligible_provisioning_organization = _legacy_organization(
            historical_apps,
            slug="ineligible-provisioning-subject",
        )
        ineligible_subject = _legacy_person(
            historical_apps,
            "ineligible-provisioning-subject",
        )
        account_model.objects.filter(id=ineligible_subject.id).update(
            is_active=False,
            email_verified_at=None,
        )
        provisioning_representation = historical_apps.get_model(
            "organizations",
            "OrganizationRepresentation",
        ).objects.create(
            organization_id=ineligible_provisioning_organization.id,
            state="provisioning",
            aggregate_version=1,
            provisioning_reason="Sensitive provisioning reason.",
            provisioned_by_id=platform_principal.id,
        )
        appointment_model.objects.create(
            representation_id=provisioning_representation.id,
            account_id=ineligible_subject.id,
            role="controller",
            state="invited",
            invitation_version=1,
            invited_by_id=platform_principal.id,
            invited_at=timezone.now(),
            reason="Sensitive ineligible invitation reason.",
        )

        rendered, report = _run_readiness_command()

        assert report["status"] == "blocked"
        assert set(report["blocker_counts"]) == EXPECTED_BLOCKER_KEYS
        assert report["blocker_counts"] == {
            "active_board_appointment_mismatch": 4,
            "active_board_insufficient_controllers": 1,
            "active_board_pending_appointments": 1,
            "active_representation_organization_not_active": 1,
            "emergency_board_evidence_mismatch": 0,
            "governed_board_activation_evidence_mismatch": 0,
            "governed_representation_activation_provenance_mismatch": 0,
            "non_draft_without_active_representation": 2,
            "platform_principal_capability_grants": 1,
            "platform_principal_role_assignments": 1,
            "provisioning_appointment_subject_ineligible": 1,
            "reserved_executive_board_bundle_mismatch": 1,
            "reserved_executive_board_cardinality": 1,
            "stray_active_executive_board_membership": 1,
            "suspended_representation_organization_not_suspended": 0,
            "unlinked_live_executive_board_assignments": 1,
        }
        expected_slugs = sorted(
            {
                non_draft.slug,
                inactive_parent["organization"].slug,
                insufficient["organization"].slug,
                pending["organization"].slug,
                orphan_bundle.slug,
                assignment_mismatch["organization"].slug,
                membership_mismatch["organization"].slug,
                subject_mismatch["organization"].slug,
                grant_organization.slug,
                assignment_organization.slug,
                ineligible_provisioning_organization.slug,
            }
        )
        assert report["blocked_organization_count"] == len(expected_slugs)
        assert report["organization_slugs"] == expected_slugs
        assert report["organization_slugs_truncated"] is False
        assert platform_principal.email not in rendered
        assert platform_principal.display_name not in rendered
        assert "Sensitive" not in rendered
        assert str(platform_principal.id) not in rendered
        assert str(platform_assignment.id) not in rendered
        assert str(insufficient["representation"].id) not in rendered
    finally:
        try:
            if historical_apps is not None:
                _remove_legacy_readiness_fixtures(historical_apps)
        finally:
            _migrate(ORGANIZATIONS_AFTER_HARDENING)


def test_pre_hardening_exact_governance_evidence_has_readiness_parity() -> None:  # noqa: PLR0915
    historical_apps = None
    try:
        executor = _migrate(ORGANIZATIONS_BEFORE_HARDENING)
        historical_apps = executor.loader.project_state(
            [
                ORGANIZATIONS_BEFORE_HARDENING,
                AUDIT_CURRENT,
                EFFECTS_CURRENT,
                IDENTITY_CURRENT,
            ]
        ).apps
        account_model = historical_apps.get_model("identity", "Account")
        audit_model = historical_apps.get_model("audit", "AuditEvent")
        appointment_model = historical_apps.get_model(
            "organizations",
            "RepresentationAppointment",
        )
        membership_model = historical_apps.get_model(
            "organizations",
            "OrganizationMembership",
        )
        organization_model = historical_apps.get_model(
            "organizations",
            "Organization",
        )
        representation_model = historical_apps.get_model(
            "organizations",
            "OrganizationRepresentation",
        )
        role_assignment_model = historical_apps.get_model(
            "authorization",
            "RoleAssignment",
        )
        appointment_activation = _legacy_active_board(
            historical_apps,
            "exact-appointment-activation",
        )
        appointment_model.objects.filter(
            id=appointment_activation["appointments"][0].id
        ).update(
            activated_at=appointment_activation["representation"].activated_at
            + timedelta(seconds=1)
        )

        assignment_effective = _legacy_active_board(
            historical_apps,
            "exact-assignment-effective",
        )
        role_assignment_model.objects.filter(
            id=assignment_effective["assignments"][0].id
        ).update(
            effective_from=assignment_effective["representation"].activated_at
            + timedelta(seconds=1)
        )

        assignment_expiry = _legacy_active_board(
            historical_apps,
            "exact-assignment-expiry",
        )
        role_assignment_model.objects.filter(
            id=assignment_expiry["assignments"][0].id
        ).update(
            expires_at=assignment_expiry["representation"].activated_at
            + timedelta(days=1)
        )

        assignment_grantor = _legacy_active_board(
            historical_apps,
            "exact-assignment-grantor",
        )
        other_administrator = _legacy_platform_administrator(
            historical_apps,
            "other-assignment-grantor",
        )
        role_assignment_model.objects.filter(
            id=assignment_grantor["assignments"][0].id
        ).update(granted_by_id=other_administrator.id)

        assignment_reason = _legacy_active_board(
            historical_apps,
            "exact-assignment-reason",
        )
        role_assignment_model.objects.filter(
            id=assignment_reason["assignments"][0].id
        ).update(reason="Different canonical reason.")

        bundle_mutations = (
            ("exact-bundle-version", {"version": 2}),
            ("exact-bundle-name", {"name": "Different root"}),
            (
                "exact-bundle-capabilities",
                {"capability_codes": ["events.view_basic"]},
            ),
            ("exact-bundle-reason", {"reason": "Different canonical reason."}),
        )
        for slug, values in bundle_mutations:
            _legacy_active_board(
                historical_apps,
                slug,
                bundle_overrides=values,
            )

        other_creator = _legacy_platform_administrator(
            historical_apps,
            "other-bundle-creator",
        )
        _legacy_active_board(
            historical_apps,
            "exact-bundle-creator",
            bundle_overrides={"created_by_id": other_creator.id},
        )

        unrelated_approver = _legacy_person(
            historical_apps,
            "unrelated-bundle-approver",
        )
        _legacy_active_board(
            historical_apps,
            "exact-bundle-approver",
            bundle_overrides={"approved_by_id": unrelated_approver.id},
        )

        unlinked_assignment = _legacy_active_board(
            historical_apps,
            "unlinked-live-assignment",
        )
        unlinked_subject = _legacy_person(historical_apps, "unlinked-subject")
        role_assignment_model.objects.create(
            organization_id=unlinked_assignment["organization"].id,
            principal_id=unlinked_subject.id,
            role_bundle_id=unlinked_assignment["bundle"].id,
            effective_from=unlinked_assignment["representation"].activated_at,
            granted_by_id=unlinked_assignment["administrator"].id,
            approved_by_id=unlinked_assignment["controllers"][0].id,
            reason=unlinked_assignment["activation_reason"],
        )

        stray_membership = _legacy_active_board(
            historical_apps,
            "stray-board-membership",
        )
        stray_subject = _legacy_person(historical_apps, "stray-member")
        membership_model.objects.create(
            organization_id=stray_membership["organization"].id,
            account_id=stray_subject.id,
            state="active",
            relationship_label="Executive Board controller",
            started_at=stray_membership["representation"].activated_at,
        )

        later_activation_audit = _legacy_active_board(
            historical_apps,
            "latest-activation-audit",
        )
        audit_model.objects.create(
            schema_version=1,
            occurred_at=timezone.now() + timedelta(minutes=1),
            principal_kind="account",
            principal_id=later_activation_audit["administrator"].id,
            organization_id=later_activation_audit["organization"].id,
            capability_code="organizations.manage_representation",
            operation="organizations.representation.activate",
            target_type="organizations.organization_representation",
            target_id=later_activation_audit["representation"].id,
            outcome="allow",
            reason_code="independent_controller_acceptance",
            obligations=["reason", "audit", "approval"],
            changed_fields=["representation_state"],
            correlation_id=uuid4(),
            source_channel="test",
            retention_class="security-extended",
        )

        missing_assignment_audit = _legacy_active_board(
            historical_apps,
            "missing-assignment-audit",
        )
        unaudited_controller = _legacy_person(
            historical_apps,
            "unaudited-controller",
        )
        unaudited_assignment = role_assignment_model.objects.create(
            organization_id=missing_assignment_audit["organization"].id,
            principal_id=unaudited_controller.id,
            role_bundle_id=missing_assignment_audit["bundle"].id,
            effective_from=missing_assignment_audit["representation"].activated_at,
            granted_by_id=missing_assignment_audit["administrator"].id,
            approved_by_id=missing_assignment_audit["controllers"][0].id,
            reason=missing_assignment_audit["activation_reason"],
        )
        membership_model.objects.create(
            organization_id=missing_assignment_audit["organization"].id,
            account_id=unaudited_controller.id,
            state="active",
            relationship_label="Executive Board controller",
            started_at=missing_assignment_audit["representation"].activated_at,
        )
        appointment_model.objects.create(
            representation_id=missing_assignment_audit["representation"].id,
            account_id=unaudited_controller.id,
            role="controller",
            state="active",
            invitation_version=3,
            invited_by_id=missing_assignment_audit["administrator"].id,
            invited_at=missing_assignment_audit["representation"].activated_at,
            responded_at=missing_assignment_audit["representation"].activated_at,
            activated_at=missing_assignment_audit["representation"].activated_at,
            reason="Synthetic unaudited appointment.",
            role_assignment_id=unaudited_assignment.id,
        )

        missing_current_event = _legacy_active_board(
            historical_apps,
            "missing-current-event",
        )
        representation_model.objects.filter(
            id=missing_current_event["representation"].id
        ).update(aggregate_version=3)

        provenance = _legacy_active_board(
            historical_apps,
            "activation-provenance",
        )
        account_model.objects.filter(id=provenance["administrator"].id).update(
            account_kind="person",
            is_staff=False,
            is_superuser=False,
        )

        invalid_suspended = _legacy_active_board(
            historical_apps,
            "invalid-emergency-suspension",
        )
        organization_model.objects.filter(
            id=invalid_suspended["organization"].id
        ).update(lifecycle="suspended")
        representation_model.objects.filter(
            id=invalid_suspended["representation"].id
        ).update(state="suspended", aggregate_version=3)

        rendered, report = _run_readiness_command()

        assert report["status"] == "blocked"
        assert report["blocker_counts"] == {
            "active_board_appointment_mismatch": 5,
            "active_board_insufficient_controllers": 0,
            "active_board_pending_appointments": 0,
            "active_representation_organization_not_active": 0,
            "emergency_board_evidence_mismatch": 1,
            "governed_board_activation_evidence_mismatch": 3,
            "governed_representation_activation_provenance_mismatch": 1,
            "non_draft_without_active_representation": 0,
            "platform_principal_capability_grants": 0,
            "platform_principal_role_assignments": 0,
            "provisioning_appointment_subject_ineligible": 0,
            "reserved_executive_board_bundle_mismatch": 6,
            "reserved_executive_board_cardinality": 0,
            "stray_active_executive_board_membership": 2,
            "suspended_representation_organization_not_suspended": 0,
            "unlinked_live_executive_board_assignments": 2,
        }
        assert report["blocked_organization_count"] == 18
        assert "Sensitive" not in rendered
        assert str(unrelated_approver.id) not in rendered
        assert unrelated_approver.email not in rendered
    finally:
        try:
            if historical_apps is not None:
                _remove_legacy_readiness_fixtures(historical_apps)
        finally:
            _migrate(ORGANIZATIONS_AFTER_HARDENING)


def test_report_caps_sorted_organization_slugs_at_twenty() -> None:
    for number in reversed(range(25)):
        OrganizationFactory(
            slug=f"blocked-{number:02d}",
            lifecycle=Organization.Lifecycle.SUSPENDED,
        )

    _, report = _run_readiness_command()

    assert report["blocked_organization_count"] == 25
    assert report["organization_slugs"] == [
        f"blocked-{number:02d}" for number in range(20)
    ]
    assert report["organization_slugs_truncated"] is True


def test_command_emits_report_then_fails_when_blockers_exist() -> None:
    OrganizationFactory(
        slug="deployment-blocker",
        lifecycle=Organization.Lifecycle.CLOSED,
    )
    output = StringIO()

    with pytest.raises(
        CommandError,
        match="Representation readiness blockers detected",
    ):
        call_command("check_representation_readiness", stdout=output)

    report = json.loads(output.getvalue())
    assert report["status"] == "blocked"
    assert report["organization_slugs"] == ["deployment-blocker"]
