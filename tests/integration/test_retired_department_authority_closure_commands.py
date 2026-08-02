"""Close-only services for expired authority below retired Departments."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.authorization.bindings import ensure_workforce_position_binding
from maru.authorization.commands import (
    grant_capability_direct,
    revoke_expired_retired_department_capability_grant,
    revoke_expired_retired_department_role_assignment,
)
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_edition_target,
    resolve_organization_target,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.models import DomainEvent
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import (
    Department,
    EditionStructureControl,
    Position,
    PositionTemplate,
)
from maru.workforce.structure_commands import retire_department
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
    RoleAssignmentFactory,
    RoleBundleFactory,
)
from tests.support.authority import activate_synthetic_board
from tests.workforce_helpers import create_department_for_test, save_position_for_test

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def _edition_target(edition: EventEdition) -> ResolvedAuthorizationTarget:
    target = resolve_edition_target(
        organization_id=edition.organization_id,
        edition_id=edition.id,
    )
    assert target is not None
    return target


def _organization_target(
    organization: Organization,
) -> ResolvedAuthorizationTarget:
    target = resolve_organization_target(organization_id=organization.id)
    assert target is not None
    return target


def _grant_revoke_authority(*, actor: Account, edition: EventEdition) -> None:
    controller, approver = activate_synthetic_board(edition.organization)
    grant_capability_direct(
        actor=controller,
        approver=approver,
        recipient=actor,
        capability_code="authorization.revoke",
        target=_edition_target(edition),
        effective_from=timezone.now(),
        expires_at=None,
        reason="Authorize exact-scope historical authority closure.",
        correlation_id=uuid4(),
        source_channel="test",
    )


def _department(edition: EventEdition, *, code: str) -> Department:
    return create_department_for_test(
        edition=edition,
        name=code.replace("-", " ").title(),
        expected_code=code,
    )


def _retire(department: Department, *, actor: Account) -> None:
    current_version = EditionStructureControl.objects.get(
        organization=department.organization,
        edition=department.edition,
    ).aggregate_version
    retire_department(
        actor=actor,
        organization_id=department.organization_id,
        series_id=department.edition.series_id,
        edition_id=department.edition_id,
        department_id=department.id,
        expected_version=current_version,
        reason="Retire the synthetic historical authority scope.",
        correlation_id=uuid4(),
        source_channel="test",
    )
    department.refresh_from_db()
    assert department.retired_at is not None


def _resource_position(
    *,
    department: Department,
    actor: Account,
) -> Position:
    role = RoleBundleFactory(
        organization=department.organization,
        capability_codes=["workforce.view_structure"],
    )
    template = PositionTemplate.objects.create(
        organization=department.organization,
        code="historical-helper",
        name="Historical helper",
        description="Synthetic resource-scope closure target.",
        default_capacity_codes=["volunteer"],
        role_bundle=role,
        created_by=actor,
    )
    return save_position_for_test(
        position=Position(
            organization=department.organization,
            edition=department.edition,
            template=template,
            department=department,
            role_bundle=role,
            code="historical-helper",
            title="Historical helper",
            description="Synthetic resource-scope closure target.",
            capacity_codes=["volunteer"],
            status=Position.Status.CLOSED,
            created_by=actor,
        )
    )


def test_authorized_actor_closes_expired_resource_grant_at_current_edition() -> None:
    edition = EventEditionFactory()
    creator = AccountFactory(is_staff=True, is_superuser=True)
    actor = AccountFactory()
    _grant_revoke_authority(actor=actor, edition=edition)
    department = _department(edition, code="grant-history")
    position = _resource_position(department=department, actor=creator)
    binding = ensure_workforce_position_binding(position=position)
    now = timezone.now()
    grant = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        resource_binding=binding,
        capability_code="workforce.view_structure",
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    authority_count = CapabilityGrant.objects.count()
    _retire(department, actor=creator)
    correlation_id = uuid4()

    closed = revoke_expired_retired_department_capability_grant(
        actor=actor,
        containing_target=_edition_target(edition),
        grant_id=grant.id,
        reason="Close the retained expired resource grant.",
        correlation_id=correlation_id,
        source_channel="test",
    )

    assert closed.revoked_at is not None
    assert closed.revoked_by_id == actor.id
    assert closed.revocation_reason == "Close the retained expired resource grant."
    assert CapabilityGrant.objects.count() == authority_count
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.organization_id == edition.organization_id
    assert audit.event_edition_id == edition.id
    assert audit.target_id == grant.id
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    assert event.organization_id == edition.organization_id
    assert event.event_edition_id == edition.id
    assert event.payload["scope_level"] == "resource"


def test_platform_actor_closes_expired_role_at_current_organization() -> None:
    edition = EventEditionFactory()
    creator = AccountFactory(is_staff=True, is_superuser=True)
    platform_actor = AccountFactory(is_staff=True, is_superuser=True)
    department = _department(edition, code="role-history")
    role = RoleBundleFactory(
        organization=edition.organization,
        code="retained-role-history",
        capability_codes=["workforce.view_structure"],
    )
    now = timezone.now()
    assignment = RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        role_bundle=role,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    assignment_count = RoleAssignment.objects.count()
    _retire(department, actor=creator)
    correlation_id = uuid4()

    closed = revoke_expired_retired_department_role_assignment(
        actor=platform_actor,
        containing_target=_organization_target(edition.organization),
        assignment_id=assignment.id,
        reason="Close retained expired role history.",
        correlation_id=correlation_id,
        source_channel="test",
    )

    assert closed.revoked_at is not None
    assert closed.revoked_by_id == platform_actor.id
    assert RoleAssignment.objects.count() == assignment_count
    audit = AuditEvent.objects.get(correlation_id=correlation_id)
    assert audit.organization_id == edition.organization_id
    assert audit.event_edition_id == edition.id
    event = DomainEvent.objects.get(correlation_id=correlation_id)
    assert event.payload["scope_level"] == "department"


def test_retired_history_closure_hides_wrong_tenant_and_wrong_edition() -> None:
    edition = EventEditionFactory()
    wrong_edition = EventEditionFactory(series__organization=edition.organization)
    wrong_organization = OrganizationFactory()
    creator = AccountFactory(is_staff=True, is_superuser=True)
    platform_actor = AccountFactory(is_staff=True, is_superuser=True)
    department = _department(edition, code="contained-history")
    role = RoleBundleFactory(
        organization=edition.organization,
        code="contained-role-history",
        capability_codes=["workforce.view_structure"],
    )
    now = timezone.now()
    grant = CapabilityGrantFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        capability_code="workforce.view_structure",
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    assignment = RoleAssignmentFactory(
        organization=edition.organization,
        edition=edition,
        department=department,
        role_bundle=role,
        effective_from=now - timedelta(days=2),
        expires_at=now - timedelta(days=1),
    )
    _retire(department, actor=creator)
    wrong_tenant_correlation = uuid4()
    wrong_edition_correlation = uuid4()

    with pytest.raises(AuthorizationDenied) as wrong_tenant:
        revoke_expired_retired_department_capability_grant(
            actor=platform_actor,
            containing_target=_organization_target(wrong_organization),
            grant_id=grant.id,
            reason="Attempt cross-tenant closure.",
            correlation_id=wrong_tenant_correlation,
            source_channel="test",
        )
    with pytest.raises(AuthorizationDenied) as wrong_scope:
        revoke_expired_retired_department_role_assignment(
            actor=platform_actor,
            containing_target=_edition_target(wrong_edition),
            assignment_id=assignment.id,
            reason="Attempt closure from another edition.",
            correlation_id=wrong_edition_correlation,
            source_channel="test",
        )

    assert wrong_tenant.value.reason_code == "authority_unavailable"
    assert wrong_scope.value.reason_code == "authority_unavailable"
    grant.refresh_from_db()
    assignment.refresh_from_db()
    assert grant.revoked_at is None
    assert assignment.revoked_at is None
    tenant_denial = AuditEvent.objects.get(correlation_id=wrong_tenant_correlation)
    scope_denial = AuditEvent.objects.get(correlation_id=wrong_edition_correlation)
    assert tenant_denial.organization_id == wrong_organization.id
    assert scope_denial.event_edition_id == wrong_edition.id
