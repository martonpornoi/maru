from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization import commands as authority_commands
from maru.authorization.commands import (
    EXECUTIVE_BOARD_ROLE_CODE,
    AuthorityCommandValidationError,
    assign_role,
    create_role_bundle_version,
    grant_capability_direct,
    revoke_capability_grant,
    revoke_role_assignment,
)
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
    ScopedResourceBinding,
)
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent, OutboxMessage
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import Department, Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleBundleFactory,
)
from tests.support.authority import activate_synthetic_board as _board_controllers
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_for_test,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


def _organization_target(
    organization: Organization,
) -> ResolvedAuthorizationTarget:
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    return target


def _edition_target(edition: EventEdition) -> ResolvedAuthorizationTarget:
    target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert target is not None
    return target


def _grant_management(
    account: Account,
    organization: Organization,
    capability_code: str,
    *,
    edition: EventEdition | None = None,
) -> CapabilityGrant:
    existing = CapabilityGrant.objects.filter(
        principal=account,
        organization=organization,
        edition=edition,
        capability_code=capability_code,
        revoked_at__isnull=True,
    ).first()
    if existing is not None:
        return existing
    first, second = _board_controllers(organization)
    actor, approver = (first, second) if account.id != second.id else (second, first)
    return grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=account,
        capability_code=capability_code,
        target=_edition_target(edition)
        if edition is not None
        else _organization_target(organization),
        effective_from=timezone.now(),
        expires_at=None,
        reason="Establish exact synthetic command authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _dual_managers(
    organization: Organization,
    capability_code: str,
    *,
    edition: EventEdition | None = None,
) -> tuple[Account, Account]:
    del capability_code, edition
    return _board_controllers(organization)


def _authorized_role_bundle(
    organization: Organization,
    *,
    capability_codes: tuple[str, ...] = ("events.view_basic",),
    code: str | None = None,
) -> RoleBundle:
    actor, approver = _board_controllers(organization)
    stable_code = code or f"synthetic-role-{uuid4().hex[:12]}"
    return create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=_organization_target(organization),
        code=stable_code,
        name="Synthetic authorized role",
        capability_codes=capability_codes,
        reason="Create a provenance-backed synthetic role definition.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _bounded_management_grant(
    *,
    principal: Account,
    organization: Organization,
    capability_code: str,
    expires_at: datetime,
    effective_from: datetime | None = None,
) -> CapabilityGrant:
    actor, approver = _board_controllers(organization)
    return grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=principal,
        capability_code=capability_code,
        target=_organization_target(organization),
        effective_from=effective_from or timezone.now(),
        expires_at=expires_at,
        reason="Create bounded provenance-backed controller authority.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _scoped_positions() -> tuple[
    Department,
    ScopedResourceBinding,
    ScopedResourceBinding,
]:
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
        code=f"operations-role-{uuid4().hex[:8]}",
        name="Operations role",
        description="Synthetic exact-scope authority command target.",
        default_capacity_codes=["staff"],
        role_bundle=role_bundle,
        created_by=creator,
    )

    def create_binding(code: str) -> ScopedResourceBinding:
        position = save_position_for_test(
            position=Position(
                organization=edition.organization,
                edition=edition,
                template=template,
                department=department,
                role_bundle=role_bundle,
                code=code,
                title=code.replace("-", " ").title(),
                description="Synthetic exact authority target.",
                capacity_codes=["staff"],
                created_by=creator,
            )
        )
        binding, _ = ScopedResourceBinding.objects.get_or_create(
            resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
            resource_id=position.id,
            defaults={
                "organization": department.organization,
                "edition": department.edition,
                "department": department,
            },
        )
        return binding

    first = create_binding(f"operations-lead-{uuid4().hex[:8]}")
    second = create_binding(f"operations-deputy-{uuid4().hex[:8]}")
    return department, first, second


