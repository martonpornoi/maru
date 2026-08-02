"""Fail-closed runtime branches for ADR 0041 authorization scope v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

import maru.authorization.commands as authority_commands
import maru.authorization.policy as authorization_policy
import maru.authorization.services as delegation_services
from maru.authorization.bindings import ensure_workforce_position_binding
from maru.authorization.commands import (
    AuthorityCommandValidationError,
    create_role_bundle_version,
)
from maru.authorization.models import (
    AuthorizationScopeWriteFence,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
    ScopedResourceBinding,
    validate_capability_codes,
)
from maru.authorization.policy import (
    PolicyDecision,
    ResolvedAuthorizationTarget,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_owned_target,
    resolve_resource_target,
    resolve_self_target,
)
from maru.authorization.services import AuthorizationDenied, delegate_capability
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import Department, Position, PositionTemplate
from tests.factories import (
    AccountFactory,
    CapabilityGrantFactory,
    EventEditionFactory,
    OrganizationFactory,
    OrganizationMembershipFactory,
    ParticipationFactory,
    RoleBundleFactory,
)
from tests.workforce_helpers import (
    create_department_for_test,
    save_position_for_test,
)

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.integration,
]


@dataclass(frozen=True, slots=True)
class _ExactScope:
    edition: EventEdition
    department: Department
    position: Position
    binding: ScopedResourceBinding


def _exact_scope() -> _ExactScope:
    edition = EventEditionFactory()
    creator = AccountFactory()
    role_bundle = RoleBundleFactory(organization=edition.organization)
    department = create_department_for_test(
        edition=edition,
        name="Scope runtime",
        expected_code="scope-runtime",
    )
    template = PositionTemplate.objects.create(
        organization=edition.organization,
        code=f"scope-runtime-{uuid4().hex[:8]}",
        name="Scope runtime position",
        description="Synthetic runtime-branch position template.",
        default_capacity_codes=["staff"],
        role_bundle=role_bundle,
        created_by=creator,
    )
    position = save_position_for_test(
        position=Position(
            organization=edition.organization,
            edition=edition,
            template=template,
            department=department,
            role_bundle=role_bundle,
            code=f"scope-runtime-{uuid4().hex[:8]}",
            title="Scope runtime position",
            description="Synthetic runtime-branch position.",
            capacity_codes=["staff"],
            created_by=creator,
        )
    )
    binding = ensure_workforce_position_binding(position=position)
    return _ExactScope(
        edition=edition,
        department=department,
        position=position,
        binding=binding,
    )


def _organization_target(organization: Organization) -> ResolvedAuthorizationTarget:
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


def _department_target(scope: _ExactScope) -> ResolvedAuthorizationTarget:
    target = resolve_department_target(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
    )
    assert target is not None
    return target


def _resource_target(scope: _ExactScope) -> ResolvedAuthorizationTarget:
    target = resolve_resource_target(
        organization_id=scope.edition.organization_id,
        edition_id=scope.edition.id,
        department_id=scope.department.id,
        resource_binding_id=scope.binding.id,
    )
    assert target is not None
    return target


def _change_target(
    target: ResolvedAuthorizationTarget,
    **changes: UUID | None,
) -> ResolvedAuthorizationTarget:
    for field_name, value in changes.items():
        object.__setattr__(target, field_name, value)
    return target


def _delegation_chain() -> tuple[CapabilityGrant, CapabilityGrant]:
    now = timezone.now()
    organization = OrganizationFactory()
    delegator = AccountFactory()
    parent = CapabilityGrantFactory(
        organization=organization,
        principal=delegator,
        effective_from=now - timedelta(days=2),
        expires_at=now + timedelta(days=3),
    )
    child = CapabilityGrantFactory(
        organization=organization,
        principal=AccountFactory(),
        capability_code=parent.capability_code,
        effective_from=now - timedelta(days=1),
        expires_at=now + timedelta(days=2),
        granted_by=delegator,
        delegated_from=parent,
    )
    return parent, child


def _delegation_command_scope() -> tuple[
    Account,
    Account,
    CapabilityGrant,
    ResolvedAuthorizationTarget,
]:
    now = timezone.now()
    organization = OrganizationFactory()
    actor = AccountFactory()
    recipient = AccountFactory()
    parent = CapabilityGrantFactory(
        organization=organization,
        principal=actor,
        effective_from=now - timedelta(minutes=5),
        expires_at=now + timedelta(days=2),
    )
    CapabilityGrantFactory(
        organization=organization,
        principal=actor,
        capability_code="authorization.delegate",
        effective_from=now - timedelta(minutes=5),
        expires_at=now + timedelta(days=2),
    )
    return actor, recipient, parent, _organization_target(organization)


def test_scope_models_reject_incomplete_and_cross_scope_evidence() -> None:
    first = EventEditionFactory()
    second = EventEditionFactory()
    principal = AccountFactory()
    revoker = AccountFactory()
    second_department = create_department_for_test(
        edition=second,
        name="Foreign runtime department",
        expected_code="foreign-runtime-department",
    )

    assert str(AuthorizationScopeWriteFence()) == "Authorization scope-v2 writes exist"
    with pytest.raises(ValidationError, match="at least one capability"):
        validate_capability_codes([])

    mismatched_binding = ScopedResourceBinding(
        organization=first.organization,
        edition=first,
        department=second_department,
        resource_kind=ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION,
        resource_id=uuid4(),
    )
    with pytest.raises(ValidationError, match="exact edition"):
        mismatched_binding.clean()

    common_grant = {
        "organization": first.organization,
        "principal": principal,
        "effective_from": timezone.now(),
        "granted_by": principal,
        "reason": "Synthetic model-validation evidence.",
    }
    with pytest.raises(ValidationError, match="scope edition"):
        CapabilityGrant(
            edition=second,
            capability_code="events.view_basic",
            **common_grant,
        ).clean()
    with pytest.raises(ValidationError, match="exact edition scope"):
        CapabilityGrant(
            edition=first,
            department=second_department,
            capability_code="events.view_basic",
            **common_grant,
        ).clean()

    unknown = CapabilityGrant(
        capability_code="synthetic.unknown-runtime-capability",
        **common_grant,
    )
    unknown.clean()

    with pytest.raises(ValidationError, match="only on a revoked authority"):
        CapabilityGrant(
            capability_code="events.view_basic",
            revoked_by=revoker,
            revocation_reason="Unexpected evidence.",
            **common_grant,
        ).clean()
    with pytest.raises(ValidationError, match="requires a revoker"):
        CapabilityGrant(
            capability_code="events.view_basic",
            revoked_at=timezone.now(),
            **common_grant,
        ).clean()

    nonpersistable_bundle = RoleBundle(
        organization=first.organization,
        code="runtime-self-role",
        name="Runtime self role",
        version=1,
        capability_codes=["registration.view_self"],
    )
    with pytest.raises(ValidationError, match="Relationship-derived"):
        RoleAssignment(
            organization=first.organization,
            principal=principal,
            role_bundle=nonpersistable_bundle,
            effective_from=timezone.now(),
            granted_by=principal,
            reason="Synthetic nonpersistable role evidence.",
        ).clean()

    role_without_bundle = RoleAssignment(
        organization=first.organization,
        principal=principal,
        effective_from=timezone.now(),
        granted_by=principal,
        reason="Synthetic partial role evidence.",
    )
    role_without_bundle.clean()

    valid_scope = _exact_scope()
    assert str(valid_scope.binding).startswith("workforce.position:")


def test_resolvers_fail_closed_for_invalid_or_stale_owned_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization = OrganizationFactory()
    membership = OrganizationMembershipFactory(organization=organization)
    participation = ParticipationFactory()

    assert resolve_owned_target(resource=Organization()) is None
    assert resolve_owned_target(resource=organization) is None

    membership_target = resolve_owned_target(resource=membership)
    assert membership_target is not None
    assert membership_target.organization_id == organization.id
    assert membership_target.edition_id is None
    assert membership_target.owner_account_id == membership.account_id

    participation_target = resolve_owned_target(resource=participation)
    assert participation_target is not None
    assert participation_target.edition_id == participation.edition_id
    assert participation_target.owner_account_id == participation.account_id

    type(participation).objects.filter(pk=participation.pk).delete()
    assert resolve_owned_target(resource=participation) is None
    assert (
        resolve_self_target(
            principal=membership.account,
            organization_id=uuid4(),
        )
        is None
    )
    assert (
        resolve_department_target(
            organization_id=organization.id,
            edition_id=uuid4(),
            department_id=uuid4(),
        )
        is None
    )
    assert (
        resolve_resource_target(
            organization_id=organization.id,
            edition_id=uuid4(),
            department_id=uuid4(),
            resource_binding_id=uuid4(),
        )
        is None
    )

    monkeypatch.setattr(
        authorization_policy,
        "resolve_organization_target",
        lambda **_kwargs: None,
    )
    assert resolve_owned_target(resource=membership) is None


def test_resolvers_reject_invalid_query_results_and_resource_kinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _InvalidQuery:
        def first(self) -> None:
            raise ValidationError("Synthetic invalid lookup.")

    assert authorization_policy._safe_first(_InvalidQuery()) is None
    with pytest.raises(ValueError, match="department target requires an edition"):
        authorization_policy._seal_target(
            organization_id=uuid4(),
            department_id=uuid4(),
        )
    with pytest.raises(ValueError, match="resource target requires a department"):
        authorization_policy._seal_target(
            organization_id=uuid4(),
            edition_id=uuid4(),
            resource_binding_id=uuid4(),
        )

    monkeypatch.setattr(
        authorization_policy,
        "_safe_first",
        lambda _query: {
            "id": uuid4(),
            "organization_id": uuid4(),
            "edition_id": uuid4(),
            "department_id": uuid4(),
            "resource_kind": "synthetic.unknown-resource-kind",
            "resource_id": uuid4(),
        },
    )
    assert (
        resolve_resource_target(
            organization_id=uuid4(),
            edition_id=uuid4(),
            department_id=uuid4(),
            resource_binding_id=uuid4(),
        )
        is None
    )


@pytest.mark.parametrize(
    "corruption",
    ["cycle", "capability", "organization", "grantor", "expiry"],
)
def test_delegation_chain_validation_rejects_loaded_corruption(
    corruption: str,
) -> None:
    parent, child = _delegation_chain()
    if corruption == "cycle":
        parent.delegated_from = child
    elif corruption == "capability":
        child.capability_code = "events.change_profile"
    elif corruption == "organization":
        parent.organization_id = uuid4()
    elif corruption == "grantor":
        child.granted_by_id = uuid4()
    else:
        parent.expires_at = timezone.now() + timedelta(hours=1)
        child.expires_at = timezone.now() + timedelta(hours=2)

    assert not authorization_policy.grant_chain_is_active(child, timezone.now())


@pytest.mark.parametrize("corruption", ["malformed", "resource", "edition"])
def test_scope_containment_rejects_corrupted_parent_shapes(corruption: str) -> None:
    parent, child = _delegation_chain()
    if corruption == "malformed":
        parent.resource_binding_id = uuid4()
    elif corruption == "resource":
        parent.edition_id = child.edition_id = uuid4()
        parent.department_id = child.department_id = uuid4()
        parent.resource_binding_id = uuid4()
        child.resource_binding_id = uuid4()
    else:
        parent.edition_id = uuid4()
        child.edition_id = uuid4()

    assert not authorization_policy._authority_scope_contains(parent, child)


@pytest.mark.parametrize(
    "case",
    [
        "organization_missing",
        "edition_missing",
        "department_without_edition",
        "department_missing",
        "resource_without_parents",
        "resource_missing",
        "resolver_recheck_failed",
    ],
)
def test_authority_command_lock_rejects_tampered_resolved_targets(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _exact_scope()
    if case == "organization_missing":
        target = _change_target(
            _organization_target(scope.edition.organization),
            organization_id=uuid4(),
        )
    elif case == "edition_missing":
        target = _change_target(_edition_target(scope.edition), edition_id=uuid4())
    elif case == "department_without_edition":
        target = _change_target(_department_target(scope), edition_id=None)
    elif case == "department_missing":
        target = _change_target(_department_target(scope), department_id=uuid4())
    elif case == "resource_without_parents":
        target = _change_target(
            _resource_target(scope),
            edition_id=None,
            department_id=None,
        )
    elif case == "resource_missing":
        target = _change_target(
            _resource_target(scope),
            resource_binding_id=uuid4(),
        )
    else:
        target = _resource_target(scope)
        monkeypatch.setattr(
            authority_commands,
            "resolve_resource_target",
            lambda **_kwargs: None,
        )

    with (
        transaction.atomic(),
        pytest.raises(AuthorityCommandValidationError) as error,
    ):
        authority_commands._lock_target(target)

    assert error.value.reason_code == "scope_unavailable"


def test_role_bundle_command_rejects_an_edition_target() -> None:
    edition = EventEditionFactory()
    actor = AccountFactory()
    approver = AccountFactory()
    for controller in (actor, approver):
        CapabilityGrantFactory(
            organization=edition.organization,
            edition=edition,
            principal=controller,
            capability_code="authorization.manage_roles",
            effective_from=timezone.now() - timedelta(minutes=1),
        )

    with pytest.raises(AuthorityCommandValidationError) as error:
        create_role_bundle_version(
            actor=actor,
            approver=approver,
            target=_edition_target(edition),
            code="edition-local-role",
            name="Edition local role",
            capability_codes=("events.view_basic",),
            reason="Synthetic organization-scope validation.",
            correlation_id=uuid4(),
        )

    assert error.value.reason_code == "organization_scope_required"


@pytest.mark.parametrize(
    "case",
    [
        "organization",
        "organization_missing",
        "edition_missing",
        "department_without_edition",
        "department_missing",
        "resource_without_parents",
        "resource_missing",
        "resolver_recheck_failed",
    ],
)
def test_delegation_target_lock_rechecks_every_persisted_parent(
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _exact_scope()
    if case == "organization":
        target = _organization_target(scope.edition.organization)
    elif case == "organization_missing":
        target = _change_target(
            _organization_target(scope.edition.organization),
            organization_id=uuid4(),
        )
    elif case == "edition_missing":
        target = _change_target(_edition_target(scope.edition), edition_id=uuid4())
    elif case == "department_without_edition":
        target = _change_target(_department_target(scope), edition_id=None)
    elif case == "department_missing":
        target = _change_target(_department_target(scope), department_id=uuid4())
    elif case == "resource_without_parents":
        target = _change_target(
            _resource_target(scope),
            edition_id=None,
            department_id=None,
        )
    elif case == "resource_missing":
        target = _change_target(
            _resource_target(scope),
            resource_binding_id=uuid4(),
        )
    else:
        target = _resource_target(scope)
        monkeypatch.setattr(
            delegation_services,
            "resolve_resource_target",
            lambda **_kwargs: None,
        )

    if case == "organization":
        with transaction.atomic():
            locked = delegation_services._lock_target(target)
        assert locked.organization_id == scope.edition.organization_id
    else:
        with transaction.atomic(), pytest.raises(AuthorizationDenied) as error:
            delegation_services._lock_target(target)
        assert error.value.reason_code == "target_unavailable"


def test_delegation_bounds_cover_edition_start_and_interval_failures() -> None:
    now = timezone.now()
    first = EventEditionFactory()
    second = EventEditionFactory()
    parent = CapabilityGrantFactory(
        organization=first.organization,
        edition=first,
        principal=AccountFactory(),
        effective_from=now,
        expires_at=now + timedelta(days=2),
    )

    assert (
        delegation_services._validate_delegation_bounds(
            parent=parent,
            target=_edition_target(second),
            effective_from=now,
            expires_at=now + timedelta(days=1),
        )
        == "delegation_scope_too_broad"
    )
    assert (
        delegation_services._validate_delegation_bounds(
            parent=parent,
            target=_edition_target(first),
            effective_from=now - timedelta(seconds=1),
            expires_at=now + timedelta(days=1),
        )
        == "delegation_effective_before_parent"
    )
    assert (
        delegation_services._validate_delegation_bounds(
            parent=parent,
            target=_edition_target(first),
            effective_from=now + timedelta(hours=1),
            expires_at=now + timedelta(hours=1),
        )
        == "delegation_invalid_interval"
    )


def test_delegation_chain_lock_and_inactive_parent_checks() -> None:
    parent, child = _delegation_chain()
    with transaction.atomic():
        locked = delegation_services._lock_parent_chain(
            parent_id=child.id,
            actor=child.principal,
        )
    assert locked.id == child.id

    parent.revoked_at = timezone.now()
    parent.revoked_by = AccountFactory()
    parent.revocation_reason = "Synthetic inactive-parent evidence."
    parent.save(update_fields=("revoked_at", "revoked_by", "revocation_reason"))
    with pytest.raises(AuthorizationDenied) as error:
        delegation_services._require_active_parent(parent)
    assert error.value.reason_code == "parent_authority_inactive"


def test_delegate_rejects_missing_parent_and_blank_reason() -> None:
    organization = OrganizationFactory()
    actor = AccountFactory()
    recipient = AccountFactory()
    target = _organization_target(organization)

    with pytest.raises(AuthorizationDenied) as missing:
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=uuid4(),
            target=target,
            effective_from=timezone.now(),
            expires_at=None,
            reason="Synthetic unavailable parent.",
            correlation_id=uuid4(),
        )
    assert missing.value.reason_code == "parent_authority_absent"

    actor, recipient, parent, target = _delegation_command_scope()
    with pytest.raises(ValidationError, match="reason is required"):
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            target=target,
            effective_from=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
            reason="  ",
            correlation_id=uuid4(),
        )


def test_delegate_rechecks_bounds_inside_the_locked_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, recipient, parent, target = _delegation_command_scope()
    results = iter((None, "delegation_scope_too_broad"))
    monkeypatch.setattr(
        delegation_services,
        "_validate_delegation_bounds",
        lambda **_kwargs: next(results),
    )

    with pytest.raises(AuthorizationDenied) as error:
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            target=target,
            effective_from=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
            reason="Synthetic locked-bound recheck.",
            correlation_id=uuid4(),
        )

    assert error.value.reason_code == "delegation_scope_too_broad"


def test_delegate_rechecks_meta_authority_inside_the_locked_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor, recipient, parent, target = _delegation_command_scope()
    decisions = iter(
        (
            PolicyDecision(
                allowed=True,
                fields=frozenset(),
                obligations=frozenset({"audit"}),
                reason_code="direct_grant",
            ),
            PolicyDecision(
                allowed=False,
                fields=frozenset(),
                obligations=frozenset(),
                reason_code="permission_absent",
            ),
        )
    )
    monkeypatch.setattr(
        delegation_services,
        "decide",
        lambda **_kwargs: next(decisions),
    )

    with pytest.raises(AuthorizationDenied) as error:
        delegate_capability(
            actor=actor,
            recipient=recipient,
            parent_grant_id=parent.id,
            target=target,
            effective_from=timezone.now(),
            expires_at=timezone.now() + timedelta(days=1),
            reason="Synthetic locked-policy recheck.",
            correlation_id=uuid4(),
        )

    assert error.value.reason_code == "delegation_permission_absent"
