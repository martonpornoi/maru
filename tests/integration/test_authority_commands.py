from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.commands import (
    AuthorityCommandValidationError,
    assign_role,
    create_role_bundle_version,
    grant_capability_direct,
    revoke_capability_grant,
    revoke_role_assignment,
)
from maru.authorization.models import CapabilityGrant, RoleAssignment, RoleBundle
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent, OutboxMessage
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleBundleFactory,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _grant_management(
    account: object,
    organization: object,
    capability_code: str,
    *,
    edition: object | None = None,
) -> None:
    CapabilityGrantFactory(
        principal=account,
        organization=organization,
        edition=edition,
        capability_code=capability_code,
        effective_from=timezone.now() - timedelta(minutes=1),
    )


def _dual_managers(
    organization: object,
    capability_code: str,
    *,
    edition: object | None = None,
) -> tuple[object, object]:
    actor = AccountFactory()
    approver = AccountFactory()
    _grant_management(
        actor,
        organization,
        capability_code,
        edition=edition,
    )
    _grant_management(
        approver,
        organization,
        capability_code,
        edition=edition,
    )
    return actor, approver


def test_direct_grant_requires_two_authorities_and_commits_complete_evidence() -> None:
    edition = EventEditionFactory()
    actor, approver = _dual_managers(
        edition.organization,
        "authorization.grant_direct",
        edition=edition,
    )
    recipient = AccountFactory()
    correlation_id = uuid4()
    effective_from = timezone.now() - timedelta(seconds=1)

    grant = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=recipient,
        capability_code="events.transition",
        organization_id=edition.organization_id,
        edition_id=edition.id,
        effective_from=effective_from,
        expires_at=effective_from + timedelta(days=2),
        reason="Temporary lifecycle authority for the event lead.",
        correlation_id=correlation_id,
    )

    assert grant.granted_by == actor
    assert grant.approved_by == approver
    assert grant.delegated_from is None
    assert decide(
        principal=recipient,
        capability_code="events.transition",
        resource=ResourceScope(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    ).allowed
    audits = list(
        AuditEvent.objects.filter(correlation_id=correlation_id).order_by(
            "occurred_at", "id"
        )
    )
    assert len(audits) == 2
    assert {audit.principal_id for audit in audits} == {actor.id, approver.id}
    assert {audit.outcome for audit in audits} == {AuditEvent.Outcome.ALLOW}
    assert any(audit.operation.endswith(".approve") for audit in audits)
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    assert event.event_name == "authorization.capability.direct_granted.v1"
    assert event.aggregate_id == grant.id
    assert event.payload == {
        "capability_code": "events.transition",
        "scope_level": "edition",
    }
    assert OutboxMessage.objects.get(event=event).workload_pool == "security"


@pytest.mark.parametrize(
    ("approver_kind", "expected_reason"),
    [
        ("actor", "distinct_approver_required"),
        ("recipient", "recipient_cannot_approve"),
        ("unauthorized", "approver_permission_absent"),
    ],
)
def test_direct_grant_denies_invalid_approval_without_state_or_effect(
    approver_kind: str,
    expected_reason: str,
) -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    recipient = AccountFactory()
    _grant_management(actor, organization, "authorization.grant_direct")
    approver = {
        "actor": actor,
        "recipient": recipient,
        "unauthorized": AccountFactory(),
    }[approver_kind]
    correlation_id = uuid4()

    with pytest.raises(AuthorizationDenied) as captured:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            organization_id=organization.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Attempt invalid approval.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == expected_reason
    assert not CapabilityGrant.objects.filter(
        principal=recipient,
        capability_code="events.view_basic",
    ).exists()
    assert not DomainEvent.objects.filter(correlation_id=correlation_id).exists()
    denial = AuditEvent.objects.get(correlation_id=correlation_id)
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert denial.reason_code == expected_reason


@pytest.mark.parametrize(
    ("capability_code", "edition_required", "expected_reason"),
    [
        ("unknown.capability", False, "unknown_capability"),
        ("participation.view_self", False, "resource_capability_not_grantable"),
        ("events.transition", True, "edition_scope_required"),
    ],
)
def test_direct_grant_rejects_unsafe_targets_with_classified_audit(
    capability_code: str,
    edition_required: bool,
    expected_reason: str,
) -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.grant_direct",
    )
    correlation_id = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=AccountFactory(),
            capability_code=capability_code,
            organization_id=organization.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason=("Missing edition scope." if edition_required else "Unsafe target."),
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == expected_reason
    failure = AuditEvent.objects.get(correlation_id=correlation_id)
    assert failure.outcome == AuditEvent.Outcome.ERROR
    assert failure.reason_code == expected_reason


