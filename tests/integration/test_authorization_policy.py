from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.models import CapabilityGrant, RoleBundle
from maru.authorization.policy import ResourceScope, decide
from maru.authorization.services import AuthorizationDenied, delegate_capability
from maru.effects.models import DomainEvent, OutboxMessage
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


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
        resource=ResourceScope(
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
        resource=ResourceScope(
            organization_id=first.organization_id,
            edition_id=first.id,
        ),
    ).allowed
    assert not decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=ResourceScope(organization_id=first.organization_id),
    ).allowed
    assert not decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=ResourceScope(
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
        effective_from=now - timedelta(days=1),
    )
    CapabilityGrantFactory(
        principal=principal,
        organization=other_organization,
    )

    decision = decide(
        principal=principal,
        capability_code="events.view_basic",
        resource=ResourceScope(
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
        resource=ResourceScope(
            organization_id=organization.id,
            owner_account_id=account.id,
        ),
    )
    other = decide(
        principal=account,
        capability_code="participation.view_self",
        resource=ResourceScope(
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
        resource=ResourceScope(
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
        resource=ResourceScope(
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
        resource=ResourceScope(
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
        resource=ResourceScope(
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
        resource=ResourceScope(organization_id=OrganizationFactory().id),
    )

    assert not decision.allowed
    assert decision.reason_code == "unknown_capability"


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
        resource=ResourceScope(
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
        organization_id=edition.organization_id,
        edition_id=edition.id,
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
        resource=ResourceScope(
            organization_id=edition.organization_id,
            edition_id=edition.id,
        ),
    ).allowed

    with pytest.raises(AuthorizationDenied) as wrong_scope:
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            organization_id=OrganizationFactory().id,
            edition_id=None,
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
            organization_id=edition.organization_id,
            edition_id=None,
            effective_from=now,
            expires_at=None,
            reason="No expiry.",
            correlation_id=uuid4(),
        )
    assert too_long.value.reason_code == "delegation_expiry_too_late"


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
            organization_id=edition.organization_id,
            edition_id=edition.id,
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
            organization_id=edition.organization_id,
            edition_id=edition.id,
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
        organization_id=edition.organization_id,
        edition_id=edition.id,
        effective_from=now,
        expires_at=now + timedelta(days=1),
        reason="Temporary event access.",
        correlation_id=uuid4(),
    )
    parent.revoked_at = timezone.now()
    parent.save()

    decision = decide(
        principal=recipient,
        capability_code="events.view_basic",
        resource=ResourceScope(
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
            organization_id=edition.organization_id,
            edition_id=edition.id,
            effective_from=now,
            expires_at=None,
            reason="Attempt non-delegable capability.",
            correlation_id=uuid4(),
        )
    assert captured.value.reason_code == "capability_not_delegable"
