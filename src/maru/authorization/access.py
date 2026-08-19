"""Computed effective-access summaries and safe read-only access previews.

This module deliberately evaluates the existing authorization lattice.  It does
not create page ACLs, synthetic assignments, alternate sessions, or an
impersonated principal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from maru.authorization.catalog import (
    CAPABILITY_DEFINITIONS,
    ScopeLevel,
    capability,
)
from maru.authorization.models import RoleBundle
from maru.authorization.policy import (
    PolicyDecision,
    ResolvedAuthorizationTarget,
    decide,
)
from maru.identity.models import Account

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

MANAGE_ACCESS_CAPABILITY = "authorization.manage_roles"

_SOURCE_LABELS = {
    "platform_administration": ("platform_oversight", "Platform oversight"),
    "direct_grant": ("direct_grant", "Direct grant"),
    "role_assignment": ("immutable_role", "Assigned immutable role"),
    "self_relationship": ("self_relationship", "Own-record relationship"),
    "permission_absent": ("unavailable", "Not assigned"),
    "account_inactive": ("unavailable", "Account inactive"),
    "target_unavailable": ("unavailable", "Target unavailable"),
    "authority_provenance_contract_invalid": (
        "unavailable",
        "Authority contract unavailable",
    ),
}

_SCOPE_DEPTH = {
    ScopeLevel.ORGANIZATION: 0,
    ScopeLevel.EDITION: 1,
    ScopeLevel.DEPARTMENT: 2,
    ScopeLevel.RESOURCE: 3,
}


@dataclass(frozen=True, slots=True)
class AccessIntent:
    """One code-owned action presented in a contextual access summary.

    Attributes
    ----------
    capability_code
        The stable capability code required by the operation.
    label
        The human-readable label shown to authorized readers.
    requested_fields
        The canonical requested fields included in the projection or mutation.
    """

    capability_code: str
    label: str
    requested_fields: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class EffectiveAccessAction:
    """Describe effective access action.

    Attributes
    ----------
    capability_code
        The stable capability code required by the operation.
    label
        The human-readable label shown to authorized readers.
    allowed
        The allowed retained in this immutable projection.
    permitted_fields
        The canonical permitted fields included in the projection or mutation.
    obligations
        The obligations retained in this immutable projection.
    reason_code
        The stable reason code from the relevant closed catalog.
    source_category
        The source category retained in this immutable projection.
    source_label
        The human-readable source label shown to authorized readers.
    """

    capability_code: str
    label: str
    allowed: bool
    permitted_fields: tuple[str, ...]
    obligations: tuple[str, ...]
    reason_code: str
    source_category: str
    source_label: str


@dataclass(frozen=True, slots=True)
class EffectiveAccessSummary:
    """Describe effective access summary.

    Attributes
    ----------
    scope_level
        The scope level retained in this immutable projection.
    scope_label
        The disclosure-safe label for the resolved authorization scope.
    can_manage_access
        The can manage access retained in this immutable projection.
    actions
        The actions retained in this immutable projection.
    """

    scope_level: str
    scope_label: str
    can_manage_access: bool
    actions: tuple[EffectiveAccessAction, ...]


@dataclass(frozen=True, slots=True)
class PreviewCapability:
    """Describe preview capability.

    Attributes
    ----------
    capability_code
        The stable capability code required by the operation.
    label
        The human-readable label shown to authorized readers.
    description
        The human-readable description shown to authorized readers.
    source_category
        The source category retained in this immutable projection.
    source_label
        The human-readable source label shown to authorized readers.
    obligations
        The obligations retained in this immutable projection.
    visible_fields
        The canonical visible fields included in the projection or mutation.
    data_preview_available
        The data preview available retained in this immutable projection.
    disclosure_limited
        The disclosure limited retained in this immutable projection.
    """

    capability_code: str
    label: str
    description: str
    source_category: str
    source_label: str
    obligations: tuple[str, ...]
    visible_fields: tuple[str, ...]
    data_preview_available: bool
    disclosure_limited: bool


@dataclass(frozen=True, slots=True)
class AccessPreviewResult:
    """Describe access preview result.

    Attributes
    ----------
    mode
        The mode retained in this immutable projection.
    subject_id
        The subject identifier within the requested scope.
    subject_label
        The human-readable subject label shown to authorized readers.
    scope_level
        The scope level retained in this immutable projection.
    evaluated_at
        The timezone-aware timestamp for evaluated.
    capabilities
        The capabilities retained in this immutable projection.
    disclosure_limited_count
        The bounded number of disclosure limited records.
    """

    mode: str
    subject_id: UUID
    subject_label: str
    scope_level: str
    evaluated_at: datetime
    capabilities: tuple[PreviewCapability, ...]
    disclosure_limited_count: int


def _source(reason_code: str) -> tuple[str, str]:
    return _SOURCE_LABELS.get(
        reason_code,
        ("other_authority", "Other code-owned authority"),
    )


def _capability_label(code: str) -> str:
    domain, _, action = code.partition(".")
    return f"{domain.replace('_', ' ').title()} · {action.replace('_', ' ').title()}"


def compute_effective_access(
    *,
    principal: Account,
    target: ResolvedAuthorizationTarget,
    scope_label: str,
    intents: tuple[AccessIntent, ...],
    at: datetime | None = None,
) -> EffectiveAccessSummary:
    """Return compute effective access.

    Parameters
    ----------
    principal : Account
        The authenticated principal whose authority is evaluated.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    scope_label : str
        The disclosure-safe label for the resolved authorization scope.
    intents : tuple[AccessIntent, ...]
        The intents evaluated while compute effective access.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    EffectiveAccessSummary
        The resolved EffectiveAccessSummary for compute effective access.
    """
    evaluation_time = at or timezone.now()
    actions: list[EffectiveAccessAction] = []
    for intent in intents:
        decision = decide(
            principal=principal,
            capability_code=intent.capability_code,
            resource=target,
            requested_fields=intent.requested_fields,
            at=evaluation_time,
        )
        source_category, source_label = _source(decision.reason_code)
        actions.append(
            EffectiveAccessAction(
                capability_code=intent.capability_code,
                label=intent.label,
                allowed=decision.allowed,
                permitted_fields=tuple(sorted(decision.fields)),
                obligations=tuple(sorted(decision.obligations)),
                reason_code=decision.reason_code,
                source_category=source_category,
                source_label=source_label,
            )
        )
    manage_decision = decide(
        principal=principal,
        capability_code=MANAGE_ACCESS_CAPABILITY,
        resource=target,
        at=evaluation_time,
    )
    return EffectiveAccessSummary(
        scope_level=target.scope_level.value,
        scope_label=scope_label,
        can_manage_access=manage_decision.allowed,
        actions=tuple(actions),
    )


def _persisted_active_account(account: Account) -> Account | None:
    return Account.objects.filter(pk=account.pk, is_active=True).first()


def _require_preview_authority(
    *,
    viewer: Account,
    target: ResolvedAuthorizationTarget,
    at: datetime,
) -> Account:
    persisted_viewer = _persisted_active_account(viewer)
    if persisted_viewer is None:
        raise PermissionDenied("Access preview is unavailable.")
    decision = decide(
        principal=persisted_viewer,
        capability_code=MANAGE_ACCESS_CAPABILITY,
        resource=target,
        at=at,
    )
    if not decision.allowed:
        raise PermissionDenied("Access preview is unavailable.")
    return persisted_viewer


def _preview_capability(
    *,
    viewer: Account,
    target: ResolvedAuthorizationTarget,
    capability_code: str,
    subject_decision: PolicyDecision,
    at: datetime,
    source_override: tuple[str, str] | None = None,
) -> PreviewCapability:
    definition = capability(capability_code)
    if definition is None:
        raise ValidationError("The preview contains an unknown capability.")
    viewer_decision = decide(
        principal=viewer,
        capability_code=capability_code,
        resource=target,
        requested_fields=subject_decision.fields,
        at=at,
    )
    visible_fields = (
        tuple(sorted(subject_decision.fields.intersection(viewer_decision.fields)))
        if viewer_decision.allowed
        else ()
    )
    source_category, source_label = source_override or _source(
        subject_decision.reason_code
    )
    return PreviewCapability(
        capability_code=capability_code,
        label=_capability_label(capability_code),
        description=definition.description,
        source_category=source_category,
        source_label=source_label,
        obligations=tuple(sorted(subject_decision.obligations)),
        visible_fields=visible_fields,
        data_preview_available=viewer_decision.allowed,
        disclosure_limited=(
            not viewer_decision.allowed
            or frozenset(visible_fields) != subject_decision.fields
        ),
    )


def preview_exact_person_access(
    *,
    viewer: Account,
    person: Account,
    target: ResolvedAuthorizationTarget,
    at: datetime | None = None,
) -> AccessPreviewResult:
    """Evaluate a real active person without changing the authenticated session.

    Parameters
    ----------
    viewer : Account
        The viewer evaluated while preview exact person access.
    person : Account
        The person whose display-safe projection is requested.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    AccessPreviewResult
        The resolved AccessPreviewResult for preview exact person access.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    evaluation_time = at or timezone.now()
    persisted_viewer = _require_preview_authority(
        viewer=viewer,
        target=target,
        at=evaluation_time,
    )
    persisted_person = Account.objects.filter(
        pk=person.pk,
        is_active=True,
        account_kind=Account.Kind.PERSON,
    ).first()
    if persisted_person is None:
        raise ValidationError("Choose an active person account.")

    capabilities: list[PreviewCapability] = []
    for definition in CAPABILITY_DEFINITIONS:
        subject_decision = decide(
            principal=persisted_person,
            capability_code=definition.code,
            resource=target,
            at=evaluation_time,
        )
        if not subject_decision.allowed:
            continue
        capabilities.append(
            _preview_capability(
                viewer=persisted_viewer,
                target=target,
                capability_code=definition.code,
                subject_decision=subject_decision,
                at=evaluation_time,
            )
        )
    capabilities.sort(key=lambda item: (item.label.casefold(), item.capability_code))
    return AccessPreviewResult(
        mode="person",
        subject_id=persisted_person.id,
        subject_label=persisted_person.display_name or persisted_person.email,
        scope_level=target.scope_level.value,
        evaluated_at=evaluation_time,
        capabilities=tuple(capabilities),
        disclosure_limited_count=sum(
            capability.disclosure_limited for capability in capabilities
        ),
    )


