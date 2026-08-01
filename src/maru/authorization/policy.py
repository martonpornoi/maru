"""Deny-by-default policy evaluation over server-resolved targets."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeGuard, cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import F, Model, Q
from django.utils import timezone

from maru.authorization.catalog import POLICY_VERSION, ScopeLevel, capability
from maru.authorization.models import CapabilityGrant, RoleAssignment
from maru.identity.models import Account

_TARGET_SEAL = object()


@dataclass(frozen=True, slots=True, init=False)
class ResolvedAuthorizationTarget:
    """Persisted authorization facts sealed by an explicit resolver.

    Callers cannot construct this value from route or request data.  The public
    resolver functions below prove the persisted tenant chain before sealing a
    target; owner facts are derived from a persisted owning record or from the
    exact principal of a code-owned self-service action.
    """

    organization_id: UUID
    edition_id: UUID | None
    department_id: UUID | None
    resource_binding_id: UUID | None
    owner_account_id: UUID | None = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self) -> None:
        raise TypeError(
            "Authorization targets must be created by an explicit persisted "
            "target resolver."
        )

    @property
    def scope_level(self) -> ScopeLevel:
        if self.resource_binding_id is not None:
            return ScopeLevel.RESOURCE
        if self.department_id is not None:
            return ScopeLevel.DEPARTMENT
        if self.edition_id is not None:
            return ScopeLevel.EDITION
        return ScopeLevel.ORGANIZATION


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    fields: frozenset[str]
    obligations: frozenset[str]
    reason_code: str
    policy_version: str = POLICY_VERSION


def _seal_target(
    *,
    organization_id: UUID,
    edition_id: UUID | None = None,
    department_id: UUID | None = None,
    resource_binding_id: UUID | None = None,
    owner_account_id: UUID | None = None,
) -> ResolvedAuthorizationTarget:
    if department_id is not None and edition_id is None:
        raise ValueError("A resolved department target requires an edition.")
    if resource_binding_id is not None and department_id is None:
        raise ValueError("A resolved resource target requires a department.")
    target = object.__new__(ResolvedAuthorizationTarget)
    object.__setattr__(target, "organization_id", organization_id)
    object.__setattr__(target, "edition_id", edition_id)
    object.__setattr__(target, "department_id", department_id)
    object.__setattr__(target, "resource_binding_id", resource_binding_id)
    object.__setattr__(target, "owner_account_id", owner_account_id)
    object.__setattr__(target, "_seal", _TARGET_SEAL)
    return target


def _safe_first(query: Any) -> dict[str, Any] | None:
    try:
        return cast("dict[str, Any] | None", query.first())
    except (TypeError, ValueError, ValidationError):
        return None


def _person_account_exists(account_id: UUID) -> bool:
    return Account.objects.filter(
        pk=account_id,
        account_kind=Account.Kind.PERSON,
    ).exists()


def resolve_organization_target(
    *, organization_id: UUID
) -> ResolvedAuthorizationTarget | None:
    """Resolve an exact persisted organization without disclosing absence."""

    from maru.organizations.models import Organization  # noqa: PLC0415

    row = _safe_first(Organization.objects.filter(pk=organization_id).values("id"))
    if row is None:
        return None
    return _seal_target(organization_id=row["id"])


def resolve_edition_target(
    *, organization_id: UUID, edition_id: UUID
) -> ResolvedAuthorizationTarget | None:
    """Resolve an edition only through its exact persisted organization."""

    from maru.events.models import EventEdition  # noqa: PLC0415

    row = _safe_first(
        EventEdition.objects.filter(
            pk=edition_id,
            organization_id=organization_id,
        ).values("id", "organization_id")
    )
    if row is None:
        return None
    return _seal_target(
        organization_id=row["organization_id"],
        edition_id=row["id"],
    )


def resolve_department_target(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
) -> ResolvedAuthorizationTarget | None:
    """Resolve one exact department; reporting descendants never inherit."""

    from maru.workforce.models import Department  # noqa: PLC0415

    row = _safe_first(
        Department.objects.filter(
            pk=department_id,
            organization_id=organization_id,
            edition_id=edition_id,
        ).values("id", "organization_id", "edition_id")
    )
    if row is None:
        return None
    return _seal_target(
        organization_id=row["organization_id"],
        edition_id=row["edition_id"],
        department_id=row["id"],
    )


def resolve_resource_target(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_id: UUID,
    resource_binding_id: UUID,
) -> ResolvedAuthorizationTarget | None:
    """Resolve one immutable typed binding through its complete parent chain."""

    from maru.authorization.models import ScopedResourceBinding  # noqa: PLC0415

    row = _safe_first(
        ScopedResourceBinding.objects.filter(
            pk=resource_binding_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
        ).values(
            "id",
            "organization_id",
            "edition_id",
            "department_id",
            "resource_kind",
            "resource_id",
        )
    )
    if row is None:
        return None
    if row["resource_kind"] != ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION:
        return None
    from maru.workforce.models import Position  # noqa: PLC0415

    position_exists = Position.objects.filter(
        pk=row["resource_id"],
        organization_id=row["organization_id"],
        edition_id=row["edition_id"],
        department_id=row["department_id"],
    ).exists()
    if not position_exists:
        return None
    return _seal_target(
        organization_id=row["organization_id"],
        edition_id=row["edition_id"],
        department_id=row["department_id"],
        resource_binding_id=row["id"],
    )


def resolve_owned_target(  # noqa: PLR0911
    *, resource: Model
) -> ResolvedAuthorizationTarget | None:
    """Derive self/owner facts from one persisted convention-owned record.

    The owning record must expose direct ``organization_id``, ``account_id``,
    and optional ``edition_id`` fields.  Values are re-read from the database;
    caller-supplied owner identifiers are never accepted.
    """

    if resource.pk is None:
        return None
    if resource._meta.label_lower == "workforce.volunteerapplication":
        row = _safe_first(
            type(resource)
            ._base_manager.filter(pk=resource.pk)
            .values(
                "account_id",
                organization_id=F("opportunity__position__organization_id"),
                edition_id=F("opportunity__position__edition_id"),
            )
        )
        if (
            row is None
            or row["account_id"] is None
            or not _person_account_exists(row["account_id"])
        ):
            return None
        base = resolve_edition_target(
            organization_id=row["organization_id"],
            edition_id=row["edition_id"],
        )
        if base is None:
            return None
        return _seal_target(
            organization_id=base.organization_id,
            edition_id=base.edition_id,
            owner_account_id=row["account_id"],
        )
    concrete_attnames = {field.attname for field in resource._meta.concrete_fields}
    if not {"organization_id", "account_id"} <= concrete_attnames:
        return None
    value_fields = ["organization_id", "account_id"]
    if "edition_id" in concrete_attnames:
        value_fields.append("edition_id")
    row = _safe_first(
        type(resource)._base_manager.filter(pk=resource.pk).values(*value_fields)
    )
    if (
        row is None
        or row["account_id"] is None
        or not _person_account_exists(row["account_id"])
    ):
        return None
    edition_id = row.get("edition_id")
    if edition_id is None:
        base = resolve_organization_target(organization_id=row["organization_id"])
    else:
        base = resolve_edition_target(
            organization_id=row["organization_id"],
            edition_id=edition_id,
        )
    if base is None:
        return None
    return _seal_target(
        organization_id=base.organization_id,
        edition_id=base.edition_id,
        owner_account_id=row["account_id"],
    )


def resolve_self_target(
    *,
    principal: Account,
    organization_id: UUID,
    edition_id: UUID | None = None,
) -> ResolvedAuthorizationTarget | None:
    """Resolve a code-owned self-service intent for the exact person principal.

    This resolver is for create/list self-service operations that have no
    owning domain row yet.  It cannot name another owner and rejects platform
    administrators as convention subjects.
    """

    person_exists = Account.objects.filter(
        pk=principal.pk,
        account_kind=Account.Kind.PERSON,
    ).exists()
    if not person_exists:
        return None
    if edition_id is None:
        base = resolve_organization_target(organization_id=organization_id)
    else:
        base = resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
    if base is None:
        return None
    return _seal_target(
        organization_id=base.organization_id,
        edition_id=base.edition_id,
        owner_account_id=principal.id,
    )


def _active_at(at: datetime) -> Q:
    return (
        Q(effective_from__lte=at)
        & (Q(expires_at__isnull=True) | Q(expires_at__gt=at))
        & Q(revoked_at__isnull=True)
    )


def _scope_filter(resource: ResolvedAuthorizationTarget) -> Q:
    organization_scope = Q(
        edition__isnull=True,
        department__isnull=True,
        resource_binding__isnull=True,
    )
    if resource.edition_id is None:
        return organization_scope
    edition_scope = Q(
        edition_id=resource.edition_id,
        department__isnull=True,
        resource_binding__isnull=True,
    )
    if resource.department_id is None:
        return organization_scope | edition_scope
    department_scope = Q(
        edition_id=resource.edition_id,
        department_id=resource.department_id,
        resource_binding__isnull=True,
    )
    if resource.resource_binding_id is None:
        return organization_scope | edition_scope | department_scope
    return (
        organization_scope
        | edition_scope
        | department_scope
        | Q(
            edition_id=resource.edition_id,
            department_id=resource.department_id,
            resource_binding_id=resource.resource_binding_id,
        )
    )


def _persistent_scope_is_valid(authority: CapabilityGrant) -> bool:
    if authority.resource_binding_id is not None:
        return authority.department_id is not None and authority.edition_id is not None
    if authority.department_id is not None:
        return authority.edition_id is not None
    return True


def _authority_scope_contains(
    parent: CapabilityGrant,
    child: CapabilityGrant,
) -> bool:
    if not _persistent_scope_is_valid(parent) or not _persistent_scope_is_valid(child):
        return False
    if parent.organization_id != child.organization_id:
        return False
    if parent.resource_binding_id is not None:
        return parent.resource_binding_id == child.resource_binding_id
    if parent.department_id is not None:
        return (
            parent.edition_id == child.edition_id
            and parent.department_id == child.department_id
        )
    if parent.edition_id is not None:
        return parent.edition_id == child.edition_id
    return True


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
            or not _persistent_scope_is_valid(current)
        ):
            return False
        if child is not None:
            if child.capability_code != current.capability_code:
                return False
            if not _authority_scope_contains(current, child):
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


def _target_is_trusted(
    resource: object,
) -> TypeGuard[ResolvedAuthorizationTarget]:
    return (
        isinstance(resource, ResolvedAuthorizationTarget)
        and getattr(resource, "_seal", None) is _TARGET_SEAL
    )


def decide(  # noqa: PLR0911
    *,
    principal: Account,
    capability_code: str,
    resource: ResolvedAuthorizationTarget | None,
    requested_fields: frozenset[str] | None = None,
    at: datetime | None = None,
) -> PolicyDecision:
    definition = capability(capability_code)
    if definition is None or not principal.is_active:
        return PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code=(
                "unknown_capability" if definition is None else "account_inactive"
            ),
        )
    if not _target_is_trusted(resource):
        return PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="target_unavailable",
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

    if not definition.persistable:
        return PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="permission_absent",
        )

    if (
        principal.is_platform_administrator
        and not definition.allow_self
        and not definition.requires_break_glass
    ):
        return PolicyDecision(
            allowed=True,
            fields=permitted_fields,
            obligations=definition.obligations,
            reason_code="platform_administration",
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