def test_direct_grant_requires_two_authorities_and_commits_complete_evidence() -> None:
    edition = EventEditionFactory()
    actor, approver = _dual_managers(
        edition.organization,
        "authorization.grant_direct",
        edition=edition,
    )
    recipient = AccountFactory()
    correlation_id = uuid4()
    effective_from = timezone.now()

    grant = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=recipient,
        capability_code="events.transition",
        target=_edition_target(edition),
        effective_from=effective_from,
        expires_at=effective_from + timedelta(days=2),
        reason="Temporary lifecycle authority for the event lead.",
        correlation_id=correlation_id,
    )

    assert grant.granted_by == actor
    assert grant.approved_by == approver
    assert grant.delegated_from is None
    issuance = AuthorityIssuance.objects.get(capability_grant=grant)
    controls = {
        control.role: control
        for control in AuthorityControl.objects.select_related(
            "source_issuance"
        ).filter(issuance=issuance)
    }
    assert set(controls) == {
        AuthorityControl.Role.ACTOR,
        AuthorityControl.Role.APPROVER,
    }
    assert controls[AuthorityControl.Role.ACTOR].principal == actor
    assert controls[AuthorityControl.Role.APPROVER].principal == approver
    assert (
        controls[AuthorityControl.Role.ACTOR].source_issuance.role_assignment.principal
        == actor
    )
    assert (
        controls[
            AuthorityControl.Role.APPROVER
        ].source_issuance.role_assignment.principal
        == approver
    )
    assert all(
        control.source_issuance_id < issuance.ordinal for control in controls.values()
    )
    assert decide(
        principal=recipient,
        capability_code="events.transition",
        resource=resolve_edition_target(
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


def test_unproven_legacy_controllers_fail_closed_without_target_or_ledger() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    recipient = AccountFactory()
    for principal in (actor, approver):
        CapabilityGrantFactory(
            organization=organization,
            principal=principal,
            capability_code="authorization.grant_direct",
            effective_from=timezone.now() - timedelta(minutes=1),
        )
    correlation_id = uuid4()

    with pytest.raises(AuthorizationDenied) as captured:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            target=_organization_target(organization),
            effective_from=timezone.now(),
            expires_at=None,
            reason="Legacy rows must not become inferred provenance.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "authority_source_unavailable"
    assert not CapabilityGrant.objects.filter(
        principal=recipient,
        capability_code="events.view_basic",
    ).exists()
    assert not AuthorityIssuance.objects.exists()
    assert not AuthorityControl.objects.exists()
    denial = AuditEvent.objects.get(correlation_id=correlation_id)
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert denial.reason_code == "authority_source_unavailable"


def test_controller_accounts_are_locked_in_stable_database_order() -> None:
    first = AccountFactory()
    second = AccountFactory()
    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        authority_commands._lock_controllers_in_stable_order(
            actor=second,
            approver=first,
        )

    lock_query = next(
        query["sql"]
        for query in queries.captured_queries
        if "identity_account" in query["sql"] and "FOR UPDATE" in query["sql"]
    )
    assert 'ORDER BY "identity_account"."id" ASC' in lock_query


def test_role_definition_accepts_bounded_point_in_time_control_sources() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    expiry = timezone.now() + timedelta(minutes=30)
    actor_grant = _bounded_management_grant(
        principal=actor,
        organization=organization,
        capability_code="authorization.manage_roles",
        expires_at=expiry,
    )
    approver_grant = _bounded_management_grant(
        principal=approver,
        organization=organization,
        capability_code="authorization.manage_roles",
        expires_at=expiry,
    )

    role = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=_organization_target(organization),
        code="bounded-definition",
        name="Bounded definition",
        capability_codes=("events.view_basic",),
        reason="A role definition is authorized at one reviewed point in time.",
        correlation_id=uuid4(),
    )

    issuance = AuthorityIssuance.objects.get(role_bundle=role)
    controls = {
        control.role: control.source_issuance_id
        for control in AuthorityControl.objects.filter(issuance=issuance)
    }
    assert controls == {
        AuthorityControl.Role.ACTOR: AuthorityIssuance.objects.get(
            capability_grant=actor_grant
        ).ordinal,
        AuthorityControl.Role.APPROVER: AuthorityIssuance.objects.get(
            capability_grant=approver_grant
        ).ordinal,
    }


def test_source_selection_pins_direct_authority_before_equivalent_role() -> None:
    edition = EventEditionFactory()
    organization = edition.organization
    actor, approver = _board_controllers(organization)
    management_role = _authorized_role_bundle(
        organization,
        capability_codes=("authorization.grant_direct",),
    )
    role_sources: list[RoleAssignment] = []
    direct_sources: list[CapabilityGrant] = []
    for principal, independent_approver in (
        (actor, approver),
        (approver, actor),
    ):
        role_sources.append(
            assign_role(
                actor=principal,
                approver=independent_approver,
                recipient=principal,
                target=_edition_target(edition),
                role_bundle_id=management_role.id,
                effective_from=timezone.now(),
                expires_at=None,
                reason="Create an equivalent role-based controller source.",
                correlation_id=uuid4(),
            )
        )
        direct_sources.append(
            grant_capability_direct(
                actor=principal,
                approver=independent_approver,
                recipient=principal,
                capability_code="authorization.grant_direct",
                target=_edition_target(edition),
                effective_from=timezone.now(),
                expires_at=None,
                reason="Create the deterministic direct controller source.",
                correlation_id=uuid4(),
            )
        )

    final_grant = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=AccountFactory(),
        capability_code="events.view_basic",
        target=_edition_target(edition),
        effective_from=timezone.now(),
        expires_at=None,
        reason="Pin the least-authority deterministic sources.",
        correlation_id=uuid4(),
    )

    final_issuance = AuthorityIssuance.objects.get(capability_grant=final_grant)
    pinned = {
        control.role: control.source_issuance_id
        for control in AuthorityControl.objects.filter(issuance=final_issuance)
    }
    expected_direct = {
        AuthorityControl.Role.ACTOR: AuthorityIssuance.objects.get(
            capability_grant=direct_sources[0]
        ).ordinal,
        AuthorityControl.Role.APPROVER: AuthorityIssuance.objects.get(
            capability_grant=direct_sources[1]
        ).ordinal,
    }
    assert pinned == expected_direct
    assert not set(pinned.values()) & {
        AuthorityIssuance.objects.get(role_assignment=source).ordinal
        for source in role_sources
    }


