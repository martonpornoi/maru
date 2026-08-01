"""Append-only writers for exact authority-issuance provenance."""

from __future__ import annotations

from datetime import datetime
from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.identity.models import Account
from maru.organizations.models import (
    OrganizationRepresentation,
    RepresentationAppointment,
)

type AuthorityTarget = CapabilityGrant | RoleBundle | RoleAssignment

_GRANT_CAPABILITY = "authorization.grant_direct"
_ROLE_CAPABILITY = "authorization.manage_roles"
_EXECUTIVE_BOARD_ROLE_CODE = "executive-board"


def _raise_validation(message: str, *, code: str) -> Never:
    raise ValidationError(message, code=code)


def _lock_target(target: AuthorityTarget) -> AuthorityTarget:
    if target.pk is None:
        _raise_validation(
            "Authority provenance requires an already-created target.",
            code="authority_target_unsaved",
        )
    model = type(target)
    try:
        return model.objects.select_for_update().get(pk=target.pk)
    except model.DoesNotExist:
        _raise_validation(
            "The authority target is unavailable.",
            code="authority_target_unavailable",
        )


def _target_field(target: AuthorityTarget) -> str:
    if isinstance(target, CapabilityGrant):
        return "capability_grant"
    if isinstance(target, RoleBundle):
        return "role_bundle"
    if isinstance(target, RoleAssignment):
        return "role_assignment"
    _raise_validation(
        "Use a supported typed authority target.",
        code="authority_target_unsupported",
    )


def _target_attribution(
    target: AuthorityTarget,
) -> tuple[UUID | None, UUID | None, UUID | None, str]:
    if isinstance(target, CapabilityGrant):
        return (
            target.granted_by_id,
            target.approved_by_id,
            target.principal_id,
            _GRANT_CAPABILITY,
        )
    if isinstance(target, RoleBundle):
        return (
            target.created_by_id,
            target.approved_by_id,
            None,
            _ROLE_CAPABILITY,
        )
    return (
        target.granted_by_id,
        target.approved_by_id,
        target.principal_id,
        _ROLE_CAPABILITY,
    )


def _target_scope(
    target: AuthorityTarget,
) -> tuple[object, object | None, object | None, object | None]:
    if isinstance(target, RoleBundle):
        return target.organization_id, None, None, None
    return (
        target.organization_id,
        target.edition_id,
        target.department_id,
        target.resource_binding_id,
    )


def _target_expiry(target: AuthorityTarget) -> datetime | None:
    return None if isinstance(target, RoleBundle) else target.expires_at


def _source_target(source: AuthorityIssuance) -> CapabilityGrant | RoleAssignment:
    candidates = (
        source.capability_grant,
        source.role_assignment,
    )
    resolved = [candidate for candidate in candidates if candidate is not None]
    if len(resolved) != 1 or source.role_bundle_id is not None:
        _raise_validation(
            "A persistent control must name one grant or role assignment issuance.",
            code="authority_source_target_invalid",
        )
    return resolved[0]


def _scope_contains(
    *,
    source: CapabilityGrant | RoleAssignment,
    target: AuthorityTarget,
) -> bool:
    organization_id, edition_id, department_id, resource_binding_id = _target_scope(
        target
    )
    if source.organization_id != organization_id:
        return False
    if source.resource_binding_id is not None:
        return source.resource_binding_id == resource_binding_id
    if source.department_id is not None:
        return source.edition_id == edition_id and source.department_id == department_id
    if source.edition_id is not None:
        return source.edition_id == edition_id
    return True


def _source_has_capability(
    source: CapabilityGrant | RoleAssignment,
    capability_code: str,
) -> bool:
    if isinstance(source, CapabilityGrant):
        return source.capability_code == capability_code
    return capability_code in source.role_bundle.capability_codes


def _validate_persistent_source(
    *,
    source_issuance: AuthorityIssuance,
    principal_id: UUID,
    capability_code: str,
    target: AuthorityTarget,
    evaluated_at: datetime,
) -> None:
    source = _source_target(source_issuance)
    if source.principal_id != principal_id:
        _raise_validation(
            "The control source belongs to another principal.",
            code="authority_source_principal_mismatch",
        )
    if not _source_has_capability(source, capability_code):
        _raise_validation(
            "The control source does not provide the required capability.",
            code="authority_source_capability_mismatch",
        )
    if not _scope_contains(source=source, target=target):
        _raise_validation(
            "The control source does not contain the target scope.",
            code="authority_source_scope_mismatch",
        )
    if (
        source.effective_from > evaluated_at
        or source.revoked_at is not None
        or (source.expires_at is not None and source.expires_at <= evaluated_at)
    ):
        _raise_validation(
            "The control source is not currently effective.",
            code="authority_source_inactive",
        )
    target_expiry = _target_expiry(target)
    if (
        not isinstance(target, RoleBundle)
        and source.expires_at is not None
        and (target_expiry is None or target_expiry > source.expires_at)
    ):
        _raise_validation(
            "The target cannot outlive its exact control source.",
            code="authority_source_horizon_too_short",
        )
    if not source.principal.is_active:
        _raise_validation(
            "The control source principal is inactive.",
            code="authority_source_principal_inactive",
        )