def test_direct_grant_effect_failure_rolls_back_state_and_success_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.grant_direct",
    )
    recipient = AccountFactory()
    correlation_id = uuid4()

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(
        "maru.authorization.commands.publish_domain_event",
        fail_publish,
    )

    with pytest.raises(RuntimeError, match="synthetic outbox"):
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            organization_id=organization.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason="This command must roll back atomically.",
            correlation_id=correlation_id,
        )

    assert not CapabilityGrant.objects.filter(
        principal=recipient,
        capability_code="events.view_basic",
    ).exists()
    failure = AuditEvent.objects.get(correlation_id=correlation_id)
    assert failure.outcome == AuditEvent.Outcome.ERROR
    assert failure.reason_code == "direct_grant_failed"


@pytest.mark.parametrize(
    ("reason", "expires_delta", "expected_reason"),
    [
        ("", None, "reason_required"),
        ("x" * 241, None, "reason_too_long"),
        ("Invalid interval.", timedelta(seconds=-1), "invalid_effective_interval"),
    ],
)
def test_direct_grant_validates_reason_and_effective_interval(
    reason: str,
    expires_delta: timedelta | None,
    expected_reason: str,
) -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.grant_direct",
    )
    effective_from = timezone.now()
    correlation_id = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=AccountFactory(),
            capability_code="events.view_basic",
            organization_id=organization.id,
            edition_id=None,
            effective_from=effective_from,
            expires_at=(
                effective_from + expires_delta if expires_delta is not None else None
            ),
            reason=reason,
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == expected_reason
    assert (
        AuditEvent.objects.get(correlation_id=correlation_id).reason_code
        == expected_reason
    )


def test_direct_grant_rejects_missing_scope_and_active_duplicate() -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.grant_direct",
    )
    recipient = AccountFactory()
    missing_scope_correlation = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as missing_scope:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            organization_id=organization.id,
            edition_id=uuid4(),
            effective_from=timezone.now(),
            expires_at=None,
            reason="The edition must exist in the tenant.",
            correlation_id=missing_scope_correlation,
        )
    assert missing_scope.value.reason_code == "scope_unavailable"

    CapabilityGrantFactory(
        organization=organization,
        principal=recipient,
        capability_code="events.view_basic",
    )
    duplicate_correlation = uuid4()
    with pytest.raises(AuthorityCommandValidationError) as duplicate:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            organization_id=organization.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Do not duplicate active authority.",
            correlation_id=duplicate_correlation,
        )
    assert duplicate.value.reason_code == "active_grant_exists"


def test_new_authority_cannot_outlive_either_controller() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    now = timezone.now()
    CapabilityGrantFactory(
        organization=organization,
        principal=actor,
        capability_code="authorization.grant_direct",
        effective_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=2),
    )
    CapabilityGrantFactory(
        organization=organization,
        principal=approver,
        capability_code="authorization.grant_direct",
        effective_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=1),
    )
    correlation_id = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=AccountFactory(),
            capability_code="events.view_basic",
            organization_id=organization.id,
            edition_id=None,
            effective_from=now,
            expires_at=now + timedelta(days=1, seconds=1),
            reason="The approver does not hold authority for this long.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "authority_expiry_too_early"
    assert (
        AuditEvent.objects.get(correlation_id=correlation_id).reason_code
        == "authority_expiry_too_early"
    )