def test_commands_persist_exact_department_and_resource_scope() -> None:
    department, first_binding, second_binding = _scoped_positions()
    edition = department.edition
    organization = department.organization
    actor, approver = _dual_managers(
        organization,
        "authorization.grant_direct",
        edition=edition,
    )
    _grant_management(
        actor,
        organization,
        "authorization.revoke",
        edition=edition,
    )
    first_target = resolve_resource_target(
        organization_id=organization.id,
        edition_id=edition.id,
        department_id=department.id,
        resource_binding_id=first_binding.id,
    )
    second_target = resolve_resource_target(
        organization_id=organization.id,
        edition_id=edition.id,
        department_id=department.id,
        resource_binding_id=second_binding.id,
    )
    assert first_target is not None
    assert second_target is not None

    recipient = AccountFactory()
    grant_correlation = uuid4()
    grant = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=recipient,
        capability_code="events.view_basic",
        target=first_target,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Limit event visibility to one exact position.",
        correlation_id=grant_correlation,
    )
    assert grant.department_id == department.id
    assert grant.resource_binding_id == first_binding.id
    assert (
        DomainEvent.objects.get(correlation_id=grant_correlation).payload["scope_level"]
        == "resource"
    )
    assert decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=first_target,
    ).allowed
    assert not decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=second_target,
    ).allowed

    revoked = revoke_capability_grant(
        actor=actor,
        target=first_target,
        grant_id=grant.id,
        reason="End exact-position access.",
        correlation_id=uuid4(),
    )
    assert revoked.revoked_by_id == actor.id
    assert revoked.revocation_reason == "End exact-position access."
    assert not decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=first_target,
    ).allowed

    role_actor, role_approver = _dual_managers(
        organization,
        "authorization.manage_roles",
        edition=edition,
    )
    role_recipient = AccountFactory()
    role = _authorized_role_bundle(organization)
    department_target = resolve_department_target(
        organization_id=organization.id,
        edition_id=edition.id,
        department_id=department.id,
    )
    assert department_target is not None
    assignment_correlation = uuid4()
    assignment = assign_role(
        actor=role_actor,
        approver=role_approver,
        recipient=role_recipient,
        target=department_target,
        role_bundle_id=role.id,
        effective_from=timezone.now(),
        expires_at=None,
        reason="Cover one exact department.",
        correlation_id=assignment_correlation,
    )
    assert assignment.department_id == department.id
    assert assignment.resource_binding_id is None
    assert (
        DomainEvent.objects.get(correlation_id=assignment_correlation).payload[
            "scope_level"
        ]
        == "department"
    )
    assert decide(
        principal=role_recipient,
        capability_code="events.view_basic",
        resource=first_target,
    ).allowed
    assert decide(
        principal=role_recipient,
        capability_code="events.view_basic",
        resource=second_target,
    ).allowed


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
            target=_organization_target(organization),
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
    assert not AuthorityIssuance.objects.filter(
        capability_grant__principal=recipient,
        capability_grant__capability_code="events.view_basic",
    ).exists()
    assert not AuthorityControl.objects.filter(
        issuance__capability_grant__principal=recipient,
        issuance__capability_grant__capability_code="events.view_basic",
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
            target=_organization_target(organization),
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
            target=_organization_target(organization),
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
            target=_organization_target(organization),
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
    assert (
        resolve_edition_target(
            organization_id=organization.id,
            edition_id=uuid4(),
        )
        is None
    )

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
            target=_organization_target(organization),
            effective_from=timezone.now(),
            expires_at=None,
            reason="Do not duplicate active authority.",
            correlation_id=duplicate_correlation,
        )
    assert duplicate.value.reason_code == "active_grant_exists"


