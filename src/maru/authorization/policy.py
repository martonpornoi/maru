"""Deny-by-default policy evaluation over server-resolved targets."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeGuard, cast
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import F, Model, Q
from django.utils import timezone

from maru.authorization.bindings import resource_binding_target_exists
from maru.authorization.catalog import POLICY_VERSION, ScopeLevel, capability
from maru.authorization.models import (
    AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION,
    AUTHORITY_PROVENANCE_ACTIVE_GENERATION,
    AUTHORITY_PROVENANCE_CONTRACT_VERSION,
    AUTHORITY_PROVENANCE_INACTIVE_GENERATION,
    AuthorityProvenanceActivation,
    AuthorityProvenanceActivationLatch,
    CapabilityGrant,
    RoleAssignment,
    ScopedResourceBinding,
)
from maru.authorization.provenance import (
    AuthorityIssuanceCurrentCheck,
    ControlHorizonMode,
    authority_issuance_is_current,
    authority_issuances_are_current,
)
from maru.identity.models import Account

_TARGET_SEAL = object()
EXACT_LINEAGE_POLICY_CONTRACT_VERSION = AUTHORITY_PROVENANCE_CONTRACT_VERSION
EXACT_LINEAGE_POLICY_VERSION = AUTHORITY_PROVENANCE_ACTIVATION_POLICY_VERSION
MAX_ROLE_ASSIGNMENT_CURRENTNESS_CHECKS = 4_096
type _AuthorityScopeKey = tuple[UUID, UUID | None, UUID | None, UUID | None]


@dataclass(frozen=True, slots=True, init=False)
class ResolvedAuthorizationTarget:
    """Persisted authorization facts sealed by an explicit resolver.

    Callers cannot construct this value from route or request data.  The public
    resolver functions below prove the persisted tenant chain before sealing a
    target; owner facts are derived from a persisted owning record or from the
    exact principal of a code-owned self-service action.

    Attributes
    ----------
    organization_id
        The organization identifier that owns the requested resource.
    edition_id
        The event edition identifier that scopes the operation.
    department_id
        The department identifier within the requested scope.
    resource_binding_id
        The resource binding identifier within the requested scope.
    owner_account_id
        The owner account identifier within the requested scope.
    """

    organization_id: UUID
    edition_id: UUID | None
    department_id: UUID | None
    resource_binding_id: UUID | None
    owner_account_id: UUID | None = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __init__(self) -> None:
        """Initialize the ResolvedAuthorizationTarget instance.

        Raises
        ------
        TypeError
            If a supplied value has an unsupported type.
        """
        raise TypeError(
            "Authorization targets must be created by an explicit persisted "
            "target resolver."
        )

    @property
    def scope_level(self) -> ScopeLevel:
        """Return scope level.

        Returns
        -------
        ScopeLevel
            The resolved ScopeLevel for scope level.
        """
        if self.resource_binding_id is not None:
            return ScopeLevel.RESOURCE
        if self.department_id is not None:
            return ScopeLevel.DEPARTMENT
        if self.edition_id is not None:
            return ScopeLevel.EDITION
        return ScopeLevel.ORGANIZATION


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Describe policy decision.

    Attributes
    ----------
    allowed
        The allowed retained in this immutable projection.
    fields
        The canonical field names included in the operation.
    obligations
        The obligations retained in this immutable projection.
    reason_code
        The stable reason code from the relevant closed catalog.
    policy_version
        The expected policy version used to reject stale updates.
    """

    allowed: bool
    fields: frozenset[str]
    obligations: frozenset[str]
    reason_code: str
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True, slots=True)
class AuthorizedScopeProjection:
    """Name-free organizer scope proven by current persisted authority.

    The projection deliberately contains no authority, issuance, principal, or
    tenant display identifiers.  Browser navigation may use it to constrain a
    later tenant-name query, but every destination must repeat its own policy
    decision.

    Attributes
    ----------
    organization_id
        The organization identifier that owns the requested resource.
    edition_id
        The event edition identifier that scopes the operation.
    department_id
        The department identifier within the requested scope.
    resource_binding_id
        The resource binding identifier within the requested scope.
    capability_codes
        The capability codes retained in this immutable projection.
    """

    organization_id: UUID
    edition_id: UUID | None
    department_id: UUID | None
    resource_binding_id: UUID | None
    capability_codes: frozenset[str]


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
    """Resolve an exact persisted organization without disclosing absence.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved ResolvedAuthorizationTarget | None for the requested scope.
    """
    from maru.organizations.models import Organization  # noqa: PLC0415

    row = _safe_first(Organization.objects.filter(pk=organization_id).values("id"))
    if row is None:
        return None
    return _seal_target(organization_id=row["id"])