def preview_role_bundle_access(
    *,
    viewer: Account,
    role_bundle: RoleBundle,
    target: ResolvedAuthorizationTarget,
    at: datetime | None = None,
) -> AccessPreviewResult:
    """Evaluate one immutable role version without issuing an assignment.

    Parameters
    ----------
    viewer : Account
        The viewer evaluated while preview role bundle access.
    role_bundle : RoleBundle
        The role bundle evaluated while preview role bundle access.
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.
    at : datetime | None, default=None
        The timezone-aware instant at which to evaluate the decision.

    Returns
    -------
    AccessPreviewResult
        The resolved AccessPreviewResult for preview role bundle access.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    evaluation_time = at or timezone.now()
    persisted_viewer = _require_preview_authority(
        viewer=viewer,
        target=target,
        at=evaluation_time,
    )
    persisted_role = RoleBundle.objects.filter(
        pk=role_bundle.pk,
        organization_id=target.organization_id,
    ).first()
    if persisted_role is None:
        raise ValidationError("Choose an immutable role version in this organizer.")

    capabilities: list[PreviewCapability] = []
    for capability_code in sorted(set(persisted_role.capability_codes)):
        definition = capability(capability_code)
        if definition is None or not definition.persistable:
            raise ValidationError("The role contains an unavailable capability.")
        if _SCOPE_DEPTH[target.scope_level] < _SCOPE_DEPTH[definition.maximum_scope]:
            continue
        hypothetical_decision = PolicyDecision(
            allowed=True,
            fields=definition.field_ceiling,
            obligations=definition.obligations,
            reason_code="hypothetical_role_bundle",
        )
        capabilities.append(
            _preview_capability(
                viewer=persisted_viewer,
                target=target,
                capability_code=capability_code,
                subject_decision=hypothetical_decision,
                at=evaluation_time,
                source_override=("hypothetical_role", "Hypothetical immutable role"),
            )
        )
    capabilities.sort(key=lambda item: (item.label.casefold(), item.capability_code))
    return AccessPreviewResult(
        mode="role",
        subject_id=persisted_role.id,
        subject_label=f"{persisted_role.name} v{persisted_role.version}",
        scope_level=target.scope_level.value,
        evaluated_at=evaluation_time,
        capabilities=tuple(capabilities),
        disclosure_limited_count=sum(
            capability.disclosure_limited for capability in capabilities
        ),
    )