def test_revocation_is_immediate_preserves_provenance_and_invalidates_descendants() -> (
    None
):
    edition = EventEditionFactory()
    actor = AccountFactory()
    _grant_management(
        actor,
        edition.organization,
        "authorization.revoke",
    )
    grantor = AccountFactory()
    parent = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=grantor,
        capability_code="events.view_basic",
        effective_from=timezone.now() - timedelta(days=1),
        reason="Original root authority.",
    )
    child = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=timezone.now() - timedelta(hours=1),
        granted_by=grantor,
        delegated_from=parent,
        reason="Bounded delegated authority.",
    )
    correlation_id = uuid4()

    revoked = revoke_capability_grant(
        actor=actor,
        organization_id=edition.organization_id,
        grant_id=parent.id,
        reason="Offboarding requires immediate removal.",
        correlation_id=correlation_id,
    )

    assert revoked.reason == "Original root authority."
    assert revoked.revoked_by == actor
    assert revoked.revocation_reason == "Offboarding requires immediate removal."
    assert not decide(
        principal=child.principal,
        capability_code=child.capability_code,
        resource=ResourceScope(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    ).allowed
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.operation == "authorization.capability.revoke"
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    assert event.event_name == "authorization.capability.revoked.v1"
    assert event.aggregate_version == 2


def test_revocation_hides_another_tenants_authority_record() -> None:
    own_organization = OrganizationFactory()
    other_grant = CapabilityGrantFactory()
    actor = AccountFactory()
    _grant_management(actor, own_organization, "authorization.revoke")
    correlation_id = uuid4()

    with pytest.raises(AuthorizationDenied) as captured:
        revoke_capability_grant(
            actor=actor,
            organization_id=own_organization.id,
            grant_id=other_grant.id,
            reason="Attempt a cross-tenant revocation.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "authority_unavailable"
    other_grant.refresh_from_db()
    assert other_grant.revoked_at is None
    denial = AuditEvent.objects.get(correlation_id=correlation_id)
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert denial.organization_id == own_organization.id


def test_grant_revocation_rejects_repeat_and_rolls_back_effect_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    _grant_management(actor, organization, "authorization.revoke")
    already_revoked = CapabilityGrantFactory(
        organization=organization,
        revoked_at=timezone.now(),
    )
    repeat_correlation = uuid4()
    with pytest.raises(AuthorityCommandValidationError) as repeated:
        revoke_capability_grant(
            actor=actor,
            organization_id=organization.id,
            grant_id=already_revoked.id,
            reason="A repeated revocation is invalid.",
            correlation_id=repeat_correlation,
        )
    assert repeated.value.reason_code == "grant_already_revoked"

    active = CapabilityGrantFactory(organization=organization)
    failed_correlation = uuid4()

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic revocation effect failure")

    monkeypatch.setattr(
        "maru.authorization.commands.publish_domain_event",
        fail_publish,
    )
    with pytest.raises(RuntimeError, match="synthetic revocation"):
        revoke_capability_grant(
            actor=actor,
            organization_id=organization.id,
            grant_id=active.id,
            reason="This revocation must roll back.",
            correlation_id=failed_correlation,
        )
    active.refresh_from_db()
    assert active.revoked_at is None
    failure = AuditEvent.objects.get(correlation_id=failed_correlation)
    assert failure.reason_code == "grant_revocation_failed"


def test_role_bundle_versions_are_sequential_immutable_and_dual_controlled() -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.manage_roles",
    )
    first_correlation = uuid4()
    second_correlation = uuid4()

    first = create_role_bundle_version(
        actor=actor,
        approver=approver,
        organization_id=organization.id,
        code="front-desk-lead",
        name="Front Desk Lead",
        capability_codes=("events.view_basic",),
        reason="Create the first reviewed role definition.",
        correlation_id=first_correlation,
    )
    second = create_role_bundle_version(
        actor=actor,
        approver=approver,
        organization_id=organization.id,
        code="front-desk-lead",
        name="Front Desk Lead",
        capability_codes=("events.view_basic", "events.transition"),
        reason="Add controlled lifecycle authority.",
        correlation_id=second_correlation,
    )

    assert (first.version, second.version) == (1, 2)
    assert second.created_by == actor
    assert second.approved_by == approver
    assert second.reason == "Add controlled lifecycle authority."
    with pytest.raises(ValidationError, match="immutable"):
        second.save()
    assert (
        AuditEvent.objects.filter(
            correlation_id=second_correlation,
            outcome=AuditEvent.Outcome.ALLOW,
        ).count()
        == 2
    )
    event = DomainEvent.objects.get(correlation_id=second_correlation)
    assert event.payload == {
        "role_code": "front-desk-lead",
        "role_version": "2",
    }


@pytest.mark.parametrize(
    ("name", "capability_codes", "expected_reason"),
    [
        ("", ("events.view_basic",), "role_name_required"),
        ("x" * 121, ("events.view_basic",), "role_name_too_long"),
        (
            "Duplicate",
            ("events.view_basic", "events.view_basic"),
            "duplicate_capability",
        ),
        ("Unknown", ("unknown.capability",), "unknown_capability"),
        (
            "Relationship role",
            ("participation.view_self",),
            "resource_capability_not_assignable",
        ),
    ],
)
def test_role_bundle_command_rejects_unsafe_definitions(
    name: str,
    capability_codes: tuple[str, ...],
    expected_reason: str,
) -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.manage_roles",
    )
    correlation_id = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        create_role_bundle_version(
            actor=actor,
            approver=approver,
            organization_id=organization.id,
            code="unsafe-role",
            name=name,
            capability_codes=capability_codes,
            reason="Exercise a rejected role definition.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == expected_reason
    assert (
        AuditEvent.objects.get(correlation_id=correlation_id).reason_code
        == expected_reason
    )


def test_role_bundle_denial_validation_and_effect_failure_are_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    _grant_management(actor, organization, "authorization.manage_roles")
    unauthorized_correlation = uuid4()
    with pytest.raises(AuthorizationDenied) as denied:
        create_role_bundle_version(
            actor=actor,
            approver=AccountFactory(),
            organization_id=organization.id,
            code="denied-role",
            name="Denied role",
            capability_codes=("events.view_basic",),
            reason="The approver is unauthorized.",
            correlation_id=unauthorized_correlation,
        )
    assert denied.value.reason_code == "approver_permission_absent"

    approver = AccountFactory()
    _grant_management(approver, organization, "authorization.manage_roles")
    invalid_correlation = uuid4()
    with pytest.raises(ValidationError):
        create_role_bundle_version(
            actor=actor,
            approver=approver,
            organization_id=organization.id,
            code="Invalid Role Code",
            name="Invalid role",
            capability_codes=("events.view_basic",),
            reason="The stable code is invalid.",
            correlation_id=invalid_correlation,
        )
    assert (
        AuditEvent.objects.get(correlation_id=invalid_correlation).reason_code
        == "role_bundle_invalid"
    )

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic role effect failure")

    monkeypatch.setattr(
        "maru.authorization.commands.publish_domain_event",
        fail_publish,
    )
    failed_correlation = uuid4()
    with pytest.raises(RuntimeError, match="synthetic role"):
        create_role_bundle_version(
            actor=actor,
            approver=approver,
            organization_id=organization.id,
            code="rolled-back-role",
            name="Rolled back role",
            capability_codes=("events.view_basic",),
            reason="This role must roll back.",
            correlation_id=failed_correlation,
        )
    assert not RoleBundle.objects.filter(
        organization=organization,
        code="rolled-back-role",
    ).exists()
    assert (
        AuditEvent.objects.get(correlation_id=failed_correlation).reason_code
        == "role_bundle_failed"
    )


def test_role_assignment_and_revocation_have_complete_policy_and_event_spine() -> None:
    edition = EventEditionFactory()
    actor, approver = _dual_managers(
        edition.organization,
        "authorization.manage_roles",
        edition=edition,
    )
    recipient = AccountFactory()
    role = RoleBundleFactory(
        organization=edition.organization,
        code="edition-controller",
        capability_codes=["events.transition"],
    )
    assigned_correlation = uuid4()
    effective_from = timezone.now() - timedelta(seconds=1)

    assignment = assign_role(
        actor=actor,
        approver=approver,
        recipient=recipient,
        organization_id=edition.organization_id,
        role_bundle_id=role.id,
        edition_id=edition.id,
        effective_from=effective_from,
        expires_at=effective_from + timedelta(days=3),
        reason="Cover the event control duty.",
        correlation_id=assigned_correlation,
    )

    assert assignment.approved_by == approver
    assert decide(
        principal=recipient,
        capability_code="events.transition",
        resource=ResourceScope(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    ).allowed
    assert (
        AuditEvent.objects.filter(
            correlation_id=assigned_correlation,
            outcome=AuditEvent.Outcome.ALLOW,
        ).count()
        == 2
    )
    assert (
        DomainEvent.objects.get(correlation_id=assigned_correlation).event_name
        == "authorization.role.assigned.v1"
    )

    revoker = AccountFactory()
    _grant_management(
        revoker,
        edition.organization,
        "authorization.revoke",
    )
    revoked_correlation = uuid4()
    revoked = revoke_role_assignment(
        actor=revoker,
        organization_id=edition.organization_id,
        assignment_id=assignment.id,
        reason="The temporary duty ended.",
        correlation_id=revoked_correlation,
    )

    assert revoked.reason == "Cover the event control duty."
    assert revoked.revoked_by == revoker
    assert revoked.revocation_reason == "The temporary duty ended."
    assert not decide(
        principal=recipient,
        capability_code="events.transition",
        resource=ResourceScope(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    ).allowed
    assert (
        DomainEvent.objects.get(correlation_id=revoked_correlation).event_name
        == "authorization.role.revoked.v1"
    )


def test_role_assignment_requires_scope_and_hides_other_tenant_bundle() -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.manage_roles",
    )
    recipient = AccountFactory()
    edition_role = RoleBundleFactory(
        organization=organization,
        capability_codes=["events.transition"],
    )

    with pytest.raises(AuthorityCommandValidationError) as missing_scope:
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            organization_id=organization.id,
            role_bundle_id=edition_role.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason="This must name an edition.",
            correlation_id=uuid4(),
        )
    assert missing_scope.value.reason_code == "edition_scope_required"

    other_role = RoleBundleFactory()
    correlation_id = uuid4()
    with pytest.raises(AuthorizationDenied) as unavailable:
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            organization_id=organization.id,
            role_bundle_id=other_role.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Attempt cross-tenant role use.",
            correlation_id=correlation_id,
        )
    assert unavailable.value.reason_code == "role_bundle_unavailable"
    assert not RoleAssignment.objects.filter(principal=recipient).exists()
    denial = AuditEvent.objects.get(correlation_id=correlation_id)
    assert denial.outcome == AuditEvent.Outcome.DENY


