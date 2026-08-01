"""Focused ADR 0044 issuance-writer and initial Board provenance coverage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.issuance import (
    create_delegated_grant_issuance,
    create_executive_board_issuance,
    create_persistent_dual_control_issuance,
)
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.effects.models import DomainEvent, OutboxMessage
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationRepresentation,
    RepresentationAppointment,
)
from maru.organizations.representation import (
    EXECUTIVE_BOARD_ROLE_CODE,
    activate_executive_board,
    invite_representation_controller,
    provision_executive_board,
    respond_to_representation_invitation,
)
from tests.factories import AccountFactory, OrganizationFactory

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _accepted_board(
    *,
    controller_count: int = 2,
) -> tuple[
    Account,
    Organization,
    OrganizationRepresentation,
    tuple[RepresentationAppointment, ...],
]:
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason="Establish synthetic provenance coverage.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    appointments = []
    for _index in range(controller_count):
        controller = AccountFactory()
        appointment = invite_representation_controller(
            actor=administrator,
            representation_id=representation.id,
            account_id=controller.id,
            reason="Invite a synthetic provenance controller.",
            correlation_id=uuid4(),
            source_channel="test",
        )
        appointments.append(
            respond_to_representation_invitation(
                actor=controller,
                appointment_id=appointment.id,
                expected_version=appointment.invitation_version,
                accept=True,
                correlation_id=uuid4(),
                source_channel="test",
            )
        )
    representation.refresh_from_db()
    return administrator, organization, representation, tuple(appointments)


def _activate_board(
    *,
    controller_count: int = 2,
) -> tuple[
    Account,
    OrganizationRepresentation,
    list[RepresentationAppointment],
    RoleBundle,
]:
    administrator, _organization, representation, _appointments = _accepted_board(
        controller_count=controller_count
    )
    result = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate exact synthetic provenance.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    active_appointments = list(
        RepresentationAppointment.objects.filter(representation=result.representation)
        .select_related("account", "role_assignment")
        .order_by("responded_at", "id")
    )
    bundle = RoleBundle.objects.get(
        organization=result.organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    )
    return administrator, result.representation, active_appointments, bundle


def _control(
    issuance: AuthorityIssuance,
    role: str,
) -> AuthorityControl:
    return AuthorityControl.objects.select_related(
        "principal",
        "source_issuance",
        "representation",
        "appointment",
    ).get(issuance=issuance, role=role)


def test_initial_board_records_exact_non_cyclic_ceremony_provenance() -> None:
    administrator, representation, appointments, bundle = _activate_board(
        controller_count=3
    )

    bundle_issuance = AuthorityIssuance.objects.get(role_bundle=bundle)
    bundle_actor = _control(bundle_issuance, AuthorityControl.Role.ACTOR)
    bundle_approver = _control(bundle_issuance, AuthorityControl.Role.APPROVER)
    assert bundle_actor.principal == administrator
    assert bundle_actor.basis == (
        AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP
    )
    assert bundle_actor.representation == representation
    assert bundle_actor.source_issuance_id is None
    assert bundle_approver.principal_id == appointments[0].account_id
    assert bundle_approver.basis == AuthorityControl.Basis.REPRESENTATION_ACCEPTANCE
    assert bundle_approver.appointment_id == appointments[0].id
    assert bundle_approver.source_issuance_id is None

    issuance_ordinals = {bundle_issuance.ordinal}
    for index, appointment in enumerate(appointments):
        assert appointment.role_assignment_id is not None
        assignment = RoleAssignment.objects.get(id=appointment.role_assignment_id)
        issuance = AuthorityIssuance.objects.get(role_assignment=assignment)
        issuance_ordinals.add(issuance.ordinal)
        actor_control = _control(issuance, AuthorityControl.Role.ACTOR)
        approver_control = _control(issuance, AuthorityControl.Role.APPROVER)
        expected_approver = appointments[(index + 1) % len(appointments)]
        assert actor_control.principal == administrator
        assert actor_control.representation == representation
        assert actor_control.basis == (
            AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP
        )
        assert approver_control.principal_id == expected_approver.account_id
        assert approver_control.appointment_id == expected_approver.id
        assert approver_control.principal_id != assignment.principal_id
        assert approver_control.basis == (
            AuthorityControl.Basis.REPRESENTATION_ACCEPTANCE
        )
        assert issuance.evaluated_at == representation.activated_at
        assert actor_control.policy_version == POLICY_VERSION
        assert approver_control.policy_version == POLICY_VERSION

    assert len(issuance_ordinals) == len(appointments) + 1
    assert not AuthorityControl.objects.filter(source_issuance__isnull=False).exists()


def test_board_provenance_rolls_back_with_activation_publication_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator, organization, representation, _appointments = _accepted_board()

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic provenance publication failure")

    monkeypatch.setattr(
        "maru.organizations.representation.publish_domain_event",
        fail_publication,
    )
    with pytest.raises(RuntimeError, match="synthetic provenance"):
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Rollback provenance with the aggregate.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    organization.refresh_from_db()
    representation.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert representation.state == OrganizationRepresentation.State.PROVISIONING
    assert not AuthorityIssuance.objects.exists()
    assert not AuthorityControl.objects.exists()
    assert not RoleBundle.objects.filter(organization=organization).exists()
    assert not RoleAssignment.objects.filter(organization=organization).exists()
    assert not DomainEvent.objects.filter(
        aggregate_id=representation.id,
        aggregate_version=representation.aggregate_version + 1,
    ).exists()


def test_board_issuance_failure_rolls_back_every_activation_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator, organization, representation, _appointments = _accepted_board()
    baseline_evidence = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )
    calls = 0

    def fail_after_bundle(
        *,
        target: RoleBundle | RoleAssignment,
        representation: OrganizationRepresentation,
        actor: Account,
        approver_appointment: RepresentationAppointment,
        evaluated_at: datetime,
    ) -> AuthorityIssuance:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValidationError(
                "Synthetic provenance control failure.",
                code="synthetic_provenance_failure",
            )
        return create_executive_board_issuance(
            target=target,
            representation=representation,
            actor=actor,
            approver_appointment=approver_appointment,
            evaluated_at=evaluated_at,
        )

    monkeypatch.setattr(
        "maru.organizations.representation.create_executive_board_issuance",
        fail_after_bundle,
    )
    with pytest.raises(ValidationError) as captured:
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Roll back an incomplete issuance ceremony.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert captured.value.code == "synthetic_provenance_failure"
    organization.refresh_from_db()
    representation.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert representation.state == OrganizationRepresentation.State.PROVISIONING
    assert not RoleBundle.objects.filter(organization=organization).exists()
    assert not RoleAssignment.objects.filter(organization=organization).exists()
    assert not AuthorityIssuance.objects.exists()
    assert not AuthorityControl.objects.exists()
    assert baseline_evidence == (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )


def test_board_writer_rejects_a_foreign_acceptance_without_partial_evidence() -> None:
    administrator, representation, _appointments, bundle = _activate_board()
    foreign_administrator, _organization, foreign_representation, appointments = (
        _accepted_board()
    )
    del foreign_administrator, foreign_representation
    counts = (AuthorityIssuance.objects.count(), AuthorityControl.objects.count())
    assert representation.activated_at is not None

    with pytest.raises(ValidationError) as captured:
        create_executive_board_issuance(
            target=bundle,
            representation=representation,
            actor=administrator,
            approver_appointment=appointments[0],
            evaluated_at=representation.activated_at,
        )

    assert captured.value.code == "representation_acceptance_mismatch"
    assert counts == (
        AuthorityIssuance.objects.count(),
        AuthorityControl.objects.count(),
    )


def test_public_issuance_writers_reject_malformed_ceremonies_without_evidence() -> None:
    administrator, representation, appointments, board_bundle = _activate_board()
    actor = appointments[0].account
    approver = appointments[1].account
    actor_source = AuthorityIssuance.objects.get(
        role_assignment=appointments[0].role_assignment_id
    )
    approver_source = AuthorityIssuance.objects.get(
        role_assignment=appointments[1].role_assignment_id
    )
    organization = representation.organization
    evaluated_at = timezone.now()
    baseline_issuances = AuthorityIssuance.objects.count()

    def assert_code(expected: str, operation: Callable[[], object]) -> None:
        with pytest.raises(ValidationError) as captured:
            operation()
        assert captured.value.code == expected
        assert AuthorityIssuance.objects.count() == baseline_issuances

    stale_bundle = RoleBundle(
        id=uuid4(),
        organization=organization,
        code="deleted-before-provenance",
        name="Deleted before provenance",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=actor,
        approved_by=approver,
        reason="Exercise unavailable target handling.",
    )
    assert_code(
        "authority_target_unavailable",
        lambda: create_persistent_dual_control_issuance(
            target=stale_bundle,
            actor_source=actor_source,
            approver_source=approver_source,
        ),
    )

    unattributed = RoleBundle.objects.create(
        organization=organization,
        code="unattributed-role",
        name="Unattributed role",
        version=1,
        capability_codes=["events.view_basic"],
        reason="Exercise missing dual-control attribution.",
    )
    assert_code(
        "distinct_authority_controls_required",
        lambda: create_persistent_dual_control_issuance(
            target=unattributed,
            actor_source=actor_source,
            approver_source=approver_source,
        ),
    )

    self_approved_recipient = AccountFactory()
    self_approved = CapabilityGrant.objects.create(
        organization=organization,
        principal=self_approved_recipient,
        capability_code="organizations.view_basic",
        effective_from=evaluated_at,
        granted_by=actor,
        approved_by=self_approved_recipient,
        reason="Exercise recipient self-approval refusal.",
    )
    assert_code(
        "recipient_cannot_approve",
        lambda: create_persistent_dual_control_issuance(
            target=self_approved,
            actor_source=actor_source,
            approver_source=approver_source,
        ),
    )

    direct = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code="organizations.view_basic",
        effective_from=evaluated_at,
        granted_by=actor,
        approved_by=approver,
        reason="Exercise the delegated-only writer boundary.",
    )
    assert_code(
        "delegated_parent_required",
        lambda: create_delegated_grant_issuance(grant=direct),
    )
    assert_code(
        "delegated_grant_target_required",
        lambda: create_delegated_grant_issuance(grant=unattributed),  # type: ignore[arg-type]
    )
    delegated = CapabilityGrant.objects.create(
        organization=organization,
        principal=AccountFactory(),
        capability_code=direct.capability_code,
        effective_from=evaluated_at,
        granted_by=direct.principal,
        delegated_from=direct,
        reason="Exercise exact delegated-parent provenance.",
    )
    assert_code(
        "delegated_parent_provenance_invalid",
        lambda: create_delegated_grant_issuance(grant=delegated),
    )
    assert_code(
        "delegated_grant_dual_control_forbidden",
        lambda: create_persistent_dual_control_issuance(
            target=delegated,
            actor_source=actor_source,
            approver_source=approver_source,
        ),
    )

    assert representation.activated_at is not None
    assert_code(
        "platform_representation_bootstrap_mismatch",
        lambda: create_executive_board_issuance(
            target=board_bundle,
            representation=representation,
            actor=administrator,
            approver_appointment=appointments[0],
            evaluated_at=representation.activated_at + timedelta(microseconds=1),
        ),
    )
    non_board = RoleBundle.objects.create(
        organization=organization,
        code="not-the-board",
        name="Not the Board",
        version=1,
        capability_codes=["events.view_basic"],
        created_by=administrator,
        approved_by=appointments[0].account,
        reason="Exercise reserved Board provenance.",
    )
    assert_code(
        "executive_board_authority_target_mismatch",
        lambda: create_executive_board_issuance(
            target=non_board,
            representation=representation,
            actor=administrator,
            approver_appointment=appointments[0],
            evaluated_at=representation.activated_at,
        ),
    )
    missing_representation = OrganizationRepresentation(id=uuid4())
    assert_code(
        "executive_board_evidence_unavailable",
        lambda: create_executive_board_issuance(
            target=non_board,
            representation=missing_representation,
            actor=administrator,
            approver_appointment=appointments[0],
            evaluated_at=representation.activated_at,
        ),
    )
    assert_code(
        "executive_board_authority_target_required",
        lambda: create_executive_board_issuance(
            target=direct,  # type: ignore[arg-type]
            representation=representation,
            actor=administrator,
            approver_appointment=appointments[0],
            evaluated_at=representation.activated_at,
        ),
    )


def test_persistent_and_delegated_writers_pin_exact_existing_lineage() -> None:
    _administrator, representation, appointments, _bundle = _activate_board()
    actor = appointments[0].account
    approver = appointments[1].account
    recipient = AccountFactory()
    actor_source = AuthorityIssuance.objects.get(
        role_assignment=appointments[0].role_assignment_id
    )
    approver_source = AuthorityIssuance.objects.get(
        role_assignment=appointments[1].role_assignment_id
    )
    evaluated_at = timezone.now()

    with transaction.atomic():
        root = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=recipient,
            capability_code="organizations.view_basic",
            effective_from=evaluated_at,
            granted_by=actor,
            approved_by=approver,
            reason="Create exact synthetic persistent provenance.",
        )
        root_issuance = create_persistent_dual_control_issuance(
            target=root,
            actor_source=actor_source,
            approver_source=approver_source,
            evaluated_at=evaluated_at,
        )
        delegated = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=AccountFactory(),
            capability_code=root.capability_code,
            effective_from=evaluated_at,
            granted_by=recipient,
            delegated_from=root,
            reason="Delegate exact synthetic authority.",
        )
        delegated_issuance = create_delegated_grant_issuance(
            grant=delegated,
            evaluated_at=evaluated_at,
        )

    root_controls = {
        control.role: control
        for control in AuthorityControl.objects.filter(issuance=root_issuance)
    }
    assert root_controls[AuthorityControl.Role.ACTOR].source_issuance == actor_source
    assert (
        root_controls[AuthorityControl.Role.APPROVER].source_issuance == approver_source
    )
    assert {control.basis for control in root_controls.values()} == {
        AuthorityControl.Basis.PERSISTENT_AUTHORITY
    }
    assert not AuthorityControl.objects.filter(issuance=delegated_issuance).exists()
    assert delegated.delegated_from == root


def test_bounded_sources_can_create_an_immutable_role_definition() -> None:
    """Role definitions retain creation evidence, not an authority lifetime."""

    _administrator, representation, appointments, _bundle = _activate_board()
    actor = appointments[0].account
    approver = appointments[1].account
    actor_board_source = AuthorityIssuance.objects.get(
        role_assignment=appointments[0].role_assignment_id
    )
    approver_board_source = AuthorityIssuance.objects.get(
        role_assignment=appointments[1].role_assignment_id
    )
    evaluated_at = timezone.now()
    expires_at = evaluated_at + timedelta(days=1)

    with transaction.atomic():
        actor_grant = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=actor,
            capability_code="authorization.manage_roles",
            effective_from=evaluated_at,
            expires_at=expires_at,
            granted_by=actor,
            approved_by=approver,
            reason="Bound the actor's synthetic role-management authority.",
        )
        actor_grant_issuance = create_persistent_dual_control_issuance(
            target=actor_grant,
            actor_source=actor_board_source,
            approver_source=approver_board_source,
            evaluated_at=evaluated_at,
        )
        approver_grant = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=approver,
            capability_code="authorization.manage_roles",
            effective_from=evaluated_at,
            expires_at=expires_at,
            granted_by=approver,
            approved_by=actor,
            reason="Bound the approver's synthetic role-management authority.",
        )
        approver_grant_issuance = create_persistent_dual_control_issuance(
            target=approver_grant,
            actor_source=approver_board_source,
            approver_source=actor_board_source,
            evaluated_at=evaluated_at,
        )
        role_bundle = RoleBundle.objects.create(
            organization=representation.organization,
            code="bounded-role-definition",
            name="Bounded-source role definition",
            version=1,
            capability_codes=["organizations.view_basic"],
            created_by=actor,
            approved_by=approver,
            reason="Prove creation-time provenance is independent of source expiry.",
        )
        role_issuance = create_persistent_dual_control_issuance(
            target=role_bundle,
            actor_source=actor_grant_issuance,
            approver_source=approver_grant_issuance,
            evaluated_at=evaluated_at,
        )

    controls = {
        control.role: control
        for control in AuthorityControl.objects.filter(issuance=role_issuance)
    }
    assert controls[AuthorityControl.Role.ACTOR].source_issuance == (
        actor_grant_issuance
    )
    assert controls[AuthorityControl.Role.APPROVER].source_issuance == (
        approver_grant_issuance
    )


def test_persistent_writer_rejects_a_source_owned_by_the_other_controller() -> None:
    _administrator, representation, appointments, _bundle = _activate_board()
    actor = appointments[0].account
    approver = appointments[1].account
    recipient = AccountFactory()
    approver_source = AuthorityIssuance.objects.get(
        role_assignment=appointments[1].role_assignment_id
    )
    before = AuthorityIssuance.objects.count()

    with transaction.atomic():
        target = CapabilityGrant.objects.create(
            organization=representation.organization,
            principal=recipient,
            capability_code="organizations.view_basic",
            effective_from=timezone.now(),
            granted_by=actor,
            approved_by=approver,
            reason="Reject a mismatched synthetic source.",
        )
        with pytest.raises(ValidationError) as captured:
            create_persistent_dual_control_issuance(
                target=target,
                actor_source=approver_source,
                approver_source=approver_source,
            )
        transaction.set_rollback(True)

    assert captured.value.code == "authority_source_principal_mismatch"
    assert AuthorityIssuance.objects.count() == before
