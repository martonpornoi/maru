from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import F
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.authorization.policy import ResourceScope, decide
from maru.effects.models import DomainEvent, OutboxMessage
from maru.identity.models import Account
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
    OrganizationMembershipFactory,
    RepresentationAppointmentFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _platform_administrator(*, is_active: bool = True) -> Account:
    return AccountFactory(
        is_active=is_active,
        is_staff=True,
        is_superuser=True,
    )


def _field_error_code(error: ValidationError, field: str) -> str | None:
    return error.error_dict[field][0].code


def _provision(
    *,
    administrator: Account,
    organization: Organization,
    reason: str = "Establish accountable synthetic governance.",
    correlation_id: UUID | None = None,
) -> OrganizationRepresentation:
    return provision_executive_board(
        actor=administrator,
        organization_id=organization.id,
        reason=reason,
        correlation_id=correlation_id or uuid4(),
        source_channel="test",
    )


def _invite(
    *,
    administrator: Account,
    representation: OrganizationRepresentation,
    account: Account,
    reason: str = "Invite a synthetic accountable controller.",
    correlation_id: UUID | None = None,
) -> RepresentationAppointment:
    return invite_representation_controller(
        actor=administrator,
        representation_id=representation.id,
        account_id=account.id,
        reason=reason,
        correlation_id=correlation_id or uuid4(),
        source_channel="test",
    )


def _accept(
    appointment: RepresentationAppointment,
    *,
    correlation_id: UUID | None = None,
) -> RepresentationAppointment:
    return respond_to_representation_invitation(
        actor=appointment.account,
        appointment_id=appointment.id,
        expected_version=appointment.invitation_version,
        accept=True,
        correlation_id=correlation_id or uuid4(),
        source_channel="test",
    )


def _accepted_board(
    *,
    administrator: Account | None = None,
    organization: Organization | None = None,
) -> tuple[
    Account,
    Organization,
    OrganizationRepresentation,
    tuple[RepresentationAppointment, RepresentationAppointment],
]:
    actor = administrator or _platform_administrator()
    parent = organization or OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=actor,
        organization=parent,
    )
    appointments = tuple(
        _accept(
            _invite(
                administrator=actor,
                representation=representation,
                account=AccountFactory(),
            )
        )
        for _ in range(2)
    )
    representation.refresh_from_db()
    return actor, parent, representation, appointments


def _all_validation_codes(error: ValidationError) -> set[str | None]:
    if hasattr(error, "error_dict"):
        return {item.code for errors in error.error_dict.values() for item in errors}
    return {item.code for item in error.error_list}


def test_complete_executive_board_journey_activates_two_human_controllers() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    reasons = {
        "provision-secret": uuid4(),
        "invite-first-secret": uuid4(),
        "invite-second-secret": uuid4(),
        "accept-first": uuid4(),
        "accept-second": uuid4(),
        "activation-secret": uuid4(),
    }

    representation = _provision(
        administrator=administrator,
        organization=organization,
        reason="provision-secret",
        correlation_id=reasons["provision-secret"],
    )
    people = (AccountFactory(), AccountFactory())
    appointments = tuple(
        _invite(
            administrator=administrator,
            representation=representation,
            account=person,
            reason=reason,
            correlation_id=reasons[reason],
        )
        for person, reason in zip(
            people,
            ("invite-first-secret", "invite-second-secret"),
            strict=True,
        )
    )
    appointments = tuple(
        _accept(appointment, correlation_id=reasons[correlation_key])
        for appointment, correlation_key in zip(
            appointments,
            ("accept-first", "accept-second"),
            strict=True,
        )
    )
    representation.refresh_from_db()

    result = activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="activation-secret",
        correlation_id=reasons["activation-secret"],
        source_channel="test",
    )

    organization.refresh_from_db()
    result.representation.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.ACTIVE
    assert result.representation.state == OrganizationRepresentation.State.ACTIVE
    assert result.representation.aggregate_version == 6
    assert result.representation.activated_by == administrator
    assert result.representation.activation_reason == "activation-secret"

    active_appointments = list(
        RepresentationAppointment.objects.filter(
            representation=result.representation,
        ).select_related("role_assignment")
    )
    assert {appointment.account_id for appointment in active_appointments} == {
        person.id for person in people
    }
    assert all(
        appointment.state == RepresentationAppointment.State.ACTIVE
        and appointment.role_assignment_id is not None
        and appointment.invitation_version == 3
        for appointment in active_appointments
    )
    memberships = OrganizationMembership.objects.filter(organization=organization)
    assert set(memberships.values_list("account_id", flat=True)) == {
        person.id for person in people
    }
    assert set(memberships.values_list("state", flat=True)) == {
        OrganizationMembership.State.ACTIVE
    }

    bundle = RoleBundle.objects.get(
        organization=organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    )
    assert bundle.capability_codes == list(EXECUTIVE_BOARD_CAPABILITIES)
    assignments = list(
        RoleAssignment.objects.filter(role_bundle=bundle).order_by("principal_id")
    )
    assert {assignment.principal_id for assignment in assignments} == {
        person.id for person in people
    }
    assert all(assignment.edition_id is None for assignment in assignments)
    assert all(
        assignment.approved_by_id in {person.id for person in people}
        and assignment.approved_by_id != assignment.principal_id
        for assignment in assignments
    )

    assert not OrganizationMembership.objects.filter(
        organization=organization,
        account=administrator,
    ).exists()
    assert not RepresentationAppointment.objects.filter(
        representation=result.representation,
        account=administrator,
    ).exists()
    assert not RoleAssignment.objects.filter(
        organization=organization,
        principal=administrator,
    ).exists()

    for controller in people:
        for capability_code in EXECUTIVE_BOARD_CAPABILITIES:
            assert decide(
                principal=controller,
                capability_code=capability_code,
                resource=ResourceScope(organization_id=organization.id),
            ).allowed, capability_code
        assert not decide(
            principal=controller,
            capability_code="organizations.change_profile",
            resource=ResourceScope(organization_id=OrganizationFactory().id),
        ).allowed

    events = list(
        DomainEvent.objects.filter(
            aggregate_type="organizations.organization_representation",
            aggregate_id=result.representation.id,
        ).order_by("aggregate_version")
    )
    assert [event.aggregate_version for event in events] == [1, 2, 3, 4, 5, 6]
    assert [event.payload["action"] for event in events] == [
        "provisioned",
        "controller_invited",
        "controller_invited",
        "controller_accepted",
        "controller_accepted",
        "activated",
    ]
    assert OutboxMessage.objects.filter(event__in=events).count() == len(events)
    assert set(
        OutboxMessage.objects.filter(event__in=events).values_list(
            "workload_pool", flat=True
        )
    ) == {"core"}
    for event in events:
        assert AuditEvent.objects.filter(
            id=event.causation_id,
            correlation_id=event.correlation_id,
            outcome=AuditEvent.Outcome.ALLOW,
        ).exists()

    audits = AuditEvent.objects.filter(organization_id=organization.id)
    assert audits.count() == 8
    evidence_text = "|".join(
        [
            str(
                (
                    audit.operation,
                    audit.reason_code,
                    audit.changed_fields,
                    audit.safe_metadata,
                )
            )
            for audit in audits
        ]
        + [str(event.payload) for event in events]
    )
    for secret_reason in (
        "provision-secret",
        "invite-first-secret",
        "invite-second-secret",
        "activation-secret",
    ):
        assert secret_reason not in evidence_text