def resolve_edition_target(
    *, organization_id: UUID, edition_id: UUID
) -> ResolvedAuthorizationTarget | None:
    """Resolve an edition only through its exact persisted organization.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved ResolvedAuthorizationTarget | None for the requested scope.
    """
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
    """Resolve one exact department; reporting descendants never inherit.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    department_id : UUID
        The department identifier within the requested scope.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved ResolvedAuthorizationTarget | None for the requested scope.
    """
    from maru.workforce.models import Department  # noqa: PLC0415

    row = _safe_first(
        Department.objects.filter(
            pk=department_id,
            organization_id=organization_id,
            edition_id=edition_id,
            retired_at__isnull=True,
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
    """Resolve one immutable typed binding through its complete parent chain.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    department_id : UUID
        The department identifier within the requested scope.
    resource_binding_id : UUID
        The resource binding identifier within the requested scope.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved ResolvedAuthorizationTarget | None for the requested scope.
    """
    from maru.authorization.models import ScopedResourceBinding  # noqa: PLC0415

    row = _safe_first(
        ScopedResourceBinding.objects.filter(
            pk=resource_binding_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            department__retired_at__isnull=True,
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
    if not resource_binding_target_exists(row):
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

    Parameters
    ----------
    resource : Model
        The resolved resource target used for scoped authorization.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved ResolvedAuthorizationTarget | None for the requested scope.
    """
    if resource.pk is None:
        return None
    if resource._meta.label_lower == "workforce.volunteerapplication":  # noqa: SLF001
        row = _safe_first(
            type(resource)  # noqa: SLF001
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
    concrete_attnames = {field.attname for field in resource._meta.concrete_fields}  # noqa: SLF001
    if not {"organization_id", "account_id"} <= concrete_attnames:
        return None
    value_fields = ["organization_id", "account_id"]
    if "edition_id" in concrete_attnames:
        value_fields.append("edition_id")
    row = _safe_first(
        type(resource)._base_manager.filter(pk=resource.pk).values(*value_fields)  # noqa: SLF001
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

    Parameters
    ----------
    principal : Account
        The authenticated principal whose authority is evaluated.
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID | None, default=None
        The event edition identifier that scopes the operation.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved ResolvedAuthorizationTarget | None for the requested scope.
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
    """Return whether grant chain is active.

    Parameters
    ----------
    grant : CapabilityGrant
        The grant evaluated while grant chain is active.
    at : datetime
        The point in time used for the operation.

    Returns
    -------
    bool
        Whether the requested condition is satisfied.
    """
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


def _exact_lineage_policy_state() -> tuple[bool, bool]:
    """Return cutover evidence and runtime-contract validity without caching.

    Returns
    -------
    tuple[bool, bool]
        The matching exact lineage policy state records in deterministic order.
    """
    latch_generation = (
        AuthorityProvenanceActivationLatch.objects.filter(singleton=True)
        .values_list("generation", flat=True)
        .first()
    )
    marker = (
        AuthorityProvenanceActivation.objects.filter(singleton=True)
        .values("contract_version", "policy_version")
        .first()
    )
    if marker is None:
        return (
            latch_generation is None
            or latch_generation != AUTHORITY_PROVENANCE_INACTIVE_GENERATION
        ), False
    return True, bool(
        latch_generation == AUTHORITY_PROVENANCE_ACTIVE_GENERATION
        and marker["contract_version"] == EXACT_LINEAGE_POLICY_CONTRACT_VERSION
        and marker["policy_version"] == EXACT_LINEAGE_POLICY_VERSION
    )


def exact_lineage_policy_is_active() -> bool:
    """Confirm that the durable marker selects this exact runtime contract.

    Returns
    -------
    bool
        `True` when Confirm that the durable marker selects this exact runtime
        contract; otherwise `False`.
    """
    marker_present, contract_valid = _exact_lineage_policy_state()
    return marker_present and contract_valid


def _exact_issuance_allows(
    *,
    authority: CapabilityGrant | RoleAssignment,
    principal: Account,
    capability_code: str,
    resource: ResolvedAuthorizationTarget,
    evaluation_time: datetime,
) -> bool:
    try:
        issuance_ordinal = authority.authority_issuance.ordinal
    except ObjectDoesNotExist:
        return False
    return authority_issuance_is_current(
        issuance_ordinal=issuance_ordinal,
        principal_id=principal.id,
        capability_code=capability_code,
        target=resource,
        requested_effective_from=evaluation_time,
        requested_expires_at=None,
        evaluated_at=evaluation_time,
        horizon_mode=ControlHorizonMode.POINT_IN_TIME,
    )


def _logistics_manifest_projection_targets(
    bindings: Collection[Mapping[str, Any]],
) -> dict[UUID, tuple[UUID, UUID, UUID]]:
    from maru.logistics.models import LogisticsManifest  # noqa: PLC0415

    resource_ids = {
        row["resource_id"]
        for row in bindings
        if row["resource_kind"] == ScopedResourceBinding.ResourceKind.LOGISTICS_MANIFEST
    }
    return {
        row["id"]: (
            row["organization_id"],
            row["edition_id"],
            row["responsible_department_id"],
        )
        for row in LogisticsManifest.objects.filter(id__in=resource_ids)
        .order_by()
        .values(
            "id",
            "organization_id",
            "edition_id",
            "responsible_department_id",
        )
    }


def _bulk_authority_projection_targets(
    scope_keys: Collection[_AuthorityScopeKey],
) -> dict[_AuthorityScopeKey, ResolvedAuthorizationTarget]:
    """Resolve every candidate tenant chain in a constant number of queries.

    Navigation can legitimately project hundreds of scoped assignments.  A
    per-authority resolver would turn that into an attacker-amplifiable query
    fan-out before the batched provenance check.  These reads remain name-free
    and retain the same exact organization/edition/department/resource chain
    validation as the public single-target resolvers.

    Parameters
    ----------
    scope_keys : Collection[_AuthorityScopeKey]
        The scope keys evaluated while bulk authority projection targets.

    Returns
    -------
    dict[_AuthorityScopeKey, ResolvedAuthorizationTarget]
        A mapping containing the resolved bulk authority projection targets
        data.
    """
    if not scope_keys:
        return {}

    from maru.charities.models import CharitySelection  # noqa: PLC0415
    from maru.events.models import EventEdition  # noqa: PLC0415
    from maru.organizations.models import Organization  # noqa: PLC0415
    from maru.venues.models import EditionSpaceSelection  # noqa: PLC0415
    from maru.workforce.models import Department, Position  # noqa: PLC0415

    organization_ids = {scope[0] for scope in scope_keys}
    valid_organizations = set(
        Organization.objects.filter(id__in=organization_ids)
        .order_by()
        .values_list("id", flat=True)
    )

    requested_edition_ids = {scope[1] for scope in scope_keys if scope[1] is not None}
    editions = {
        row["id"]: row["organization_id"]
        for row in EventEdition.objects.filter(id__in=requested_edition_ids)
        .order_by()
        .values("id", "organization_id")
    }

    requested_department_ids = {
        scope[2] for scope in scope_keys if scope[2] is not None
    }
    departments = {
        row["id"]: (row["organization_id"], row["edition_id"])
        for row in Department.objects.filter(
            id__in=requested_department_ids,
            retired_at__isnull=True,
        )
        .order_by()
        .values("id", "organization_id", "edition_id")
    }

    requested_binding_ids = {scope[3] for scope in scope_keys if scope[3] is not None}
    bindings = {
        row["id"]: row
        for row in ScopedResourceBinding.objects.filter(
            id__in=requested_binding_ids,
        )
        .order_by()
        .values(
            "id",
            "organization_id",
            "edition_id",
            "department_id",
            "resource_kind",
            "resource_id",
        )
    }
    position_ids = {
        row["resource_id"]
        for row in bindings.values()
        if row["resource_kind"] == ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION
    }
    positions = {
        row["id"]: (
            row["organization_id"],
            row["edition_id"],
            row["department_id"],
        )
        for row in Position.objects.filter(id__in=position_ids)
        .order_by()
        .values("id", "organization_id", "edition_id", "department_id")
    }
    charity_selection_ids = {
        row["resource_id"]
        for row in bindings.values()
        if row["resource_kind"] == ScopedResourceBinding.ResourceKind.CHARITY_SELECTION
    }
    charity_selections = {
        row["id"]: (
            row["organization_id"],
            row["edition_id"],
            row["responsible_department_id"],
        )
        for row in CharitySelection.objects.filter(id__in=charity_selection_ids)
        .order_by()
        .values(
            "id",
            "organization_id",
            "edition_id",
            "responsible_department_id",
        )
    }
    venue_space_ids = {
        row["resource_id"]
        for row in bindings.values()
        if row["resource_kind"]
        == ScopedResourceBinding.ResourceKind.VENUE_EDITION_SPACE
    }
    venue_spaces = {
        row["id"]: (
            row["organization_id"],
            row["edition_id"],
            row["responsible_department_id"],
        )
        for row in EditionSpaceSelection.objects.filter(id__in=venue_space_ids)
        .order_by()
        .values(
            "id",
            "organization_id",
            "edition_id",
            "responsible_department_id",
        )
    }
    logistics_manifests = _logistics_manifest_projection_targets(bindings.values())

    resolved: dict[_AuthorityScopeKey, ResolvedAuthorizationTarget] = {}
    for scope_key in scope_keys:
        organization_id, edition_id, department_id, binding_id = scope_key
        if organization_id not in valid_organizations:
            continue
        if edition_id is None:
            if department_id is not None or binding_id is not None:
                continue
            resolved[scope_key] = _seal_target(organization_id=organization_id)
            continue
        if editions.get(edition_id) != organization_id:
            continue
        if department_id is None:
            if binding_id is not None:
                continue
            resolved[scope_key] = _seal_target(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            continue
        if departments.get(department_id) != (organization_id, edition_id):
            continue
        if binding_id is None:
            resolved[scope_key] = _seal_target(
                organization_id=organization_id,
                edition_id=edition_id,
                department_id=department_id,
            )
            continue
        binding = bindings.get(binding_id)
        workforce_target_valid = (
            binding is not None
            and binding["resource_kind"]
            == ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION
            and positions.get(binding["resource_id"])
            == (organization_id, edition_id, department_id)
        )
        charity_target_valid = (
            binding is not None
            and binding["resource_kind"]
            == ScopedResourceBinding.ResourceKind.CHARITY_SELECTION
            and charity_selections.get(binding["resource_id"])
            == (organization_id, edition_id, department_id)
        )
        venue_target_valid = (
            binding is not None
            and binding["resource_kind"]
            == ScopedResourceBinding.ResourceKind.VENUE_EDITION_SPACE
            and venue_spaces.get(binding["resource_id"])
            == (organization_id, edition_id, department_id)
        )
        if (
            binding is None
            or binding["organization_id"] != organization_id
            or binding["edition_id"] != edition_id
            or binding["department_id"] != department_id
            or not (
                workforce_target_valid
                or charity_target_valid
                or venue_target_valid
                or (
                    binding["resource_kind"]
                    == ScopedResourceBinding.ResourceKind.LOGISTICS_MANIFEST
                    and logistics_manifests.get(binding["resource_id"])
                    == (organization_id, edition_id, department_id)
                )
            )
        ):
            continue
        resolved[scope_key] = _seal_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=binding_id,
        )
    return resolved


def _persistable_authority_capability_codes(
    authority: CapabilityGrant | RoleAssignment,
) -> tuple[str, ...]:
    raw_codes = (
        (authority.capability_code,)
        if isinstance(authority, CapabilityGrant)
        else tuple(authority.role_bundle.capability_codes)
    )
    return tuple(
        sorted(
            code
            for code in raw_codes
            if (definition := capability(code)) is not None and definition.persistable
        )
    )


def current_role_assignment_ids(
    *,
    assignment_ids: Collection[UUID],
    at: datetime | None = None,
) -> frozenset[UUID]:
    """Return only current, exact-lineage-valid rows from one bounded ID set.

    This is the public authorization-owned read boundary for another module
    that already resolved its own relationship records. Dormant deployments
    retain compatible term checks. Once exact lineage is selected, every row
    must retain and pass its own pinned issuance; a missing or malformed
    required-exact contract fails closed instead of rebinding to equivalent
    authority.

    Parameters
    ----------
    assignment_ids : Collection[UUID]
        The selected assignment identifiers.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    frozenset[UUID]
        The matching current role assignment ids records in deterministic order.

    Raises
    ------
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    requested_ids = frozenset(assignment_ids)
    if len(requested_ids) > MAX_ROLE_ASSIGNMENT_CURRENTNESS_CHECKS:
        raise ValueError("Too many role assignments for one currentness check.")
    if not requested_ids:
        return frozenset()

    evaluation_time = at or timezone.now()
    if not timezone.is_aware(evaluation_time):
        return frozenset()
    marker_present, exact_lineage_active = _exact_lineage_policy_state()
    if (
        marker_present or settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE
    ) and not exact_lineage_active:
        return frozenset()

    assignments = tuple(
        RoleAssignment.objects.filter(
            _active_at(evaluation_time),
            id__in=requested_ids,
        )
        .select_related("authority_issuance", "role_bundle")
        .order_by("id")
    )
    if not exact_lineage_active:
        return frozenset(assignment.id for assignment in assignments)

    target_cache = _bulk_authority_projection_targets(
        {
            (
                assignment.organization_id,
                assignment.edition_id,
                assignment.department_id,
                assignment.resource_binding_id,
            )
            for assignment in assignments
        }
    )
    pending: list[tuple[UUID, AuthorityIssuanceCurrentCheck]] = []
    for assignment in assignments:
        scope_key = (
            assignment.organization_id,
            assignment.edition_id,
            assignment.department_id,
            assignment.resource_binding_id,
        )
        target = target_cache.get(scope_key)
        capability_codes = _persistable_authority_capability_codes(assignment)
        if target is None or not capability_codes:
            continue
        try:
            issuance_ordinal = assignment.authority_issuance.ordinal
        except ObjectDoesNotExist:
            continue
        pending.append(
            (
                assignment.id,
                AuthorityIssuanceCurrentCheck(
                    issuance_ordinal=issuance_ordinal,
                    principal_id=assignment.principal_id,
                    capability_code=capability_codes[0],
                    target=target,
                    requested_effective_from=evaluation_time,
                    requested_expires_at=None,
                    horizon_mode=ControlHorizonMode.POINT_IN_TIME,
                ),
            )
        )
    if not pending:
        return frozenset()
    results = authority_issuances_are_current(
        checks=tuple(item[1] for item in pending),
        evaluated_at=evaluation_time,
    )
    return frozenset(
        assignment_id
        for (assignment_id, _check), is_current in zip(
            pending,
            results,
            strict=True,
        )
        if is_current
    )


def project_active_authority_scopes(  # noqa: PLR0912
    *,
    principal: Account,
    at: datetime | None = None,
) -> tuple[AuthorizedScopeProjection, ...]:
    """Project current organizer authority without names or existential rebinding.

    This read-only query is the shared boundary for navigation and other
    non-sensitive scope pickers.  It reads the activation contract once,
    resolves each candidate through its persisted tenant chain, and validates
    that candidate row's own pinned issuance exactly once.  Equivalent rows do
    not rescue an invalid candidate; their independently valid capabilities
    are merged only after validation.  Dormant compatibility retains the
    legacy delegated-chain behavior until the external exact-lineage fence is
    selected.  Platform oversight and self-service remain outside this
    organizer-authority projection.

    Parameters
    ----------
    principal : Account
        The authenticated principal whose authority is evaluated.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    tuple[AuthorizedScopeProjection, ...]
        The matching project active authority scopes records in deterministic
        order.
    """
    evaluation_time = at or timezone.now()
    if (
        not timezone.is_aware(evaluation_time)
        or principal.is_platform_administrator
        or not principal.is_active
        or not Account.objects.filter(
            pk=principal.pk,
            account_kind=Account.Kind.PERSON,
            is_active=True,
        ).exists()
    ):
        return ()

    marker_present, exact_lineage_active = _exact_lineage_policy_state()
    if (
        marker_present or settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE
    ) and not exact_lineage_active:
        return ()

    authorities: tuple[CapabilityGrant | RoleAssignment, ...] = (
        *CapabilityGrant.objects.filter(
            _active_at(evaluation_time),
            principal=principal,
        )
        .select_related("authority_issuance", "delegated_from")
        .order_by("id"),
        *RoleAssignment.objects.filter(
            _active_at(evaluation_time),
            principal=principal,
        )
        .select_related("authority_issuance", "role_bundle")
        .order_by("id"),
    )
    scope_keys = {
        (
            authority.organization_id,
            authority.edition_id,
            authority.department_id,
            authority.resource_binding_id,
        )
        for authority in authorities
    }
    target_cache = _bulk_authority_projection_targets(scope_keys)
    projected: dict[
        _AuthorityScopeKey,
        set[str],
    ] = {}
    pending_exact: list[
        tuple[
            _AuthorityScopeKey,
            tuple[str, ...],
            AuthorityIssuanceCurrentCheck,
        ]
    ] = []
    for authority in authorities:
        scope_key = (
            authority.organization_id,
            authority.edition_id,
            authority.department_id,
            authority.resource_binding_id,
        )
        target = target_cache.get(scope_key)
        if target is None:
            continue
        capability_codes = _persistable_authority_capability_codes(authority)
        if not capability_codes:
            continue
        if exact_lineage_active:
            try:
                issuance_ordinal = authority.authority_issuance.ordinal
            except ObjectDoesNotExist:
                continue
            pending_exact.append(
                (
                    scope_key,
                    capability_codes,
                    AuthorityIssuanceCurrentCheck(
                        issuance_ordinal=issuance_ordinal,
                        principal_id=principal.id,
                        capability_code=capability_codes[0],
                        target=target,
                        requested_effective_from=evaluation_time,
                        requested_expires_at=None,
                        horizon_mode=ControlHorizonMode.POINT_IN_TIME,
                    ),
                )
            )
            continue
        if isinstance(authority, CapabilityGrant):
            authority_is_current = grant_chain_is_active(authority, evaluation_time)
        else:
            authority_is_current = True
        if authority_is_current:
            projected.setdefault(scope_key, set()).update(capability_codes)

    if pending_exact:
        exact_results = authority_issuances_are_current(
            checks=tuple(item[2] for item in pending_exact),
            evaluated_at=evaluation_time,
        )
        for (scope_key, capability_codes, _check), is_current in zip(
            pending_exact,
            exact_results,
            strict=True,
        ):
            if is_current:
                projected.setdefault(scope_key, set()).update(capability_codes)

    return tuple(
        AuthorizedScopeProjection(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=resource_binding_id,
            capability_codes=frozenset(projected[scope_key]),
        )
        for scope_key in sorted(
            projected,
            key=lambda values: tuple(
                "" if value is None else str(value) for value in values
            ),
        )
        for organization_id, edition_id, department_id, resource_binding_id in (
            scope_key,
        )
    )


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
    """Evaluate one capability against a trusted, scoped resource target.

    Parameters
    ----------
    principal : Account
        The authenticated principal whose authority is evaluated.
    capability_code : str
        The stable capability code required by the operation.
    resource : ResolvedAuthorizationTarget | None
        The resolved resource target used for scoped authorization.
    requested_fields : frozenset[str] | None, default=None
        The canonical requested fields included in the projection or mutation.
    at : datetime | None, default=None
        Optional evaluation instant; defaults to the current timezone-aware
        time.

    Returns
    -------
    PolicyDecision
        A fail-closed decision containing allowed fields, obligations, and a
        stable reason code.

    Notes
    -----
    Denial is data, not an exception. Unknown capabilities, inactive accounts,
    unsealed targets, invalid authority provenance, and absent grants all
    return a denied decision with no fields. Requested fields can only narrow
    the capability's code-owned field ceiling.
    """
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
    marker_present, exact_lineage_active = _exact_lineage_policy_state()
    if (
        marker_present or settings.REQUIRE_EXACT_AUTHORITY_PROVENANCE
    ) and not exact_lineage_active:
        return PolicyDecision(
            allowed=False,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="authority_provenance_contract_invalid",
        )
    direct_grants = CapabilityGrant.objects.filter(
        _active_at(evaluation_time),
        _scope_filter(resource),
        organization_id=resource.organization_id,
        principal=principal,
        capability_code=capability_code,
    ).select_related("authority_issuance", "delegated_from")
    direct_grant_allowed = (
        any(
            _exact_issuance_allows(
                authority=grant,
                principal=principal,
                capability_code=capability_code,
                resource=resource,
                evaluation_time=evaluation_time,
            )
            for grant in direct_grants
        )
        if exact_lineage_active
        else any(
            grant_chain_is_active(grant, evaluation_time) for grant in direct_grants
        )
    )
    if direct_grant_allowed:
        return PolicyDecision(
            allowed=True,
            fields=permitted_fields,
            obligations=definition.obligations,
            reason_code="direct_grant",
        )

    role_assignments = RoleAssignment.objects.filter(
        _active_at(evaluation_time),
        _scope_filter(resource),
        organization_id=resource.organization_id,
        principal=principal,
        role_bundle__capability_codes__contains=[capability_code],
    ).select_related("authority_issuance", "role_bundle")
    role_assignment_allowed = (
        any(
            _exact_issuance_allows(
                authority=assignment,
                principal=principal,
                capability_code=capability_code,
                resource=resource,
                evaluation_time=evaluation_time,
            )
            for assignment in role_assignments
        )
        if exact_lineage_active
        else role_assignments.exists()
    )
    if role_assignment_allowed:
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
