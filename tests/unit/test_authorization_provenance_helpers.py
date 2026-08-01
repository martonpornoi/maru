"""Focused boundary matrices for ADR 0044's pure provenance rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.authorization import issuance, provenance
from maru.authorization.catalog import ScopeLevel
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.identity.models import Account


def _at(minutes: int = 0) -> datetime:
    return timezone.now() + timedelta(minutes=minutes)


def test_locking_entry_points_require_an_explicit_transaction() -> None:
    bundle = RoleBundle(
        organization_id=uuid4(),
        code="unsaved-lock-boundary",
        name="Unsaved lock boundary",
        version=1,
        capability_codes=["events.view_basic"],
    )
    target = SimpleNamespace(
        organization_id=uuid4(),
        edition_id=None,
        department_id=None,
        resource_binding_id=None,
    )

    with pytest.raises(RuntimeError, match="locking requires a transaction"):
        provenance.role_bundle_provenance_is_historical(bundle=bundle, lock=True)
    with pytest.raises(RuntimeError, match="locking requires a transaction"):
        provenance.authority_issuance_is_current(
            issuance_ordinal=1,
            principal_id=uuid4(),
            capability_code="events.view_basic",
            target=target,
            requested_effective_from=_at(),
            requested_expires_at=None,
            lock=True,
        )


def test_issuance_target_helpers_are_typed_and_fail_closed() -> None:
    organization_id = uuid4()
    actor_id = uuid4()
    approver_id = uuid4()
    recipient_id = uuid4()
    expires_at = _at(30)
    grant = CapabilityGrant(
        id=None,
        organization_id=organization_id,
        principal_id=recipient_id,
        capability_code="events.view_basic",
        effective_from=_at(),
        expires_at=expires_at,
        granted_by_id=actor_id,
        approved_by_id=approver_id,
    )
    bundle = RoleBundle(
        organization_id=organization_id,
        code="synthetic-role",
        name="Synthetic role",
        version=1,
        capability_codes=["events.view_basic"],
        created_by_id=actor_id,
        approved_by_id=approver_id,
    )
    assignment = RoleAssignment(
        organization_id=organization_id,
        principal_id=recipient_id,
        role_bundle=bundle,
        effective_from=_at(),
        expires_at=expires_at,
        granted_by_id=actor_id,
        approved_by_id=approver_id,
    )

    assert issuance._target_field(grant) == "capability_grant"
    assert issuance._target_field(bundle) == "role_bundle"
    assert issuance._target_field(assignment) == "role_assignment"
    assert issuance._target_attribution(grant) == (
        actor_id,
        approver_id,
        recipient_id,
        "authorization.grant_direct",
    )
    assert issuance._target_attribution(bundle) == (
        actor_id,
        approver_id,
        None,
        "authorization.manage_roles",
    )
    assert issuance._target_attribution(assignment) == (
        actor_id,
        approver_id,
        recipient_id,
        "authorization.manage_roles",
    )
    assert issuance._target_scope(bundle) == (organization_id, None, None, None)
    assert issuance._target_expiry(bundle) is None
    assert issuance._target_expiry(grant) == expires_at

    with pytest.raises(ValidationError) as captured:
        issuance._target_field(SimpleNamespace())
    assert captured.value.code == "authority_target_unsupported"
    with pytest.raises(ValidationError) as captured:
        issuance._lock_target(grant)
    assert captured.value.code == "authority_target_unsaved"


def test_issuance_scope_and_capability_helpers_cover_exact_containment() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    department_id = uuid4()
    resource_id = uuid4()

    def scoped(**overrides: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "organization_id": organization_id,
            "edition_id": None,
            "department_id": None,
            "resource_binding_id": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    target = scoped(
        edition_id=edition_id,
        department_id=department_id,
        resource_binding_id=resource_id,
    )
    assert issuance._scope_contains(source=scoped(), target=target)
    assert issuance._scope_contains(source=scoped(edition_id=edition_id), target=target)
    assert issuance._scope_contains(
        source=scoped(edition_id=edition_id, department_id=department_id),
        target=target,
    )
    assert issuance._scope_contains(source=target, target=target)
    assert not issuance._scope_contains(
        source=scoped(organization_id=uuid4()), target=target
    )
    assert not issuance._scope_contains(
        source=scoped(edition_id=uuid4()), target=target
    )
    assert not issuance._scope_contains(
        source=scoped(edition_id=edition_id, department_id=uuid4()), target=target
    )
    assert not issuance._scope_contains(
        source=scoped(
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=uuid4(),
        ),
        target=target,
    )

    grant = CapabilityGrant(capability_code="events.view_basic")
    assignment = RoleAssignment(
        role_bundle=RoleBundle(capability_codes=["events.view_basic"])
    )
    assert issuance._source_has_capability(grant, "events.view_basic")
    assert not issuance._source_has_capability(grant, "events.edit")
    assert issuance._source_has_capability(assignment, "events.view_basic")
    assert not issuance._source_has_capability(assignment, "events.edit")


def test_persistent_source_validation_rejects_each_authority_mismatch() -> None:
    organization_id = uuid4()
    principal_id = uuid4()
    evaluated_at = _at()
    active_principal = Account(id=principal_id, is_active=True)
    target = CapabilityGrant(
        organization_id=organization_id,
        principal_id=uuid4(),
        capability_code="events.view_basic",
        effective_from=evaluated_at,
        expires_at=evaluated_at + timedelta(days=2),
        granted_by_id=uuid4(),
        approved_by_id=uuid4(),
    )

    def source(**overrides: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "principal_id": principal_id,
            "principal": active_principal,
            "capability_code": "authorization.grant_direct",
            "organization_id": organization_id,
            "edition_id": None,
            "department_id": None,
            "resource_binding_id": None,
            "effective_from": evaluated_at - timedelta(days=1),
            "expires_at": None,
            "revoked_at": None,
        }
        values.update(overrides)
        grant = CapabilityGrant(**values)
        return SimpleNamespace(
            capability_grant=grant,
            role_assignment=None,
            role_bundle_id=None,
        )

    cases = (
        (
            source(principal_id=uuid4()),
            "authority_source_principal_mismatch",
        ),
        (
            source(capability_code="events.view_basic"),
            "authority_source_capability_mismatch",
        ),
        (
            source(organization_id=uuid4()),
            "authority_source_scope_mismatch",
        ),
        (
            source(effective_from=evaluated_at + timedelta(minutes=1)),
            "authority_source_inactive",
        ),
        (
            source(expires_at=evaluated_at + timedelta(days=1)),
            "authority_source_horizon_too_short",
        ),
        (
            source(principal=Account(id=principal_id, is_active=False)),
            "authority_source_principal_inactive",
        ),
    )
    for source_issuance, expected_code in cases:
        with pytest.raises(ValidationError) as captured:
            issuance._validate_persistent_source(
                source_issuance=source_issuance,
                principal_id=principal_id,
                capability_code="authorization.grant_direct",
                target=target,
                evaluated_at=evaluated_at,
            )
        assert captured.value.code == expected_code

    malformed_sources = (
        SimpleNamespace(
            capability_grant=None,
            role_assignment=None,
            role_bundle_id=None,
        ),
        SimpleNamespace(
            capability_grant=CapabilityGrant(),
            role_assignment=RoleAssignment(),
            role_bundle_id=None,
        ),
        SimpleNamespace(
            capability_grant=CapabilityGrant(),
            role_assignment=None,
            role_bundle_id=uuid4(),
        ),
    )
    for malformed in malformed_sources:
        with pytest.raises(ValidationError) as captured:
            issuance._source_target(malformed)
        assert captured.value.code == "authority_source_target_invalid"
    with pytest.raises(RuntimeError, match="open transaction"):
        provenance.select_authorized_control_source(
            principal=SimpleNamespace(pk=uuid4()),
            role=AuthorityControl.Role.ACTOR,
            capability_code="events.view_basic",
            target=target,
            requested_expires_at=None,
        )


def test_scope_shape_and_containment_matrix() -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    department_id = uuid4()
    resource_id = uuid4()
    organization = provenance._Scope(organization_id=organization_id)
    edition = provenance._Scope(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    department = provenance._Scope(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
    )
    resource = provenance._Scope(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=department_id,
        resource_binding_id=resource_id,
    )

    assert provenance._scope_shape_is_valid(organization)
    assert provenance._scope_shape_is_valid(edition)
    assert provenance._scope_shape_is_valid(department)
    assert provenance._scope_shape_is_valid(resource)
    assert not provenance._scope_shape_is_valid(
        provenance._Scope(
            organization_id=organization_id,
            department_id=department_id,
        )
    )
    assert not provenance._scope_shape_is_valid(
        provenance._Scope(
            organization_id=organization_id,
            edition_id=edition_id,
            resource_binding_id=resource_id,
        )
    )

    assert provenance._scope_contains(source=organization, target=resource)
    assert provenance._scope_contains(source=edition, target=department)
    assert provenance._scope_contains(source=department, target=resource)
    assert provenance._scope_contains(source=resource, target=resource)
    assert not provenance._scope_contains(
        source=resource,
        target=provenance._Scope(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=uuid4(),
        ),
    )
    assert not provenance._scope_contains(
        source=department,
        target=provenance._Scope(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=uuid4(),
        ),
    )
    assert not provenance._scope_contains(
        source=edition,
        target=provenance._Scope(
            organization_id=organization_id,
            edition_id=uuid4(),
        ),
    )
    assert not provenance._scope_contains(
        source=organization,
        target=provenance._Scope(organization_id=uuid4()),
    )


def test_scope_conversion_rejects_missing_or_malformed_targets() -> None:
    organization_id = uuid4()
    target = SimpleNamespace(
        organization_id=organization_id,
        edition_id=None,
        department_id=None,
        resource_binding_id=None,
    )

    assert provenance._scope_from_target(target) == provenance._Scope(
        organization_id=organization_id
    )
    assert provenance._scope_from_target(SimpleNamespace()) is None
    assert (
        provenance._scope_from_target(
            SimpleNamespace(
                organization_id=organization_id,
                edition_id=None,
                department_id=uuid4(),
                resource_binding_id=None,
            )
        )
        is None
    )


def test_time_window_validation_distinguishes_point_and_persistent_horizons() -> None:
    start = _at()
    end = _at(10)
    naive = datetime.now()  # noqa: DTZ005 - deliberately invalid boundary input.

    assert provenance._time_window_is_valid(
        requested_effective_from=start,
        requested_expires_at=None,
        evaluated_at=start,
        horizon_mode=provenance.ControlHorizonMode.POINT_IN_TIME,
    )
    assert not provenance._time_window_is_valid(
        requested_effective_from=start,
        requested_expires_at=end,
        evaluated_at=start,
        horizon_mode=provenance.ControlHorizonMode.POINT_IN_TIME,
    )
    assert provenance._time_window_is_valid(
        requested_effective_from=start,
        requested_expires_at=end,
        evaluated_at=start,
        horizon_mode=provenance.ControlHorizonMode.PERSISTENT,
    )
    assert not provenance._time_window_is_valid(
        requested_effective_from=start,
        requested_expires_at=start,
        evaluated_at=start,
        horizon_mode=provenance.ControlHorizonMode.PERSISTENT,
    )
    assert not provenance._time_window_is_valid(
        requested_effective_from=naive,
        requested_expires_at=None,
        evaluated_at=start,
        horizon_mode=provenance.ControlHorizonMode.PERSISTENT,
    )


def test_current_and_historical_horizon_matrices() -> None:
    evaluated_at = _at()
    expectation = provenance._Expectation(
        principal_id=uuid4(),
        capability_code="events.view_basic",
        target_scope=provenance._Scope(organization_id=uuid4()),
        requested_effective_from=evaluated_at,
        requested_expires_at=_at(10),
        evaluated_at=evaluated_at,
    )

    def source(**overrides: object) -> SimpleNamespace:
        values: dict[str, object] = {
            "effective_from": _at(-10),
            "expires_at": _at(20),
            "revoked_at": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    assert provenance._horizon_is_covered(source=source(), expectation=expectation)
    assert not provenance._horizon_is_covered(
        source=source(effective_from=_at(1)),
        expectation=expectation,
    )
    assert not provenance._horizon_is_covered(
        source=source(revoked_at=_at(5)),
        expectation=expectation,
    )
    assert not provenance._horizon_is_covered(
        source=source(expires_at=evaluated_at),
        expectation=expectation,
    )
    assert provenance._horizon_is_covered(
        source=source(expires_at=None),
        expectation=expectation,
    )
    assert not provenance._horizon_is_covered(
        source=source(expires_at=_at(5)),
        expectation=expectation,
    )

    point_expectation = provenance._Expectation(
        principal_id=expectation.principal_id,
        capability_code=expectation.capability_code,
        target_scope=expectation.target_scope,
        requested_effective_from=evaluated_at,
        requested_expires_at=None,
        evaluated_at=evaluated_at,
        horizon_mode=provenance.ControlHorizonMode.POINT_IN_TIME,
    )
    assert provenance._horizon_is_covered(
        source=source(expires_at=_at(1)),
        expectation=point_expectation,
    )

    assert provenance._historical_horizon_is_covered(
        source=source(revoked_at=_at(1)),
        expectation=expectation,
    )
    assert not provenance._historical_horizon_is_covered(
        source=source(revoked_at=evaluated_at),
        expectation=expectation,
    )
    assert provenance._historical_horizon_is_covered(
        source=source(expires_at=None),
        expectation=expectation,
    )
    assert provenance._historical_horizon_is_covered(
        source=source(expires_at=_at(1)),
        expectation=point_expectation,
    )


def test_source_capability_attribution_and_scope_helpers() -> None:
    organization_id = uuid4()
    principal_id = uuid4()
    actor_id = uuid4()
    approver_id = uuid4()
    grant = CapabilityGrant(
        organization_id=organization_id,
        principal_id=principal_id,
        capability_code="events.view_basic",
        effective_from=_at(),
        granted_by_id=actor_id,
        approved_by_id=approver_id,
    )
    bundle = RoleBundle(
        organization_id=organization_id,
        code="synthetic-helper-role",
        name="Synthetic helper role",
        version=1,
        capability_codes=["authorization.manage_roles"],
        created_by_id=actor_id,
        approved_by_id=approver_id,
    )
    assignment = RoleAssignment(
        organization_id=organization_id,
        principal_id=principal_id,
        role_bundle=bundle,
        effective_from=_at(),
        granted_by_id=actor_id,
        approved_by_id=approver_id,
    )

    assert provenance._source_has_capability(grant, "events.view_basic")
    assert not provenance._source_has_capability(grant, "events.change_profile")
    assert provenance._source_has_capability(
        assignment,
        "authorization.manage_roles",
    )
    assert provenance._target_attribution(grant) == (
        actor_id,
        approver_id,
        principal_id,
    )
    assert provenance._target_attribution(bundle) == (actor_id, approver_id, None)
    assert provenance._target_attribution(assignment) == (
        actor_id,
        approver_id,
        principal_id,
    )
    assert provenance._scope_from_authority(grant).level is ScopeLevel.ORGANIZATION


def test_source_rank_and_control_projection_are_stable() -> None:
    evaluated_at = _at()
    source_id = uuid4()
    principal_id = uuid4()
    grant = CapabilityGrant(
        id=source_id,
        organization_id=uuid4(),
        principal_id=principal_id,
        capability_code="authorization.manage_roles",
        effective_from=evaluated_at,
        expires_at=_at(10),
    )
    issuance = AuthorityIssuance(
        ordinal=7,
        policy_version="synthetic-policy-v1",
        evaluated_at=evaluated_at,
        capability_grant=grant,
    )

    rank = provenance._source_rank(
        issuance=issuance,
        source_kind=provenance.PersistentSourceKind.CAPABILITY_GRANT,
        source=grant,
    )
    assert rank[-1] == 7
    control = provenance._authorized_control(
        role=AuthorityControl.Role.ACTOR,
        principal_id=principal_id,
        capability_code=grant.capability_code,
        source_kind=provenance.PersistentSourceKind.CAPABILITY_GRANT,
        issuance=issuance,
        source=grant,
        evaluated_at=evaluated_at,
    )
    assert control.source_authority_id == source_id
    assert control.source_scope is ScopeLevel.ORGANIZATION
    assert control.source_issuance_ordinal == 7
    assert control.policy_version == "synthetic-policy-v1"
