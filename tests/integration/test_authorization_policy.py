from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.models import (
    CapabilityGrant,
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
    resolve_self_target,
)
from maru.authorization.services import AuthorizationDenied, delegate_capability
from maru.effects.models import DomainEvent, OutboxMessage
from maru.identity.models import Account
from maru.workforce.models import Department, Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _target(
    *,
    organization_id: UUID,
    edition_id: UUID | None = None,
    owner_account_id: UUID | None = None,
) -> ResolvedAuthorizationTarget:
    if owner_account_id is not None:
        owner = Account.objects.get(pk=owner_account_id)
        target = resolve_self_target(
            principal=owner,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    elif edition_id is not None:
        target = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
    else:
        target = resolve_organization_target(organization_id=organization_id)
    assert target is not None
    return target


def _workforce_resources() -> tuple[
    Department,
    Position,
    ScopedResourceBinding,
    Position,
    ScopedResourceBinding,
]:
    edition = EventEditionFactory()
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(organization=edition.organization)
    department = Department.objects.create(
        organization=edition.organization,
        edition=edition,
        code=f"operations-{uuid4().hex[:8]}",
        name="Operations",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code=f"operations-role-{uuid4().hex[:8]}",
        name="Operations role",
        description="Synthetic authorization scope target.",
        default_capacity_codes=["staff"],
        role_bundle=role_bundle,
        created_by=creator,
    )

    def create_position(code: str) -> tuple[Position, ScopedResourceBinding]:
        position = Position.objects.create(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code=code,
            title=code.replace("-", " ").title(),
            description="Synthetic exact resource target.",
            capacity_codes=["staff"],
            created_by=creator,
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
        return position, binding

    first_position, first_binding = create_position(
        f"operations-lead-{uuid4().hex[:8]}"
    )
    second_position, second_binding = create_position(
        f"operations-deputy-{uuid4().hex[:8]}"
    )
    return (
        department,
        first_position,
        first_binding,
        second_position,
        second_binding,
    )


def _grant_delegation_authority(actor: object, organization: object) -> None:
    CapabilityGrantFactory(
        principal=actor,
        organization=organization,
        capability_code="authorization.delegate",
    )


def test_direct_organization_grant_covers_an_edition_and_limits_fields() -> None:
    edition = EventEditionFactory()
    principal = AccountFactory()
    CapabilityGrantFactory(
        principal=principal,
        organization=edition.organization,
        capability_code="events.view_basic",
    )

    decision = decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
        requested_fields=frozenset({"name", "lifecycle", "email"}),
    )

    assert decision.allowed
    assert decision.fields == frozenset({"name", "lifecycle"})
    assert decision.reason_code == "direct_grant"
    assert decision.policy_version


def test_edition_grant_does_not_cover_organization_or_other_edition() -> None:
    first = EventEditionFactory()
    second = EventEditionFactory(
        organization=first.organization,
        series__organization=first.organization,
    )
    principal = AccountFactory()
    CapabilityGrantFactory(
        principal=principal,
        organization=first.organization,
        edition=first,
    )

    assert decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=first.organization_id,
            edition_id=first.id,
        ),
    ).allowed
    assert not decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=_target(organization_id=first.organization_id),
    ).allowed
    assert not decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=first.organization_id,
            edition_id=second.id,
        ),
    ).allowed


def test_wrong_tenant_expired_and_revoked_grants_deny() -> None:
    edition = EventEditionFactory()
    principal = AccountFactory()
    other_organization = OrganizationFactory()
    now = timezone.now()
    CapabilityGrantFactory(
        principal=principal,
        organization=edition.organization,
        expires_at=now - timedelta(seconds=1),
        effective_from=now - timedelta(days=1),
    )
    CapabilityGrantFactory(
        principal=principal,
        organization=edition.organization,
        revoked_at=now,
        revoked_by=AccountFactory(),
        revocation_reason="Synthetic revoked authority.",
        effective_from=now - timedelta(days=1),
    )
    CapabilityGrantFactory(
        principal=principal,
        organization=other_organization,
    )

    decision = decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
        at=now,
    )

    assert not decision.allowed
    assert decision.fields == frozenset()
    assert decision.reason_code == "permission_absent"


