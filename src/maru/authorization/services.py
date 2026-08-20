"""Audited grant and delegation commands."""

from datetime import datetime
from typing import Never
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.bindings import resource_binding_target_exists
from maru.authorization.catalog import POLICY_VERSION, require_capability
from maru.authorization.issuance import create_delegated_grant_issuance
from maru.authorization.models import (
    AuthorityIssuance,
    CapabilityGrant,
    ScopedResourceBinding,
)
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    decide,
    grant_chain_is_active,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.authorization.provenance import authority_issuance_is_current
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import Organization
from maru.workforce.models import Department


class AuthorizationDenied(PermissionDenied):
    """Signal authorization denied."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        """Initialize the AuthorizationDenied instance.

        Parameters
        ----------
        message : str
            The disclosure-safe message associated with the outcome.
        reason_code : str
            The stable reason code from the relevant closed catalog.
        """
        self.reason_code = reason_code
        super().__init__(message)


def _raise_authorization(message: str, *, reason_code: str) -> Never:
    raise AuthorizationDenied(message, reason_code=reason_code)


def _scope_is_within(
    *,
    parent: CapabilityGrant,
    target: ResolvedAuthorizationTarget,
) -> bool:
    if parent.organization_id != target.organization_id:
        return False
    if parent.resource_binding_id is not None:
        return parent.resource_binding_id == target.resource_binding_id
    if parent.department_id is not None:
        return (
            parent.edition_id == target.edition_id
            and parent.department_id == target.department_id
        )
    if parent.edition_id is not None:
        return parent.edition_id == target.edition_id
    return True


def _append_delegation_audit(
    *,
    actor: Account,
    recipient: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    outcome: str,
    reason_code: str,
    obligations: tuple[str, ...] = (),
    delegated_authority: bool = False,
) -> None:
    append_audit(
        AuditRecord(
            principal_kind="account",
            principal_id=actor.id,
            principal_context_id=None,
            organization_id=organization_id,
            event_edition_id=edition_id,
            capability_code="authorization.delegate",
            operation="authorization.capability.delegate",
            target_type="identity.account",
            target_id=recipient.id,
            outcome=outcome,
            reason_code=reason_code,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            obligations=obligations,
            changed_fields=("capability_grant",) if outcome == "allow" else (),
            delegated=delegated_authority,
            safe_metadata={"policy_version": POLICY_VERSION},
            retention_class="security-extended",
        )
    )


def _raise_denial(
    *,
    message: str,
    reason_code: str,
    actor: Account,
    recipient: Account,
    organization_id: UUID,
    edition_id: UUID | None,
    correlation_id: UUID,
    request_id: UUID | None,
    source_channel: str,
    obligations: tuple[str, ...] = (),
    delegated_authority: bool = False,
) -> Never:
    _append_delegation_audit(
        actor=actor,
        recipient=recipient,
        organization_id=organization_id,
        edition_id=edition_id,
        correlation_id=correlation_id,
        request_id=request_id,
        source_channel=source_channel,
        outcome=AuditEvent.Outcome.DENY,
        reason_code=reason_code,
        obligations=obligations,
        delegated_authority=delegated_authority,
    )
    raise AuthorizationDenied(message, reason_code=reason_code)


def _validate_delegation_bounds(
    *,
    parent: CapabilityGrant,
    target: ResolvedAuthorizationTarget,
    effective_from: datetime,
    expires_at: datetime | None,
) -> str | None:
    if not _scope_is_within(
        parent=parent,
        target=target,
    ):
        return "delegation_scope_too_broad"
    if effective_from < parent.effective_from:
        return "delegation_effective_before_parent"
    if expires_at is not None and expires_at <= effective_from:
        return "delegation_invalid_interval"
    if parent.expires_at is not None and (
        expires_at is None or expires_at > parent.expires_at
    ):
        return "delegation_expiry_too_late"
    return None


def _lock_parent_chain(
    *,
    parent_id: UUID,
    actor: Account,
) -> CapabilityGrant:
    parent = CapabilityGrant.objects.select_for_update().get(
        pk=parent_id,
        principal=actor,
    )
    current = parent
    while current.delegated_from_id is not None:
        current = CapabilityGrant.objects.select_for_update().get(
            pk=current.delegated_from_id
        )
    return parent


def _lock_target(  # noqa: PLR0912
    target: ResolvedAuthorizationTarget,
) -> ResolvedAuthorizationTarget:
    if (
        not Organization.objects.select_for_update()
        .filter(pk=target.organization_id)
        .exists()
    ):
        raise AuthorizationDenied(
            "The authority scope is unavailable.",
            reason_code="target_unavailable",
        )
    edition_id = target.edition_id
    department_id = target.department_id
    resource_binding_id = target.resource_binding_id
    if edition_id is not None and not (
        EventEdition.objects.select_for_update()
        .filter(
            pk=edition_id,
            organization_id=target.organization_id,
        )
        .exists()
    ):
        raise AuthorizationDenied(
            "The authority scope is unavailable.",
            reason_code="target_unavailable",
        )
    if department_id is not None:
        if edition_id is None:
            raise AuthorizationDenied(
                "The authority scope is unavailable.",
                reason_code="target_unavailable",
            )
        department_exists = (
            Department.objects.select_for_update()
            .filter(
                pk=department_id,
                organization_id=target.organization_id,
                edition_id=edition_id,
            )
            .exists()
        )
        if not department_exists:
            raise AuthorizationDenied(
                "The authority scope is unavailable.",
                reason_code="target_unavailable",
            )
    if resource_binding_id is not None:
        if edition_id is None or department_id is None:
            raise AuthorizationDenied(
                "The authority scope is unavailable.",
                reason_code="target_unavailable",
            )
        binding = (
            ScopedResourceBinding.objects.select_for_update()
            .filter(
                pk=resource_binding_id,
                organization_id=target.organization_id,
                edition_id=edition_id,
                department_id=department_id,
            )
            .first()
        )
        if binding is None or not resource_binding_target_exists(
            binding,
            for_update=True,
        ):
            raise AuthorizationDenied(
                "The authority scope is unavailable.",
                reason_code="target_unavailable",
            )
    if resource_binding_id is not None:
        if edition_id is None or department_id is None:
            raise AuthorizationDenied(
                "The authority scope is unavailable.",
                reason_code="target_unavailable",
            )
        refreshed = resolve_resource_target(
            organization_id=target.organization_id,
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=resource_binding_id,
        )
    elif department_id is not None:
        if edition_id is None:
            raise AuthorizationDenied(
                "The authority scope is unavailable.",
                reason_code="target_unavailable",
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
        raise AuthorizationDenied(
            "The authority scope is unavailable.",
            reason_code="target_unavailable",
        )
    return refreshed


def _require_active_parent(parent: CapabilityGrant) -> None:
    if not grant_chain_is_active(parent, timezone.now()):
        raise AuthorizationDenied(
            "The parent authority is no longer active.",
            reason_code="parent_authority_inactive",
        )


def _require_current_parent_issuance(
    *,
    parent: CapabilityGrant,
    target: ResolvedAuthorizationTarget,
    effective_from: datetime,
    expires_at: datetime | None,
    evaluated_at: datetime,
) -> AuthorityIssuance:
    """Validate only the named delegated parent; never select a replacement.

    Parameters
    ----------
    parent : CapabilityGrant
        The parent applied within the audited domain transition.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    effective_from : datetime
        The timezone-aware boundary for effective from.
    expires_at : datetime | None
        The timezone-aware timestamp for expires.
    evaluated_at : datetime
        The timezone-aware timestamp for evaluated.

    Returns
    -------
    AuthorityIssuance
        The resolved AuthorityIssuance for require current parent issuance.

    Raises
    ------
    AuthorizationDenied
        If the actor lacks the required scoped capability.
    """
    issuance = (
        AuthorityIssuance.objects.select_for_update()
        .only("ordinal")
        .filter(capability_grant_id=parent.id)
        .first()
    )
    if issuance is None:
        raise AuthorizationDenied(
            "The parent authority has no exact issuance provenance.",
            reason_code="parent_authority_unproven",
        )
    _require_active_parent(parent)
    if not authority_issuance_is_current(
        issuance_ordinal=issuance.ordinal,
        principal_id=parent.principal_id,
        capability_code=parent.capability_code,
        target=target,
        requested_effective_from=effective_from,
        requested_expires_at=expires_at,
        evaluated_at=evaluated_at,
        lock=True,
    ):
        raise AuthorizationDenied(
            "The parent authority no longer has current exact lineage.",
            reason_code="parent_authority_lineage_invalid",
        )
    return issuance


def delegate_capability(  # noqa: DOC503, PLR0915 - bare re-raise preserves original error
    *,
    actor: Account,
    recipient: Account,
    parent_grant_id: UUID,
    target: ResolvedAuthorizationTarget,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CapabilityGrant:
    """Return delegate capability.

    Parameters
    ----------
    actor : Account
        The authenticated person performing the operation.
    recipient : Account
        The recipient applied within the audited domain transition.
    parent_grant_id : UUID
        The identifier of the parent grant.
    target : ResolvedAuthorizationTarget
        The target applied within the audited domain transition.
    effective_from : datetime
        The timezone-aware boundary for effective from.
    expires_at : datetime | None
        The time at which the value expires.
    reason : str
        The operator-supplied reason for the operation.
    correlation_id : UUID
        The correlation identifier for audit tracing.
    request_id : UUID | None, default=None
        The identifier of the request.
    source_channel : str, default='service'
        The trusted channel that initiated the operation.

    Returns
    -------
    CapabilityGrant
        The CapabilityGrant established after delegate capability completes.

    Raises
    ------
    AuthorizationDenied
        If the caller lacks the authority required by the operation.
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    parent = (
        CapabilityGrant.objects.filter(
            pk=parent_grant_id,
            principal=actor,
        )
        .select_related("delegated_from")
        .first()
    )
    if parent is None:
        _raise_denial(
            message="The parent authority is unavailable.",
            reason_code="parent_authority_absent",
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )

    definition = require_capability(parent.capability_code)
    at = timezone.now()
    delegated_authority = parent.delegated_from_id is not None
    if not definition.delegable:
        _raise_denial(
            message="The capability cannot be delegated.",
            reason_code="capability_not_delegable",
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            delegated_authority=delegated_authority,
        )
    if not grant_chain_is_active(parent, at):
        _raise_denial(
            message="The parent authority is no longer active.",
            reason_code="parent_authority_inactive",
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            delegated_authority=delegated_authority,
        )

    bounds_error = _validate_delegation_bounds(
        parent=parent,
        target=target,
        effective_from=effective_from,
        expires_at=expires_at,
    )
    if bounds_error is not None:
        messages = {
            "delegation_scope_too_broad": (
                "Delegation must use an equal or narrower scope."
            ),
            "delegation_effective_before_parent": (
                "Delegation cannot begin before its parent authority."
            ),
            "delegation_invalid_interval": (
                "Delegation expiry must follow its effective time."
            ),
            "delegation_expiry_too_late": (
                "Delegation cannot outlive the parent grant."
            ),
        }
        _raise_denial(
            message=messages[bounds_error],
            reason_code=bounds_error,
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            delegated_authority=delegated_authority,
        )

    meta_decision = decide(
        principal=actor,
        capability_code="authorization.delegate",
        resource=target,
    )
    obligations = tuple(sorted(meta_decision.obligations))
    if not meta_decision.allowed:
        _raise_denial(
            message="Separate capability-delegation authority is required.",
            reason_code="delegation_permission_absent",
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            obligations=obligations,
            delegated_authority=delegated_authority,
        )

    normalized_reason = reason.strip()
    if not normalized_reason:
        _append_delegation_audit(
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="reason_required",
            obligations=obligations,
            delegated_authority=delegated_authority,
        )
        raise ValidationError(
            {"reason": "A delegation reason is required."},
            code="reason_required",
        )

    try:
        with transaction.atomic():
            # Every authority writer enters the shared Page 9/provenance/
            # retirement boundary before taking tenant or target row locks.
            # Keeping this legacy delegation path in the same order as the
            # newer command services prevents a Department editor and a
            # delegation from waiting on each other's advisory/row locks.
            lock_retired_department_authority_boundaries()
            locked_target = _lock_target(target)
            locked_parent = _lock_parent_chain(
                parent_id=parent.id,
                actor=actor,
            )
            locked_bounds_error = _validate_delegation_bounds(
                parent=locked_parent,
                target=locked_target,
                effective_from=effective_from,
                expires_at=expires_at,
            )
            if locked_bounds_error is not None:
                _raise_authorization(
                    "Delegation is no longer valid for the resolved target.",
                    reason_code=locked_bounds_error,
                )
            evaluated_at = timezone.now()
            locked_meta_decision = decide(
                principal=actor,
                capability_code="authorization.delegate",
                resource=locked_target,
            )
            obligations = tuple(sorted(locked_meta_decision.obligations))
            if not locked_meta_decision.allowed:
                _raise_authorization(
                    "Separate capability-delegation authority is required.",
                    reason_code="delegation_permission_absent",
                )
            _require_current_parent_issuance(
                parent=locked_parent,
                target=locked_target,
                effective_from=effective_from,
                expires_at=expires_at,
                evaluated_at=evaluated_at,
            )
            child = CapabilityGrant.objects.create(
                principal=recipient,
                capability_code=locked_parent.capability_code,
                organization_id=locked_target.organization_id,
                edition_id=locked_target.edition_id,
                department_id=locked_target.department_id,
                resource_binding_id=locked_target.resource_binding_id,
                effective_from=effective_from,
                expires_at=expires_at,
                granted_by=actor,
                delegated_from=locked_parent,
                reason=normalized_reason,
            )
            try:
                create_delegated_grant_issuance(
                    grant=child,
                    evaluated_at=evaluated_at,
                )
            except ValidationError:
                _raise_authorization(
                    "The delegated authority could not retain exact parent lineage.",
                    reason_code="delegated_issuance_invalid",
                )
            audit = append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor.id,
                    principal_context_id=None,
                    organization_id=locked_target.organization_id,
                    event_edition_id=locked_target.edition_id,
                    capability_code="authorization.delegate",
                    operation="authorization.capability.delegate",
                    target_type="authorization.capability_grant",
                    target_id=child.id,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code=locked_meta_decision.reason_code,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    source_channel=source_channel,
                    obligations=obligations,
                    changed_fields=("capability_grant",),
                    delegated=delegated_authority,
                    safe_metadata={"policy_version": POLICY_VERSION},
                    retention_class="security-extended",
                )
            )
            publish_domain_event(
                DomainEventRecord(
                    event_name="authorization.capability.delegated.v1",
                    schema_version=1,
                    organization_id=locked_target.organization_id,
                    event_edition_id=locked_target.edition_id,
                    aggregate_type="authorization.capability_grant",
                    aggregate_id=child.id,
                    aggregate_version=1,
                    payload={
                        "capability_code": child.capability_code,
                        "scope_level": locked_target.scope_level,
                    },
                    correlation_id=correlation_id,
                    causation_id=audit.id,
                    actor_kind="account",
                    actor_id=actor.id,
                    retention_class="security-extended",
                ),
                workload_pool="security",
            )
            return child
    except AuthorizationDenied as error:
        _append_delegation_audit(
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.DENY,
            reason_code=error.reason_code,
            obligations=obligations,
            delegated_authority=delegated_authority,
        )
        raise
    except Exception:
        _append_delegation_audit(
            actor=actor,
            recipient=recipient,
            organization_id=target.organization_id,
            edition_id=target.edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="delegation_failed",
            obligations=obligations,
            delegated_authority=delegated_authority,
        )
        raise
