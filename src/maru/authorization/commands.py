"""Audited application commands for root grants and versioned roles."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.bindings import resource_binding_target_exists
from maru.authorization.catalog import (
    POLICY_VERSION,
    ScopeLevel,
    capability,
    require_capability,
)
from maru.authorization.issuance import create_persistent_dual_control_issuance
from maru.authorization.models import (
    AuthorityControl,
    AuthorityIssuance,
    CapabilityGrant,
    RoleAssignment,
    RoleBundle,
    ScopedResourceBinding,
)
from maru.authorization.policy import (
    PolicyDecision,
    ResolvedAuthorizationTarget,
    decide,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.authorization.provenance import (
    AuthorizedControl,
    ControlHorizonMode,
    role_bundle_provenance_is_historical,
    select_authorized_control_source,
)
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.authorization.services import AuthorizationDenied
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.adoption import profile_allows_capabilities
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.organizations.representation_catalog import REPRESENTATION_ROLE_CODES
from maru.workforce.models import Department

GRANT_CAPABILITY = "authorization.grant_direct"
REVOKE_CAPABILITY = "authorization.revoke"
ROLE_CAPABILITY = "authorization.manage_roles"
MAX_AUTHORITY_REASON_LENGTH = 240
MAX_ROLE_NAME_LENGTH = 120
EXECUTIVE_BOARD_ROLE_CODE = "executive-board"
REPRESENTATION_MANAGED_ROLE_CODES = REPRESENTATION_ROLE_CODES
DUAL_CONTROL_COUNT = 2


class AuthorityCommandValidationError(ValidationError):
    """A safe, classified validation failure at the authority boundary."""

    def __init__(
        self,
        message: str | dict[str, str],
        *,
        reason_code: str,
    ) -> None:
        """Initialize the AuthorityCommandValidationError instance.

        Parameters
        ----------
        message : str | dict[str, str]
            The message mapping to validate or transform.
        reason_code : str
            The stable reason code from the relevant closed catalog.
        """
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
    target: ResolvedAuthorizationTarget,
) -> PolicyDecision:
    decision = decide(
        principal=principal,
        capability_code=capability_code,
        resource=target,
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
    target: ResolvedAuthorizationTarget,
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
        target=target,
    )
    try:
        _require_permission(
            principal=approver,
            capability_code=capability_code,
            target=target,
        )
    except AuthorizationDenied as error:
        raise AuthorizationDenied(
            "The independent approver lacks authority.",
            reason_code="approver_permission_absent",
        ) from error
    return actor_decision


@dataclass(frozen=True, slots=True)
class _SelectedDualControlSources:
    actor_issuance: AuthorityIssuance
    approver_issuance: AuthorityIssuance
    evaluated_at: datetime


def _lock_controllers_in_stable_order(
    *,
    actor: Account,
    approver: Account,
) -> tuple[Account, Account]:
    """Lock both controllers before either source graph is traversed.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    approver : Account
        The independent authority source approving the transition.

    Returns
    -------
    tuple[Account, Account]
        The matching lock controllers in stable order records in deterministic
        order.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    controller_ids = {actor.id, approver.id}
    locked = {
        account.id: account
        for account in Account.objects.select_for_update()
        .filter(id__in=controller_ids)
        .order_by("id")
    }
    if len(locked) != DUAL_CONTROL_COUNT:
        raise AuthorizationDenied(
            "Exact controller authority is unavailable.",
            reason_code="authority_source_unavailable",
        )
    return locked[actor.id], locked[approver.id]


def _select_one_control_source(
    *,
    principal: Account,
    role: str,
    capability_code: str,
    target: ResolvedAuthorizationTarget,
    requested_effective_from: datetime,
    requested_expires_at: datetime | None,
    evaluated_at: datetime,
    horizon_mode: ControlHorizonMode,
) -> AuthorizedControl:
    selected = select_authorized_control_source(
        principal=principal,
        role=role,
        capability_code=capability_code,
        target=target,
        requested_effective_from=requested_effective_from,
        requested_expires_at=requested_expires_at,
        evaluated_at=evaluated_at,
        horizon_mode=horizon_mode,
    )
    if selected is not None:
        return selected

    # Preserve the safe horizon classification without treating an unproven
    # legacy row as authority. A current proven source that cannot cover the
    # requested interval is distinct from having no exact source at all.
    if horizon_mode is ControlHorizonMode.PERSISTENT:
        current_source = select_authorized_control_source(
            principal=principal,
            role=role,
            capability_code=capability_code,
            target=target,
            requested_effective_from=evaluated_at,
            requested_expires_at=None,
            evaluated_at=evaluated_at,
            horizon_mode=ControlHorizonMode.POINT_IN_TIME,
        )
        if current_source is not None:
            start_covering_source = select_authorized_control_source(
                principal=principal,
                role=role,
                capability_code=capability_code,
                target=target,
                requested_effective_from=requested_effective_from,
                requested_expires_at=None,
                evaluated_at=evaluated_at,
                horizon_mode=ControlHorizonMode.POINT_IN_TIME,
            )
            if start_covering_source is None:
                raise AuthorityCommandValidationError(
                    {
                        "effective_from": (
                            "The new authority cannot begin before either "
                            "controlling authority."
                        )
                    },
                    reason_code="authority_effective_from_too_early",
                )
            raise AuthorityCommandValidationError(
                {
                    "expires_at": (
                        "The new authority cannot outlive either controlling authority."
                    )
                },
                reason_code="authority_expiry_too_early",
            )
    raise AuthorizationDenied(
        "Exact controller authority is unavailable.",
        reason_code="authority_source_unavailable",
    )