@pytest.mark.parametrize(
    "lifecycle",
    [
        Organization.Lifecycle.ACTIVE,
        Organization.Lifecycle.SUSPENDED,
        Organization.Lifecycle.CLOSED,
    ],
)
def test_provision_requires_active_platform_admin_and_draft_parent(
    lifecycle: str,
) -> None:
    organization = OrganizationFactory(lifecycle=lifecycle)
    ordinary = AccountFactory()
    inactive_administrator = _platform_administrator(is_active=False)

    with pytest.raises(PermissionDenied):
        _provision(administrator=ordinary, organization=organization)
    with pytest.raises(PermissionDenied):
        _provision(
            administrator=inactive_administrator,
            organization=organization,
        )
    with pytest.raises(ValidationError) as captured:
        _provision(
            administrator=_platform_administrator(),
            organization=organization,
        )

    assert captured.value.code == "representation_parent_not_draft"
    assert not OrganizationRepresentation.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_provisioning_is_not_silently_replayed() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    evidence_counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(ValidationError) as captured:
        _provision(
            administrator=administrator,
            organization=organization,
            reason="A different replay reason must not be accepted.",
        )

    assert captured.value.code == "representation_exists"
    assert OrganizationRepresentation.objects.get() == representation
    assert (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == evidence_counts


@pytest.mark.parametrize("reason", ["", "   ", "x" * 241])
def test_representation_reason_is_required_and_bounded(reason: str) -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)

    with pytest.raises(ValidationError) as captured:
        _provision(
            administrator=administrator,
            organization=organization,
            reason=reason,
        )

    assert _field_error_code(captured.value, "reason") in {
        "reason_required",
        "reason_too_long",
    }
    assert not OrganizationRepresentation.objects.exists()
    assert not AuditEvent.objects.exists()
    assert not DomainEvent.objects.exists()
    assert not OutboxMessage.objects.exists()


def test_ended_board_membership_can_be_reinvited_without_stale_dates() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    ended_at = timezone.now()
    membership = OrganizationMembershipFactory(
        organization=organization,
        state=OrganizationMembership.State.ENDED,
        relationship_label="Executive Board controller",
        started_at=ended_at,
        ended_at=ended_at,
    )

    appointment = _invite(
        administrator=administrator,
        representation=representation,
        account=membership.account,
    )

    membership.refresh_from_db()
    assert appointment.state == RepresentationAppointment.State.INVITED
    assert membership.state == OrganizationMembership.State.INVITED
    assert membership.relationship_label == "Executive Board controller"
    assert membership.started_at is None
    assert membership.ended_at is None


