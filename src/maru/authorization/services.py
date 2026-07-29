"""Audited grant and delegation commands."""

from datetime import datetime
from typing import Never
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from maru.audit.models import AuditEvent
from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION, require_capability
from maru.authorization.models import CapabilityGrant
from maru.authorization.policy import (
    ResourceScope,
    decide,
    grant_chain_is_active,
)
from maru.effects.services import DomainEventRecord, publish_domain_event
from maru.identity.models import Account


class AuthorizationDenied(PermissionDenied):
    def __init__(self, message: str, *, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(message)


def _scope_is_within(
    *,
    parent: CapabilityGrant,
    organization_id: UUID,
    edition_id: UUID | None,
) -> bool:
    if parent.organization_id != organization_id:
        return False
    if parent.edition_id is None:
        return True
    return parent.edition_id == edition_id


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
    organization_id: UUID,
    edition_id: UUID | None,
    effective_from: datetime,
    expires_at: datetime | None,
) -> str | None:
    if not _scope_is_within(
        parent=parent,
        organization_id=organization_id,
        edition_id=edition_id,
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


def _require_active_parent(parent: CapabilityGrant) -> None:
    if not grant_chain_is_active(parent, timezone.now()):
        raise AuthorizationDenied(
            "The parent authority is no longer active.",
            reason_code="parent_authority_inactive",
        )


def delegate_capability(
    *,
    actor: Account,
    recipient: Account,
    parent_grant_id: UUID,
    organization_id: UUID,
    edition_id: UUID | None,
    effective_from: datetime,
    expires_at: datetime | None,
    reason: str,
    correlation_id: UUID,
    request_id: UUID | None = None,
    source_channel: str = "service",
) -> CapabilityGrant:
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
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
        )

    definition = require_capability(parent.capability_code)
    at = timezone.now()
    delegated_authority = parent.delegated_from_id is not None
    if not definition.delegable or not grant_chain_is_active(parent, at):
        _raise_denial(
            message="The capability cannot be delegated.",
            reason_code="capability_not_delegable",
            actor=actor,
            recipient=recipient,
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            delegated_authority=delegated_authority,
        )

    bounds_error = _validate_delegation_bounds(
        parent=parent,
        organization_id=organization_id,
        edition_id=edition_id,
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
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            delegated_authority=delegated_authority,
        )

    meta_decision = decide(
        principal=actor,
        capability_code="authorization.delegate",
        resource=ResourceScope(
            organization_id=organization_id,
            edition_id=edition_id,
        ),
    )
    obligations = tuple(sorted(meta_decision.obligations))
    if not meta_decision.allowed:
        _raise_denial(
            message="Separate capability-delegation authority is required.",
            reason_code="delegation_permission_absent",
            actor=actor,
            recipient=recipient,
            organization_id=organization_id,
            edition_id=edition_id,
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
            organization_id=organization_id,
            edition_id=edition_id,
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
            locked_parent = _lock_parent_chain(
                parent_id=parent.id,
                actor=actor,
            )
            _require_active_parent(locked_parent)
            child = CapabilityGrant.objects.create(
                principal=recipient,
                capability_code=locked_parent.capability_code,
                organization_id=organization_id,
                edition_id=edition_id,
                effective_from=effective_from,
                expires_at=expires_at,
                granted_by=actor,
                delegated_from=locked_parent,
                reason=normalized_reason,
            )
            audit = append_audit(
                AuditRecord(
                    principal_kind="account",
                    principal_id=actor.id,
                    principal_context_id=None,
                    organization_id=organization_id,
                    event_edition_id=edition_id,
                    capability_code="authorization.delegate",
                    operation="authorization.capability.delegate",
                    target_type="authorization.capability_grant",
                    target_id=child.id,
                    outcome=AuditEvent.Outcome.ALLOW,
                    reason_code=meta_decision.reason_code,
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
                    organization_id=organization_id,
                    event_edition_id=edition_id,
                    aggregate_type="authorization.capability_grant",
                    aggregate_id=child.id,
                    aggregate_version=1,
                    payload={
                        "capability_code": child.capability_code,
                        "scope_level": "edition" if edition_id else "organization",
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
            organization_id=organization_id,
            edition_id=edition_id,
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
            organization_id=organization_id,
            edition_id=edition_id,
            correlation_id=correlation_id,
            request_id=request_id,
            source_channel=source_channel,
            outcome=AuditEvent.Outcome.ERROR,
            reason_code="delegation_failed",
            obligations=obligations,
            delegated_authority=delegated_authority,
        )
        raise