def require_authorized_control_horizon(  # noqa: DOC502 - selector owns failures
    *,
    principal: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget,
    requested_effective_from: datetime,
    requested_expires_at: datetime | None,
) -> None:
    """Require one exact current source to cover a persistent write interval.

    This read-only assertion must run inside the caller's target-writing
    transaction. It locks eligible authority sources for the transaction but
    returns no source identifier or provenance to the caller.

    Parameters
    ----------
    principal : Account
        Authenticated controller whose exact authority is evaluated.
    capability_code : str
        Stable capability required by the proposed persistent write.
    target : ResolvedAuthorizationTarget
        Exact current resource targeted by the proposed write.
    requested_effective_from : datetime
        Timezone-aware inclusive start of the proposed authority interval.
    requested_expires_at : datetime | None
        Optional timezone-aware end of the proposed authority interval.

    Raises
    ------
    AuthorityCommandValidationError
        If a current exact source cannot cover the requested interval.
    AuthorizationDenied
        If no current exact source authorizes the principal at the target.
    RuntimeError
        If the caller has not opened a transaction for source locking.
    """
    _select_one_control_source(
        principal=principal,
        role=AuthorityControl.Role.ACTOR,
        capability_code=capability_code,
        target=target,
        requested_effective_from=requested_effective_from,
        requested_expires_at=requested_expires_at,
        evaluated_at=timezone.now(),
        horizon_mode=ControlHorizonMode.PERSISTENT,
    )