def test_role_assignment_duplicate_and_effect_failures_roll_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.manage_roles",
    )
    recipient = AccountFactory()
    role = RoleBundleFactory(organization=organization)
    existing = RoleAssignment.objects.create(
        organization=organization,
        principal=recipient,
        role_bundle=role,
        effective_from=timezone.now() - timedelta(minutes=1),
        granted_by=actor,
        reason="Existing assignment.",
    )
    duplicate_correlation = uuid4()
    with pytest.raises(AuthorityCommandValidationError) as duplicate:
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            organization_id=organization.id,
            role_bundle_id=role.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Do not duplicate active assignments.",
            correlation_id=duplicate_correlation,
        )
    assert duplicate.value.reason_code == "active_assignment_exists"

    existing.revoked_at = timezone.now()
    existing.save(update_fields=("revoked_at", "updated_at"))

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic assignment effect failure")

    monkeypatch.setattr(
        "maru.authorization.commands.publish_domain_event",
        fail_publish,
    )
    failed_correlation = uuid4()
    with pytest.raises(RuntimeError, match="synthetic assignment"):
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            organization_id=organization.id,
            role_bundle_id=role.id,
            edition_id=None,
            effective_from=timezone.now(),
            expires_at=None,
            reason="This assignment must roll back.",
            correlation_id=failed_correlation,
        )
    assert (
        RoleAssignment.objects.filter(
            principal=recipient,
            role_bundle=role,
        ).count()
        == 1
    )
    assert (
        AuditEvent.objects.get(correlation_id=failed_correlation).reason_code
        == "role_assignment_failed"
    )