def test_self_relationship_is_explicit_without_persistent_grant() -> None:
    account = AccountFactory()
    organization = OrganizationFactory()

    own = decide(
        principal=account,
        capability_code="participation.view_self",
        resource=_target(
            organization_id=organization.id,
            owner_account_id=account.id,
        ),
    )
    other = decide(
        principal=account,
        capability_code="participation.view_self",
        resource=_target(
            organization_id=organization.id,
            owner_account_id=AccountFactory().id,
        ),
    )

    assert own.allowed
    assert own.reason_code == "self_relationship"
    assert not other.allowed


def test_inactive_account_cannot_use_self_relationship() -> None:
    account = AccountFactory(is_active=False)
    organization = OrganizationFactory()

    decision = decide(
        principal=account,
        capability_code="participation.view_self",
        resource=_target(
            organization_id=organization.id,
            owner_account_id=account.id,
        ),
    )

    assert not decision.allowed
    assert decision.fields == frozenset()
    assert decision.obligations == frozenset()
    assert decision.reason_code == "account_inactive"


def test_inactive_account_cannot_use_direct_grant() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    CapabilityGrantFactory(
        principal=account,
        organization=edition.organization,
        capability_code="events.view_basic",
    )
    account.is_active = False
    account.save(update_fields=("is_active",))

    decision = decide(
        principal=account,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    )

    assert not decision.allowed
    assert decision.fields == frozenset()
    assert decision.obligations == frozenset()
    assert decision.reason_code == "account_inactive"


def test_inactive_account_cannot_use_role_assignment() -> None:
    edition = EventEditionFactory()
    account = AccountFactory()
    bundle = RoleBundleFactory(organization=edition.organization)
    RoleAssignmentFactory(
        organization=edition.organization,
        principal=account,
        role_bundle=bundle,
    )
    account.is_active = False
    account.save(update_fields=("is_active",))

    decision = decide(
        principal=account,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    )

    assert not decision.allowed
    assert decision.fields == frozenset()
    assert decision.obligations == frozenset()
    assert decision.reason_code == "account_inactive"


def test_inactive_platform_administrator_is_denied_by_policy() -> None:
    edition = EventEditionFactory()
    administrator = AccountFactory(is_staff=True, is_superuser=True)
    administrator.is_active = False
    administrator.save(update_fields=("is_active",))

    decision = decide(
        principal=administrator,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    )

    assert not decision.allowed
    assert decision.fields == frozenset()
    assert decision.obligations == frozenset()
    assert decision.reason_code == "account_inactive"


def test_unknown_capability_is_deny_by_default() -> None:
    decision = decide(
        principal=AccountFactory(),
        capability_code="unknown.do_anything",
        resource=_target(organization_id=OrganizationFactory().id),
    )

    assert not decision.allowed
    assert decision.reason_code == "unknown_capability"


def test_only_server_resolved_targets_reach_policy() -> None:
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    with pytest.raises(TypeError, match="explicit persisted target resolver"):
        ResolvedAuthorizationTarget()

    forged = object.__new__(ResolvedAuthorizationTarget)
    for unavailable in (None, forged):
        decision = decide(
            principal=administrator,
            capability_code="events.view_basic",
            resource=unavailable,
        )
        assert not decision.allowed
        assert decision.reason_code == "target_unavailable"


def test_resolvers_reject_missing_foreign_and_platform_self_targets() -> None:
    edition = EventEditionFactory()
    foreign_edition = EventEditionFactory()
    administrator = AccountFactory(is_staff=True, is_superuser=True)

    assert (
        resolve_edition_target(
            organization_id=foreign_edition.organization_id,
            edition_id=edition.id,
        )
        is None
    )
    assert resolve_organization_target(organization_id=uuid4()) is None
    assert (
        resolve_self_target(
            principal=administrator,
            organization_id=edition.organization_id,
            edition_id=edition.id,
        )
        is None
    )


