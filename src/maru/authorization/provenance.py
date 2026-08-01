"""Internal source selection and dynamic validation for ADR 0044 provenance.

Public policy decisions deliberately remain identifier-free.  This module is
an application-internal boundary for authority writers and sensitive access
explanations that need the exact persistent source selected for one controller.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypeVar
from uuid import UUID

from django.db import connection, models
from django.db.models import Q, QuerySet
from django.utils import timezone

from maru.authorization.catalog import ScopeLevel
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.identity.models import Account
from maru.organizations.models import (
    Organization,
    OrganizationMembership,
    OrganizationRepresentation,
    RepresentationAppointment,
)

MAX_AUTHORITY_LINEAGE_DEPTH = 64
_REQUIRED_CONTROL_COUNT = 2
_GRANT_CONTROL_CAPABILITY = "authorization.grant_direct"
_ROLE_CONTROL_CAPABILITY = "authorization.manage_roles"
_EXECUTIVE_BOARD_ROLE_CODE = "executive-board"
_ModelT = TypeVar("_ModelT", bound=models.Model)


class _ResolvedTarget(Protocol):
    @property
    def organization_id(self) -> UUID: ...

    @property
    def edition_id(self) -> UUID | None: ...

    @property
    def department_id(self) -> UUID | None: ...

    @property
    def resource_binding_id(self) -> UUID | None: ...


class PersistentSourceKind(StrEnum):
    CAPABILITY_GRANT = "capability_grant"
    ROLE_ASSIGNMENT = "role_assignment"


class _IssuanceTargetKind(StrEnum):
    CAPABILITY_GRANT = "capability_grant"
    ROLE_BUNDLE = "role_bundle"
    ROLE_ASSIGNMENT = "role_assignment"


class ControlHorizonMode(StrEnum):
    """How long a controller source must cover the requested operation."""

    PERSISTENT = "persistent"
    POINT_IN_TIME = "point_in_time"


@dataclass(frozen=True, slots=True)
class AuthorizedControl:
    """One exact, source-bearing control selected for an issuance writer."""

    role: str
    principal_id: UUID
    capability_code: str
    source_kind: PersistentSourceKind
    source_issuance_ordinal: int
    source_authority_id: UUID
    source_scope: ScopeLevel
    source_effective_from: datetime
    source_expires_at: datetime | None
    evaluated_at: datetime
    policy_version: str


@dataclass(frozen=True, slots=True)
class _Scope:
    organization_id: UUID
    edition_id: UUID | None = None
    department_id: UUID | None = None
    resource_binding_id: UUID | None = None

    @property
    def level(self) -> ScopeLevel:
        if self.resource_binding_id is not None:
            return ScopeLevel.RESOURCE
        if self.department_id is not None:
            return ScopeLevel.DEPARTMENT
        if self.edition_id is not None:
            return ScopeLevel.EDITION
        return ScopeLevel.ORGANIZATION

    @property
    def rank(self) -> int:
        return {
            ScopeLevel.ORGANIZATION: 0,
            ScopeLevel.EDITION: 1,
            ScopeLevel.DEPARTMENT: 2,
            ScopeLevel.RESOURCE: 3,
        }[self.level]


@dataclass(frozen=True, slots=True)
class _Expectation:
    principal_id: UUID
    capability_code: str
    target_scope: _Scope
    requested_effective_from: datetime
    requested_expires_at: datetime | None
    evaluated_at: datetime
    horizon_mode: ControlHorizonMode = ControlHorizonMode.PERSISTENT


@dataclass(slots=True)
class _LineageContext:
    lock: bool
    issuances: dict[int, AuthorityIssuance | None] = field(default_factory=dict)
    controls: dict[int, tuple[AuthorityControl, ...]] = field(default_factory=dict)
    accounts: dict[UUID, Account | None] = field(default_factory=dict)
    grants: dict[UUID, CapabilityGrant | None] = field(default_factory=dict)
    assignments: dict[UUID, RoleAssignment | None] = field(default_factory=dict)
    bundles: dict[UUID, RoleBundle | None] = field(default_factory=dict)
    historical_bundles: dict[tuple[UUID, datetime], bool] = field(default_factory=dict)
    historical_bundle_path: set[tuple[UUID, datetime]] = field(default_factory=set)
    historical_validity: dict[tuple[object, ...], bool] = field(default_factory=dict)
    validity: dict[tuple[object, ...], bool] = field(default_factory=dict)

    def _locked(self, queryset: QuerySet[_ModelT]) -> QuerySet[_ModelT]:
        return queryset.select_for_update() if self.lock else queryset

    def issuance(self, ordinal: int) -> AuthorityIssuance | None:
        if ordinal not in self.issuances:
            queryset = self._locked(AuthorityIssuance.objects.all())
            self.issuances[ordinal] = queryset.filter(ordinal=ordinal).first()
        return self.issuances[ordinal]

    def issuance_controls(self, ordinal: int) -> tuple[AuthorityControl, ...]:
        if ordinal not in self.controls:
            queryset = self._locked(AuthorityControl.objects.all())
            self.controls[ordinal] = tuple(
                queryset.filter(issuance_id=ordinal).order_by("role", "id")
            )
        return self.controls[ordinal]

    def account(self, account_id: UUID) -> Account | None:
        if account_id not in self.accounts:
            queryset = self._locked(Account.objects.all())
            self.accounts[account_id] = queryset.filter(pk=account_id).first()
        return self.accounts[account_id]

    def grant(self, grant_id: UUID) -> CapabilityGrant | None:
        if grant_id not in self.grants:
            queryset = self._locked(CapabilityGrant.objects.select_related("principal"))
            self.grants[grant_id] = queryset.filter(pk=grant_id).first()
        return self.grants[grant_id]

    def assignment(self, assignment_id: UUID) -> RoleAssignment | None:
        if assignment_id not in self.assignments:
            queryset = self._locked(
                RoleAssignment.objects.select_related("principal", "role_bundle")
            )
            self.assignments[assignment_id] = queryset.filter(pk=assignment_id).first()
        return self.assignments[assignment_id]

    def bundle(self, bundle_id: UUID) -> RoleBundle | None:
        if bundle_id not in self.bundles:
            queryset = self._locked(RoleBundle.objects.all())
            self.bundles[bundle_id] = queryset.filter(pk=bundle_id).first()
        return self.bundles[bundle_id]

    def issuance_for_grant(self, grant_id: UUID) -> AuthorityIssuance | None:
        queryset = self._locked(AuthorityIssuance.objects.all())
        issuance = queryset.filter(capability_grant_id=grant_id).first()
        if issuance is not None:
            self.issuances[issuance.ordinal] = issuance
        return issuance

    def issuance_for_bundle(self, bundle_id: UUID) -> AuthorityIssuance | None:
        queryset = self._locked(AuthorityIssuance.objects.all())
        issuance = queryset.filter(role_bundle_id=bundle_id).first()
        if issuance is not None:
            self.issuances[issuance.ordinal] = issuance
        return issuance


def _scope_shape_is_valid(scope: _Scope) -> bool:
    if scope.department_id is not None and scope.edition_id is None:
        return False
    return not (scope.resource_binding_id is not None and scope.department_id is None)


def _scope_from_target(target: _ResolvedTarget) -> _Scope | None:
    try:
        scope = _Scope(
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            department_id=target.department_id,
            resource_binding_id=target.resource_binding_id,
        )
    except AttributeError:
        return None
    return scope if _scope_shape_is_valid(scope) else None


def _scope_from_authority(authority: CapabilityGrant | RoleAssignment) -> _Scope:
    return _Scope(
        organization_id=authority.organization_id,
        edition_id=authority.edition_id,
        department_id=authority.department_id,
        resource_binding_id=authority.resource_binding_id,
    )


def _scope_contains(*, source: _Scope, target: _Scope) -> bool:
    if (
        not _scope_shape_is_valid(source)
        or not _scope_shape_is_valid(target)
        or source.organization_id != target.organization_id
    ):
        return False
    if source.resource_binding_id is not None:
        return source.resource_binding_id == target.resource_binding_id
    if source.department_id is not None:
        return (
            source.edition_id == target.edition_id
            and source.department_id == target.department_id
        )
    if source.edition_id is not None:
        return source.edition_id == target.edition_id
    return True


def _resolved_target_is_current(target: _ResolvedTarget) -> bool:
    """Repeat exact persisted target resolution without importing policy eagerly."""

    from maru.authorization.policy import (  # noqa: PLC0415
        resolve_department_target,
        resolve_edition_target,
        resolve_organization_target,
        resolve_resource_target,
    )

    scope = _scope_from_target(target)
    if scope is None:
        return False
    if scope.resource_binding_id is not None:
        if scope.edition_id is None or scope.department_id is None:
            return False
        resolved = resolve_resource_target(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
            resource_binding_id=scope.resource_binding_id,
        )
    elif scope.department_id is not None:
        if scope.edition_id is None:
            return False
        resolved = resolve_department_target(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
            department_id=scope.department_id,
        )
    elif scope.edition_id is not None:
        resolved = resolve_edition_target(
            organization_id=scope.organization_id,
            edition_id=scope.edition_id,
        )
    else:
        resolved = resolve_organization_target(organization_id=scope.organization_id)
    return resolved is not None and _scope_from_target(resolved) == scope


def _authority_scope_is_current(authority: CapabilityGrant | RoleAssignment) -> bool:
    scope = _scope_from_authority(authority)
    if not _scope_shape_is_valid(scope):
        return False
    return _resolved_target_is_current(scope)


def _time_window_is_valid(
    *,
    requested_effective_from: datetime,
    requested_expires_at: datetime | None,
    evaluated_at: datetime,
    horizon_mode: ControlHorizonMode,
) -> bool:
    values = [requested_effective_from, evaluated_at]
    if requested_expires_at is not None:
        values.append(requested_expires_at)
    if not all(timezone.is_aware(value) for value in values):
        return False
    if horizon_mode is ControlHorizonMode.POINT_IN_TIME:
        return requested_expires_at is None
    return (
        requested_expires_at is None or requested_expires_at > requested_effective_from
    )


def _horizon_is_covered(
    *,
    source: CapabilityGrant | RoleAssignment,
    expectation: _Expectation,
) -> bool:
    if (
        source.effective_from > expectation.evaluated_at
        or source.effective_from > expectation.requested_effective_from
        or source.revoked_at is not None
        or (
            source.expires_at is not None
            and source.expires_at <= expectation.evaluated_at
        )
    ):
        return False
    if source.expires_at is None:
        return True
    if expectation.horizon_mode is ControlHorizonMode.POINT_IN_TIME:
        return True
    return (
        expectation.requested_expires_at is not None
        and expectation.requested_expires_at <= source.expires_at
    )


def _historical_horizon_is_covered(
    *,
    source: CapabilityGrant | RoleAssignment,
    expectation: _Expectation,
) -> bool:
    """Evaluate one immutable source at a past instant.

    A later revocation may not rewrite an already-authorized role definition,
    while a revocation at or before that definition's evaluation still fails.
    """

    if (
        source.effective_from > expectation.evaluated_at
        or source.effective_from > expectation.requested_effective_from
        or (
            source.revoked_at is not None
            and source.revoked_at <= expectation.evaluated_at
        )
        or (
            source.expires_at is not None
            and source.expires_at <= expectation.evaluated_at
        )
    ):
        return False
    if expectation.horizon_mode is ControlHorizonMode.POINT_IN_TIME:
        return True
    if source.expires_at is None:
        return True
    return (
        expectation.requested_expires_at is not None
        and expectation.requested_expires_at <= source.expires_at
    )


def _source_has_capability(
    source: CapabilityGrant | RoleAssignment,
    capability_code: str,
) -> bool:
    if isinstance(source, CapabilityGrant):
        return source.capability_code == capability_code
    return capability_code in source.role_bundle.capability_codes


def _target_attribution(
    target: CapabilityGrant | RoleBundle | RoleAssignment,
) -> tuple[UUID | None, UUID | None, UUID | None]:
    if isinstance(target, RoleBundle):
        return target.created_by_id, target.approved_by_id, None
    return target.granted_by_id, target.approved_by_id, target.principal_id


def _issuance_target(
    context: _LineageContext,
    issuance: AuthorityIssuance,
) -> (
    tuple[
        _IssuanceTargetKind,
        CapabilityGrant | RoleBundle | RoleAssignment,
    ]
    | None
):
    target_ids = (
        issuance.capability_grant_id,
        issuance.role_bundle_id,
        issuance.role_assignment_id,
    )
    if sum(target_id is not None for target_id in target_ids) != 1:
        return None
    if issuance.capability_grant_id is not None:
        grant = context.grant(issuance.capability_grant_id)
        return (
            (_IssuanceTargetKind.CAPABILITY_GRANT, grant) if grant is not None else None
        )
    if issuance.role_assignment_id is not None:
        assignment = context.assignment(issuance.role_assignment_id)
        return (
            (_IssuanceTargetKind.ROLE_ASSIGNMENT, assignment)
            if assignment is not None
            else None
        )
    bundle_id = issuance.role_bundle_id
    if bundle_id is None:
        return None
    bundle = context.bundle(bundle_id)
    return (_IssuanceTargetKind.ROLE_BUNDLE, bundle) if bundle is not None else None


def _controls_by_role(
    context: _LineageContext,
    issuance: AuthorityIssuance,
) -> dict[str, AuthorityControl] | None:
    controls = context.issuance_controls(issuance.ordinal)
    by_role = {control.role: control for control in controls}
    if len(controls) != _REQUIRED_CONTROL_COUNT or set(by_role) != {
        AuthorityControl.Role.ACTOR,
        AuthorityControl.Role.APPROVER,
    }:
        return None
    return by_role


def _control_metadata_matches(
    *,
    issuance: AuthorityIssuance,
    control: AuthorityControl,
) -> bool:
    return (
        bool(issuance.policy_version)
        and control.policy_version == issuance.policy_version
        and control.evaluated_at == issuance.evaluated_at
    )


def _principal_is_current(context: _LineageContext, principal_id: UUID) -> bool:
    principal = context.account(principal_id)
    return bool(
        principal is not None
        and principal.account_kind == Account.Kind.PERSON
        and principal.is_active
    )


def _validate_ordinary_controls(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    target: CapabilityGrant | RoleAssignment,
    required_capability: str,
    evaluated_at: datetime,
    path: frozenset[int],
    depth: int,
) -> bool:
    controls = _controls_by_role(context, issuance)
    if controls is None:
        return False
    actor_id, approver_id, recipient_id = _target_attribution(target)
    if (
        actor_id is None
        or approver_id is None
        or approver_id in (actor_id, recipient_id)
    ):
        return False
    target_scope = _scope_from_authority(target)
    for role, expected_principal_id in (
        (AuthorityControl.Role.ACTOR, actor_id),
        (AuthorityControl.Role.APPROVER, approver_id),
    ):
        control = controls[role]
        if (
            control.principal_id != expected_principal_id
            or control.basis != AuthorityControl.Basis.PERSISTENT_AUTHORITY
            or control.source_issuance_id is None
            or control.source_issuance_id >= issuance.ordinal
            or control.representation_id is not None
            or control.appointment_id is not None
            or not _control_metadata_matches(issuance=issuance, control=control)
            or not _principal_is_current(context, expected_principal_id)
        ):
            return False
        expectation = _Expectation(
            principal_id=expected_principal_id,
            capability_code=required_capability,
            target_scope=target_scope,
            requested_effective_from=target.effective_from,
            requested_expires_at=target.expires_at,
            evaluated_at=evaluated_at,
        )
        if not _validate_issuance_current(
            context=context,
            ordinal=control.source_issuance_id,
            expectation=expectation,
            path=path,
            depth=depth + 1,
        ):
            return False
    return True


def _special_controls_are_historical(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    organization_id: UUID,
    recipient_id: UUID | None,
) -> tuple[OrganizationRepresentation, RepresentationAppointment] | None:
    controls = _controls_by_role(context, issuance)
    if controls is None:
        return None
    actor = controls[AuthorityControl.Role.ACTOR]
    approver = controls[AuthorityControl.Role.APPROVER]
    if (
        actor.basis != AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP
        or actor.representation_id is None
        or actor.source_issuance_id is not None
        or actor.appointment_id is not None
        or approver.basis != AuthorityControl.Basis.REPRESENTATION_ACCEPTANCE
        or approver.appointment_id is None
        or approver.source_issuance_id is not None
        or approver.representation_id is not None
        or not _control_metadata_matches(issuance=issuance, control=actor)
        or not _control_metadata_matches(issuance=issuance, control=approver)
    ):
        return None
    platform_actor = context.account(actor.principal_id)
    if (
        platform_actor is None
        or platform_actor.account_kind != Account.Kind.PLATFORM_ADMINISTRATOR
    ):
        return None
    representation_query = context._locked(OrganizationRepresentation.objects.all())
    representation = representation_query.filter(
        pk=actor.representation_id,
        organization_id=organization_id,
        activated_by_id=actor.principal_id,
    ).first()
    appointment_query = context._locked(
        RepresentationAppointment.objects.select_related("representation")
    )
    appointment = appointment_query.filter(
        pk=approver.appointment_id,
        representation_id=actor.representation_id,
        account_id=approver.principal_id,
        state__in=(
            RepresentationAppointment.State.ACTIVE,
            RepresentationAppointment.State.ENDED,
        ),
    ).first()
    if (
        representation is None
        or appointment is None
        or representation.activated_at != issuance.evaluated_at
        or appointment.responded_at is None
        or appointment.responded_at > issuance.evaluated_at
        or (recipient_id is not None and appointment.account_id == recipient_id)
    ):
        return None
    return representation, appointment


def _ordinary_bundle_ceremony_is_historical(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    bundle: RoleBundle,
    evaluated_at: datetime,
) -> bool:
    controls = _controls_by_role(context, issuance)
    if controls is None or issuance.evaluated_at > evaluated_at:
        return False
    actor_id, approver_id, _recipient_id = _target_attribution(bundle)
    if actor_id is None or approver_id is None or actor_id == approver_id:
        return False
    expectation_scope = _Scope(organization_id=bundle.organization_id)
    for role, principal_id in (
        (AuthorityControl.Role.ACTOR, actor_id),
        (AuthorityControl.Role.APPROVER, approver_id),
    ):
        control = controls[role]
        if (
            control.principal_id != principal_id
            or control.basis != AuthorityControl.Basis.PERSISTENT_AUTHORITY
            or control.source_issuance_id is None
            or control.source_issuance_id >= issuance.ordinal
            or control.representation_id is not None
            or control.appointment_id is not None
            or not _control_metadata_matches(issuance=issuance, control=control)
        ):
            return False
        if not _validate_issuance_historical(
            context=context,
            ordinal=control.source_issuance_id,
            expectation=_Expectation(
                principal_id=principal_id,
                capability_code=_ROLE_CONTROL_CAPABILITY,
                target_scope=expectation_scope,
                requested_effective_from=issuance.evaluated_at,
                requested_expires_at=None,
                evaluated_at=issuance.evaluated_at,
                horizon_mode=ControlHorizonMode.POINT_IN_TIME,
            ),
        ):
            return False
    return True


def _bundle_ceremony_is_historical(
    *,
    context: _LineageContext,
    bundle: RoleBundle,
    evaluated_at: datetime,
) -> bool:
    key = (bundle.id, evaluated_at)
    if key in context.historical_bundles:
        return context.historical_bundles[key]
    if key in context.historical_bundle_path:
        context.historical_bundles[key] = False
        return False
    context.historical_bundle_path.add(key)
    issuance = context.issuance_for_bundle(bundle.id)
    valid = False
    if issuance is not None:
        target = _issuance_target(context, issuance)
        if (
            target is not None
            and target[0] is _IssuanceTargetKind.ROLE_BUNDLE
            and target[1].id == bundle.id
            and issuance.evaluated_at <= evaluated_at
        ):
            if bundle.code == _EXECUTIVE_BOARD_ROLE_CODE:
                historical = _special_controls_are_historical(
                    context=context,
                    issuance=issuance,
                    organization_id=bundle.organization_id,
                    recipient_id=None,
                )
                if historical is not None:
                    representation, appointment = historical
                    actor_id, approver_id, _recipient_id = _target_attribution(bundle)
                    valid = (
                        actor_id == representation.activated_by_id
                        and approver_id == appointment.account_id
                    )
            else:
                valid = _ordinary_bundle_ceremony_is_historical(
                    context=context,
                    issuance=issuance,
                    bundle=bundle,
                    evaluated_at=evaluated_at,
                )
    context.historical_bundles[key] = valid
    context.historical_bundle_path.discard(key)
    return valid


def _board_bundle_ceremony_is_valid(
    *,
    context: _LineageContext,
    bundle: RoleBundle,
    representation_id: UUID,
) -> bool:
    issuance = context.issuance_for_bundle(bundle.id)
    if issuance is None:
        return False
    target = _issuance_target(context, issuance)
    if (
        target is None
        or target[0] is not _IssuanceTargetKind.ROLE_BUNDLE
        or target[1].id != bundle.id
    ):
        return False
    actor_id, approver_id, _recipient_id = _target_attribution(bundle)
    historical = _special_controls_are_historical(
        context=context,
        issuance=issuance,
        organization_id=bundle.organization_id,
        recipient_id=None,
    )
    if historical is None:
        return False
    representation, appointment = historical
    return (
        bundle.code == _EXECUTIVE_BOARD_ROLE_CODE
        and representation.id == representation_id
        and actor_id == representation.activated_by_id
        and approver_id == appointment.account_id
    )


def _board_assignment_is_current(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    assignment: RoleAssignment,
) -> bool:
    historical = _special_controls_are_historical(
        context=context,
        issuance=issuance,
        organization_id=assignment.organization_id,
        recipient_id=assignment.principal_id,
    )
    if historical is None:
        return False
    representation, approver_appointment = historical
    current_appointment_query = context._locked(
        RepresentationAppointment.objects.select_related("representation")
    )
    current_appointment = current_appointment_query.filter(
        role_assignment_id=assignment.id,
        representation_id=representation.id,
        account_id=assignment.principal_id,
        role=RepresentationAppointment.Role.CONTROLLER,
        state=RepresentationAppointment.State.ACTIVE,
        ended_at__isnull=True,
    ).first()
    organization_query = context._locked(Organization.objects.all())
    membership_query = context._locked(OrganizationMembership.objects.all())
    if (
        current_appointment is None
        or representation.state != OrganizationRepresentation.State.ACTIVE
        or representation.activated_at != issuance.evaluated_at
        or current_appointment.responded_at is None
        or current_appointment.responded_at > issuance.evaluated_at
        or current_appointment.activated_at != issuance.evaluated_at
        or assignment.granted_by_id != representation.activated_by_id
        or assignment.approved_by_id != approver_appointment.account_id
        or not organization_query.filter(
            pk=assignment.organization_id,
            lifecycle=Organization.Lifecycle.ACTIVE,
        ).exists()
        or not membership_query.filter(
            organization_id=assignment.organization_id,
            account_id=assignment.principal_id,
            state=OrganizationMembership.State.ACTIVE,
            ended_at__isnull=True,
        ).exists()
    ):
        return False
    return _board_bundle_ceremony_is_valid(
        context=context,
        bundle=assignment.role_bundle,
        representation_id=representation.id,
    )


def _principal_was_person(context: _LineageContext, principal_id: UUID) -> bool:
    principal = context.account(principal_id)
    return bool(principal is not None and principal.account_kind == Account.Kind.PERSON)


def _board_assignment_was_current_at(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    assignment: RoleAssignment,
    evaluated_at: datetime,
) -> bool:
    historical = _special_controls_are_historical(
        context=context,
        issuance=issuance,
        organization_id=assignment.organization_id,
        recipient_id=assignment.principal_id,
    )
    if historical is None:
        return False
    representation, approver_appointment = historical
    appointment_query = context._locked(RepresentationAppointment.objects.all())
    appointment = (
        appointment_query.filter(
            role_assignment_id=assignment.id,
            representation_id=representation.id,
            account_id=assignment.principal_id,
            role=RepresentationAppointment.Role.CONTROLLER,
            state__in=(
                RepresentationAppointment.State.ACTIVE,
                RepresentationAppointment.State.ENDED,
            ),
            activated_at__lte=evaluated_at,
        )
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=evaluated_at))
        .first()
    )
    membership_query = context._locked(OrganizationMembership.objects.all())
    membership_exists = (
        membership_query.filter(
            organization_id=assignment.organization_id,
            account_id=assignment.principal_id,
            started_at__isnull=False,
            started_at__lte=evaluated_at,
        )
        .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=evaluated_at))
        .exists()
    )
    return bool(
        appointment is not None
        and representation.activated_at == issuance.evaluated_at
        and representation.activated_at <= evaluated_at
        and assignment.granted_by_id == representation.activated_by_id
        and assignment.approved_by_id == approver_appointment.account_id
        and Organization.objects.filter(pk=assignment.organization_id).exists()
        and membership_exists
        and _board_bundle_ceremony_is_valid(
            context=context,
            bundle=assignment.role_bundle,
            representation_id=representation.id,
        )
    )


def _validate_ordinary_controls_historical(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    target: CapabilityGrant | RoleAssignment,
    required_capability: str,
    evaluated_at: datetime,
    path: frozenset[int],
    depth: int,
) -> bool:
    controls = _controls_by_role(context, issuance)
    if controls is None:
        return False
    actor_id, approver_id, recipient_id = _target_attribution(target)
    if (
        actor_id is None
        or approver_id is None
        or approver_id in (actor_id, recipient_id)
    ):
        return False
    target_scope = _scope_from_authority(target)
    for role, principal_id in (
        (AuthorityControl.Role.ACTOR, actor_id),
        (AuthorityControl.Role.APPROVER, approver_id),
    ):
        control = controls[role]
        if (
            control.principal_id != principal_id
            or control.basis != AuthorityControl.Basis.PERSISTENT_AUTHORITY
            or control.source_issuance_id is None
            or control.source_issuance_id >= issuance.ordinal
            or control.representation_id is not None
            or control.appointment_id is not None
            or not _control_metadata_matches(issuance=issuance, control=control)
            or not _principal_was_person(context, principal_id)
            or not _validate_issuance_historical(
                context=context,
                ordinal=control.source_issuance_id,
                expectation=_Expectation(
                    principal_id=principal_id,
                    capability_code=required_capability,
                    target_scope=target_scope,
                    requested_effective_from=target.effective_from,
                    requested_expires_at=target.expires_at,
                    evaluated_at=evaluated_at,
                ),
                path=path,
                depth=depth + 1,
            )
        ):
            return False
    return True


def _validate_issuance_historical(  # noqa: PLR0911
    *,
    context: _LineageContext,
    ordinal: int,
    expectation: _Expectation,
    path: frozenset[int] = frozenset(),
    depth: int = 0,
) -> bool:
    """Prove an entire persistent lineage at one immutable past instant."""

    key = _validity_key(ordinal, expectation)
    if key in context.historical_validity:
        return context.historical_validity[key]
    if depth >= MAX_AUTHORITY_LINEAGE_DEPTH or ordinal in path:
        context.historical_validity[key] = False
        return False
    issuance = context.issuance(ordinal)
    if (
        issuance is None
        or not issuance.policy_version
        or issuance.evaluated_at > expectation.evaluated_at
    ):
        context.historical_validity[key] = False
        return False
    resolved = _issuance_target(context, issuance)
    if resolved is None or resolved[0] is _IssuanceTargetKind.ROLE_BUNDLE:
        context.historical_validity[key] = False
        return False
    source = resolved[1]
    if not isinstance(source, (CapabilityGrant, RoleAssignment)):
        context.historical_validity[key] = False
        return False
    if (
        source.principal_id != expectation.principal_id
        or not _principal_was_person(context, source.principal_id)
        or not _source_has_capability(source, expectation.capability_code)
        or not _authority_scope_is_current(source)
        or not _scope_contains(
            source=_scope_from_authority(source),
            target=expectation.target_scope,
        )
        or not _historical_horizon_is_covered(
            source=source,
            expectation=expectation,
        )
    ):
        context.historical_validity[key] = False
        return False
    if isinstance(source, RoleAssignment) and not _bundle_ceremony_is_historical(
        context=context,
        bundle=source.role_bundle,
        evaluated_at=expectation.evaluated_at,
    ):
        context.historical_validity[key] = False
        return False
    next_path = path | {ordinal}
    if isinstance(source, CapabilityGrant):
        if source.delegated_from_id is not None:
            parent_issuance = context.issuance_for_grant(source.delegated_from_id)
            valid = (
                not context.issuance_controls(ordinal)
                and parent_issuance is not None
                and _validate_issuance_historical(
                    context=context,
                    ordinal=parent_issuance.ordinal,
                    expectation=_Expectation(
                        principal_id=source.granted_by_id,
                        capability_code=source.capability_code,
                        target_scope=_scope_from_authority(source),
                        requested_effective_from=source.effective_from,
                        requested_expires_at=source.expires_at,
                        evaluated_at=expectation.evaluated_at,
                    ),
                    path=next_path,
                    depth=depth + 1,
                )
            )
        else:
            valid = _validate_ordinary_controls_historical(
                context=context,
                issuance=issuance,
                target=source,
                required_capability=_GRANT_CONTROL_CAPABILITY,
                evaluated_at=expectation.evaluated_at,
                path=next_path,
                depth=depth,
            )
    elif source.role_bundle.code == _EXECUTIVE_BOARD_ROLE_CODE:
        valid = _board_assignment_was_current_at(
            context=context,
            issuance=issuance,
            assignment=source,
            evaluated_at=expectation.evaluated_at,
        )
    else:
        valid = _validate_ordinary_controls_historical(
            context=context,
            issuance=issuance,
            target=source,
            required_capability=_ROLE_CONTROL_CAPABILITY,
            evaluated_at=expectation.evaluated_at,
            path=next_path,
            depth=depth,
        )
    context.historical_validity[key] = valid
    return valid


def _validity_key(ordinal: int, expectation: _Expectation) -> tuple[object, ...]:
    return (
        ordinal,
        expectation.principal_id,
        expectation.capability_code,
        expectation.target_scope,
        expectation.requested_effective_from,
        expectation.requested_expires_at,
        expectation.evaluated_at,
        expectation.horizon_mode,
    )


def _validate_issuance_current(  # noqa: PLR0911, PLR0912
    *,
    context: _LineageContext,
    ordinal: int,
    expectation: _Expectation,
    path: frozenset[int] = frozenset(),
    depth: int = 0,
) -> bool:
    key = _validity_key(ordinal, expectation)
    if key in context.validity:
        return context.validity[key]
    if depth >= MAX_AUTHORITY_LINEAGE_DEPTH or ordinal in path:
        context.validity[key] = False
        return False
    issuance = context.issuance(ordinal)
    if (
        issuance is None
        or not issuance.policy_version
        or issuance.evaluated_at > expectation.evaluated_at
    ):
        context.validity[key] = False
        return False
    resolved = _issuance_target(context, issuance)
    if resolved is None or resolved[0] is _IssuanceTargetKind.ROLE_BUNDLE:
        context.validity[key] = False
        return False
    _source_kind, source = resolved
    if not isinstance(source, (CapabilityGrant, RoleAssignment)):
        context.validity[key] = False
        return False
    if (
        source.principal_id != expectation.principal_id
        or not _principal_is_current(context, source.principal_id)
        or not _source_has_capability(source, expectation.capability_code)
        or not _authority_scope_is_current(source)
        or not _scope_contains(
            source=_scope_from_authority(source),
            target=expectation.target_scope,
        )
        or not _horizon_is_covered(source=source, expectation=expectation)
    ):
        context.validity[key] = False
        return False
    if isinstance(source, RoleAssignment) and not _bundle_ceremony_is_historical(
        context=context,
        bundle=source.role_bundle,
        evaluated_at=expectation.evaluated_at,
    ):
        context.validity[key] = False
        return False
    next_path = path | {ordinal}
    if isinstance(source, CapabilityGrant):
        if source.delegated_from_id is not None:
            if context.issuance_controls(ordinal):
                valid = False
            else:
                parent_issuance = context.issuance_for_grant(source.delegated_from_id)
                valid = parent_issuance is not None and _validate_issuance_current(
                    context=context,
                    ordinal=parent_issuance.ordinal,
                    expectation=_Expectation(
                        principal_id=source.granted_by_id,
                        capability_code=source.capability_code,
                        target_scope=_scope_from_authority(source),
                        requested_effective_from=source.effective_from,
                        requested_expires_at=source.expires_at,
                        evaluated_at=expectation.evaluated_at,
                    ),
                    path=next_path,
                    depth=depth + 1,
                )
        else:
            valid = _validate_ordinary_controls(
                context=context,
                issuance=issuance,
                target=source,
                required_capability=_GRANT_CONTROL_CAPABILITY,
                evaluated_at=expectation.evaluated_at,
                path=next_path,
                depth=depth,
            )
    elif source.role_bundle.code == _EXECUTIVE_BOARD_ROLE_CODE:
        valid = _board_assignment_is_current(
            context=context,
            issuance=issuance,
            assignment=source,
        )
    else:
        valid = _validate_ordinary_controls(
            context=context,
            issuance=issuance,
            target=source,
            required_capability=_ROLE_CONTROL_CAPABILITY,
            evaluated_at=expectation.evaluated_at,
            path=next_path,
            depth=depth,
        )
    context.validity[key] = valid
    return valid


def _source_rank(
    *,
    issuance: AuthorityIssuance,
    source_kind: PersistentSourceKind,
    source: CapabilityGrant | RoleAssignment,
) -> tuple[object, ...]:
    scope = _scope_from_authority(source)
    return (
        -scope.rank,
        0 if source_kind is PersistentSourceKind.CAPABILITY_GRANT else 1,
        1 if source.expires_at is None else 0,
        source.expires_at or source.effective_from,
        issuance.ordinal,
    )


def _authorized_control(
    *,
    role: str,
    principal_id: UUID,
    capability_code: str,
    source_kind: PersistentSourceKind,
    issuance: AuthorityIssuance,
    source: CapabilityGrant | RoleAssignment,
    evaluated_at: datetime,
) -> AuthorizedControl:
    return AuthorizedControl(
        role=role,
        principal_id=principal_id,
        capability_code=capability_code,
        source_kind=source_kind,
        source_issuance_ordinal=issuance.ordinal,
        source_authority_id=source.id,
        source_scope=_scope_from_authority(source).level,
        source_effective_from=source.effective_from,
        source_expires_at=source.expires_at,
        evaluated_at=evaluated_at,
        policy_version=issuance.policy_version,
    )


def role_bundle_provenance_is_historical(
    *,
    bundle: RoleBundle,
    evaluated_at: datetime | None = None,
    lock: bool = False,
) -> bool:
    """Verify a bundle's complete immutable creation proof.

    Assignment writers pass ``lock=True`` inside their target transaction.
    Read-only policy and reconciliation paths may leave locking disabled.
    """

    if lock and not connection.in_atomic_block:
        raise RuntimeError("Role-bundle provenance locking requires a transaction.")
    effective_evaluation = evaluated_at or timezone.now()
    if not timezone.is_aware(effective_evaluation) or bundle.pk is None:
        return False
    context = _LineageContext(lock=lock)
    bundle_query = context._locked(RoleBundle.objects.all())
    persisted_bundle = bundle_query.filter(pk=bundle.pk).first()
    if persisted_bundle is None:
        return False
    context.bundles[persisted_bundle.id] = persisted_bundle
    return _bundle_ceremony_is_historical(
        context=context,
        bundle=persisted_bundle,
        evaluated_at=effective_evaluation,
    )


def authority_issuance_is_current(
    *,
    issuance_ordinal: int,
    principal_id: UUID,
    capability_code: str,
    target: _ResolvedTarget,
    requested_effective_from: datetime,
    requested_expires_at: datetime | None,
    evaluated_at: datetime | None = None,
    lock: bool = False,
) -> bool:
    """Validate one caller-pinned issuance without selecting a replacement."""

    if lock and not connection.in_atomic_block:
        raise RuntimeError("Authority-issuance locking requires a transaction.")
    effective_evaluation = evaluated_at or timezone.now()
    target_scope = _scope_from_target(target)
    if (
        issuance_ordinal <= 0
        or not capability_code
        or target_scope is None
        or not _time_window_is_valid(
            requested_effective_from=requested_effective_from,
            requested_expires_at=requested_expires_at,
            evaluated_at=effective_evaluation,
            horizon_mode=ControlHorizonMode.PERSISTENT,
        )
        or not _resolved_target_is_current(target)
    ):
        return False
    return _validate_issuance_current(
        context=_LineageContext(lock=lock),
        ordinal=issuance_ordinal,
        expectation=_Expectation(
            principal_id=principal_id,
            capability_code=capability_code,
            target_scope=target_scope,
            requested_effective_from=requested_effective_from,
            requested_expires_at=requested_expires_at,
            evaluated_at=effective_evaluation,
        ),
    )


def select_authorized_control_source(
    *,
    principal: Account,
    role: str,
    capability_code: str,
    target: _ResolvedTarget,
    requested_expires_at: datetime | None,
    requested_effective_from: datetime | None = None,
    evaluated_at: datetime | None = None,
    horizon_mode: ControlHorizonMode = ControlHorizonMode.PERSISTENT,
) -> AuthorizedControl | None:
    """Lock, validate, and deterministically select one least-authority source.

    The caller supplies no source identifier.  This function must run inside
    the target-writing transaction so the selected issuance and controller are
    locked until the new provenance row is committed.
    """

    if not connection.in_atomic_block:
        raise RuntimeError("Authority source selection requires an open transaction.")
    if role not in {AuthorityControl.Role.ACTOR, AuthorityControl.Role.APPROVER}:
        raise ValueError("Use the actor or approver control role.")
    effective_evaluation = evaluated_at or timezone.now()
    effective_start = requested_effective_from or effective_evaluation
    if (
        not capability_code
        or not _time_window_is_valid(
            requested_effective_from=effective_start,
            requested_expires_at=requested_expires_at,
            evaluated_at=effective_evaluation,
            horizon_mode=horizon_mode,
        )
        or not _resolved_target_is_current(target)
    ):
        return None
    locked_principal = (
        Account.objects.select_for_update()
        .filter(
            pk=principal.pk,
            account_kind=Account.Kind.PERSON,
            is_active=True,
        )
        .first()
    )
    if locked_principal is None:
        return None
    target_scope = _scope_from_target(target)
    if target_scope is None:
        return None
    grant_ids = CapabilityGrant.objects.filter(principal_id=locked_principal.id).values(
        "id"
    )
    assignment_ids = RoleAssignment.objects.filter(
        principal_id=locked_principal.id
    ).values("id")
    candidate_query = AuthorityIssuance.objects.select_for_update().filter(
        Q(capability_grant_id__in=grant_ids) | Q(role_assignment_id__in=assignment_ids)
    )
    context = _LineageContext(lock=True)
    context.accounts[locked_principal.id] = locked_principal
    eligible: list[
        tuple[
            tuple[object, ...],
            AuthorityIssuance,
            PersistentSourceKind,
            CapabilityGrant | RoleAssignment,
        ]
    ] = []
    expectation = _Expectation(
        principal_id=locked_principal.id,
        capability_code=capability_code,
        target_scope=target_scope,
        requested_effective_from=effective_start,
        requested_expires_at=requested_expires_at,
        evaluated_at=effective_evaluation,
        horizon_mode=horizon_mode,
    )
    for candidate in candidate_query.order_by("ordinal"):
        context.issuances[candidate.ordinal] = candidate
        resolved = _issuance_target(context, candidate)
        if (
            resolved is None
            or resolved[0] is _IssuanceTargetKind.ROLE_BUNDLE
            or not isinstance(resolved[1], (CapabilityGrant, RoleAssignment))
            or not _validate_issuance_current(
                context=context,
                ordinal=candidate.ordinal,
                expectation=expectation,
            )
        ):
            continue
        source_kind = PersistentSourceKind(resolved[0].value)
        source = resolved[1]
        eligible.append(
            (
                _source_rank(
                    issuance=candidate,
                    source_kind=source_kind,
                    source=source,
                ),
                candidate,
                source_kind,
                source,
            )
        )
    if not eligible:
        return None
    _rank, issuance, source_kind, source = min(eligible, key=lambda item: item[0])
    return _authorized_control(
        role=role,
        principal_id=locked_principal.id,
        capability_code=capability_code,
        source_kind=source_kind,
        issuance=issuance,
        source=source,
        evaluated_at=effective_evaluation,
    )


def authorized_control_is_current(
    *,
    control: AuthorizedControl,
    target: _ResolvedTarget,
    requested_expires_at: datetime | None,
    requested_effective_from: datetime | None = None,
    evaluated_at: datetime | None = None,
    horizon_mode: ControlHorizonMode = ControlHorizonMode.PERSISTENT,
) -> bool:
    """Revalidate a previously selected source without silently rebinding it."""

    effective_evaluation = evaluated_at or timezone.now()
    effective_start = requested_effective_from or effective_evaluation
    target_scope = _scope_from_target(target)
    if (
        control.role
        not in {AuthorityControl.Role.ACTOR, AuthorityControl.Role.APPROVER}
        or target_scope is None
        or not _resolved_target_is_current(target)
        or not _time_window_is_valid(
            requested_effective_from=effective_start,
            requested_expires_at=requested_expires_at,
            evaluated_at=effective_evaluation,
            horizon_mode=horizon_mode,
        )
    ):
        return False
    context = _LineageContext(lock=False)
    expectation = _Expectation(
        principal_id=control.principal_id,
        capability_code=control.capability_code,
        target_scope=target_scope,
        requested_effective_from=effective_start,
        requested_expires_at=requested_expires_at,
        evaluated_at=effective_evaluation,
        horizon_mode=horizon_mode,
    )
    if not _validate_issuance_current(
        context=context,
        ordinal=control.source_issuance_ordinal,
        expectation=expectation,
    ):
        return False
    issuance = context.issuance(control.source_issuance_ordinal)
    if issuance is None:
        return False
    resolved = _issuance_target(context, issuance)
    if (
        resolved is None
        or resolved[0] is _IssuanceTargetKind.ROLE_BUNDLE
        or not isinstance(resolved[1], (CapabilityGrant, RoleAssignment))
    ):
        return False
    source_kind = PersistentSourceKind(resolved[0].value)
    source = resolved[1]
    return (
        source_kind == control.source_kind
        and source.id == control.source_authority_id
        and issuance.policy_version == control.policy_version
        and _scope_from_authority(source).level == control.source_scope
        and source.effective_from == control.source_effective_from
        and source.expires_at == control.source_expires_at
    )