def test_role_assignment_cannot_outlive_role_management_authority() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    recipient = AccountFactory()
    role = RoleBundleFactory(organization=organization)
    now = timezone.now()
    management_role = RoleBundleFactory(
        organization=organization,
        capability_codes=["authorization.manage_roles"],
    )
    for principal, expires_at in (
        (actor, now + timedelta(days=3)),
        (approver, now + timedelta(days=1)),
    ):
        RoleAssignment.objects.create(
            organization=organization,
            principal=principal,
            role_bundle=management_role,
            effective_from=now - timedelta(minutes=1),
            expires_at=expires_at,
            granted_by=AccountFactory(),
            reason="Bounded role-management authority.",
        )
    correlation_id = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            organization_id=organization.id,
            role_bundle_id=role.id,
            edition_id=None,
            effective_from=now,
            expires_at=now + timedelta(days=2),
            reason="The assignment exceeds the approval horizon.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "authority_expiry_too_early"
    assert not RoleAssignment.objects.filter(
        principal=recipient,
        role_bundle=role,
    ).exists()


def test_role_revocation_denial_repeat_and_effect_failure_are_classified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    own_organization = OrganizationFactory()
    actor = AccountFactory()
    _grant_management(actor, own_organization, "authorization.revoke")
    other_role = RoleBundleFactory()
    other_assignment = RoleAssignment.objects.create(
        organization=other_role.organization,
        principal=AccountFactory(),
        role_bundle=other_role,
        effective_from=timezone.now(),
        granted_by=AccountFactory(),
        reason="Other tenant assignment.",
    )
    missing_correlation = uuid4()
    with pytest.raises(AuthorizationDenied) as missing:
        revoke_role_assignment(
            actor=actor,
            organization_id=own_organization.id,
            assignment_id=other_assignment.id,
            reason="Attempt cross-tenant removal.",
            correlation_id=missing_correlation,
        )
    assert missing.value.reason_code == "authority_unavailable"

    role = RoleBundleFactory(organization=own_organization)
    already_revoked = RoleAssignment.objects.create(
        organization=own_organization,
        principal=AccountFactory(),
        role_bundle=role,
        effective_from=timezone.now(),
        revoked_at=timezone.now(),
        granted_by=AccountFactory(),
        reason="Already revoked.",
    )
    repeat_correlation = uuid4()
    with pytest.raises(AuthorityCommandValidationError) as repeated:
        revoke_role_assignment(
            actor=actor,
            organization_id=own_organization.id,
            assignment_id=already_revoked.id,
            reason="Do not revoke twice.",
            correlation_id=repeat_correlation,
        )
    assert repeated.value.reason_code == "assignment_already_revoked"

    active = RoleAssignment.objects.create(
        organization=own_organization,
        principal=AccountFactory(),
        role_bundle=role,
        effective_from=timezone.now(),
        granted_by=AccountFactory(),
        reason="Active assignment.",
    )

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic role revocation effect failure")

    monkeypatch.setattr(
        "maru.authorization.commands.publish_domain_event",
        fail_publish,
    )
    failed_correlation = uuid4()
    with pytest.raises(RuntimeError, match="synthetic role revocation"):
        revoke_role_assignment(
            actor=actor,
            organization_id=own_organization.id,
            assignment_id=active.id,
            reason="This revocation must roll back.",
            correlation_id=failed_correlation,
        )
    active.refresh_from_db()
    assert active.revoked_at is None
    assert (
        AuditEvent.objects.get(correlation_id=failed_correlation).reason_code
        == "assignment_revocation_failed"
    )