def test_department_scope_is_exact_without_hierarchy_inheritance() -> None:
    department, *_ = _workforce_resources()
    child = Department.objects.create(
        organization=department.organization,
        edition=department.edition,
        parent=department,
        code=f"operations-child-{uuid4().hex[:8]}",
        name="Operations child",
    )
    principal = AccountFactory()
    CapabilityGrantFactory(
        principal=principal,
        organization=department.organization,
        edition=department.edition,
        department=department,
    )
    parent_target = resolve_department_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
    )
    child_target = resolve_department_target(
        organization_id=child.organization_id,
        edition_id=child.edition_id,
        department_id=child.id,
    )
    assert parent_target is not None
    assert child_target is not None

    assert decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=parent_target,
    ).allowed
    assert not decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=child_target,
    ).allowed


def test_resource_grants_are_exact_and_parent_scopes_cover_resources() -> None:
    department, _, first_binding, _, second_binding = _workforce_resources()
    exact_principal = AccountFactory()
    department_principal = AccountFactory()
    CapabilityGrantFactory(
        principal=exact_principal,
        organization=department.organization,
        edition=department.edition,
        department=department,
        resource_binding=first_binding,
    )
    CapabilityGrantFactory(
        principal=department_principal,
        organization=department.organization,
        edition=department.edition,
        department=department,
    )
    first_target = resolve_resource_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
        resource_binding_id=first_binding.id,
    )
    second_target = resolve_resource_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
        resource_binding_id=second_binding.id,
    )
    department_target = resolve_department_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
    )
    assert first_target is not None
    assert second_target is not None
    assert department_target is not None

    assert decide(
        principal=exact_principal,
        capability_code="events.view_basic",
        resource=first_target,
    ).allowed
    assert not decide(
        principal=exact_principal,
        capability_code="events.view_basic",
        resource=second_target,
    ).allowed
    assert not decide(
        principal=exact_principal,
        capability_code="events.view_basic",
        resource=department_target,
    ).allowed
    assert decide(
        principal=department_principal,
        capability_code="events.view_basic",
        resource=first_target,
    ).allowed
    assert decide(
        principal=department_principal,
        capability_code="events.view_basic",
        resource=second_target,
    ).allowed


def test_role_assignments_use_the_same_exact_resource_containment() -> None:
    department, _, first_binding, _, second_binding = _workforce_resources()
    principal = AccountFactory()
    bundle = RoleBundleFactory(organization=department.organization)
    RoleAssignmentFactory(
        organization=department.organization,
        edition=department.edition,
        department=department,
        resource_binding=first_binding,
        principal=principal,
        role_bundle=bundle,
    )
    first_target = resolve_resource_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
        resource_binding_id=first_binding.id,
    )
    second_target = resolve_resource_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
        resource_binding_id=second_binding.id,
    )
    assert first_target is not None
    assert second_target is not None

    assert decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=first_target,
    ).allowed
    assert not decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=second_target,
    ).allowed


def test_versioned_role_assignment_provides_capability() -> None:
    edition = EventEditionFactory()
    principal = AccountFactory()
    bundle = RoleBundleFactory(organization=edition.organization)
    RoleAssignmentFactory(
        organization=edition.organization,
        principal=principal,
        role_bundle=bundle,
    )

    decision = decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    )

    assert decision.allowed
    assert decision.reason_code == "role_assignment"


def test_scope_models_reject_incompatible_edition_and_role() -> None:
    grant = CapabilityGrantFactory()
    other_edition = EventEditionFactory()
    with transaction.atomic(), pytest.raises(IntegrityError):
        CapabilityGrant.objects.filter(pk=grant.pk).update(edition=other_edition)

    bundle = RoleBundleFactory()
    with pytest.raises(ValidationError, match="another organization"):
        RoleAssignmentFactory(
            organization=OrganizationFactory(),
            role_bundle=bundle,
        )