def _select_dual_control_sources(
    *,
    actor: Account,
    approver: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget,
    requested_effective_from: datetime,
    requested_expires_at: datetime | None,
    horizon_mode: ControlHorizonMode,
) -> _SelectedDualControlSources:
    """Select and pin exact sources inside the target-writing transaction.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    approver : Account
        The independent authority source approving the transition.
    capability_code : str
        The stable capability code required by the operation.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    requested_effective_from : datetime
        The timezone-aware boundary for requested effective from.
    requested_expires_at : datetime | None
        The timezone-aware timestamp for requested expires.
    horizon_mode : ControlHorizonMode
        The closed horizon mode discriminator defined by the domain catalog.

    Returns
    -------
    _SelectedDualControlSources
        The resolved _SelectedDualControlSources for select dual control sources.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    locked_actor, locked_approver = _lock_controllers_in_stable_order(
        actor=actor,
        approver=approver,
    )
    evaluated_at = timezone.now()
    actor_source = _select_one_control_source(
        principal=locked_actor,
        role=AuthorityControl.Role.ACTOR,
        capability_code=capability_code,
        target=target,
        requested_effective_from=requested_effective_from,
        requested_expires_at=requested_expires_at,
        evaluated_at=evaluated_at,
        horizon_mode=horizon_mode,
    )
    approver_source = _select_one_control_source(
        principal=locked_approver,
        role=AuthorityControl.Role.APPROVER,
        capability_code=capability_code,
        target=target,
        requested_effective_from=requested_effective_from,
        requested_expires_at=requested_expires_at,
        evaluated_at=evaluated_at,
        horizon_mode=horizon_mode,
    )
    source_ordinals = {
        actor_source.source_issuance_ordinal,
        approver_source.source_issuance_ordinal,
    }
    locked_issuances = {
        issuance.ordinal: issuance
        for issuance in AuthorityIssuance.objects.select_for_update()
        .filter(ordinal__in=source_ordinals)
        .order_by("ordinal")
    }
    if set(locked_issuances) != source_ordinals:
        raise AuthorizationDenied(
            "Exact controller authority is unavailable.",
            reason_code="authority_source_unavailable",
        )
    return _SelectedDualControlSources(
        actor_issuance=locked_issuances[actor_source.source_issuance_ordinal],
        approver_issuance=locked_issuances[approver_source.source_issuance_ordinal],
        evaluated_at=evaluated_at,
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


def _scope_level(target: ResolvedAuthorizationTarget) -> str:
    return target.scope_level


_SCOPE_DEPTH = {
    ScopeLevel.ORGANIZATION: 0,
    ScopeLevel.EDITION: 1,
    ScopeLevel.DEPARTMENT: 2,
    ScopeLevel.RESOURCE: 3,
}


def _target_supports_capability(
    target: ResolvedAuthorizationTarget,
    maximum_scope: ScopeLevel,
) -> bool:
    return _SCOPE_DEPTH[target.scope_level] >= _SCOPE_DEPTH[maximum_scope]


@dataclass(frozen=True, slots=True)
class _LockedTarget:
    target: ResolvedAuthorizationTarget
    organization: Organization
    edition: EventEdition | None
    department: Department | None
    resource_binding: ScopedResourceBinding | None


def _lock_target(  # noqa: PLR0912
    target: ResolvedAuthorizationTarget,
) -> _LockedTarget:
    organization = (
        Organization.objects.select_for_update()
        .filter(pk=target.organization_id)
        .first()
    )
    if organization is None:
        _raise_validation(
            "The requested authority scope is unavailable.",
            reason_code="scope_unavailable",
        )
    edition_id = target.edition_id
    department_id = target.department_id
    resource_binding_id = target.resource_binding_id
    edition = None
    if edition_id is not None:
        edition = (
            EventEdition.objects.select_for_update()
            .filter(
                pk=edition_id,
                organization_id=target.organization_id,
            )
            .first()
        )
        if edition is None:
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
    department = None
    if department_id is not None:
        if edition_id is None:
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
        department = (
            Department.objects.select_for_update()
            .filter(
                pk=department_id,
                organization_id=target.organization_id,
                edition_id=edition_id,
                retired_at__isnull=True,
            )
            .first()
        )
        if department is None:
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
    resource_binding = None
    if resource_binding_id is not None:
        if edition_id is None or department_id is None:
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
        resource_binding = (
            ScopedResourceBinding.objects.select_for_update()
            .filter(
                pk=resource_binding_id,
                organization_id=target.organization_id,
                edition_id=edition_id,
                department_id=department_id,
            )
            .first()
        )
        if resource_binding is None:
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
        if not resource_binding_target_exists(resource_binding, for_update=True):
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
    if resource_binding_id is not None:
        if edition_id is None or department_id is None:
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
        refreshed = resolve_resource_target(
            organization_id=target.organization_id,
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=resource_binding_id,
        )
    elif department_id is not None:
        if edition_id is None:
            _raise_validation(
                "The requested authority scope is unavailable.",
                reason_code="scope_unavailable",
            )
        refreshed = resolve_department_target(
            organization_id=target.organization_id,
            edition_id=edition_id,
            department_id=department_id,
        )
    elif edition_id is not None:
        refreshed = resolve_edition_target(
            organization_id=target.organization_id,
            edition_id=edition_id,
        )
    else:
        refreshed = resolve_organization_target(organization_id=target.organization_id)
    if refreshed is None:
        _raise_validation(
            "The requested authority scope is unavailable.",
            reason_code="scope_unavailable",
        )
    return _LockedTarget(
        target=refreshed,
        organization=organization,
        edition=edition,
        department=department,
        resource_binding=resource_binding,
    )


def _require_current_history_container(
    target: ResolvedAuthorizationTarget,
) -> None:
    """Limit retired-scope closure to a current organizer or edition boundary.

    Parameters
    ----------
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    """
    if target.department_id is not None or target.resource_binding_id is not None:
        _raise_authorization(
            "The authority record is unavailable.",
            reason_code="authority_unavailable",
        )


def _lock_retired_department_history_scope(
    *,
    container: _LockedTarget,
    organization_id: UUID,
    edition_id: UUID | None,
    department_id: UUID | None,
    resource_binding_id: UUID | None,
) -> ScopeLevel:
    """Prove one stored retired scope is inside the locked current container.

    Parameters
    ----------
    container : _LockedTarget
        The container applied within the audited domain transition.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID | None
        The event edition identifier that scopes the operation.
    department_id : UUID | None
        The department identifier within the requested scope.
    resource_binding_id : UUID | None
        The resource binding identifier within the requested scope.

    Returns
    -------
    ScopeLevel
        The resolved ScopeLevel for lock retired department history scope.
    """
    container_target = container.target
    if (
        container_target.department_id is not None
        or container_target.resource_binding_id is not None
        or organization_id != container_target.organization_id
        or edition_id is None
        or department_id is None
        or (
            container_target.edition_id is not None
            and edition_id != container_target.edition_id
        )
    ):
        _raise_authorization(
            "The authority record is unavailable.",
            reason_code="authority_unavailable",
        )

    department_exists = (
        Department.objects.select_for_update()
        .filter(
            pk=department_id,
            organization_id=organization_id,
            edition_id=edition_id,
            retired_at__isnull=False,
        )
        .exists()
    )
    if not department_exists:
        _raise_authorization(
            "The authority record is unavailable.",
            reason_code="authority_unavailable",
        )

    if resource_binding_id is None:
        return ScopeLevel.DEPARTMENT

    binding_exists = (
        ScopedResourceBinding.objects.select_for_update()
        .filter(
            pk=resource_binding_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
        )
        .exists()
    )
    if not binding_exists:
        _raise_authorization(
            "The authority record is unavailable.",
            reason_code="authority_unavailable",
        )
    return ScopeLevel.RESOURCE


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


def grant_capability_direct(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    approver: Account,
    recipient: Account,
    capability_code: str,
    target: ResolvedAuthorizationTarget,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CapabilityGrant:
    """Create a root grant only when two independently authorized people agree.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    approver : Account
        The independent authority source approving the transition.
    recipient : Account
        The recipient applied within the audited domain transition.
    capability_code : str
        The stable capability code required by the operation.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    effective_from : datetime
        The timezone-aware boundary for effective from.
    expires_at : datetime | None
        The timezone-aware timestamp for expires.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    CapabilityGrant
        The resolved CapabilityGrant for grant capability direct.

    Raises
    ------
    AuthorityCommandValidationError
        If the requested state violates a domain invariant.
    """
    obligations = tuple(sorted(require_capability(GRANT_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=GRANT_CAPABILITY,
        operation="authorization.capability.grant_direct",
        target_type="identity.account",
        target_id=recipient.id,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
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
            target=target,
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
        if not definition.persistable:
            _raise_validation(
                {
                    "capability_code": (
                        "Relationship-derived authority cannot be granted directly."
                    )
                },
                reason_code="resource_capability_not_grantable",
            )
        if not _target_supports_capability(target, definition.maximum_scope):
            _raise_validation(
                {
                    "scope": (
                        "This capability requires "
                        f"{definition.maximum_scope.value} scope."
                    )
                },
                reason_code=f"{definition.maximum_scope.value}_scope_required",
            )

        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            locked = _lock_target(target)
            locked_target = locked.target
            if locked_target.edition_id is not None and (
                locked_target.adoption_profile_code is None
                or locked_target.adoption_profile_version is None
                or not profile_allows_capabilities(
                    locked_target.adoption_profile_code,
                    locked_target.adoption_profile_version,
                    (capability_code,),
                )
            ):
                _raise_validation(
                    {
                        "capability_code": (
                            "This edition has not adopted the requested capability."
                        )
                    },
                    reason_code="module_not_adopted",
                )
            decision = _require_dual_control(
                actor=actor,
                approver=approver,
                recipient=recipient,
                capability_code=GRANT_CAPABILITY,
                target=locked_target,
            )
            sources = _select_dual_control_sources(
                actor=actor,
                approver=approver,
                capability_code=GRANT_CAPABILITY,
                target=locked_target,
                requested_effective_from=effective_from,
                requested_expires_at=expires_at,
                horizon_mode=ControlHorizonMode.PERSISTENT,
            )
            if CapabilityGrant.objects.filter(
                organization=locked.organization,
                edition=locked.edition,
                department=locked.department,
                resource_binding=locked.resource_binding,
                principal=recipient,
                capability_code=capability_code,
                revoked_at__isnull=True,
            ).exists():
                _raise_validation(
                    "An active matching capability grant already exists.",
                    reason_code="active_grant_exists",
                )
            grant = CapabilityGrant.objects.create(
                organization=locked.organization,
                edition=locked.edition,
                department=locked.department,
                resource_binding=locked.resource_binding,
                principal=recipient,
                capability_code=capability_code,
                effective_from=effective_from,
                expires_at=expires_at,
                granted_by=actor,
                approved_by=approver,
                delegated_from=None,
                reason=normalized_reason,
            )
            create_persistent_dual_control_issuance(
                target=grant,
                actor_source=sources.actor_issuance,
                approver_source=sources.approver_issuance,
                evaluated_at=sources.evaluated_at,
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
                organization_id=locked_target.organization_id,
                edition_id=locked_target.edition_id,
                aggregate_type="authorization.capability_grant",
                aggregate_id=grant.id,
                aggregate_version=1,
                payload={
                    "capability_code": grant.capability_code,
                    "scope_level": _scope_level(locked_target),
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


def revoke_capability_grant(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    target: ResolvedAuthorizationTarget,
    grant_id: UUID,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
    revoked_at: datetime | None = None,
) -> CapabilityGrant:
    """Immediately revoke a root or delegated grant; revocation is single-control.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    grant_id : UUID
        The grant identifier within the requested scope.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.
    revoked_at : datetime | None, default=None
        The timezone-aware timestamp for revoked.

    Returns
    -------
    CapabilityGrant
        The updated CapabilityGrant after the transition is committed.

    Raises
    ------
    AuthorityCommandValidationError
        If the requested state violates a domain invariant.
    """
    obligations = tuple(sorted(require_capability(REVOKE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=REVOKE_CAPABILITY,
        operation="authorization.capability.revoke",
        target_type="authorization.capability_grant",
        target_id=grant_id,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
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
            target=target,
        )
        normalized_reason = _normalized_reason(reason)
        effective_revocation = revoked_at or timezone.now()
        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            locked = _lock_target(target)
            locked_target = locked.target
            grant = (
                CapabilityGrant.objects.select_for_update()
                .filter(
                    pk=grant_id,
                    organization_id=locked_target.organization_id,
                    edition_id=locked_target.edition_id,
                    department=locked.department,
                    resource_binding_id=locked_target.resource_binding_id,
                )
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
                target=locked_target,
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
            audit = _append_command_audit(
                principal=actor,
                command=command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            _publish_authority_event(
                event_name="authorization.capability.revoked.v1",
                organization_id=locked_target.organization_id,
                edition_id=locked_target.edition_id,
                aggregate_type="authorization.capability_grant",
                aggregate_id=grant.id,
                aggregate_version=2,
                payload={
                    "capability_code": grant.capability_code,
                    "scope_level": _scope_level(locked_target),
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


def create_role_bundle_version(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    approver: Account,
    target: ResolvedAuthorizationTarget,
    code: str,
    name: str,
    capability_codes: tuple[str, ...],
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RoleBundle:
    """Create the next immutable version of one organizer-owned role bundle.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    approver : Account
        The independent authority source approving the transition.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    code : str
        The stable domain code to resolve or validate.
    name : str
        The human-readable name to normalize or persist.
    capability_codes : tuple[str, ...]
        The capability codes applied within the audited domain transition.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RoleBundle
        The newly created RoleBundle.

    Raises
    ------
    AuthorityCommandValidationError
        If the requested state violates a domain invariant.
    ValidationError
        If the requested state violates a domain invariant.
    """
    obligations = tuple(sorted(require_capability(ROLE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=ROLE_CAPABILITY,
        operation="authorization.role_bundle.version_create",
        target_type="authorization.role_bundle",
        target_id=None,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
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
            target=target,
        )
        if target.scope_level is not ScopeLevel.ORGANIZATION:
            _raise_validation(
                "Role bundle versions belong to an exact organization.",
                reason_code="organization_scope_required",
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
            if not definition.persistable:
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
            lock_retired_department_authority_boundaries()
            locked = _lock_target(target)
            organization = locked.organization
            decision = _require_dual_control(
                actor=actor,
                approver=approver,
                recipient=None,
                capability_code=ROLE_CAPABILITY,
                target=locked.target,
            )
            sources = _select_dual_control_sources(
                actor=actor,
                approver=approver,
                capability_code=ROLE_CAPABILITY,
                target=locked.target,
                requested_effective_from=timezone.now(),
                requested_expires_at=None,
                horizon_mode=ControlHorizonMode.POINT_IN_TIME,
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
            create_persistent_dual_control_issuance(
                target=role,
                actor_source=sources.actor_issuance,
                approver_source=sources.approver_issuance,
                evaluated_at=sources.evaluated_at,
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
                organization_id=locked.target.organization_id,
                edition_id=locked.target.edition_id,
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


def assign_role(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    approver: Account,
    recipient: Account,
    target: ResolvedAuthorizationTarget,
    role_bundle_id: UUID,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RoleAssignment:
    """Assign one exact immutable role version under dual control.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    approver : Account
        The independent authority source approving the transition.
    recipient : Account
        The recipient applied within the audited domain transition.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    role_bundle_id : UUID
        The role bundle identifier within the requested scope.
    effective_from : datetime
        The timezone-aware boundary for effective from.
    expires_at : datetime | None
        The timezone-aware timestamp for expires.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RoleAssignment
        The resolved RoleAssignment for assign role.

    Raises
    ------
    AuthorityCommandValidationError
        If the requested state violates a domain invariant.
    ValidationError
        If the requested state violates a domain invariant.
    """
    obligations = tuple(sorted(require_capability(ROLE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=ROLE_CAPABILITY,
        operation="authorization.role.assign",
        target_type="identity.account",
        target_id=recipient.id,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
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
            target=target,
        )
        normalized_reason = _normalized_reason(reason)
        _validate_interval(
            effective_from=effective_from,
            expires_at=expires_at,
        )
        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            locked = _lock_target(target)
            locked_target = locked.target
            organization = locked.organization
            decision = _require_dual_control(
                actor=actor,
                approver=approver,
                recipient=recipient,
                capability_code=ROLE_CAPABILITY,
                target=locked_target,
            )
            sources = _select_dual_control_sources(
                actor=actor,
                approver=approver,
                capability_code=ROLE_CAPABILITY,
                target=locked_target,
                requested_effective_from=effective_from,
                requested_expires_at=expires_at,
                horizon_mode=ControlHorizonMode.PERSISTENT,
            )
            role = (
                RoleBundle.objects.filter(
                    pk=role_bundle_id,
                    organization=organization,
                )
                .exclude(code__in=REPRESENTATION_MANAGED_ROLE_CODES)
                .only("id", "organization_id", "code", "version", "capability_codes")
                .first()
            )
            if role is None:
                _raise_authorization(
                    "The role bundle is unavailable.",
                    reason_code="role_bundle_unavailable",
                )
            if locked_target.edition_id is not None and (
                locked_target.adoption_profile_code is None
                or locked_target.adoption_profile_version is None
                or not profile_allows_capabilities(
                    locked_target.adoption_profile_code,
                    locked_target.adoption_profile_version,
                    role.capability_codes,
                )
            ):
                _raise_validation(
                    {
                        "role_bundle": (
                            "This access group includes a module this edition has "
                            "not adopted."
                        )
                    },
                    reason_code="module_not_adopted",
                )
            if not role_bundle_provenance_is_historical(
                bundle=role,
                evaluated_at=sources.evaluated_at,
                lock=True,
            ):
                _raise_authorization(
                    "The role bundle is unavailable.",
                    reason_code="role_bundle_unavailable",
                )
            definitions = [require_capability(item) for item in role.capability_codes]
            unavailable_scope = next(
                (
                    definition.maximum_scope
                    for definition in definitions
                    if not _target_supports_capability(
                        locked_target,
                        definition.maximum_scope,
                    )
                ),
                None,
            )
            if unavailable_scope is not None:
                _raise_validation(
                    {
                        "scope": (
                            "This role bundle requires "
                            f"{unavailable_scope.value} scope."
                        )
                    },
                    reason_code=f"{unavailable_scope.value}_scope_required",
                )
            if RoleAssignment.objects.filter(
                organization=organization,
                edition=locked.edition,
                department=locked.department,
                resource_binding=locked.resource_binding,
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
                edition=locked.edition,
                department=locked.department,
                resource_binding=locked.resource_binding,
                principal=recipient,
                role_bundle=role,
                effective_from=effective_from,
                expires_at=expires_at,
                granted_by=actor,
                approved_by=approver,
                reason=normalized_reason,
            )
            create_persistent_dual_control_issuance(
                target=assignment,
                actor_source=sources.actor_issuance,
                approver_source=sources.approver_issuance,
                evaluated_at=sources.evaluated_at,
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
                organization_id=locked_target.organization_id,
                edition_id=locked_target.edition_id,
                aggregate_type="authorization.role_assignment",
                aggregate_id=assignment.id,
                aggregate_version=1,
                payload={
                    "role_code": role.code,
                    "role_version": str(role.version),
                    "scope_level": _scope_level(locked_target),
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


def revoke_role_assignment(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    target: ResolvedAuthorizationTarget,
    assignment_id: UUID,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
    revoked_at: datetime | None = None,
) -> RoleAssignment:
    """Immediately revoke a role assignment; revocation is single-control.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    assignment_id : UUID
        The assignment identifier within the requested scope.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.
    revoked_at : datetime | None, default=None
        The timezone-aware timestamp for revoked.

    Returns
    -------
    RoleAssignment
        The updated RoleAssignment after the transition is committed.

    Raises
    ------
    AuthorityCommandValidationError
        If the requested state violates a domain invariant.
    """
    obligations = tuple(sorted(require_capability(REVOKE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=REVOKE_CAPABILITY,
        operation="authorization.role.revoke",
        target_type="authorization.role_assignment",
        target_id=assignment_id,
        organization_id=target.organization_id,
        edition_id=target.edition_id,
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
            target=target,
        )
        normalized_reason = _normalized_reason(reason)
        effective_revocation = revoked_at or timezone.now()
        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            locked = _lock_target(target)
            locked_target = locked.target
            assignment = (
                RoleAssignment.objects.select_for_update()
                .select_related("role_bundle")
                .filter(
                    pk=assignment_id,
                    organization_id=locked_target.organization_id,
                    edition_id=locked_target.edition_id,
                    department=locked.department,
                    resource_binding_id=locked_target.resource_binding_id,
                )
                .exclude(role_bundle__code__in=REPRESENTATION_MANAGED_ROLE_CODES)
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
                target=locked_target,
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
            audit = _append_command_audit(
                principal=actor,
                command=command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            role = assignment.role_bundle
            _publish_authority_event(
                event_name="authorization.role.revoked.v1",
                organization_id=locked_target.organization_id,
                edition_id=locked_target.edition_id,
                aggregate_type="authorization.role_assignment",
                aggregate_id=assignment.id,
                aggregate_version=2,
                payload={
                    "role_code": role.code,
                    "role_version": str(role.version),
                    "scope_level": _scope_level(locked_target),
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


def revoke_expired_retired_department_capability_grant(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    containing_target: ResolvedAuthorizationTarget,
    grant_id: UUID,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CapabilityGrant:
    """Close expired grant history below a retired Department.

    Retired Departments cannot be resolved as live authorization targets. This
    deliberately narrow path authorizes at a current organization or edition
    container, then derives and verifies the exact historical scope from the
    persisted grant. It can only add revocation evidence to an already expired
    row; it cannot issue, extend, move, or reopen authority.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    containing_target : ResolvedAuthorizationTarget
        The containing target applied within the audited domain transition.
    grant_id : UUID
        The grant identifier within the requested scope.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    CapabilityGrant
        The updated CapabilityGrant after the transition is committed.

    Raises
    ------
    AuthorityCommandValidationError
        If the requested state violates a domain invariant.
    """
    obligations = tuple(sorted(require_capability(REVOKE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=REVOKE_CAPABILITY,
        operation="authorization.capability.revoke",
        target_type="authorization.capability_grant",
        target_id=grant_id,
        organization_id=containing_target.organization_id,
        edition_id=containing_target.edition_id,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=("revoked_at",),
    )
    try:
        _require_current_history_container(containing_target)
        decision = _require_permission(
            principal=actor,
            capability_code=REVOKE_CAPABILITY,
            target=containing_target,
        )
        normalized_reason = _normalized_reason(reason)
        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            locked_container = _lock_target(containing_target)
            decision = _require_permission(
                principal=actor,
                capability_code=REVOKE_CAPABILITY,
                target=locked_container.target,
            )
            grant_query = CapabilityGrant.objects.select_for_update().filter(
                pk=grant_id,
                organization_id=locked_container.target.organization_id,
            )
            if locked_container.target.edition_id is not None:
                grant_query = grant_query.filter(
                    edition_id=locked_container.target.edition_id
                )
            grant = grant_query.first()
            if grant is None:
                _raise_authorization(
                    "The authority record is unavailable.",
                    reason_code="authority_unavailable",
                )
            scope_level = _lock_retired_department_history_scope(
                container=locked_container,
                organization_id=grant.organization_id,
                edition_id=grant.edition_id,
                department_id=grant.department_id,
                resource_binding_id=grant.resource_binding_id,
            )
            command = replace(
                command,
                organization_id=grant.organization_id,
                edition_id=grant.edition_id,
            )
            if grant.revoked_at is not None:
                _raise_validation(
                    "The capability grant is already revoked.",
                    reason_code="grant_already_revoked",
                )
            evaluated_at = timezone.now()
            if grant.expires_at is None or grant.expires_at > evaluated_at:
                _raise_validation(
                    "Only expired authority history can be closed through this path.",
                    reason_code="historical_authority_not_expired",
                )
            grant.revoked_at = evaluated_at
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
            audit = _append_command_audit(
                principal=actor,
                command=command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            _publish_authority_event(
                event_name="authorization.capability.revoked.v1",
                organization_id=grant.organization_id,
                edition_id=grant.edition_id,
                aggregate_type="authorization.capability_grant",
                aggregate_id=grant.id,
                aggregate_version=2,
                payload={
                    "capability_code": grant.capability_code,
                    "scope_level": scope_level,
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
            fallback_reason="retired_grant_closure_invalid",
        )
        raise
    except Exception as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="retired_grant_closure_failed",
        )
        raise


def revoke_expired_retired_department_role_assignment(  # noqa: DOC503 - bare re-raise preserves original error
    *,
    actor: Account,
    containing_target: ResolvedAuthorizationTarget,
    assignment_id: UUID,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> RoleAssignment:
    """Close expired role history below a retired Department.

    Parameters
    ----------
    actor : Account
        The authenticated account authorizing the operation.
    containing_target : ResolvedAuthorizationTarget
        The containing target applied within the audited domain transition.
    assignment_id : UUID
        The assignment identifier within the requested scope.
    reason : str
        The operator-supplied rationale recorded with the change.
    correlation_id : UUID
        The request correlation identifier used for audit tracing.
    request_id : UUID | None, default=None
        The correlation identifier attached to the incoming request.
    source_channel : str, default='service'
        The closed channel code identifying where the request originated.

    Returns
    -------
    RoleAssignment
        The updated RoleAssignment after the transition is committed.

    Raises
    ------
    AuthorityCommandValidationError
        If the requested state violates a domain invariant.
    """
    obligations = tuple(sorted(require_capability(REVOKE_CAPABILITY).obligations))
    command = _CommandAudit(
        capability_code=REVOKE_CAPABILITY,
        operation="authorization.role.revoke",
        target_type="authorization.role_assignment",
        target_id=assignment_id,
        organization_id=containing_target.organization_id,
        edition_id=containing_target.edition_id,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        obligations=obligations,
        changed_fields=("revoked_at",),
    )
    try:
        _require_current_history_container(containing_target)
        decision = _require_permission(
            principal=actor,
            capability_code=REVOKE_CAPABILITY,
            target=containing_target,
        )
        normalized_reason = _normalized_reason(reason)
        with transaction.atomic():
            lock_retired_department_authority_boundaries()
            locked_container = _lock_target(containing_target)
            decision = _require_permission(
                principal=actor,
                capability_code=REVOKE_CAPABILITY,
                target=locked_container.target,
            )
            assignment_query = RoleAssignment.objects.select_for_update().filter(
                pk=assignment_id,
                organization_id=locked_container.target.organization_id,
            )
            if locked_container.target.edition_id is not None:
                assignment_query = assignment_query.filter(
                    edition_id=locked_container.target.edition_id
                )
            assignment = assignment_query.first()
            if assignment is None:
                _raise_authorization(
                    "The authority record is unavailable.",
                    reason_code="authority_unavailable",
                )
            role = (
                RoleBundle.objects.only("code", "version")
                .filter(pk=assignment.role_bundle_id)
                .first()
            )
            if (
                role is None
                or role.code.casefold() in REPRESENTATION_MANAGED_ROLE_CODES
            ):
                _raise_authorization(
                    "The authority record is unavailable.",
                    reason_code="authority_unavailable",
                )
            scope_level = _lock_retired_department_history_scope(
                container=locked_container,
                organization_id=assignment.organization_id,
                edition_id=assignment.edition_id,
                department_id=assignment.department_id,
                resource_binding_id=assignment.resource_binding_id,
            )
            command = replace(
                command,
                organization_id=assignment.organization_id,
                edition_id=assignment.edition_id,
            )
            if assignment.revoked_at is not None:
                _raise_validation(
                    "The role assignment is already revoked.",
                    reason_code="assignment_already_revoked",
                )
            evaluated_at = timezone.now()
            if assignment.expires_at is None or assignment.expires_at > evaluated_at:
                _raise_validation(
                    "Only expired authority history can be closed through this path.",
                    reason_code="historical_authority_not_expired",
                )
            assignment.revoked_at = evaluated_at
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
            audit = _append_command_audit(
                principal=actor,
                command=command,
                outcome=AuditEvent.Outcome.ALLOW,
                reason_code=decision.reason_code,
            )
            _publish_authority_event(
                event_name="authorization.role.revoked.v1",
                organization_id=assignment.organization_id,
                edition_id=assignment.edition_id,
                aggregate_type="authorization.role_assignment",
                aggregate_id=assignment.id,
                aggregate_version=2,
                payload={
                    "role_code": role.code,
                    "role_version": str(role.version),
                    "scope_level": scope_level,
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
            fallback_reason="retired_assignment_closure_invalid",
        )
        raise
    except Exception as error:
        _audit_failure(
            actor=actor,
            command=command,
            error=error,
            fallback_reason="retired_assignment_closure_failed",
        )
        raise