@pytest.mark.parametrize(
    "requested_expiry_delta",
    [timedelta(days=1, seconds=1), None],
    ids=("ends-after-controller", "unbounded-under-bounded-controller"),
)
def test_new_authority_cannot_outlive_either_controller(
    requested_expiry_delta: timedelta | None,
) -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    now = timezone.now()
    _bounded_management_grant(
        principal=actor,
        organization=organization,
        capability_code="authorization.grant_direct",
        expires_at=now + timedelta(days=2),
    )
    _bounded_management_grant(
        principal=approver,
        organization=organization,
        capability_code="authorization.grant_direct",
        expires_at=now + timedelta(days=1),
    )
    correlation_id = uuid4()
    requested_start = timezone.now()
    recipient = AccountFactory()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            target=_organization_target(organization),
            effective_from=requested_start,
            expires_at=(
                now + requested_expiry_delta
                if requested_expiry_delta is not None
                else None
            ),
            reason="The approver does not hold authority for this long.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "authority_expiry_too_early"
    assert set(captured.value.message_dict) == {"expires_at"}
    assert not CapabilityGrant.objects.filter(
        organization=organization,
        principal=recipient,
        capability_code="events.view_basic",
    ).exists()
    assert (
        AuditEvent.objects.get(correlation_id=correlation_id).reason_code
        == "authority_expiry_too_early"
    )


