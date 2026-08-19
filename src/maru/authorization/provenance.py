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

from django.db import DatabaseError, connection, models
from django.db.models import Q, QuerySet
from django.db.transaction import TransactionManagementError
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
_POSTGRESQL_BIGINT_MAX = 9_223_372_036_854_775_807
_CURRENT_CHECK_DATABASE_BATCH_SIZE = 256
_REQUIRED_CONTROL_COUNT = 2
_AUTHORITY_PROVENANCE_ACTIVATION_LOCK = 4_400_440_007
_GRANT_CONTROL_CAPABILITY = "authorization.grant_direct"
_ROLE_CONTROL_CAPABILITY = "authorization.manage_roles"
_ModelT = TypeVar("_ModelT", bound=models.Model)


class AuthorityProvenanceWriterBoundaryError(DatabaseError):
    """A writer cannot safely join the active provenance generation."""


class AuthorityProvenanceWriterRestartRequiredError(
    AuthorityProvenanceWriterBoundaryError
):
    """The caller must restart its whole transaction in the new generation."""

    sqlstate = "40001"


def lock_authority_provenance_writer_boundary() -> int:
    """Join ADR 0044's writer boundary before taking narrower row locks.

    Structure and other cross-module commands call this inside their outermost
    transaction and before locking Organization or Department rows. The shared
    advisory lock serializes with cutover; the allowlisted latch helper retains
    the least-privilege runtime role and current trigger contract.

    Returns
    -------
    int
        The resolved int for lock authority provenance writer boundary.

    Raises
    ------
    AuthorityProvenanceWriterBoundaryError
        If the operation encounters a authority provenance writer boundary
        condition.
    AuthorityProvenanceWriterRestartRequiredError
        If the operation encounters a authority provenance writer restart
        required condition.
    TransactionManagementError
        If the operation encounters a transaction management condition.
    """
    if connection.get_autocommit() or not connection.in_atomic_block:
        raise TransactionManagementError(
            "The authority writer boundary requires an atomic transaction."
        )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                pg_catalog.pg_advisory_xact_lock_shared(%s),
                public.maru_lock_authority_provenance_latch(),
                pg_catalog.transaction_timestamp()
            """,
            [_AUTHORITY_PROVENANCE_ACTIVATION_LOCK],
        )
        row = cursor.fetchone()
        if row is None:
            raise AuthorityProvenanceWriterBoundaryError(
                "The authority provenance latch is unavailable."
            )
        generation = int(row[1])
        transaction_started_at = row[2]
        if generation == 0:
            return generation
        if generation != 1:
            raise AuthorityProvenanceWriterBoundaryError(
                "The authority provenance latch generation is unsupported."
            )
        cursor.execute(
            """
            SELECT activated_at
              FROM public.authorization_authorityprovenanceactivation
             WHERE singleton IS TRUE
            """
        )
        marker = cursor.fetchone()
        if marker is None or marker[0] is None:
            raise AuthorityProvenanceWriterBoundaryError(
                "The authority provenance cutover state is inconsistent."
            )
        if transaction_started_at < marker[0]:
            raise AuthorityProvenanceWriterRestartRequiredError(
                "The writer transaction predates authority provenance activation."
            )
        return generation


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
    """Enumerate supported persistent source kind values."""

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
    """One exact, source-bearing control selected for an issuance writer.

    Attributes
    ----------
    role
        The immutable or edition-owned role evaluated for authority.
    principal_id
        The principal identifier within the requested scope.
    capability_code
        The stable capability code required by the operation.
    source_kind
        The closed source kind discriminator defined by the domain catalog.
    source_issuance_ordinal
        The deterministic display position within the owning collection.
    source_authority_id
        The source authority identifier within the requested scope.
    source_scope
        The source scope retained in this immutable projection.
    source_effective_from
        The timezone-aware boundary for source effective from.
    source_expires_at
        The timezone-aware timestamp for source expires.
    evaluated_at
        The timezone-aware timestamp for evaluated.
    policy_version
        The expected policy version used to reject stale updates.
    """

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
class AuthorityIssuanceCurrentCheck:
    """One read-only exact-lineage validation in a call-scoped batch.

    The result boundary is positional booleans only.  Callers retain no shared
    validator state and receive no authority or issuance identifiers back.

    Attributes
    ----------
    issuance_ordinal
        The deterministic display position within the owning collection.
    principal_id
        The principal identifier within the requested scope.
    capability_code
        The stable capability code required by the operation.
    target
        The exact domain resource targeted by the operation.
    requested_effective_from
        The timezone-aware boundary for requested effective from.
    requested_expires_at
        The timezone-aware timestamp for requested expires.
    horizon_mode
        The closed horizon mode discriminator defined by the domain catalog.
    """

    issuance_ordinal: int
    principal_id: UUID
    capability_code: str
    target: _ResolvedTarget
    requested_effective_from: datetime
    requested_expires_at: datetime | None
    horizon_mode: ControlHorizonMode = ControlHorizonMode.PERSISTENT


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
    special_controls: dict[
        tuple[int, UUID, UUID | None],
        tuple[OrganizationRepresentation, RepresentationAppointment] | None,
    ] = field(default_factory=dict)
    current_board_assignments: dict[UUID, bool] = field(default_factory=dict)
    current_board_bundles: dict[tuple[UUID, UUID], bool] = field(default_factory=dict)
    current_scopes: dict[_Scope, bool] = field(default_factory=dict)
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
    """Repeat exact persisted target resolution without importing policy eagerly.

    Parameters
    ----------
    target : _ResolvedTarget
        The exact domain resource targeted by the operation.

    Returns
    -------
    bool
        `True` when Repeat exact persisted target resolution without importing
        policy eagerly; otherwise `False`.
    """
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


def _authority_scope_is_current(
    context: _LineageContext,
    authority: CapabilityGrant | RoleAssignment,
) -> bool:
    scope = _scope_from_authority(authority)
    if not _scope_shape_is_valid(scope):
        return False
    if scope not in context.current_scopes:
        context.current_scopes[scope] = _resolved_target_is_current(scope)
    return context.current_scopes[scope]


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

    Parameters
    ----------
    source : CapabilityGrant | RoleAssignment
        The immutable source record or definition from which data is derived.
    expectation : _Expectation
        The expectation evaluated while historical horizon is covered.

    Returns
    -------
    bool
        `True` when Evaluate one immutable source at a past instant; otherwise
        `False`.
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
    key = (issuance.ordinal, organization_id, recipient_id)
    if key not in context.special_controls:
        context.special_controls[key] = _load_special_controls_historical(
            context=context,
            issuance=issuance,
            organization_id=organization_id,
            recipient_id=recipient_id,
        )
    return context.special_controls[key]


def _executive_board_definition() -> tuple[str, str, int, frozenset[str], str]:
    """Load the representation service's canonical reserved-role definition.

    Returns
    -------
    tuple[str, str, int, frozenset[str], str]
        The matching executive board definition records in deterministic order.
    """
    from maru.organizations.representation import (  # noqa: PLC0415
        EXECUTIVE_BOARD_CAPABILITIES,
        EXECUTIVE_BOARD_MEMBERSHIP_LABEL,
        EXECUTIVE_BOARD_ROLE_CODE,
        EXECUTIVE_BOARD_ROLE_NAME,
        EXECUTIVE_BOARD_ROLE_VERSION,
    )

    return (
        EXECUTIVE_BOARD_ROLE_CODE,
        EXECUTIVE_BOARD_ROLE_NAME,
        EXECUTIVE_BOARD_ROLE_VERSION,
        frozenset(EXECUTIVE_BOARD_CAPABILITIES),
        EXECUTIVE_BOARD_MEMBERSHIP_LABEL,
    )


def _is_executive_board_role(bundle: RoleBundle) -> bool:
    role_code, _role_name, _role_version, _capabilities, _membership_label = (
        _executive_board_definition()
    )
    return bundle.code == role_code


def _executive_board_bundle_shape_is_valid(bundle: RoleBundle) -> bool:
    role_code, role_name, role_version, capabilities, _membership_label = (
        _executive_board_definition()
    )
    capability_codes = tuple(bundle.capability_codes)
    return bool(
        bundle.code == role_code
        and bundle.name == role_name
        and bundle.version == role_version
        and len(capability_codes) == len(capabilities)
        and frozenset(capability_codes) == capabilities
    )


def _load_special_controls_historical(
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
        actor.principal_id == approver.principal_id
        or actor.basis != AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP
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
        or representation.code != OrganizationRepresentation.EXECUTIVE_BOARD_CODE
        or representation.name != OrganizationRepresentation.EXECUTIVE_BOARD_NAME
        or appointment.role != RepresentationAppointment.Role.CONTROLLER
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
            if _executive_board_bundle_shape_is_valid(bundle):
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
            elif not _is_executive_board_role(bundle):
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
    key = (bundle.id, representation_id)
    if key not in context.current_board_bundles:
        context.current_board_bundles[key] = _load_board_bundle_ceremony_is_valid(
            context=context,
            bundle=bundle,
            representation_id=representation_id,
        )
    return context.current_board_bundles[key]


def _load_board_bundle_ceremony_is_valid(
    *,
    context: _LineageContext,
    bundle: RoleBundle,
    representation_id: UUID,
) -> bool:
    if not _executive_board_bundle_shape_is_valid(bundle):
        return False
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
        representation.id == representation_id
        and actor_id == representation.activated_by_id
        and approver_id == appointment.account_id
    )


def _board_assignment_is_current(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    assignment: RoleAssignment,
) -> bool:
    if assignment.id not in context.current_board_assignments:
        context.current_board_assignments[assignment.id] = (
            _load_board_assignment_is_current(
                context=context,
                issuance=issuance,
                assignment=assignment,
            )
        )
    return context.current_board_assignments[assignment.id]


def _load_board_assignment_is_current(
    *,
    context: _LineageContext,
    issuance: AuthorityIssuance,
    assignment: RoleAssignment,
) -> bool:
    principal = context.account(assignment.principal_id)
    if (
        not _executive_board_bundle_shape_is_valid(assignment.role_bundle)
        or assignment.edition_id is not None
        or assignment.department_id is not None
        or assignment.resource_binding_id is not None
        or assignment.effective_from != issuance.evaluated_at
        or assignment.expires_at is not None
        or assignment.revoked_at is not None
        or principal is None
        or principal.account_kind != Account.Kind.PERSON
        or not principal.is_active
        or not principal.has_verified_email
    ):
        return False
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
    _code, _name, _version, _capabilities, membership_label = (
        _executive_board_definition()
    )
    membership = membership_query.filter(
        organization_id=assignment.organization_id,
        account_id=assignment.principal_id,
    ).first()
    if (
        current_appointment is None
        or representation.state != OrganizationRepresentation.State.ACTIVE
        or representation.activated_at != issuance.evaluated_at
        or assignment.reason != representation.activation_reason
        or current_appointment.responded_at is None
        or current_appointment.responded_at > issuance.evaluated_at
        or current_appointment.activated_at != issuance.evaluated_at
        or assignment.granted_by_id != representation.activated_by_id
        or assignment.approved_by_id != approver_appointment.account_id
        or not organization_query.filter(
            pk=assignment.organization_id,
            lifecycle=Organization.Lifecycle.ACTIVE,
        ).exists()
        or membership is None
        or membership.state != OrganizationMembership.State.ACTIVE
        or membership.relationship_label != membership_label
        or membership.started_at is None
        or membership.ended_at is not None
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
    if (
        not _executive_board_bundle_shape_is_valid(assignment.role_bundle)
        or assignment.edition_id is not None
        or assignment.department_id is not None
        or assignment.resource_binding_id is not None
        or assignment.effective_from != issuance.evaluated_at
        or assignment.expires_at is not None
        or (assignment.revoked_at is not None and assignment.revoked_at <= evaluated_at)
        or not _principal_was_person(context, assignment.principal_id)
    ):
        return False
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
        and assignment.reason == representation.activation_reason
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
    """Prove an entire persistent lineage at one immutable past instant.

    Parameters
    ----------
    context : _LineageContext
        The request context supplied by the calling framework.
    ordinal : int
        The deterministic display position within the owning collection.
    expectation : _Expectation
        The expectation evaluated while validate issuance historical.
    path : frozenset[int], default=frozenset()
        The filesystem path to read, validate, or write.
    depth : int, default=0
        The depth evaluated while validate issuance historical.

    Returns
    -------
    bool
        `True` when Prove an entire persistent lineage at one immutable past
        instant; otherwise `False`.
    """
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
        or not _authority_scope_is_current(context, source)
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
    elif _is_executive_board_role(source.role_bundle):
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
        or not _authority_scope_is_current(context, source)
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
    elif _is_executive_board_role(source.role_bundle):
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

    Parameters
    ----------
    bundle : RoleBundle
        The bundle evaluated while role bundle provenance is historical.
    evaluated_at : datetime | None, default=None
        The timezone-aware timestamp for evaluated.
    lock : bool, default=False
        The database lock or mutex protecting this transition.

    Returns
    -------
    bool
        `True` when Verify a bundle's complete immutable creation proof;
        otherwise `False`.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
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


def _authority_issuances_are_current_python(
    *,
    checks: tuple[AuthorityIssuanceCurrentCheck, ...],
    evaluated_at: datetime,
    lock: bool,
) -> tuple[bool, ...]:
    """Run the Python validator, retaining the lock-capable writer path.

    Parameters
    ----------
    checks : tuple[AuthorityIssuanceCurrentCheck, ...]
        The named integrity checks required for readiness.
    evaluated_at : datetime
        The timezone-aware timestamp for evaluated.
    lock : bool
        The database lock or mutex protecting this transition.

    Returns
    -------
    tuple[bool, ...]
        The matching authority issuances are current python records in
        deterministic order.
    """
    context = _LineageContext(lock=lock)
    current_targets: dict[_Scope, bool] = {}
    results: list[bool] = []
    for check in checks:
        try:
            target_scope = _scope_from_target(check.target)
            if (
                check.issuance_ordinal <= 0
                or not check.capability_code
                or target_scope is None
                or not _time_window_is_valid(
                    requested_effective_from=check.requested_effective_from,
                    requested_expires_at=check.requested_expires_at,
                    evaluated_at=evaluated_at,
                    horizon_mode=check.horizon_mode,
                )
            ):
                valid = False
            else:
                if target_scope not in current_targets:
                    current_targets[target_scope] = _resolved_target_is_current(
                        check.target
                    )
                valid = current_targets[target_scope] and _validate_issuance_current(
                    context=context,
                    ordinal=check.issuance_ordinal,
                    expectation=_Expectation(
                        principal_id=check.principal_id,
                        capability_code=check.capability_code,
                        target_scope=target_scope,
                        requested_effective_from=check.requested_effective_from,
                        requested_expires_at=check.requested_expires_at,
                        evaluated_at=evaluated_at,
                        horizon_mode=check.horizon_mode,
                    ),
                )
        except (AttributeError, TypeError, ValueError):
            # Malformed in-process callers do not gain authority or prevent
            # later independent positions from being evaluated.
            valid = False
        results.append(valid)
    return tuple(results)


def _database_current_check_is_well_formed(
    *,
    check: AuthorityIssuanceCurrentCheck,
    target_scope: _Scope | None,
    evaluated_at: datetime,
) -> bool:
    """Reject malformed values before they reach PostgreSQL's typed boundary.

    Parameters
    ----------
    check : AuthorityIssuanceCurrentCheck
        The check evaluated while database current check is well formed.
    target_scope : _Scope | None
        The target scope evaluated while database current check is well formed.
    evaluated_at : datetime
        The timezone-aware timestamp for evaluated.

    Returns
    -------
    bool
        `True` when Reject malformed values before they reach PostgreSQL's typed
        boundary; otherwise `False`.
    """
    scope_values = (
        ()
        if target_scope is None
        else (
            target_scope.organization_id,
            target_scope.edition_id,
            target_scope.department_id,
            target_scope.resource_binding_id,
        )
    )
    return bool(
        isinstance(check.issuance_ordinal, int)
        and not isinstance(check.issuance_ordinal, bool)
        and 0 < check.issuance_ordinal <= _POSTGRESQL_BIGINT_MAX
        and isinstance(check.principal_id, UUID)
        and isinstance(check.capability_code, str)
        and bool(check.capability_code.strip())
        and target_scope is not None
        and isinstance(target_scope.organization_id, UUID)
        and all(value is None or isinstance(value, UUID) for value in scope_values)
        and isinstance(check.requested_effective_from, datetime)
        and (
            check.requested_expires_at is None
            or isinstance(check.requested_expires_at, datetime)
        )
        and check.horizon_mode
        in {ControlHorizonMode.PERSISTENT, ControlHorizonMode.POINT_IN_TIME}
        and _time_window_is_valid(
            requested_effective_from=check.requested_effective_from,
            requested_expires_at=check.requested_expires_at,
            evaluated_at=evaluated_at,
            horizon_mode=check.horizon_mode,
        )
    )


def _authority_issuances_are_current_database(
    *,
    checks: tuple[AuthorityIssuanceCurrentCheck, ...],
    evaluated_at: datetime,
) -> tuple[bool, ...]:
    """Evaluate pinned issuances through the fingerprinted database contract.

    Persisted target resolution remains in Python so a valid ancestor scope
    cannot authorize an identifier whose current tenant ancestry has changed.
    PostgreSQL receives only already-resolved identifiers and returns positional
    booleans; it never selects or discloses an alternative authority source.

    Parameters
    ----------
    checks : tuple[AuthorityIssuanceCurrentCheck, ...]
        The named integrity checks required for readiness.
    evaluated_at : datetime
        The timezone-aware timestamp for evaluated.

    Returns
    -------
    tuple[bool, ...]
        The matching authority issuances are current database records in
        deterministic order.
    """
    results = [False] * len(checks)
    current_targets: dict[_Scope, bool] = {}
    prepared: list[tuple[int, AuthorityIssuanceCurrentCheck, _Scope]] = []
    for position, check in enumerate(checks):
        try:
            target_scope = _scope_from_target(check.target)
            if not _database_current_check_is_well_formed(
                check=check,
                target_scope=target_scope,
                evaluated_at=evaluated_at,
            ):
                continue
            if target_scope is None:
                continue
            if target_scope not in current_targets:
                current_targets[target_scope] = _resolved_target_is_current(
                    check.target
                )
            if current_targets[target_scope]:
                prepared.append((position, check, target_scope))
        except (AttributeError, TypeError, ValueError):
            # One malformed in-process position cannot suppress independent
            # checks or widen authority.
            continue
    if not prepared:
        return tuple(results)

    statement = """
        WITH validation_input AS (
            SELECT *
              FROM ROWS FROM (
                  pg_catalog.unnest(%s::integer[]),
                  pg_catalog.unnest(%s::bigint[]),
                  pg_catalog.unnest(%s::uuid[]),
                  pg_catalog.unnest(%s::varchar[]),
                  pg_catalog.unnest(%s::uuid[]),
                  pg_catalog.unnest(%s::uuid[]),
                  pg_catalog.unnest(%s::uuid[]),
                  pg_catalog.unnest(%s::uuid[]),
                  pg_catalog.unnest(%s::timestamptz[]),
                  pg_catalog.unnest(%s::timestamptz[]),
                  pg_catalog.unnest(%s::boolean[])
              ) AS supplied(
                  position,
                  issuance_ordinal,
                  principal_id,
                  capability_code,
                  organization_id,
                  edition_id,
                  department_id,
                  resource_binding_id,
                  requested_effective_from,
                  requested_expires_at,
                  persistent_horizon
              )
        )
        SELECT supplied.position,
               public.maru_authority_issuance_valid_v1(
                   supplied.issuance_ordinal,
                   supplied.principal_id,
                   supplied.capability_code,
                   supplied.organization_id,
                   supplied.edition_id,
                   supplied.department_id,
                   supplied.resource_binding_id,
                   supplied.requested_effective_from,
                   supplied.requested_expires_at,
                   %s::timestamptz,
                   TRUE,
                   supplied.persistent_horizon,
                   ARRAY[]::bigint[],
                   0
               ) AS is_current
          FROM validation_input AS supplied
         ORDER BY supplied.position
    """
    for offset in range(0, len(prepared), _CURRENT_CHECK_DATABASE_BATCH_SIZE):
        batch = prepared[offset : offset + _CURRENT_CHECK_DATABASE_BATCH_SIZE]
        parameters = (
            [item[0] for item in batch],
            [item[1].issuance_ordinal for item in batch],
            [item[1].principal_id for item in batch],
            [item[1].capability_code for item in batch],
            [item[2].organization_id for item in batch],
            [item[2].edition_id for item in batch],
            [item[2].department_id for item in batch],
            [item[2].resource_binding_id for item in batch],
            [item[1].requested_effective_from for item in batch],
            [item[1].requested_expires_at for item in batch],
            [item[1].horizon_mode is ControlHorizonMode.PERSISTENT for item in batch],
            evaluated_at,
        )
        with connection.cursor() as cursor:
            cursor.execute(statement, parameters)
            for position, is_current in cursor.fetchall():
                results[position] = bool(is_current)
    return tuple(results)


def authority_issuances_are_current(
    *,
    checks: tuple[AuthorityIssuanceCurrentCheck, ...],
    evaluated_at: datetime | None = None,
    lock: bool = False,
) -> tuple[bool, ...]:
    """Validate exact issuances at their supplied ordinals as positional booleans.

    Read-only batches use ADR 0044's installed and fingerprinted PostgreSQL
    validator in one round trip.  The lock-capable writer path deliberately
    retains the independent Python validator.  Neither path performs
    existential source selection, and duplicate ordinals stay distinct input
    positions.

    Parameters
    ----------
    checks : tuple[AuthorityIssuanceCurrentCheck, ...]
        The named integrity checks required for readiness.
    evaluated_at : datetime | None, default=None
        The timezone-aware timestamp for evaluated.
    lock : bool, default=False
        The database lock or mutex protecting this transition.

    Returns
    -------
    tuple[bool, ...]
        The matching authority issuances are current records in deterministic
        order.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    """
    if lock and not connection.in_atomic_block:
        raise RuntimeError("Authority-issuance locking requires a transaction.")
    effective_evaluation = evaluated_at or timezone.now()
    if lock:
        return _authority_issuances_are_current_python(
            checks=checks,
            evaluated_at=effective_evaluation,
            lock=True,
        )
    return _authority_issuances_are_current_database(
        checks=checks,
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
    horizon_mode: ControlHorizonMode = ControlHorizonMode.PERSISTENT,
    lock: bool = False,
) -> bool:
    """Validate one caller-pinned issuance without selecting a replacement.

    Single-source and writer checks retain the Python implementation.  The
    database fast path is intentionally confined to the explicit read batch
    boundary above, which is differentially tested against this path.

    Parameters
    ----------
    issuance_ordinal : int
        The deterministic display position within the owning collection.
    principal_id : UUID
        The principal identifier within the requested scope.
    capability_code : str
        The stable capability code required by the operation.
    target : _ResolvedTarget
        The exact domain resource targeted by the operation.
    requested_effective_from : datetime
        The timezone-aware boundary for requested effective from.
    requested_expires_at : datetime | None
        The timezone-aware timestamp for requested expires.
    evaluated_at : datetime | None, default=None
        The timezone-aware timestamp for evaluated.
    horizon_mode : ControlHorizonMode, default=ControlHorizonMode.PERSISTENT
        The closed horizon mode discriminator defined by the domain catalog.
    lock : bool, default=False
        The database lock or mutex protecting this transition.

    Returns
    -------
    bool
        `True` when Validate one caller-pinned issuance without selecting a
        replacement; otherwise `False`.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    """
    effective_evaluation = evaluated_at or timezone.now()
    if lock and not connection.in_atomic_block:
        raise RuntimeError("Authority-issuance locking requires a transaction.")
    return _authority_issuances_are_current_python(
        checks=(
            AuthorityIssuanceCurrentCheck(
                issuance_ordinal=issuance_ordinal,
                principal_id=principal_id,
                capability_code=capability_code,
                target=target,
                requested_effective_from=requested_effective_from,
                requested_expires_at=requested_expires_at,
                horizon_mode=horizon_mode,
            ),
        ),
        evaluated_at=effective_evaluation,
        lock=lock,
    )[0]


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

    Parameters
    ----------
    principal : Account
        The authenticated principal whose authority is evaluated.
    role : str
        The immutable or edition-owned role evaluated for authority.
    capability_code : str
        The stable capability code required by the operation.
    target : _ResolvedTarget
        The exact domain resource targeted by the operation.
    requested_expires_at : datetime | None
        The timezone-aware timestamp for requested expires.
    requested_effective_from : datetime | None, default=None
        The timezone-aware boundary for requested effective from.
    evaluated_at : datetime | None, default=None
        The timezone-aware timestamp for evaluated.
    horizon_mode : ControlHorizonMode, default=ControlHorizonMode.PERSISTENT
        The closed horizon mode discriminator defined by the domain catalog.

    Returns
    -------
    AuthorizedControl | None
        The AuthorizedControl | None produced by select authorized control
        source.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    ValueError
        If the supplied value cannot satisfy the documented contract.
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
    """Revalidate a previously selected source without silently rebinding it.

    Parameters
    ----------
    control : AuthorizedControl
        The control evaluated while authorized control is current.
    target : _ResolvedTarget
        The exact domain resource targeted by the operation.
    requested_expires_at : datetime | None
        The timezone-aware timestamp for requested expires.
    requested_effective_from : datetime | None, default=None
        The timezone-aware boundary for requested effective from.
    evaluated_at : datetime | None, default=None
        The timezone-aware timestamp for evaluated.
    horizon_mode : ControlHorizonMode, default=ControlHorizonMode.PERSISTENT
        The closed horizon mode discriminator defined by the domain catalog.

    Returns
    -------
    bool
        `True` when Revalidate a previously selected source without silently
        rebinding it; otherwise `False`.
    """
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