def _new_issuance(
    *,
    target: AuthorityTarget,
    evaluated_at: datetime,
) -> AuthorityIssuance:
    values: dict[str, object] = {
        "policy_version": POLICY_VERSION,
        "evaluated_at": evaluated_at,
        _target_field(target): target,
    }
    issuance = AuthorityIssuance(**values)
    issuance.full_clean()
    issuance.save(force_insert=True)
    return issuance


def _new_control(
    *,
    issuance: AuthorityIssuance,
    role: str,
    principal_id: UUID,
    basis: str,
    evaluated_at: datetime,
    source_issuance: AuthorityIssuance | None = None,
    representation: OrganizationRepresentation | None = None,
    appointment: RepresentationAppointment | None = None,
) -> AuthorityControl:
    control = AuthorityControl(
        issuance=issuance,
        role=role,
        principal_id=principal_id,
        basis=basis,
        source_issuance=source_issuance,
        representation=representation,
        appointment=appointment,
        policy_version=POLICY_VERSION,
        evaluated_at=evaluated_at,
    )
    control.full_clean()
    control.save(force_insert=True)
    return control


@transaction.atomic
def create_persistent_dual_control_issuance(
    *,
    target: AuthorityTarget,
    actor_source: AuthorityIssuance,
    approver_source: AuthorityIssuance,
    evaluated_at: datetime | None = None,
) -> AuthorityIssuance:
    """Pin two exact persistent sources for an ordinary root issuance."""

    locked_target = _lock_target(target)
    if isinstance(locked_target, CapabilityGrant) and (
        locked_target.delegated_from_id is not None
    ):
        _raise_validation(
            "A delegated grant uses its parent lineage, not dual controls.",
            code="delegated_grant_dual_control_forbidden",
        )
    actor_id, approver_id, recipient_id, capability_code = _target_attribution(
        locked_target
    )
    if actor_id is None or approver_id is None or actor_id == approver_id:
        _raise_validation(
            "Root issuance requires two distinct attributed controllers.",
            code="distinct_authority_controls_required",
        )
    if recipient_id is not None and approver_id == recipient_id:
        _raise_validation(
            "The authority recipient cannot approve their own issuance.",
            code="recipient_cannot_approve",
        )
    effective_evaluation = evaluated_at or timezone.now()
    for principal_id, source in (
        (actor_id, actor_source),
        (approver_id, approver_source),
    ):
        _validate_persistent_source(
            source_issuance=source,
            principal_id=principal_id,
            capability_code=capability_code,
            target=locked_target,
            evaluated_at=effective_evaluation,
        )
    issuance = _new_issuance(
        target=locked_target,
        evaluated_at=effective_evaluation,
    )
    _new_control(
        issuance=issuance,
        role=AuthorityControl.Role.ACTOR,
        principal_id=actor_id,
        basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
        source_issuance=actor_source,
        evaluated_at=effective_evaluation,
    )
    _new_control(
        issuance=issuance,
        role=AuthorityControl.Role.APPROVER,
        principal_id=approver_id,
        basis=AuthorityControl.Basis.PERSISTENT_AUTHORITY,
        source_issuance=approver_source,
        evaluated_at=effective_evaluation,
    )
    return issuance


@transaction.atomic
def create_delegated_grant_issuance(
    *,
    grant: CapabilityGrant,
    evaluated_at: datetime | None = None,
) -> AuthorityIssuance:
    """Record one delegated grant whose exact source remains ``delegated_from``."""

    locked_grant = _lock_target(grant)
    if not isinstance(locked_grant, CapabilityGrant):
        _raise_validation(
            "Delegated provenance requires a capability grant.",
            code="delegated_grant_target_required",
        )
    if locked_grant.delegated_from_id is None:
        _raise_validation(
            "A zero-control issuance requires an exact delegated parent.",
            code="delegated_parent_required",
        )
    parent = locked_grant.delegated_from
    if (
        parent is None
        or parent.principal_id != locked_grant.granted_by_id
        or parent.capability_code != locked_grant.capability_code
        or not hasattr(parent, "authority_issuance")
    ):
        _raise_validation(
            "The delegated parent lacks exact issuance provenance.",
            code="delegated_parent_provenance_invalid",
        )
    return _new_issuance(
        target=locked_grant,
        evaluated_at=evaluated_at or timezone.now(),
    )