@pytest.mark.parametrize(
    "account_attributes",
    [
        {"is_active": False},
        {"email_verified_at": None},
        {"is_staff": True, "is_superuser": True},
    ],
)
def test_invitation_rejects_ineligible_and_platform_accounts(
    account_attributes: dict[str, object],
) -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    account = AccountFactory(**account_attributes)
    version = representation.aggregate_version
    evidence_counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(ValidationError) as captured:
        _invite(
            administrator=administrator,
            representation=representation,
            account=account,
        )

    assert _field_error_code(captured.value, "account") == (
        "representation_account_ineligible"
    )
    representation.refresh_from_db()
    assert representation.aggregate_version == version
    assert not RepresentationAppointment.objects.exists()
    assert not OrganizationMembership.objects.exists()
    assert not RoleAssignment.objects.filter(principal=account).exists()
    assert (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == evidence_counts


def test_invitation_requires_authority_and_rejects_duplicate_open_term() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    person = AccountFactory()

    with pytest.raises(PermissionDenied):
        _invite(
            administrator=AccountFactory(),
            representation=representation,
            account=person,
        )
    appointment = _invite(
        administrator=administrator,
        representation=representation,
        account=person,
    )
    representation.refresh_from_db()
    version = representation.aggregate_version
    evidence_counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(ValidationError) as captured:
        _invite(
            administrator=administrator,
            representation=representation,
            account=person,
        )

    assert _field_error_code(captured.value, "account") == (
        "representation_appointment_exists"
    )
    representation.refresh_from_db()
    assert representation.aggregate_version == version
    assert RepresentationAppointment.objects.get() == appointment
    assert (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == evidence_counts


def test_invitation_response_is_exact_account_versioned_and_not_replayable() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    appointment = _invite(
        administrator=administrator,
        representation=representation,
        account=AccountFactory(),
    )
    other_account = AccountFactory()

    with pytest.raises(RepresentationAppointment.DoesNotExist):
        respond_to_representation_invitation(
            actor=other_account,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
        )
    with pytest.raises(RepresentationAppointment.DoesNotExist):
        respond_to_representation_invitation(
            actor=other_account,
            appointment_id=uuid4(),
            expected_version=appointment.invitation_version,
            accept=True,
            correlation_id=uuid4(),
        )
    with pytest.raises(ValidationError) as stale:
        respond_to_representation_invitation(
            actor=appointment.account,
            appointment_id=appointment.id,
            expected_version=appointment.invitation_version + 1,
            accept=True,
            correlation_id=uuid4(),
        )
    assert stale.value.code == "stale_representation_invitation"

    accepted = _accept(appointment)
    assert accepted.state == RepresentationAppointment.State.ACCEPTED
    assert accepted.invitation_version == 2
    evidence_counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    with pytest.raises(ValidationError) as stale_replay:
        respond_to_representation_invitation(
            actor=appointment.account,
            appointment_id=appointment.id,
            expected_version=1,
            accept=True,
            correlation_id=uuid4(),
        )
    assert stale_replay.value.code == "stale_representation_invitation"
    with pytest.raises(ValidationError) as answered_replay:
        respond_to_representation_invitation(
            actor=appointment.account,
            appointment_id=appointment.id,
            expected_version=2,
            accept=True,
            correlation_id=uuid4(),
        )
    assert answered_replay.value.code == "representation_invitation_answered"
    assert (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == evidence_counts


def test_activation_requires_current_version_two_eligible_acceptances_and_draft() -> (
    None
):
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    first = _accept(
        _invite(
            administrator=administrator,
            representation=representation,
            account=AccountFactory(),
        )
    )
    representation.refresh_from_db()

    with pytest.raises(ValidationError) as incomplete:
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Too early.",
            correlation_id=uuid4(),
        )
    assert incomplete.value.code == "representation_controllers_incomplete"

    second = _accept(
        _invite(
            administrator=administrator,
            representation=representation,
            account=AccountFactory(),
        )
    )
    representation.refresh_from_db()
    with pytest.raises(ValidationError) as stale:
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version - 1,
            reason="Stale page.",
            correlation_id=uuid4(),
        )
    assert stale.value.code == "stale_representation"

    second.account.is_active = False
    second.account.save(update_fields=("is_active",))
    with pytest.raises(ValidationError) as ineligible:
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Ineligible controller.",
            correlation_id=uuid4(),
        )
    assert ineligible.value.code == "representation_controller_ineligible"
    second.account.is_active = True
    second.account.save(update_fields=("is_active",))

    Organization.objects.filter(id=organization.id).update(
        lifecycle=Organization.Lifecycle.SUSPENDED
    )
    with pytest.raises(ValidationError) as wrong_lifecycle:
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Wrong organization lifecycle.",
            correlation_id=uuid4(),
        )
    assert wrong_lifecycle.value.code == "representation_parent_not_draft"

    assert {first.state, second.state} == {RepresentationAppointment.State.ACCEPTED}
    assert not RoleBundle.objects.filter(
        organization=organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    ).exists()
    assert not RoleAssignment.objects.filter(organization=organization).exists()


def test_activation_rejects_unanswered_extra_invitation() -> None:
    administrator, organization, representation, _appointments = _accepted_board()
    _invite(
        administrator=administrator,
        representation=representation,
        account=AccountFactory(),
    )
    representation.refresh_from_db()

    with pytest.raises(ValidationError) as captured:
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Do not strand an invitation.",
            correlation_id=uuid4(),
        )

    assert captured.value.code == "representation_invitations_pending"
    organization.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert not RoleAssignment.objects.filter(organization=organization).exists()


