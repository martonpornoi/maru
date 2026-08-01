"""Audited application commands for root grants and versioned roles."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import (
    POLICY_VERSION,
    ScopeLevel,
    capability,
    require_capability,
)
from maru.authorization.models import (
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
)
from maru.authorization.policy import (
    PolicyDecision,
    ResourceScope,
    decide,
    grant_chain_is_active,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization

GRANT_CAPABILITY = "authorization.grant_direct"
REVOKE_CAPABILITY = "authorization.revoke"
ROLE_CAPABILITY = "authorization.manage_roles"
MAX_AUTHORITY_REASON_LENGTH = 240
MAX_ROLE_NAME_LENGTH = 120
EXECUTIVE_BOARD_ROLE_CODE = "executive-board"
REPRESENTATION_MANAGED_ROLE_CODES = frozenset({EXECUTIVE_BOARD_ROLE_CODE})


class AuthorityCommandValidationError(ValidationError):
    """A safe, classified validation failure at the authority boundary."""

    def __init__(
        self,
        message: str | dict[str, str],
        *,
        reason_code: str,
    ) -> None:
        self.reason_code = reason_code
        super().__init__(message, code=reason_code)


@dataclass(frozen=True, slots=True)
class _CommandAudit:
    capability_code: str
    operation: str
    target_type: str
    target_id: UUID | None
    organization_id: UUID
    edition_id: UUID | None
    correlation_id: UUID
    request_id: UUID | None
    source_channel: str
    obligations: tuple[str, ...]
    changed_fields: tuple[str, ...]
    elevated: bool = False


def _append_command_audit(
    *,
    principal: Account,
    command: _CommandAudit,
    outcome: str,
    reason_code: str,
    approval: bool = False,
    causation_id: UUID | None = None,
) -> AuditEvent:
    operation = f"{command.operation}.approve" if approval else command.operation
    return append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=principal.id,
            principal_context_id=None,
            organization_id=command.organization_id,
            event_edition_id=command.edition_id,
            capability_code=command.capability_code,
            operation=operation,
            target_type=command.target_type,
            target_id=command.target_id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=command.correlation_id,
            request_id=command.request_id,
            source_channel=command.source_channel,
            obligations=command.obligations,
            changed_fields=command.changed_fields,
            causation_id=causation_id,
            elevated=command.elevated,
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )


def _deny(
    *,
    actor: Account,
    command: _CommandAudit,
    message: str,
    reason_code: str,
) -> Never:
    _append_command_audit(
        principal=actor,
        command=command,
        outcome=AuditEvent.Outcome.DENY,
        reason_code=reason_code,
    )
    raise AuthorizationDenied(message, reason_code=reason_code)


def _require_permission(
    *,
    principal: Account,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID | None,
) -> PolicyDecision:
    decision = decide(
        principal=principal,
        capability_code=capability_code,
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    if not decision.allowed:
        raise AuthorizationDenied(
            "Authority management is not permitted.",
            reason_code=decision.reason_code,
        )
    return decision


def _require_dual_control(
    *,
    actor: Account,
    approver: Account,
    recipient: Account | None,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID | None,
) -> PolicyDecision:
    if actor.id == approver.id:
        raise AuthorizationDenied(
            "An independent approver is required.",
            reason_code="distinct_approver_required",
        )
    if recipient is not None and approver.id == recipient.id:
        raise AuthorizationDenied(
            "The recipient cannot approve their own authority.",
            reason_code="recipient_cannot_approve",
        )
    actor_decision = _require_permission(
        principal=actor,
        capability_code=capability_code,
        organization_id=organization_id,
        edition_id=edition_id,
    )
    try:
        _require_permission(
            principal=approver,
            capability_code=capability_code,
            organization_id=organization_id,
            edition_id=edition_id,
        )
    except AuthorizationDenied as error:
        raise AuthorizationDenied(
            "The independent approver lacks authority.",
            reason_code="approver_permission_absent",
        ) from error
    return actor_decision


def _authority_outlives(
    *,
    principal: Account,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID | None,
    requested_expiry: datetime | None,
    at: datetime,
) -> bool:
    if principal.is_active and principal.is_platform_administrator:
        return True

    scope = (
        Q(edition__isnull=True)
        if edition_id is None
        else Q(edition__isnull=True) | Q(edition_id=edition_id)
    )
    active = (
        Q(effective_from__lte=at)
        & (Q(expires_at__isnull=True) | Q(expires_at__gt=at))
        & Q(revoked_at__isnull=True)
    )
    grants = CapabilityGrant.objects.filter(
        active,
        scope,
        principal=principal,
        organization_id=organization_id,
        capability_code=capability_code,
    ).select_related("delegated_from")
    grant_expiries = (
        grant.expires_at for grant in grants if grant_chain_is_active(grant, at)
    )
    assignment_expiries = RoleAssignment.objects.filter(
        active,
        scope,
        principal=principal,
        organization_id=organization_id,
        role_bundle__capability_codes__contains=[capability_code],
    ).values_list("expires_at", flat=True)
    return any(
        expiry is None or (requested_expiry is not None and requested_expiry <= expiry)
        for expiry in (*grant_expiries, *assignment_expiries)
    )


def _require_dual_authority_horizon(
    *,
    actor: Account,
    approver: Account,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID | None,
    requested_expiry: datetime | None,
) -> None:
    at = timezone.now()
    if all(
        _authority_outlives(
            principal=principal,
            capability_code=capability_code,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_expiry=requested_expiry,
            at=at,
        )
        for principal in (actor, approver)
    ):
        return
    raise AuthorityCommandValidationError(
        {
            "expires_at": (
                "The new authority cannot outlive either controlling authority."
            )
        },
        reason_code="authority_expiry_too_early",
    )


def _normalized_reason(reason: str) -> str:
    normalized = reason.strip()
    if not normalized:
        raise AuthorityCommandValidationError(
            {"reason": "A reason is required."},
            reason_code="reason_required",
        )
    if len(normalized) > MAX_AUTHORITY_REASON_LENGTH:
        raise AuthorityCommandValidationError(
            {"reason": "The reason must contain at most 240 characters."},
            reason_code="reason_too_long",
        )
    return normalized


def _raise_validation(
    message: str | dict[str, str],
    *,
    reason_code: str,
) -> Never:
    raise AuthorityCommandValidationError(message, reason_code=reason_code)


def _raise_authorization(message: str, *, reason_code: str) -> Never:
    raise AuthorizationDenied(message, reason_code=reason_code)


def _validate_interval(
    *,
    effective_from: datetime,
    expires_at: datetime | None,
) -> None:
    if expires_at is not None and expires_at <= effective_from:
        raise AuthorityCommandValidationError(
            {"expires_at": "Expiry must follow the effective time."},
            reason_code="invalid_effective_interval",
        )


def _scope_level(edition_id: UUID | None) -> str:
    return ScopeLevel.EDITION if edition_id else ScopeLevel.ORGANIZATION


def _resolve_edition(
    *,
    organization_id: UUID,
    edition_id: UUID | None,
) -> EventEdition | None:
    if edition_id is None:
        return None
    edition = EventEdition.objects.filter(
        pk=edition_id,
        organization_id=organization_id,
    ).first()
    if edition is None:
        raise AuthorityCommandValidationError(
            {"edition": "The requested authority scope is unavailable."},
            reason_code="scope_unavailable",
        )
    return edition


def _lock_organization(organization_id: UUID) -> Organization:
    organization = (
        Organization.objects.select_for_update().filter(pk=organization_id).first()
    )
    if organization is None:
        raise AuthorityCommandValidationError(
            "The requested organization is unavailable.",
            reason_code="scope_unavailable",
        )
    return organization


def _publish_authority_event(
    *,
    event_name: str,
    organization_id: UUID,
    edition_id: UUID | None,
    aggregate_type: str,
    aggregate_id: UUID,
    aggregate_version: int,
    payload: dict[str, object],
    correlation_id: UUID,
    causation_id: UUID,
    actor: Account,
) -> None:
    publish_domain_event(
        DomainEventRecord(
            event_name=event_name,
            schema_version=1,
            organization_id=organization_id,
            event_edition_id=edition_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            actor_kind="account",
            actor_id=actor.id,
            retention_class="security-extended",
        ),
        workload_pool="security",
    )


def _audit_failure(
    *,
    actor: Account,
    command: _CommandAudit,
    error: Exception,
    fallback_reason: str,
) -> None:
    reason_code = (
        error.reason_code
        if isinstance(error, AuthorityCommandValidationError)
        else fallback_reason
    )
    _append_command_audit(
        principal=actor,
        command=command,
        outcome=AuditEvent.Outcome.ERROR,
        reason_code=reason_code,
    )


def grant_capability_direct(
    *,
    actor: Account,
    approver: Account,
    recipient: Account,
    capability_code: str,
    organization_id: UUID,
    edition_id: UUID | None,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CapabilityGrant:
    """Create a root grant only when two independently authorized people agree."""

    obligations = tuple(sorted(require_capability(GRANT_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=GRANT_CAPABILITY,
        operation="authorization.capability.grant_direct",
        target_type="identity.account",
        target_id=recipient.id,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=("capability_grant",),
        elevated=recipient.id == actor.id,
    )
    try:
        decision = _require_dual_control(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code=GRANT_CAPABILITY,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        definition = capability(capability_code)
        if definition is None:
            _raise_validation(
                {"capability_code": "Use a capability declared by the platform."},
                reason_code="unknown_capability",
            )
        normalized_reason = _normalized_reason(reason)
        _validate_interval(
            effective_from=effective_from,
            expires_at=expires_at,
        )
        _require_dual_authority_horizon(
            actor=actor,
            approver=approver,
            capability_code=GRANT_CAPABILITY,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_expiry=expires_at,
        )
        if definition.maximum_scope is ScopeLevel.RESOURCE:
            _raise_validation(
                {
                    "capability_code": (
                        "Relationship-derived authority cannot be granted directly."
                    )
                },
                reason_code="resource_capability_not_grantable",
            )
        if definition.maximum_scope is ScopeLevel.EDITION and edition_id is None:
            _raise_validation(
                {"edition": "This capability requires edition scope."},
                reason_code="edition_scope_required",
            )

        with transaction.atomic():
            organization = _lock_organization(organization_id)
            decision = _require_dual_control(
                actor=actor,
                approver=approver,
                recipient=recipient,
                capability_code=GRANT_CAPABILITY,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            _require_dual_authority_horizon(
                actor=actor,
                approver=approver,
                capability_code=GRANT_CAPABILITY,
                organization_id=organization_id,
                edition_id=edition_id,
                requested_expiry=expires_at,
            )
            edition = _resolve_edition(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            if CapabilityGrant.objects.filter(
                organization=organization,
                edition=edition,
                principal=recipient,
                capability_code=capability_code,
                revoked_at__isnull=True,
            ).exists():
                _raise_validation(
                    "An active matching capability grant already exists.",
                    reason_code="active_grant_exists",
                )
            grant = CapabilityGrant.objects.create(
                organization=organization,
                edition=edition,
                principal=recipient,
                capability_code=capability_code,
                effective_from=effective_from,
                expires_at=expires_at,
                granted_by=actor,
                approved_by=approver,
                delegated_from=None,
                reason=normalized_reason,
            )
            success_command = replace(
                command,
                target_type="authorization.capability_grant",
                target_id=grant.id,
            )
            actor_audit = _append_command_audit(
                principal=actor,
                command=success_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            _append_command_audit(
                principal=approver,
                command=success_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="independent_approval",
                approval=True,
                causation_id=actor_audit.id,
            )
            _publish_authority_event(
                event_name="authorization.capability.direct_granted.v1",
                organization_id=organization_id,
                edition_id=edition_id,
                aggregate_type="authorization.capability_grant",
                aggregate_id=grant.id,
                aggregate_version=1,
                payload={
                    "capability_code": grant.capability_code,
                    "scope_level": _scope_level(edition_id),
                },
                correlation_id=correlation_id,
                causation_id=actor_audit.id,
                actor=actor,
            )
            return grant
    except AuthorizationDenied as error:
        _deny(
            actor=actor,
            command=command,
            message=str(error),
            reason_code=error.reason_code,
        )
    except AuthorityCommandValidationError as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="direct_grant_invalid",
        )
        raise
    except Exception as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="direct_grant_failed",
        )
        raise


def revoke_capability_grant(
    *,
    actor: Account,
    organization_id: UUID,
    grant_id: UUID,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
    revoked_at: datetime | None = None,
) -> CapabilityGrant:
    """Immediately revoke a root or delegated grant; revocation is single-control."""

    obligations = tuple(sorted(require_capability(REVOKE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=REVOKE_CAPABILITY,
        operation="authorization.capability.revoke",
        target_type="authorization.capability_grant",
        target_id=grant_id,
        organization_id=organization_id,
        edition_id=None,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=("revoked_at",),
    )
    try:
        decision = _require_permission(
            principal=actor,
            capability_code=REVOKE_CAPABILITY,
            organization_id=organization_id,
            edition_id=None,
        )
        normalized_reason = _normalized_reason(reason)
        effective_revocation = revoked_at or timezone.now()
        with transaction.atomic():
            _lock_organization(organization_id)
            grant = (
                CapabilityGrant.objects.select_for_update()
                .filter(pk=grant_id, organization_id=organization_id)
                .first()
            )
            if grant is None:
                _raise_authorization(
                    "The authority record is unavailable.",
                    reason_code="authority_unavailable",
                )
            decision = _require_permission(
                principal=actor,
                capability_code=REVOKE_CAPABILITY,
                organization_id=organization_id,
                edition_id=grant.edition_id,
            )
            if grant.revoked_at is not None:
                _raise_validation(
                    "The capability grant is already revoked.",
                    reason_code="grant_already_revoked",
                )
            grant.revoked_at = effective_revocation
            grant.revoked_by = actor
            grant.revocation_reason = normalized_reason
            grant.save(
                update_fields=(
                    "revoked_at",
                    "revoked_by",
                    "revocation_reason",
                    "updated_at",
                )
            )
            scoped_command = replace(command, edition_id=grant.edition_id)
            audit = _append_command_audit(
                principal=actor,
                command=scoped_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            _publish_authority_event(
                event_name="authorization.capability.revoked.v1",
                organization_id=organization_id,
                edition_id=grant.edition_id,
                aggregate_type="authorization.capability_grant",
                aggregate_id=grant.id,
                aggregate_version=2,
                payload={
                    "capability_code": grant.capability_code,
                    "scope_level": _scope_level(grant.edition_id),
                },
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor=actor,
            )
            return grant
    except AuthorizationDenied as error:
        _deny(
            actor=actor,
            command=command,
            message=str(error),
            reason_code=error.reason_code,
        )
    except AuthorityCommandValidationError as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="grant_revocation_invalid",
        )
        raise
    except Exception as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="grant_revocation_failed",
        )
        raise


def create_role_bundle_version(
    *,
    actor: Account,
    approver: Account,
    organization_id: UUID,
    code: str,
    name: str,
    capability_codes: tuple[str, ...],
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RoleBundle:
    """Create the next immutable version of one organizer-owned role bundle."""

    obligations = tuple(sorted(require_capability(ROLE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=ROLE_CAPABILITY,
        operation="authorization.role_bundle.version_create",
        target_type="authorization.role_bundle",
        target_id=None,
        organization_id=organization_id,
        edition_id=None,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=("role_bundle_version",),
    )
    try:
        decision = _require_dual_control(
            actor=actor,
            approver=approver,
            recipient=None,
            capability_code=ROLE_CAPABILITY,
            organization_id=organization_id,
            edition_id=None,
        )
        normalized_reason = _normalized_reason(reason)
        normalized_code = code.strip()
        normalized_name = name.strip()
        normalized_capabilities = tuple(dict.fromkeys(capability_codes))
        if normalized_code.casefold() in REPRESENTATION_MANAGED_ROLE_CODES:
            _raise_validation(
                {
                    "code": (
                        "This role code is managed only by the organization "
                        "representation lifecycle."
                    )
                },
                reason_code="reserved_role_code",
            )
        if not normalized_name:
            _raise_validation(
                {"name": "A role name is required."},
                reason_code="role_name_required",
            )
        if len(normalized_name) > MAX_ROLE_NAME_LENGTH:
            _raise_validation(
                {"name": "The role name must contain at most 120 characters."},
                reason_code="role_name_too_long",
            )
        if len(normalized_capabilities) != len(capability_codes):
            _raise_validation(
                {"capability_codes": "Role capability codes must be unique."},
                reason_code="duplicate_capability",
            )
        for item in normalized_capabilities:
            definition = capability(item)
            if definition is None:
                _raise_validation(
                    {
                        "capability_codes": (
                            "Role bundles may use only platform capabilities."
                        )
                    },
                    reason_code="unknown_capability",
                )
            if definition.maximum_scope is ScopeLevel.RESOURCE:
                _raise_validation(
                    {
                        "capability_codes": (
                            "Relationship-derived authority cannot be assigned "
                            "through a role bundle."
                        )
                    },
                    reason_code="resource_capability_not_assignable",
                )

        with transaction.atomic():
            organization = _lock_organization(organization_id)
            decision = _require_dual_control(
                actor=actor,
                approver=approver,
                recipient=None,
                capability_code=ROLE_CAPABILITY,
                organization_id=organization_id,
                edition_id=None,
            )
            latest = (
                RoleBundle.objects.filter(
                    organization=organization,
                    code=normalized_code,
                )
                .order_by("-version")
                .first()
            )
            role = RoleBundle.objects.create(
                organization=organization,
                code=normalized_code,
                name=normalized_name,
                version=latest.version + 1 if latest else 1,
                capability_codes=list(normalized_capabilities),
                created_by=actor,
                approved_by=approver,
                reason=normalized_reason,
            )
            success_command = replace(command, target_id=role.id)
            actor_audit = _append_command_audit(
                principal=actor,
                command=success_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            _append_command_audit(
                principal=approver,
                command=success_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="independent_approval",
                approval=True,
                causation_id=actor_audit.id,
            )
            _publish_authority_event(
                event_name="authorization.role_bundle.version_created.v1",
                organization_id=organization_id,
                edition_id=None,
                aggregate_type="authorization.role_bundle",
                aggregate_id=role.id,
                aggregate_version=1,
                payload={
                    "role_code": role.code,
                    "role_version": str(role.version),
                },
                correlation_id=correlation_id,
                causation_id=actor_audit.id,
                actor=actor,
            )
            return role
    except AuthorizationDenied as error:
        _deny(
            actor=actor,
            command=command,
            message=str(error),
            reason_code=error.reason_code,
        )
    except (AuthorityCommandValidationError, ValidationError) as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="role_bundle_invalid",
        )
        raise
    except Exception as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="role_bundle_failed",
        )
        raise


def assign_role(
    *,
    actor: Account,
    approver: Account,
    recipient: Account,
    organization_id: UUID,
    role_bundle_id: UUID,
    edition_id: UUID | None,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RoleAssignment:
    """Assign one exact immutable role version under dual control."""

    obligations = tuple(sorted(require_capability(ROLE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=ROLE_CAPABILITY,
        operation="authorization.role.assign",
        target_type="identity.account",
        target_id=recipient.id,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=("role_assignment",),
        elevated=recipient.id == actor.id,
    )
    try:
        decision = _require_dual_control(
            actor=actor,
            approver=approver,
            recipient=recipient,
            capability_code=ROLE_CAPABILITY,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        normalized_reason = _normalized_reason(reason)
        _validate_interval(
            effective_from=effective_from,
            expires_at=expires_at,
        )
        _require_dual_authority_horizon(
            actor=actor,
            approver=approver,
            capability_code=ROLE_CAPABILITY,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_expiry=expires_at,
        )
        with transaction.atomic():
            organization = _lock_organization(organization_id)
            decision = _require_dual_control(
                actor=actor,
                approver=approver,
                recipient=recipient,
                capability_code=ROLE_CAPABILITY,
                organization_id=organization_id,
                edition_id=edition_id,
            )
            _require_dual_authority_horizon(
                actor=actor,
                approver=approver,
                capability_code=ROLE_CAPABILITY,
                organization_id=organization_id,
                edition_id=edition_id,
                requested_expiry=expires_at,
            )
            edition = _resolve_edition(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            role = (
                RoleBundle.objects.filter(
                    pk=role_bundle_id,
                    organization=organization,
                )
                .exclude(code__iexact=EXECUTIVE_BOARD_ROLE_CODE)
                .only("id", "organization_id", "code", "version", "capability_codes")
                .first()
            )
            if role is None:
                _raise_authorization(
                    "The role bundle is unavailable.",
                    reason_code="role_bundle_unavailable",
                )
            definitions = [require_capability(item) for item in role.capability_codes]
            if (
                any(
                    definition.maximum_scope is ScopeLevel.EDITION
                    for definition in definitions
                )
                and edition is None
            ):
                _raise_validation(
                    {"edition": "This role bundle requires edition scope."},
                    reason_code="edition_scope_required",
                )
            if RoleAssignment.objects.filter(
                organization=organization,
                edition=edition,
                principal=recipient,
                role_bundle=role,
                revoked_at__isnull=True,
            ).exists():
                _raise_validation(
                    "An active matching role assignment already exists.",
                    reason_code="active_assignment_exists",
                )
            assignment = RoleAssignment.objects.create(
                organization=organization,
                edition=edition,
                principal=recipient,
                role_bundle=role,
                effective_from=effective_from,
                expires_at=expires_at,
                granted_by=actor,
                approved_by=approver,
                reason=normalized_reason,
            )
            success_command = replace(
                command,
                target_type="authorization.role_assignment",
                target_id=assignment.id,
            )
            actor_audit = _append_command_audit(
                principal=actor,
                command=success_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            _append_command_audit(
                principal=approver,
                command=success_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code="independent_approval",
                approval=True,
                causation_id=actor_audit.id,
            )
            _publish_authority_event(
                event_name="authorization.role.assigned.v1",
                organization_id=organization_id,
                edition_id=edition_id,
                aggregate_type="authorization.role_assignment",
                aggregate_id=assignment.id,
                aggregate_version=1,
                payload={
                    "role_code": role.code,
                    "role_version": str(role.version),
                    "scope_level": _scope_level(edition_id),
                },
                correlation_id=correlation_id,
                causation_id=actor_audit.id,
                actor=actor,
            )
            return assignment
    except AuthorizationDenied as error:
        _deny(
            actor=actor,
            command=command,
            message=str(error),
            reason_code=error.reason_code,
        )
    except (AuthorityCommandValidationError, ValidationError) as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="role_assignment_invalid",
        )
        raise
    except Exception as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="role_assignment_failed",
        )
        raise


def revoke_role_assignment(
    *,
    actor: Account,
    organization_id: UUID,
    assignment_id: UUID,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
    revoked_at: datetime | None = None,
) -> RoleAssignment:
    """Immediately revoke a role assignment; revocation is single-control."""

    obligations = tuple(sorted(require_capability(REVOKE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=REVOKE_CAPABILITY,
        operation="authorization.role.revoke",
        target_type="authorization.role_assignment",
        target_id=assignment_id,
        organization_id=organization_id,
        edition_id=None,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=("revoked_at",),
    )
    try:
        decision = _require_permission(
            principal=actor,
            capability_code=REVOKE_CAPABILITY,
            organization_id=organization_id,
            edition_id=None,
        )
        normalized_reason = _normalized_reason(reason)
        effective_revocation = revoked_at or timezone.now()
        with transaction.atomic():
            _lock_organization(organization_id)
            assignment = (
                RoleAssignment.objects.select_for_update()
                .select_related("role_bundle")
                .filter(pk=assignment_id, organization_id=organization_id)
                .exclude(role_bundle__code__iexact=EXECUTIVE_BOARD_ROLE_CODE)
                .first()
            )
            if assignment is None:
                _raise_authorization(
                    "The authority record is unavailable.",
                    reason_code="authority_unavailable",
                )
            decision = _require_permission(
                principal=actor,
                capability_code=REVOKE_CAPABILITY,
                organization_id=organization_id,
                edition_id=assignment.edition_id,
            )
            if assignment.revoked_at is not None:
                _raise_validation(
                    "The role assignment is already revoked.",
                    reason_code="assignment_already_revoked",
                )
            assignment.revoked_at = effective_revocation
            assignment.revoked_by = actor
            assignment.revocation_reason = normalized_reason
            assignment.save(
                update_fields=(
                    "revoked_at",
                    "revoked_by",
                    "revocation_reason",
                    "updated_at",
                )
            )
            scoped_command = replace(command, edition_id=assignment.edition_id)
            audit = _append_command_audit(
                principal=actor,
                command=scoped_command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            role = assignment.role_bundle
            _publish_authority_event(
                event_name="authorization.role.revoked.v1",
                organization_id=organization_id,
                edition_id=assignment.edition_id,
                aggregate_type="authorization.role_assignment",
                aggregate_id=assignment.id,
                aggregate_version=2,
                payload={
                    "role_code": role.code,
                    "role_version": str(role.version),
                    "scope_level": _scope_level(assignment.edition_id),
                },
                correlation_id=correlation_id,
                causation_id=audit.id,
                actor=actor,
            )
            return assignment
    except AuthorizationDenied as error:
        _deny(
            actor=actor,
            command=command,
            message=str(error),
            reason_code=error.reason_code,
        )
    except AuthorityCommandValidationError as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="assignment_revocation_invalid",
        )
        raise
    except Exception as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="assignment_revocation_failed",
        )
        raise