def test_role_bundle_version_is_immutable_in_model_and_database() -> None:
    bundle = RoleBundleFactory()
    bundle.name = "Changed"
    with pytest.raises(ValidationError, match="new version"):
        bundle.save()

    with transaction.atomic(), pytest.raises(IntegrityError):
        RoleBundle.objects.filter(pk=bundle.pk).update(name="Raw change")


def test_scope_ceiling_requires_edition_and_rejects_self_capability_grant() -> None:
    with pytest.raises(ValidationError, match="requires edition"):
        CapabilityGrantFactory(
            capability_code="events.transition",
            edition=None,
        )

    with pytest.raises(ValidationError, match="relationship-derived"):
        CapabilityGrantFactory(
            capability_code="participation.view_self",
        )


def test_delegation_must_be_narrower_and_not_outlive_parent() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    parent = CapabilityGrantFactory(
        principal=actor,
        granted_by=AccountFactory(),
        organization=edition.organization,
        effective_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=2),
    )
    _grant_delegation_authority(actor, edition.organization)

    correlation_id = uuid4()
    child = delegate_capability(
        actor=actor,
        recipient=recipient,
        parent_grant_id=parent.id,
        target=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
        effective_from=now,
        expires_at=now + timedelta(days=1),
        reason="Cover one edition.",
        correlation_id=correlation_id,
    )

    assert child.delegated_from_id == parent.id
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    assert audit.outcome == AuditEvent.Outcome.ALLOW
    assert audit.target_id == child.id
    assert event.aggregate_id == child.id
    assert event.causation_id == audit.id
    assert event.payload == {
        "capability_code": "events.view_basic",
        "scope_level": "edition",
    }
    assert OutboxMessage.objects.get(event=event).workload_pool == "security"
    assert decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    ).allowed

    with pytest.raises(AuthorizationDenied) as wrong_scope:
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            target=_target(organization_id=OrganizationFactory().id),
            effective_from=now,
            expires_at=now + timedelta(days=1),
            reason="Too broad.",
            correlation_id=uuid4(),
        )
    assert wrong_scope.value.reason_code == "delegation_scope_too_broad"

    with pytest.raises(AuthorizationDenied) as too_long:
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            target=_target(organization_id=edition.organization_id),
            effective_from=now,
            expires_at=None,
            reason="No expiry.",
            correlation_id=uuid4(),
        )
    assert too_long.value.reason_code == "delegation_expiry_too_late"


def test_delegation_preserves_exact_department_and_resource_containment() -> None:
    department, _, first_binding, _, second_binding = _workforce_resources()
    actor = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    parent = CapabilityGrantFactory(
        principal=actor,
        granted_by=AccountFactory(),
        organization=department.organization,
        edition=department.edition,
        department=department,
        effective_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=2),
    )
    _grant_delegation_authority(actor, department.organization)
    first_target = resolve_resource_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
        resource_binding_id=first_binding.id,
    )
    second_target = resolve_resource_target(
        organization_id=department.organization_id,
        edition_id=department.edition_id,
        department_id=department.id,
        resource_binding_id=second_binding.id,
    )
    assert first_target is not None
    assert second_target is not None

    child = delegate_capability(
        actor=actor,
        recipient=recipient,
        parent_grant_id=parent.id,
        target=first_target,
        effective_from=now,
        expires_at=now + timedelta(days=1),
        reason="Delegate one exact workforce position.",
        correlation_id=uuid4(),
    )
    assert child.department_id == department.id
    assert child.resource_binding_id == first_binding.id
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

    resource_actor = AccountFactory()
    exact_parent = CapabilityGrantFactory(
        principal=resource_actor,
        granted_by=AccountFactory(),
        organization=department.organization,
        edition=department.edition,
        department=department,
        resource_binding=first_binding,
        effective_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=2),
    )
    _grant_delegation_authority(resource_actor, department.organization)
    with pytest.raises(AuthorizationDenied) as sibling_scope:
        delegate_capability(
            actor=resource_actor,
            recipient=AccountFactory(),
            parent_grant_id=exact_parent.id,
            target=second_target,
            effective_from=now,
            expires_at=now + timedelta(days=1),
            reason="Attempt a sibling position.",
            correlation_id=uuid4(),
        )
    assert sibling_scope.value.reason_code == "delegation_scope_too_broad"