def test_invitation_publication_failure_rolls_back_relationship_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    baseline_counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic private invite publication failure")

    monkeypatch.setattr(
        "maru.organizations.representation.publish_domain_event",
        fail_publication,
    )
    with pytest.raises(RuntimeError, match="synthetic private"):
        _invite(
            administrator=administrator,
            representation=representation,
            account=AccountFactory(),
        )

    representation.refresh_from_db()
    assert representation.aggregate_version == 1
    assert not RepresentationAppointment.objects.exists()
    assert not OrganizationMembership.objects.exists()
    assert (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == baseline_counts


def test_activation_publication_failure_rolls_back_every_authority_side_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator, organization, representation, appointments = _accepted_board()
    baseline_counts = (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    )

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic private activation publication failure")

    monkeypatch.setattr(
        "maru.organizations.representation.publish_domain_event",
        fail_publication,
    )
    with pytest.raises(RuntimeError, match="synthetic private"):
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Rollback all authority.",
            correlation_id=uuid4(),
        )

    organization.refresh_from_db()
    representation.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert representation.state == OrganizationRepresentation.State.PROVISIONING
    assert representation.aggregate_version == 5
    assert not RoleBundle.objects.filter(organization=organization).exists()
    assert not RoleAssignment.objects.filter(organization=organization).exists()
    assert set(
        RepresentationAppointment.objects.filter(
            id__in=[appointment.id for appointment in appointments]
        ).values_list("state", flat=True)
    ) == {RepresentationAppointment.State.ACCEPTED}
    assert set(
        OrganizationMembership.objects.filter(organization=organization).values_list(
            "state", flat=True
        )
    ) == {OrganizationMembership.State.INVITED}
    assert (
        AuditEvent.objects.count(),
        DomainEvent.objects.count(),
        OutboxMessage.objects.count(),
    ) == baseline_counts


def test_database_guards_open_term_platform_subject_and_raw_activation() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    appointment = _invite(
        administrator=administrator,
        representation=representation,
        account=AccountFactory(),
    )

    with transaction.atomic(), pytest.raises(IntegrityError):
        RepresentationAppointment.objects.bulk_create(
            [
                RepresentationAppointment(
                    representation=representation,
                    account=appointment.account,
                    invited_by=administrator,
                    invited_at=timezone.now(),
                    reason="Duplicate raw open term.",
                )
            ]
        )

    with transaction.atomic(), pytest.raises(IntegrityError):
        RepresentationAppointment.objects.bulk_create(
            [
                RepresentationAppointment(
                    representation=representation,
                    account=administrator,
                    invited_by=administrator,
                    invited_at=timezone.now(),
                    reason="Forbidden raw platform appointment.",
                )
            ]
        )

    with transaction.atomic(), pytest.raises(IntegrityError):
        Organization.objects.filter(id=organization.id).update(
            lifecycle=Organization.Lifecycle.ACTIVE
        )


def test_model_rejects_cross_account_or_cross_tenant_representation_assignment() -> (
    None
):
    appointment = RepresentationAppointmentFactory()
    foreign_bundle = RoleBundleFactory()
    foreign_assignment = RoleAssignmentFactory(
        role_bundle=foreign_bundle,
        principal=appointment.account,
    )
    appointment.state = RepresentationAppointment.State.ACTIVE
    appointment.responded_at = timezone.now()
    appointment.activated_at = timezone.now()
    appointment.role_assignment = foreign_assignment

    with pytest.raises(ValidationError) as captured:
        appointment.save()

    assert "representation_assignment_scope_mismatch" in _all_validation_codes(
        captured.value
    )


def test_suspended_membership_cannot_be_reactivated_by_board_invitation() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    membership = OrganizationMembershipFactory(
        organization=organization,
        state=OrganizationMembership.State.SUSPENDED,
    )

    with pytest.raises(ValidationError) as captured:
        _invite(
            administrator=administrator,
            representation=representation,
            account=membership.account,
        )

    assert _field_error_code(captured.value, "account") == (
        "representation_membership_suspended"
    )
    membership.refresh_from_db()
    assert membership.state == OrganizationMembership.State.SUSPENDED
    assert not RepresentationAppointment.objects.filter(
        representation=representation,
        account=membership.account,
    ).exists()


def _activate_board(
    *,
    administrator: Account,
    representation: OrganizationRepresentation,
) -> None:
    representation.refresh_from_db()
    activate_executive_board(
        actor=administrator,
        representation_id=representation.id,
        expected_version=representation.aggregate_version,
        reason="Activate synthetic reviewed governance.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _check_and_redefer_constraints() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def _force_deferred_constraints() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_database_freezes_representation_scope_provenance_and_versions() -> None:
    administrator = _platform_administrator()
    other_administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    foreign_organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match="organization representation identity is immutable",
        ),
    ):
        OrganizationRepresentation.objects.filter(pk=representation.pk).update(
            organization_id=foreign_organization.id
        )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match="organization representation identity is immutable",
        ),
    ):
        OrganizationRepresentation.objects.filter(pk=representation.pk).update(
            provisioned_by_id=other_administrator.id
        )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match="invalid organization representation aggregate version",
        ),
    ):
        OrganizationRepresentation.objects.filter(pk=representation.pk).update(
            aggregate_version=F("aggregate_version") + 2
        )

    representation.refresh_from_db()
    assert representation.organization_id == organization.id
    assert representation.provisioned_by_id == administrator.id
    assert representation.aggregate_version == 1


