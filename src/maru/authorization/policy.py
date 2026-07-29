"""Deny-by-default policy evaluation."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from maru.authorization.catalog import POLICY_VERSION, capability
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.identity.models import Account


@dataclass(frozen=True, slots=True)
class ResourceScope:
    organization_id: UUID
    edition_id: UUID | None = None
    owner_account_id: UUID | None = None
    state: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    fields: frozenset[str]
    obligations: frozenset[str]
    reason_code: str
    policy_version: str = POLICY_VERSION


def _active_at(at: datetime) -> Q:
    return (
        Q(effective_from__lte=at)
        & (Q(expires_at__isnull=True) | Q(expires_at__gt=at))
        & Q(revoked_at__isnull=True)
    )


def _scope_filter(resource: ResourceScope) -> Q:
    if resource.edition_id is None:
        return Q(edition__isnull=True)
    return Q(edition__isnull=True) | Q(edition_id=resource.edition_id)


def grant_chain_is_active(  # noqa: PLR0911
    grant: CapabilityGrant,
    at: datetime,
) -> bool:
    seen: set[UUID] = set()
    current: CapabilityGrant | None = grant
    child: CapabilityGrant | None = None

    while current is not None:
        if current.id in seen:
            return False
        seen.add(current.id)
        if (
            current.effective_from > at
            or (current.expires_at is not None and current.expires_at <= at)
            or current.revoked_at is not None
        ):
            return False
        if child is not None:
            if child.capability_code != current.capability_code:
                return False
            if child.organization_id != current.organization_id:
                return False
            if (
                current.edition_id is not None
                and child.edition_id != current.edition_id
            ):
                return False
            if child.granted_by_id != current.principal_id:
                return False
            if current.expires_at is not None and (
                child.expires_at is None or child.expires_at > current.expires_at
            ):
                return False
        child = current
        current = current.delegated_from
    return True


def decide(
    *,
    principal: Account,
    capability_code: str,
    resource: ResourceScope,
    requested_fields: frozenset[str] | None = None,
    at: datetime | None = None,
) -> PolicyDecision:
    definition = capability(capability_code)
    if definition is None:
        return PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="unknown_capability",
        )

    permitted_fields = definition.field_ceiling
    if requested_fields is not None:
        permitted_fields = permitted_fields.intersection(requested_fields)

    if definition.allow_self and resource.owner_account_id == principal.id:
        return PolicyDecision(
            allowed=True,
            fields=permitted_fields,
            obligations=definition.obligations,
            reason_code="self_relationship",
        )

    evaluation_time = at or timezone.now()
    direct_grants = CapabilityGrant.objects.filter(
        _active_at(evaluation_time),
        _scope_filter(resource),
        organization_id=resource.organization_id,
        principal=principal,
        capability_code=capability_code,
    ).select_related("delegated_from")
    if any(grant_chain_is_active(grant, evaluation_time) for grant in direct_grants):
        return PolicyDecision(
            allowed=True,
            fields=permitted_fields,
            obligations=definition.obligations,
            reason_code="direct_grant",
        )

    role_assignment_exists = RoleAssignment.objects.filter(
        _active_at(evaluation_time),
        _scope_filter(resource),
        organization_id=resource.organization_id,
        principal=principal,
        role_bundle__capability_codes__contains=[capability_code],
    ).exists()
    if role_assignment_exists:
        return PolicyDecision(
            allowed=True,
            fields=permitted_fields,
            obligations=definition.obligations,
            reason_code="role_assignment",
        )

    return PolicyDecision(
        allowed=False,
        fields=frozenset(),
        obligations=frozenset(),
        reason_code="permission_absent",
    )