def test_delegation_requires_separate_meta_authority_and_audits_denial() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    recipient = AccountFactory()
    parent = CapabilityGrantFactory(
        principal=actor,
        organization=edition.organization,
    )
    correlation_id = uuid4()

    with pytest.raises(AuthorizationDenied) as captured:
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            target=_target(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            ),
            effective_from=timezone.now(),
            expires_at=None,
            reason="Attempt without delegation authority.",
            correlation_id=correlation_id,
        )

    assert captured.value.reason_code == "delegation_permission_absent"
    denial = AuditEvent.objects.get(correlation_id=correlation_id)
    assert denial.outcome == AuditEvent.Outcome.DENY
    assert denial.target_id == recipient.id
    assert not DomainEvent.objects.filter(correlation_id=correlation_id).exists()
    assert not CapabilityGrant.objects.filter(
        delegated_from=parent,
        principal=recipient,
    ).exists()


def test_delegation_outbox_failure_rolls_back_grant_and_records_safe_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    parent = CapabilityGrantFactory(
        principal=actor,
        organization=edition.organization,
        effective_from=now - timedelta(minutes=1),
    )
    _grant_delegation_authority(actor, edition.organization)
    correlation_id = uuid4()

    def fail_publish(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic effect failure")

    monkeypatch.setattr(
        "maru.authorization.services.publish_domain_event",
        fail_publish,
    )

    with pytest.raises(RuntimeError, match="synthetic effect"):
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            target=_target(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            ),
            effective_from=now,
            expires_at=None,
            reason="Temporary scoped access.",
            correlation_id=correlation_id,
        )

    assert not CapabilityGrant.objects.filter(
        delegated_from=parent,
        principal=recipient,
    ).exists()
    assert not DomainEvent.objects.filter(correlation_id=correlation_id).exists()
    failure = AuditEvent.objects.get(correlation_id=correlation_id)
    assert failure.outcome == AuditEvent.Outcome.ERROR
    assert failure.reason_code == "delegation_failed"


def test_revoked_parent_invalidates_delegated_child() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    recipient = AccountFactory()
    now = timezone.now()
    parent = CapabilityGrantFactory(
        principal=actor,
        organization=edition.organization,
        effective_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=2),
    )
    _grant_delegation_authority(actor, edition.organization)
    delegate_capability(
        actor=actor,
        recipient=recipient,
        parent_grant_id=parent.id,
        target=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
        effective_from=now,
        expires_at=now + timedelta(days=1),
        reason="Temporary event access.",
        correlation_id=uuid4(),
    )
    parent.revoked_at = timezone.now()
    parent.revoked_by = AccountFactory()
    parent.revocation_reason = "Synthetic parent revocation."
    parent.save(
        update_fields=(
            "revoked_at",
            "revoked_by",
            "revocation_reason",
            "updated_at",
        )
    )

    decision = decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=_target(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    )

    assert not decision.allowed


def test_non_delegable_capability_stays_non_delegable() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    now = timezone.now()
    parent = CapabilityGrantFactory(
        principal=actor,
        organization=edition.organization,
        edition=edition,
        capability_code="events.transition",
        effective_from=now - timedelta(minutes=1),
    )

    with pytest.raises(AuthorizationDenied) as captured:
        delegate_capability(
            actor=actor,
            recipient=AccountFactory(),
            parent_grant_id=parent.id,
            target=_target(
                organization_id=edition.organization_id,
                edition_id=edition.id,
            ),
            effective_from=now,
            expires_at=None,
            reason="Attempt non-delegable capability.",
            correlation_id=uuid4(),
        )
    assert captured.value.reason_code == "capability_not_delegable"