def test_database_forbids_raw_platform_role_assignment_bulk_insert() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory()
    role = RoleBundleFactory(
        organization=organization,
        capability_codes=["events.view_basic"],
    )

    with (
        transaction.atomic(),
        pytest.raises(
            IntegrityError,
            match="platform accounts cannot receive convention roles",
        ),
    ):
        RoleAssignment.objects.bulk_create(
            [
                RoleAssignment(
                    organization=organization,
                    edition=None,
                    principal=administrator,
                    role_bundle=role,
                    effective_from=timezone.now(),
                    granted_by=AccountFactory(),
                    approved_by=AccountFactory(),
                    reason="Forbidden raw platform authority.",
                )
            ]
        )

    assert not RoleAssignment.objects.filter(principal=administrator).exists()


def test_database_freezes_linked_root_assignment_identity_and_provenance() -> None:
    administrator, organization, representation, appointments = _accepted_board()
    _activate_board(
        administrator=administrator,
        representation=representation,
    )
    _check_and_redefer_constraints()
    assignment = RoleAssignment.objects.get(
        representation_appointment__id=appointments[0].id
    )
    outsider = AccountFactory()
    replacement_bundle = RoleBundleFactory(
        organization=organization,
        capability_codes=["events.view_basic"],
    )

    for changes in (
        {"principal_id": outsider.id},
        {"role_bundle_id": replacement_bundle.id},
        {"approved_by_id": outsider.id},
    ):
        with (
            transaction.atomic(),
            pytest.raises(
                IntegrityError,
                match="linked Executive Board assignment provenance is immutable",
            ),
        ):
            RoleAssignment.objects.filter(pk=assignment.pk).update(**changes)

    assignment.refresh_from_db()
    assert assignment.principal_id == appointments[0].account_id
    assert assignment.role_bundle.code == EXECUTIVE_BOARD_ROLE_CODE
    assert assignment.approved_by_id != assignment.principal_id


def _raw_activation_without_command_evidence(
    *,
    administrator: Account,
    organization: Organization,
    representation: OrganizationRepresentation,
    appointments: tuple[RepresentationAppointment, RepresentationAppointment],
    capabilities: tuple[str, ...] = EXECUTIVE_BOARD_CAPABILITIES,
    leave_membership_invited: bool = False,
    self_approve: bool = False,
    future_effective: bool = False,
) -> None:
    activated_at = timezone.now()
    reason = "Fabricated raw Executive Board activation."
    role = RoleBundle.objects.create(
        organization=organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
        name="Executive Board",
        version=1,
        capability_codes=list(capabilities),
        created_by=administrator,
        approved_by=appointments[0].account,
        reason=reason,
    )
    assignments: list[RoleAssignment] = []
    for index, appointment in enumerate(appointments):
        approver = (
            appointment.account
            if self_approve and index == 0
            else appointments[(index + 1) % len(appointments)].account
        )
        assignments.append(
            RoleAssignment.objects.create(
                organization=organization,
                edition=None,
                principal=appointment.account,
                role_bundle=role,
                effective_from=(
                    activated_at + timedelta(minutes=5)
                    if future_effective and index == 0
                    else activated_at
                ),
                expires_at=None,
                granted_by=administrator,
                approved_by=approver,
                reason=reason,
            )
        )

    memberships = OrganizationMembership.objects.filter(
        organization=organization,
        account_id__in=[appointment.account_id for appointment in appointments],
    )
    if leave_membership_invited:
        memberships = memberships.exclude(account_id=appointments[0].account_id)
    memberships.update(
        state=OrganizationMembership.State.ACTIVE,
        relationship_label="Executive Board controller",
        started_at=activated_at,
        ended_at=None,
        updated_at=activated_at,
    )

    for appointment, assignment in zip(appointments, assignments, strict=True):
        RepresentationAppointment.objects.filter(pk=appointment.pk).update(
            state=RepresentationAppointment.State.ACTIVE,
            activated_at=activated_at,
            role_assignment_id=assignment.id,
            invitation_version=F("invitation_version") + 1,
            updated_at=activated_at,
        )
    OrganizationRepresentation.objects.filter(pk=representation.pk).update(
        state=OrganizationRepresentation.State.ACTIVE,
        activated_by=administrator,
        activated_at=activated_at,
        activation_reason=reason,
        aggregate_version=F("aggregate_version") + 1,
        updated_at=activated_at,
    )
    Organization.objects.filter(pk=organization.pk).update(
        lifecycle=Organization.Lifecycle.ACTIVE,
        updated_at=activated_at,
    )
    _force_deferred_constraints()


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        (
            "capabilities",
            "reserved Executive Board bundle is invalid",
        ),
        ("inactive", "representation appointment requires an eligible person"),
        ("membership", "active Executive Board controller evidence is incomplete"),
        ("pending", "active representation cannot retain pending appointments"),
        ("approval", "active Executive Board controller evidence is incomplete"),
        ("effective", "active Executive Board controller evidence is incomplete"),
        ("evidence", "active representation lacks activation audit evidence"),
    ],
)
def test_database_rejects_raw_fabricated_activation_invariants(
    scenario: str,
    message: str,
) -> None:
    administrator, organization, representation, appointments = _accepted_board()
    if scenario == "pending":
        _invite(
            administrator=administrator,
            representation=representation,
            account=AccountFactory(),
        )

    def perform_fabricated_activation() -> None:
        if scenario == "inactive":
            appointments[0].account.is_active = False
            appointments[0].account.save(update_fields=("is_active",))
        _raw_activation_without_command_evidence(
            administrator=administrator,
            organization=organization,
            representation=representation,
            appointments=appointments,
            capabilities=(
                ("events.view_basic",)
                if scenario == "capabilities"
                else EXECUTIVE_BOARD_CAPABILITIES
            ),
            leave_membership_invited=scenario == "membership",
            self_approve=scenario == "approval",
            future_effective=scenario == "effective",
        )

    with pytest.raises(IntegrityError, match=message), transaction.atomic():
        perform_fabricated_activation()

    organization.refresh_from_db()
    representation.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert representation.state == OrganizationRepresentation.State.PROVISIONING
    assert not RoleBundle.objects.filter(
        organization=organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
    ).exists()