def test_new_authority_cannot_start_before_either_controller() -> None:
    organization = OrganizationFactory()
    _board_controllers(organization)
    actor = AccountFactory()
    approver = AccountFactory()
    controller_start = timezone.now()
    controller_expiry = controller_start + timedelta(days=2)
    for principal in (actor, approver):
        _bounded_management_grant(
            principal=principal,
            organization=organization,
            capability_code="authorization.grant_direct",
            effective_from=controller_start,
            expires_at=controller_expiry,
        )
    recipient = AccountFactory()
    correlation_id = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        grant_capability_direct(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code="events.view_basic",
            target=_organization_target(organization),
            effective_from=controller_start - timedelta(seconds=1),
            expires_at=controller_expiry,
            reason="The controllers do not hold authority this early.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "authority_effective_from_too_early"
    assert set(captured.value.message_dict) == {"effective_from"}
    assert not CapabilityGrant.objects.filter(
        organization=organization,
        principal=recipient,
        capability_code="events.view_basic",
    ).exists()
    assert (
        AuditEvent.objects.get(correlation_id=correlation_id).reason_code
        == "authority_effective_from_too_early"
    )


def test_new_authority_accepts_equal_controller_boundaries() -> None:
    organization = OrganizationFactory()
    _board_controllers(organization)
    actor = AccountFactory()
    approver = AccountFactory()
    controller_start = timezone.now()
    controller_expiry = controller_start + timedelta(days=2)
    for principal in (actor, approver):
        _bounded_management_grant(
            principal=principal,
            organization=organization,
            capability_code="authorization.grant_direct",
            effective_from=controller_start,
            expires_at=controller_expiry,
        )

    grant = grant_capability_direct(
        actor=actor,
        approver=approver,
        recipient=AccountFactory(),
        capability_code="events.view_basic",
        target=_organization_target(organization),
        effective_from=controller_start,
        expires_at=controller_expiry,
        reason="Use the controllers' exact inclusive boundaries.",
        correlation_id=uuid4(),
    )

    assert grant.effective_from == controller_start
    assert grant.expires_at == controller_expiry


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
        target=_edition_target(edition),
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
        resource=resolve_edition_target(
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
            target=_organization_target(own_organization),
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
            target=_organization_target(organization),
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
            target=_organization_target(organization),
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
        target=_organization_target(organization),
        code="front-desk-lead",
        name="Front Desk Lead",
        capability_codes=("events.view_basic",),
        reason="Create the first reviewed role definition.",
        correlation_id=first_correlation,
    )
    second = create_role_bundle_version(
        actor=actor,
        approver=approver,
        target=_organization_target(organization),
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


def test_generic_role_commands_cannot_manage_executive_board_authority() -> None:
    organization = OrganizationFactory()
    board = RoleBundleFactory(
        organization=organization,
        code=EXECUTIVE_BOARD_ROLE_CODE,
        name="Executive Board",
        capability_codes=[
            "authorization.manage_roles",
            "authorization.revoke",
        ],
    )
    controllers = (AccountFactory(), AccountFactory())
    assignments = tuple(
        RoleAssignment.objects.create(
            organization=organization,
            principal=controller,
            role_bundle=board,
            effective_from=timezone.now() - timedelta(minutes=1),
            granted_by=AccountFactory(),
            approved_by=controllers[(index + 1) % len(controllers)],
            reason="Synthetic Executive Board activation evidence.",
        )
        for index, controller in enumerate(controllers)
    )
    platform_administrators = (
        AccountFactory(is_staff=True, is_superuser=True),
        AccountFactory(is_staff=True, is_superuser=True),
    )

    for actor, approver in (controllers, platform_administrators):
        version_correlation = uuid4()
        with pytest.raises(AuthorityCommandValidationError) as reserved:
            create_role_bundle_version(
                actor=actor,
                approver=approver,
                target=_organization_target(organization),
                code=EXECUTIVE_BOARD_ROLE_CODE,
                name="Executive Board replacement",
                capability_codes=("authorization.manage_roles",),
                reason="Attempt a generic reserved-role version.",
                correlation_id=version_correlation,
            )
        assert reserved.value.reason_code == "reserved_role_code"
        assert (
            AuditEvent.objects.get(correlation_id=version_correlation).reason_code
            == "reserved_role_code"
        )

        recipient = AccountFactory()
        assign_correlation = uuid4()
        with pytest.raises(AuthorizationDenied) as unavailable:
            assign_role(
                actor=actor,
                approver=approver,
                recipient=recipient,
                target=_organization_target(organization),
                role_bundle_id=board.id,
                effective_from=timezone.now(),
                expires_at=None,
                reason="Attempt to share reserved Board authority.",
                correlation_id=assign_correlation,
            )
        assert unavailable.value.reason_code == "authority_source_unavailable"
        assert not RoleAssignment.objects.filter(
            organization=organization,
            principal=recipient,
        ).exists()

        revoke_correlation = uuid4()
        with pytest.raises(AuthorizationDenied) as protected:
            revoke_role_assignment(
                actor=actor,
                target=_organization_target(organization),
                assignment_id=assignments[1].id,
                reason="Attempt to revoke reserved Board authority.",
                correlation_id=revoke_correlation,
            )
        assert protected.value.reason_code == "authority_unavailable"

    assert (
        RoleBundle.objects.filter(
            organization=organization,
            code=EXECUTIVE_BOARD_ROLE_CODE,
        ).count()
        == 1
    )
    assert (
        RoleAssignment.objects.filter(
            organization=organization,
            role_bundle=board,
            revoked_at__isnull=True,
        ).count()
        == 2
    )


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
            target=_organization_target(organization),
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
            target=_organization_target(organization),
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
            target=_organization_target(organization),
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
            target=_organization_target(organization),
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
    assert not AuthorityIssuance.objects.filter(
        role_bundle__organization=organization,
        role_bundle__code="rolled-back-role",
    ).exists()
    assert not AuthorityControl.objects.filter(
        issuance__role_bundle__organization=organization,
        issuance__role_bundle__code="rolled-back-role",
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
    role = _authorized_role_bundle(
        edition.organization,
        code="edition-controller",
        capability_codes=("events.transition",),
    )
    assigned_correlation = uuid4()
    effective_from = timezone.now()

    assignment = assign_role(
        actor=actor,
        approver=approver,
        recipient=recipient,
        target=_edition_target(edition),
        role_bundle_id=role.id,
        effective_from=effective_from,
        expires_at=effective_from + timedelta(days=3),
        reason="Cover the event control duty.",
        correlation_id=assigned_correlation,
    )

    assert assignment.approved_by == approver
    assert decide(
        principal=recipient,
        capability_code="events.transition",
        resource=resolve_edition_target(
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
        target=_edition_target(edition),
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
        resource=resolve_edition_target(
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
    edition_role = _authorized_role_bundle(
        organization,
        capability_codes=("events.transition",),
    )

    with pytest.raises(AuthorityCommandValidationError) as missing_scope:
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            target=_organization_target(organization),
            role_bundle_id=edition_role.id,
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
            target=_organization_target(organization),
            role_bundle_id=other_role.id,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Attempt cross-tenant role use.",
            correlation_id=correlation_id,
        )
    assert unavailable.value.reason_code == "role_bundle_unavailable"
    assert not RoleAssignment.objects.filter(principal=recipient).exists()
    denial = AuditEvent.objects.get(correlation_id=correlation_id)
    assert denial.outcome == AuditEvent.Outcome.DENY


def test_role_assignment_rejects_unproven_bundle_without_orphan_evidence() -> None:
    organization = OrganizationFactory()
    actor, approver = _board_controllers(organization)
    unproven = RoleBundleFactory(organization=organization)
    recipient = AccountFactory()
    issuance_count = AuthorityIssuance.objects.count()
    control_count = AuthorityControl.objects.count()
    correlation_id = uuid4()

    with pytest.raises(AuthorizationDenied) as captured:
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            target=_organization_target(organization),
            role_bundle_id=unproven.id,
            effective_from=timezone.now(),
            expires_at=None,
            reason="An unproven definition cannot establish current authority.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "role_bundle_unavailable"
    assert not RoleAssignment.objects.filter(
        role_bundle=unproven,
        principal=recipient,
    ).exists()
    assert AuthorityIssuance.objects.count() == issuance_count
    assert AuthorityControl.objects.count() == control_count
    denial = AuditEvent.objects.get(correlation_id=correlation_id)
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert denial.reason_code == "role_bundle_unavailable"


def test_role_assignment_duplicate_and_effect_failures_roll_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    actor, approver = _dual_managers(
        organization,
        "authorization.manage_roles",
    )
    recipient = AccountFactory()
    role = _authorized_role_bundle(organization)
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
            target=_organization_target(organization),
            role_bundle_id=role.id,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Do not duplicate active assignments.",
            correlation_id=duplicate_correlation,
        )
    assert duplicate.value.reason_code == "active_assignment_exists"

    existing.revoked_at = timezone.now()
    existing.revoked_by = actor
    existing.revocation_reason = "Synthetic completed assignment."
    existing.save(
        update_fields=(
            "revoked_at",
            "revoked_by",
            "revocation_reason",
            "updated_at",
        )
    )

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
            target=_organization_target(organization),
            role_bundle_id=role.id,
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
    assert not AuthorityIssuance.objects.filter(
        role_assignment__principal=recipient,
        role_assignment__role_bundle=role,
    ).exists()
    assert not AuthorityControl.objects.filter(
        issuance__role_assignment__principal=recipient,
        issuance__role_assignment__role_bundle=role,
    ).exists()
    assert (
        AuditEvent.objects.get(correlation_id=failed_correlation).reason_code
        == "role_assignment_failed"
    )


def test_role_assignment_cannot_outlive_role_management_authority() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    recipient = AccountFactory()
    role = _authorized_role_bundle(organization)
    now = timezone.now()
    management_role = _authorized_role_bundle(
        organization,
        capability_codes=("authorization.manage_roles",),
    )
    board_actor, board_approver = _board_controllers(organization)
    for principal, expires_at in (
        (actor, now + timedelta(days=3)),
        (approver, now + timedelta(days=1)),
    ):
        assign_role(
            actor=board_actor,
            approver=board_approver,
            recipient=principal,
            target=_organization_target(organization),
            role_bundle_id=management_role.id,
            effective_from=now,
            expires_at=expires_at,
            reason="Create bounded role-management authority.",
            correlation_id=uuid4(),
            source_channel="test",
        )
    correlation_id = uuid4()

    with pytest.raises(AuthorityCommandValidationError) as captured:
        assign_role(
            actor=actor,
            approver=approver,
            recipient=recipient,
            target=_organization_target(organization),
            role_bundle_id=role.id,
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
            target=_organization_target(own_organization),
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
        revoked_by=actor,
        revocation_reason="Synthetic prior revocation.",
        granted_by=AccountFactory(),
        reason="Already revoked.",
    )
    repeat_correlation = uuid4()
    with pytest.raises(AuthorityCommandValidationError) as repeated:
        revoke_role_assignment(
            actor=actor,
            target=_organization_target(own_organization),
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
            target=_organization_target(own_organization),
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
