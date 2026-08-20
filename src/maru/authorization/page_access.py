"""Stable page-level access summaries over Maru's scoped authority lattice.

The values in this module are presentation contracts, not page ACLs.  Mutable
summaries point at the existing immutable-role assignment domain; fixed-policy
summaries explain code-owned self, audience, safeguarding, and security rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast
from uuid import UUID

from django.core import signing
from django.core.exceptions import ValidationError
from django.urls import reverse

from maru.authorization.access import (
    AccessIntent,
    EffectiveAccessAction,
    compute_effective_access,
)
from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_department_target,
    resolve_edition_target,
    resolve_organization_target,
    resolve_resource_target,
)
from maru.identity.models import Account

PAGE_ACCESS_CONTRACT_VERSION = "page-access.v1"
PAGE_ACCESS_SIGNING_SALT = "maru.authorization.page-access.v1"
MAX_PAGE_ACCESS_TOKEN_LENGTH = 2_048
DEFAULT_SCOPED_ACCESS_EXPLANATION = (
    "Access is computed from current scoped capabilities, exact Department "
    "scope, and immutable role assignments. This page does not store its "
    "own sharing list."
)

PageAccessPolicy = Literal[
    "scoped",
    "platform",
    "self",
    "public",
    "attendee_audience",
    "representation",
    "safeguarding",
    "security",
    "fixed",
]


@dataclass(frozen=True, slots=True)
class PageAccessSpec:
    """Code-owned description of how one rendered page is governed.

    Attributes
    ----------
    policy
        The closed policy definition governing the requested decision.
    scope_label
        The disclosure-safe label for the resolved authorization scope.
    explanation
        The disclosure-safe explanation presented to the caller.
    target
        The exact domain resource targeted by the operation.
    intents
        The intents retained in this immutable projection.
    audience_labels
        The audience labels retained in this immutable projection.
    mutation_supported
        The mutation supported retained in this immutable projection.
    """

    policy: PageAccessPolicy
    scope_label: str
    explanation: str
    target: ResolvedAuthorizationTarget | None = None
    intents: tuple[AccessIntent, ...] = ()
    audience_labels: tuple[str, ...] = ()
    mutation_supported: bool = False


@dataclass(frozen=True, slots=True)
class PageAccessSummary:
    """Disclosure-safe component context shared by every HTML surface.

    Attributes
    ----------
    available
        The available retained in this immutable projection.
    policy
        The closed policy definition governing the requested decision.
    policy_label
        The human-readable policy label shown to authorized readers.
    scope_label
        The disclosure-safe label for the resolved authorization scope.
    explanation
        The disclosure-safe explanation presented to the caller.
    audience_labels
        The audience labels retained in this immutable projection.
    actions
        The actions retained in this immutable projection.
    can_manage
        The can manage retained in this immutable projection.
    manage_url
        The validated absolute HTTPS manage url.
    preview_url
        The validated absolute HTTPS preview url.
    """

    available: bool
    policy: PageAccessPolicy
    policy_label: str
    scope_label: str
    explanation: str
    audience_labels: tuple[str, ...]
    actions: tuple[EffectiveAccessAction, ...]
    can_manage: bool
    manage_url: str
    preview_url: str


_POLICY_LABELS: dict[PageAccessPolicy, str] = {
    "scoped": "Scoped authority",
    "platform": "Platform authority",
    "self": "Own-record policy",
    "public": "Published audience policy",
    "attendee_audience": "Attendee audience policy",
    "representation": "Representation governance",
    "safeguarding": "Safeguarding policy",
    "security": "Security policy",
    "fixed": "Fixed system policy",
}


def scoped_page_access(
    *,
    target: ResolvedAuthorizationTarget | None,
    scope_label: str,
    intents: tuple[AccessIntent, ...],
    explanation: str = DEFAULT_SCOPED_ACCESS_EXPLANATION,
) -> PageAccessSpec:
    """Describe one mutable organizer target without granting authority.

    Parameters
    ----------
    target : ResolvedAuthorizationTarget | None
        The exact domain resource targeted by the operation.
    scope_label : str
        The disclosure-safe label for the resolved authorization scope.
    intents : tuple[AccessIntent, ...]
        The intents evaluated while scoped page access.
    explanation : str, default=DEFAULT_SCOPED_ACCESS_EXPLANATION
        The disclosure-safe explanation presented to the caller.

    Returns
    -------
    PageAccessSpec
        The resolved PageAccessSpec for scoped page access.
    """
    return PageAccessSpec(
        policy="scoped",
        scope_label=scope_label,
        explanation=explanation,
        target=target,
        intents=intents,
        mutation_supported=target is not None,
    )


def fixed_page_access(
    *,
    policy: PageAccessPolicy,
    scope_label: str,
    explanation: str,
    audience_labels: tuple[str, ...] = (),
) -> PageAccessSpec:
    """Describe a code-owned audience or relationship policy.

    Parameters
    ----------
    policy : PageAccessPolicy
        The closed policy definition governing the requested decision.
    scope_label : str
        The disclosure-safe label for the resolved authorization scope.
    explanation : str
        The disclosure-safe explanation presented to the caller.
    audience_labels : tuple[str, ...], default=()
        The audience labels evaluated while fixed page access.

    Returns
    -------
    PageAccessSpec
        The resolved PageAccessSpec for fixed page access.

    Raises
    ------
    ValueError
        If the supplied value cannot satisfy the documented contract.
    """
    if policy == "scoped":
        raise ValueError("Use scoped_page_access for mutable scoped authority.")
    return PageAccessSpec(
        policy=policy,
        scope_label=scope_label,
        explanation=explanation,
        audience_labels=audience_labels,
        mutation_supported=False,
    )


def unavailable_page_access() -> PageAccessSummary:
    """Return a stable empty value for pages without a resolvable target.

    Returns
    -------
    PageAccessSummary
        The resolved PageAccessSummary for unavailable page access.
    """
    return PageAccessSummary(
        available=False,
        policy="fixed",
        policy_label=_POLICY_LABELS["fixed"],
        scope_label="",
        explanation="",
        audience_labels=(),
        actions=(),
        can_manage=False,
        manage_url="",
        preview_url="",
    )


def build_page_access_summary(
    *,
    principal: object,
    spec: PageAccessSpec,
) -> PageAccessSummary:
    """Build page access summary.

    Parameters
    ----------
    principal : object
        The authenticated principal whose authority is evaluated.
    spec : PageAccessSpec
        The spec evaluated while build page access summary.

    Returns
    -------
    PageAccessSummary
        The resolved PageAccessSummary for build page access summary.
    """
    if spec.policy != "scoped":
        return PageAccessSummary(
            available=True,
            policy=spec.policy,
            policy_label=_POLICY_LABELS[spec.policy],
            scope_label=spec.scope_label,
            explanation=spec.explanation,
            audience_labels=spec.audience_labels,
            actions=(),
            can_manage=False,
            manage_url="",
            preview_url="",
        )
    if not isinstance(principal, Account) or spec.target is None:
        return PageAccessSummary(
            available=True,
            policy="scoped",
            policy_label=_POLICY_LABELS["scoped"],
            scope_label=spec.scope_label,
            explanation=spec.explanation,
            audience_labels=(),
            actions=(),
            can_manage=False,
            manage_url="",
            preview_url="",
        )
    effective = compute_effective_access(
        principal=principal,
        target=spec.target,
        scope_label=spec.scope_label,
        intents=spec.intents,
    )
    can_manage = bool(spec.mutation_supported and effective.can_manage_access)
    workspace_url = ""
    if can_manage:
        workspace_url = reverse(
            "page-access-workspace",
            kwargs={"scope_token": encode_page_access_target(spec.target)},
        )
    return PageAccessSummary(
        available=True,
        policy="scoped",
        policy_label=_POLICY_LABELS["scoped"],
        scope_label=effective.scope_label,
        explanation=spec.explanation,
        audience_labels=(),
        actions=effective.actions,
        can_manage=can_manage,
        manage_url=workspace_url,
        preview_url=f"{workspace_url}#access-preview" if workspace_url else "",
    )


def _target_payload(target: ResolvedAuthorizationTarget) -> dict[str, object]:
    return {
        "contract": PAGE_ACCESS_CONTRACT_VERSION,
        "organization_id": str(target.organization_id),
        "edition_id": str(target.edition_id) if target.edition_id else None,
        "department_id": (str(target.department_id) if target.department_id else None),
        "resource_binding_id": (
            str(target.resource_binding_id) if target.resource_binding_id else None
        ),
    }


def encode_page_access_target(target: ResolvedAuthorizationTarget) -> str:
    """Sign a server-resolved scope for a contextual workspace link.

    Parameters
    ----------
    target : ResolvedAuthorizationTarget
        The exact domain resource targeted by the operation.

    Returns
    -------
    str
        The normalized text for encode page access target.
    """
    return signing.dumps(
        _target_payload(target),
        salt=PAGE_ACCESS_SIGNING_SALT,
        compress=True,
    )


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValidationError("The access target is unavailable.")
    return UUID(value)


def decode_page_access_target(  # noqa: PLR0911
    token: str,
) -> ResolvedAuthorizationTarget | None:
    """Verify, close, and re-resolve a signed target against persisted scope.

    Parameters
    ----------
    token : str
        The untrusted opaque token to authenticate or digest.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The ResolvedAuthorizationTarget | None produced by decode page access
        target.
    """
    if not token or len(token) > MAX_PAGE_ACCESS_TOKEN_LENGTH:
        return None
    try:
        raw = signing.loads(token, salt=PAGE_ACCESS_SIGNING_SALT)
    except signing.BadSignature:
        return None
    if not isinstance(raw, dict) or set(raw) != {
        "contract",
        "organization_id",
        "edition_id",
        "department_id",
        "resource_binding_id",
    }:
        return None
    values = cast("dict[str, Any]", raw)
    if values["contract"] != PAGE_ACCESS_CONTRACT_VERSION:
        return None
    try:
        organization_id = _optional_uuid(values["organization_id"])
        edition_id = _optional_uuid(values["edition_id"])
        department_id = _optional_uuid(values["department_id"])
        resource_binding_id = _optional_uuid(values["resource_binding_id"])
    except (TypeError, ValueError, ValidationError):
        return None
    if organization_id is None:
        return None
    if resource_binding_id is not None:
        if edition_id is None or department_id is None:
            return None
        return resolve_resource_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
            resource_binding_id=resource_binding_id,
        )
    if department_id is not None:
        if edition_id is None:
            return None
        return resolve_department_target(
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
        )
    if edition_id is not None:
        return resolve_edition_target(
            organization_id=organization_id,
            edition_id=edition_id,
        )
    return resolve_organization_target(organization_id=organization_id)