def test_fabricated_activation_cannot_borrow_foreign_board_evidence() -> None:
    foreign_admin, _, foreign_representation, _ = _accepted_board()
    _activate_board(
        administrator=foreign_admin,
        representation=foreign_representation,
    )
    administrator, organization, representation, appointments = _accepted_board()

    with (
        pytest.raises(
            IntegrityError,
            match="active Executive Board controller evidence is incomplete",
        ),
        transaction.atomic(),
    ):
        _raw_activation_without_command_evidence(
            administrator=administrator,
            organization=organization,
            representation=representation,
            appointments=appointments,
            leave_membership_invited=True,
        )

    foreign_representation.refresh_from_db()
    representation.refresh_from_db()
    assert foreign_representation.state == OrganizationRepresentation.State.ACTIVE
    assert representation.state == OrganizationRepresentation.State.PROVISIONING


def _accepted_board_with_controller_count(
    *, administrator: Account, count: int
) -> tuple[
    Organization,
    OrganizationRepresentation,
    tuple[RepresentationAppointment, ...],
]:
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    appointments = tuple(
        _accept(
            _invite(
                administrator=administrator,
                representation=representation,
                account=AccountFactory(),
            )
        )
        for _index in range(count)
    )
    return organization, representation, appointments


def test_emergency_removal_contains_every_open_relationship_globally() -> None:
    administrator = _platform_administrator()
    _organization, representation, appointments = _accepted_board_with_controller_count(
        administrator=administrator, count=3
    )
    _activate_board(administrator=administrator, representation=representation)
    subject = appointments[0].account

    second_active_organization = OrganizationFactory(
        lifecycle=Organization.Lifecycle.DRAFT
    )
    second_active_representation = _provision(
        administrator=administrator,
        organization=second_active_organization,
    )
    second_active_subject_term = _accept(
        _invite(
            administrator=administrator,
            representation=second_active_representation,
            account=subject,
        )
    )
    _accept(
        _invite(
            administrator=administrator,
            representation=second_active_representation,
            account=AccountFactory(),
        )
    )
    _activate_board(
        administrator=administrator,
        representation=second_active_representation,
    )
    accepted_organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    accepted_representation = _provision(
        administrator=administrator,
        organization=accepted_organization,
    )
    accepted_invitation = _accept(
        _invite(
            administrator=administrator,
            representation=accepted_representation,
            account=subject,
        )
    )
    invited_organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    invited_representation = _provision(
        administrator=administrator,
        organization=invited_organization,
    )
    invited = _invite(
        administrator=administrator,
        representation=invited_representation,
        account=subject,
    )
    representation.refresh_from_db()
    correlation_id = uuid4()

    result = emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=representation.id,
        appointment_id=appointments[0].id,
        expected_version=representation.aggregate_version,
        reason="Contain a synthetic globally compromised controller.",
        correlation_id=correlation_id,
        source_channel="test",
    )
    _check_and_redefer_constraints()

    subject.refresh_from_db()
    representation.refresh_from_db()
    second_active_organization.refresh_from_db()
    second_active_representation.refresh_from_db()
    accepted_representation.refresh_from_db()
    invited_representation.refresh_from_db()
    assert subject.is_active is False
    assert result.quorum_preserved is True
    assert len(result.affected_representations) == 4
    assert representation.state == OrganizationRepresentation.State.ACTIVE
    assert (
        second_active_representation.state == OrganizationRepresentation.State.SUSPENDED
    )
    assert second_active_organization.lifecycle == Organization.Lifecycle.SUSPENDED
    assert (
        accepted_representation.state == OrganizationRepresentation.State.PROVISIONING
    )
    assert invited_representation.state == OrganizationRepresentation.State.PROVISIONING
    assert set(
        RepresentationAppointment.objects.filter(
            id__in=(
                appointments[0].id,
                second_active_subject_term.id,
                accepted_invitation.id,
                invited.id,
            )
        ).values_list("state", flat=True)
    ) == {RepresentationAppointment.State.ENDED}
    assert not OrganizationMembership.objects.filter(
        account=subject,
        relationship_label="Executive Board controller",
        state__in=(
            OrganizationMembership.State.INVITED,
            OrganizationMembership.State.ACTIVE,
        ),
    ).exists()
    assert RoleAssignment.objects.filter(
        representation_appointment__id=appointments[0].id,
        revoked_at__isnull=False,
    ).exists()
    assert (
        RepresentationAppointment.objects.filter(
            representation=representation,
            state=RepresentationAppointment.State.ACTIVE,
        ).count()
        == 2
    )
    assert (
        AuditEvent.objects.filter(
            organization_id__isnull=True,
            operation="identity.account.emergency_deactivate",
            target_id=subject.id,
            correlation_id=correlation_id,
        ).count()
        == 1
    )
    assert DomainEvent.objects.filter(correlation_id=correlation_id).count() == 4
    assert set(
        DomainEvent.objects.filter(correlation_id=correlation_id).values_list(
            "payload__action", flat=True
        )
    ) == {
        "controller_ended",
        "controller_invitation_ended",
        "representation_suspended",
    }