def _validate_board_basis(
    *,
    target: RoleBundle | RoleAssignment,
    representation: OrganizationRepresentation,
    actor: Account,
    approver_appointment: RepresentationAppointment,
    evaluated_at: datetime,
) -> None:
    actor_id, approver_id, recipient_id, _capability_code = _target_attribution(target)
    if (
        representation.organization_id != target.organization_id
        or representation.state != OrganizationRepresentation.State.ACTIVE
        or representation.activated_by_id != actor.id
        or representation.activated_at != evaluated_at
        or actor_id != actor.id
        or not actor.is_active
        or not actor.is_platform_administrator
    ):
        _raise_validation(
            "The platform bootstrap basis does not match this activation.",
            code="platform_representation_bootstrap_mismatch",
        )
    if (
        approver_appointment.representation_id != representation.id
        or approver_appointment.account_id != approver_id
        or approver_appointment.state
        not in (
            RepresentationAppointment.State.ACCEPTED,
            RepresentationAppointment.State.ACTIVE,
        )
        or approver_appointment.responded_at is None
        or approver_appointment.responded_at > evaluated_at
        or (
            recipient_id is not None and approver_appointment.account_id == recipient_id
        )
    ):
        _raise_validation(
            "The representation acceptance does not match the independent approver.",
            code="representation_acceptance_mismatch",
        )
    if isinstance(target, RoleBundle):
        valid_target = target.code == _EXECUTIVE_BOARD_ROLE_CODE
    else:
        valid_target = (
            target.role_bundle.code == _EXECUTIVE_BOARD_ROLE_CODE
            and target.edition_id is None
            and target.department_id is None
            and target.resource_binding_id is None
            and target.effective_from == evaluated_at
            and target.expires_at is None
        )
    if not valid_target:
        _raise_validation(
            "Special representation provenance is reserved for the root Board.",
            code="executive_board_authority_target_mismatch",
        )


def _lock_board_evidence(
    *,
    representation: OrganizationRepresentation,
    actor: Account,
    approver_appointment: RepresentationAppointment,
) -> tuple[OrganizationRepresentation, Account, RepresentationAppointment]:
    """Reload exact ceremony evidence so relation caches cannot affect validation."""

    try:
        locked_representation = (
            OrganizationRepresentation.objects.select_for_update().get(
                pk=representation.pk
            )
        )
        locked_actor = Account.objects.select_for_update().get(pk=actor.pk)
        locked_appointment = (
            RepresentationAppointment.objects.select_for_update()
            .select_related("representation")
            .get(pk=approver_appointment.pk)
        )
    except (
        OrganizationRepresentation.DoesNotExist,
        Account.DoesNotExist,
        RepresentationAppointment.DoesNotExist,
    ):
        _raise_validation(
            "The Executive Board ceremony evidence is unavailable.",
            code="executive_board_evidence_unavailable",
        )
    return locked_representation, locked_actor, locked_appointment


@transaction.atomic
def create_executive_board_issuance(
    *,
    target: RoleBundle | RoleAssignment,
    representation: OrganizationRepresentation,
    actor: Account,
    approver_appointment: RepresentationAppointment,
    evaluated_at: datetime,
) -> AuthorityIssuance:
    """Record the non-cyclic, code-owned initial Executive Board ceremony."""

    locked_target = _lock_target(target)
    if not isinstance(locked_target, (RoleBundle, RoleAssignment)):
        _raise_validation(
            "Executive Board provenance requires a bundle or assignment.",
            code="executive_board_authority_target_required",
        )
    locked_representation, locked_actor, locked_appointment = _lock_board_evidence(
        representation=representation,
        actor=actor,
        approver_appointment=approver_appointment,
    )
    _validate_board_basis(
        target=locked_target,
        representation=locked_representation,
        actor=locked_actor,
        approver_appointment=locked_appointment,
        evaluated_at=evaluated_at,
    )
    issuance = _new_issuance(target=locked_target, evaluated_at=evaluated_at)
    _new_control(
        issuance=issuance,
        role=AuthorityControl.Role.ACTOR,
        principal_id=locked_actor.id,
        basis=AuthorityControl.Basis.PLATFORM_REPRESENTATION_BOOTSTRAP,
        representation=locked_representation,
        evaluated_at=evaluated_at,
    )
    _new_control(
        issuance=issuance,
        role=AuthorityControl.Role.APPROVER,
        principal_id=locked_appointment.account_id,
        basis=AuthorityControl.Basis.REPRESENTATION_ACCEPTANCE,
        appointment=locked_appointment,
        evaluated_at=evaluated_at,
    )
    return issuance
