"""Closed dormant Programme access intents; validation never grants authority."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_recipes import programme_role_recipe

PROGRAMME_ROLE_APPROVAL_DAYS = 7
_MAX_REASON = 240
_MAX_RAW_REASON = 4096


@dataclass(frozen=True, slots=True)
class ProgrammeRoleScope:
    """Bind intended scope to one future Programme context, without resolving it.

    Attributes
    ----------
    organization_id, programme_edition_id
        Exact owner and adoption context, required even for shared Venue facts.
    level
        Explicit Organization, Edition, Department or typed-resource choice.
    department_id, resource_binding_id, resource_kind
        Required narrower identity chain; all inapplicable facts must be absent.
        A command must independently resolve every value from persisted owner facts.
    """

    organization_id: UUID
    programme_edition_id: UUID
    level: ScopeLevel
    department_id: UUID | None = None
    resource_binding_id: UUID | None = None
    resource_kind: str = ""


@dataclass(frozen=True, slots=True)
class ProgrammeRoleIntent:
    """Describe exactly what the author proposes for another person's own review.

    Attributes
    ----------
    recipe_code, recipe_version
        Exact code-owned definition; arbitrary capability lists are not accepted.
    recipient_id, approver_id
        Distinct named people, not evidence of eligibility or actual approval.
        The command separately requires the author to differ from the approver.
    not_before
        Earliest desired instant, or None for approval-time start. Never backdate.
    expires_at
        Explicit requested end, or unbounded only when current source horizons allow.
    reason
        Required bounded rationale; do not include unrelated private information.
    """

    recipe_code: str
    recipe_version: int
    recipient_id: UUID
    approver_id: UUID
    not_before: datetime | None
    expires_at: datetime | None
    reason: str


class ProgrammeRoleDecision(StrEnum):
    """Name deliberate terminal actions, not an editable status field."""

    APPROVE = "approve"
    DECLINE = "decline"
    CANCEL = "cancel"


def _require_uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValidationError(
            "Use an exact non-empty identifier.",
            code="programme_role_identifier_invalid",
        )


def _instant(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ValidationError(
            "Use a timezone-aware instant.", code="programme_role_instant_invalid"
        )
    try:
        result = value.astimezone(UTC) if value.utcoffset() is not None else None
    except (TypeError, ValueError, OverflowError) as error:
        raise ValidationError(
            "Use a timezone-aware instant.", code="programme_role_instant_invalid"
        ) from error
    if result is None:
        raise ValidationError(
            "Use a timezone-aware instant.", code="programme_role_instant_invalid"
        )
    return result


def _reason(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_RAW_REASON
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValidationError(
            "Enter a bounded plain-text reason.", code="programme_role_reason_invalid"
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized or len(normalized) > _MAX_REASON:
        raise ValidationError(
            "Enter a reason of 1 to 240 characters.",
            code="programme_role_reason_invalid",
        )
    return normalized


def normalize_programme_role_intent(
    details: ProgrammeRoleIntent,
) -> ProgrammeRoleIntent:
    """Normalize closed role intent without authority, profile or database checks.

    Parameters
    ----------
    details : ProgrammeRoleIntent
        Original exact definition, people, interval and rationale.

    Returns
    -------
    ProgrammeRoleIntent
        New immutable normalized intent with canonical UTC instants.

    Raises
    ------
    ValidationError
        For unknown definition, malformed or identical people, naive/invalid times,
        empty interval or invalid reason. Current eligibility, expiry and source
        horizon are deliberately the later owning command's responsibility.
    """
    if not isinstance(details, ProgrammeRoleIntent):
        raise ValidationError(
            "Submit one closed Programme role intent.",
            code="programme_role_intent_invalid",
        )
    if programme_role_recipe(details.recipe_code, details.recipe_version) is None:
        raise ValidationError(
            "Choose an exact supported role definition.",
            code="programme_role_recipe_unavailable",
        )
    _require_uuid(details.recipient_id)
    _require_uuid(details.approver_id)
    if details.recipient_id == details.approver_id:
        raise ValidationError(
            "The recipient cannot approve their own authority.",
            code="programme_role_independence_required",
        )
    start, end = _instant(details.not_before), _instant(details.expires_at)
    if start is not None and end is not None and end <= start:
        raise ValidationError(
            "The requested end must follow the earliest start.",
            code="programme_role_interval_invalid",
        )
    return replace(
        details, not_before=start, expires_at=end, reason=_reason(details.reason)
    )


def programme_role_intent_digest(
    *, scope: ProgrammeRoleScope, details: ProgrammeRoleIntent
) -> str:
    """Bind complete normalized intent and scope, not permission or source proof.

    Parameters
    ----------
    scope : ProgrammeRoleScope
        Exact shape the future owner command must independently resolve and lock.
    details : ProgrammeRoleIntent
        Closed original terms; author and retry key are bound separately by receipt.

    Returns
    -------
    str
        Lowercase canonical SHA-256; correlation, preview labels and approver-session
        state are not part of the original request.

    Raises
    ------
    ValidationError
        For invalid intent, scope/recipe mismatch, missing or inapplicable identities,
        or a resource kind other than the recipe's exact declared binding kind.
    """
    normalized = normalize_programme_role_intent(details)
    recipe = programme_role_recipe(normalized.recipe_code, normalized.recipe_version)
    if (
        not isinstance(scope, ProgrammeRoleScope)
        or recipe is None
        or not isinstance(scope.level, ScopeLevel)
        or scope.level not in recipe.target_scopes
    ):
        raise ValidationError(
            "Choose the exact role scope.", code="programme_role_scope_invalid"
        )
    _require_uuid(scope.organization_id)
    _require_uuid(scope.programme_edition_id)
    if scope.level in {ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE}:
        if scope.department_id is None:
            raise ValidationError(
                "An exact Department is required.", code="programme_role_scope_invalid"
            )
        _require_uuid(scope.department_id)
    elif scope.department_id is not None:
        raise ValidationError(
            "A Department is not applicable.", code="programme_role_scope_invalid"
        )
    if scope.level == ScopeLevel.RESOURCE:
        if (
            scope.resource_binding_id is None
            or scope.resource_kind != recipe.resource_kind
        ):
            raise ValidationError(
                "An exact compatible resource binding is required.",
                code="programme_role_scope_invalid",
            )
        _require_uuid(scope.resource_binding_id)
    elif scope.resource_binding_id is not None or scope.resource_kind != "":
        raise ValidationError(
            "A resource binding is not applicable.", code="programme_role_scope_invalid"
        )
    payload = {
        "contract": "authorization.programme-role-request@1",
        "profile": ["programme_operations", 1],
        "organization_id": str(scope.organization_id),
        "programme_edition_id": str(scope.programme_edition_id),
        "scope": scope.level.value,
        "department_id": str(scope.department_id) if scope.department_id else None,
        "resource_binding_id": str(scope.resource_binding_id)
        if scope.resource_binding_id
        else None,
        "resource_kind": scope.resource_kind,
        "recipe": recipe.catalog_entry,
        "recipe_digest": recipe.digest,
        "recipient_id": str(normalized.recipient_id),
        "approver_id": str(normalized.approver_id),
        "not_before": normalized.not_before.isoformat()
        if normalized.not_before
        else None,
        "expires_at": normalized.expires_at.isoformat()
        if normalized.expires_at
        else None,
        "reason": normalized.reason,
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def programme_role_decision_digest(
    *, request_id: UUID, decision: ProgrammeRoleDecision, reason: str
) -> str:
    """Bind a deliberate terminal action to its original request and rationale.

    Parameters
    ----------
    request_id : UUID
        Exact immutable request, not a user-supplied authority target.
    decision : ProgrammeRoleDecision
        Typed approve, decline or cancel action; the command authorizes actual actor.
    reason : str
        Bounded rationale retained with the terminal result.

    Returns
    -------
    str
        Canonical SHA-256 for exact retry, never approval, cancellation or a grant.

    Raises
    ------
    ValidationError
        For malformed request, unknown/untyped action or invalid rationale.
    """
    _require_uuid(request_id)
    if not isinstance(decision, ProgrammeRoleDecision):
        raise ValidationError(
            "Choose one terminal action.", code="programme_role_decision_invalid"
        )
    payload = {
        "contract": "authorization.programme-role-decision@1",
        "request_id": str(request_id),
        "decision": decision.value,
        "reason": _reason(reason),
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