def test_emergency_removal_suspends_board_that_loses_quorum() -> None:
    administrator = _platform_administrator()
    organization, representation, appointments = _accepted_board_with_controller_count(
        administrator=administrator, count=2
    )
    _activate_board(administrator=administrator, representation=representation)
    representation.refresh_from_db()

    result = emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=representation.id,
        appointment_id=appointments[0].id,
        expected_version=representation.aggregate_version,
        reason="Contain a synthetic controller without leaving single-person root.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    _check_and_redefer_constraints()

    organization.refresh_from_db()
    representation.refresh_from_db()
    assert result.quorum_preserved is False
    assert organization.lifecycle == Organization.Lifecycle.SUSPENDED
    assert representation.state == OrganizationRepresentation.State.SUSPENDED
    assert set(
        RepresentationAppointment.objects.filter(
            representation=representation
        ).values_list("state", flat=True)
    ) == {RepresentationAppointment.State.ENDED}
    assert not RoleAssignment.objects.filter(
        organization=organization,
        role_bundle__code=EXECUTIVE_BOARD_ROLE_CODE,
        revoked_at__isnull=True,
    ).exists()
    assert not OrganizationMembership.objects.filter(
        organization=organization,
        relationship_label="Executive Board controller",
        state__in=(
            OrganizationMembership.State.INVITED,
            OrganizationMembership.State.ACTIVE,
        ),
    ).exists()


def test_emergency_removal_can_start_from_pending_only_relationship() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    invitation = _invite(
        administrator=administrator,
        representation=representation,
        account=AccountFactory(),
    )
    representation.refresh_from_db()

    result = emergency_remove_executive_board_controller(
        actor=administrator,
        representation_id=representation.id,
        appointment_id=invitation.id,
        expected_version=representation.aggregate_version,
        reason="Contain a synthetic account before Board activation.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    _check_and_redefer_constraints()

    invitation.refresh_from_db()
    invitation.account.refresh_from_db()
    representation.refresh_from_db()
    assert result.quorum_preserved is None
    assert invitation.state == RepresentationAppointment.State.ENDED
    assert invitation.responded_at is not None
    assert invitation.account.is_active is False
    assert representation.state == OrganizationRepresentation.State.PROVISIONING
    assert organization.lifecycle == Organization.Lifecycle.DRAFT


def test_emergency_publication_failure_rolls_back_global_containment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    administrator = _platform_administrator()
    organization, representation, appointments = _accepted_board_with_controller_count(
        administrator=administrator, count=2
    )
    _activate_board(administrator=administrator, representation=representation)
    representation.refresh_from_db()
    correlation_id = uuid4()

    def fail_publication(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic emergency publication failure")

    monkeypatch.setattr(
        "maru.organizations.representation.publish_domain_event",
        fail_publication,
    )
    with pytest.raises(RuntimeError, match="synthetic emergency"):
        emergency_remove_executive_board_controller(
            actor=administrator,
            representation_id=representation.id,
            appointment_id=appointments[0].id,
            expected_version=representation.aggregate_version,
            reason="Rollback a synthetic failed containment.",
            correlation_id=correlation_id,
            source_channel="test",
        )

    organization.refresh_from_db()
    representation.refresh_from_db()
    appointments[0].account.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.ACTIVE
    assert representation.state == OrganizationRepresentation.State.ACTIVE
    assert appointments[0].account.is_active is True
    assert not AuditEvent.objects.filter(correlation_id=correlation_id).exists()


def test_activation_rejects_an_ended_controller_membership() -> None:
    administrator, organization, representation, appointments = _accepted_board()
    membership = OrganizationMembership.objects.get(
        organization=organization,
        account=appointments[0].account,
    )
    membership.state = OrganizationMembership.State.ENDED
    membership.ended_at = timezone.now()
    membership.save(update_fields=("state", "ended_at", "updated_at"))
    representation.refresh_from_db()

    with pytest.raises(ValidationError) as captured:
        activate_executive_board(
            actor=administrator,
            representation_id=representation.id,
            expected_version=representation.aggregate_version,
            reason="Do not reactivate an ended relationship implicitly.",
            correlation_id=uuid4(),
            source_channel="test",
        )

    assert captured.value.code == "representation_membership_incompatible"
    organization.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.DRAFT
    assert not RoleAssignment.objects.filter(organization=organization).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_invitation_responses_serialize_without_lost_update() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    representation = _provision(
        administrator=administrator,
        organization=organization,
    )
    invitations = tuple(
        _invite(
            administrator=administrator,
            representation=representation,
            account=AccountFactory(),
        )
        for _index in range(2)
    )
    representation.refresh_from_db()
    initial_version = representation.aggregate_version
    start = Barrier(2)

    def accept_invitation(appointment_id: UUID, account_id: UUID) -> str:
        close_old_connections()
        try:
            start.wait(timeout=10)
            appointment = RepresentationAppointment.objects.get(id=appointment_id)
            actor = Account.objects.get(id=account_id)
            respond_to_representation_invitation(
                actor=actor,
                appointment_id=appointment.id,
                expected_version=appointment.invitation_version,
                accept=True,
                correlation_id=uuid4(),
                source_channel="test",
            )
            return "accepted"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda invitation: accept_invitation(
                    invitation.id, invitation.account_id
                ),
                invitations,
            )
        )

    representation.refresh_from_db()
    assert outcomes == ["accepted", "accepted"]
    assert representation.aggregate_version == initial_version + 2
    assert set(
        RepresentationAppointment.objects.filter(
            id__in=[item.id for item in invitations]
        ).values_list("state", flat=True)
    ) == {RepresentationAppointment.State.ACCEPTED}


@pytest.mark.django_db(transaction=True)
def test_capability_insert_and_platform_reclassification_cannot_both_commit() -> None:
    administrator = _platform_administrator()
    organization = OrganizationFactory(lifecycle=Organization.Lifecycle.DRAFT)
    subject = AccountFactory()
    start = Barrier(2)

    def insert_grant() -> str:
        close_old_connections()
        try:
            with transaction.atomic():
                start.wait(timeout=10)
                CapabilityGrant.objects.bulk_create(
                    [
                        CapabilityGrant(
                            organization_id=organization.id,
                            principal_id=subject.id,
                            capability_code="events.view_basic",
                            effective_from=timezone.now(),
                            granted_by_id=administrator.id,
                            reason="Synthetic concurrent grant.",
                        )
                    ]
                )
        except IntegrityError:
            return "rejected"
        else:
            return "committed"
        finally:
            connection.close()

    def reclassify_subject() -> str:
        close_old_connections()
        try:
            with transaction.atomic():
                start.wait(timeout=10)
                Account.objects.filter(id=subject.id).update(
                    account_kind=Account.Kind.PLATFORM_ADMINISTRATOR,
                    is_staff=True,
                    is_superuser=True,
                )
        except IntegrityError:
            return "rejected"
        else:
            return "committed"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        grant_future = executor.submit(insert_grant)
        reclassification_future = executor.submit(reclassify_subject)
        outcomes = (grant_future.result(), reclassification_future.result())

    subject.refresh_from_db()
    grant_exists = CapabilityGrant.objects.filter(principal=subject).exists()
    assert sorted(outcomes) == ["committed", "rejected"]
    assert not (subject.is_platform_administrator and grant_exists)


@pytest.mark.django_db(transaction=True)
def test_emergency_and_assignment_update_follow_one_lock_order() -> None:
    administrator = _platform_administrator()
    _organization, representation, appointments = _accepted_board_with_controller_count(
        administrator=administrator, count=3
    )
    _activate_board(administrator=administrator, representation=representation)
    representation.refresh_from_db()
    assignment_id = RepresentationAppointment.objects.get(
        id=appointments[0].id
    ).role_assignment_id
    assert assignment_id is not None
    expected_version = representation.aggregate_version
    start = Barrier(2)

    def contain_subject() -> str:
        close_old_connections()
        try:
            start.wait(timeout=10)
            emergency_remove_executive_board_controller(
                actor=Account.objects.get(id=administrator.id),
                representation_id=representation.id,
                appointment_id=appointments[0].id,
                expected_version=expected_version,
                reason="Synthetic concurrent containment.",
                correlation_id=uuid4(),
                source_channel="test",
            )
            return "contained"
        finally:
            connection.close()

    def touch_assignment() -> str:
        close_old_connections()
        try:
            start.wait(timeout=10)
            with transaction.atomic():
                RoleAssignment.objects.filter(id=assignment_id).update(
                    updated_at=timezone.now()
                )
            return "updated"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        containment_future = executor.submit(contain_subject)
        update_future = executor.submit(touch_assignment)
        outcomes = (
            containment_future.result(timeout=20),
            update_future.result(timeout=20),
        )

    assert outcomes == ("contained", "updated")
    representation.refresh_from_db()
    assert representation.state == OrganizationRepresentation.State.ACTIVE
    assert (
        RepresentationAppointment.objects.filter(
            representation=representation,
            state=RepresentationAppointment.State.ACTIVE,
        ).count()
        == 2
    )


@pytest.mark.django_db(transaction=True)
def test_activation_and_membership_update_follow_one_lock_order() -> None:
    administrator, organization, representation, appointments = _accepted_board()
    representation.refresh_from_db()
    membership_id = OrganizationMembership.objects.get(
        organization=organization,
        account=appointments[0].account,
    ).id
    expected_version = representation.aggregate_version
    start = Barrier(2)

    def activate_board() -> str:
        close_old_connections()
        try:
            start.wait(timeout=10)
            activate_executive_board(
                actor=Account.objects.get(id=administrator.id),
                representation_id=representation.id,
                expected_version=expected_version,
                reason="Synthetic concurrent activation.",
                correlation_id=uuid4(),
                source_channel="test",
            )
            return "activated"
        finally:
            connection.close()

    def touch_membership() -> str:
        close_old_connections()
        try:
            start.wait(timeout=10)
            with transaction.atomic():
                OrganizationMembership.objects.filter(id=membership_id).update(
                    updated_at=timezone.now()
                )
            return "updated"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        activation_future = executor.submit(activate_board)
        update_future = executor.submit(touch_membership)
        outcomes = (
            activation_future.result(timeout=20),
            update_future.result(timeout=20),
        )

    assert outcomes == ("activated", "updated")
    organization.refresh_from_db()
    representation.refresh_from_db()
    assert organization.lifecycle == Organization.Lifecycle.ACTIVE
    assert representation.state == OrganizationRepresentation.State.ACTIVE
