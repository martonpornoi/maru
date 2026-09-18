"""Fixed Volunteer meaning and closed own-person Programme starter intents."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from uuid import UUID

from django.core.exceptions import ValidationError

PROGRAMME_STARTER_APPROVAL_DAYS = 7
_MAX_RAW_REASON = 4096
_MAX_REASON = 240


@dataclass(frozen=True, slots=True)
class ProgrammeStarterDefinition:
    """Describe one shared immutable template, never an authority grant.

    Attributes
    ----------
    code, version, name, description
        Original code-owned template identity and readable meaning.
    capability_codes, capacity_codes, default_headcount
        Limited future Position authority, semantic capacity and default count.
    """

    code: str
    version: int
    name: str
    description: str
    capability_codes: tuple[str, ...]
    capacity_codes: tuple[str, ...]
    default_headcount: int

    @property
    def catalog_entry(self) -> str:
        """Return the exact profile pin for this reusable template meaning.

        Returns
        -------
        str
            Literal owner catalog identity, not evidence that an edition adopts it.
        """
        return f"workforce.position-template.{self.code}@{self.version}"

    @property
    def digest(self) -> str:
        """Bind every meaningful immutable definition field.

        Returns
        -------
        str
            Canonical SHA-256 checked independently by native retained evidence.
        """
        return _digest(asdict(self))


PROGRAMME_STARTER_DEFINITION = ProgrammeStarterDefinition(
    code="workforce-volunteer",
    version=1,
    name="Workforce volunteer",
    description=(
        "Contributes to one convention without organizer or attendee authority."
    ),
    capability_codes=("events.view_basic", "workforce.view_structure"),
    capacity_codes=("volunteer",),
    default_headcount=1,
)


@dataclass(frozen=True, slots=True)
class ProgrammeStarterScope:
    """Name the exact adoption context, without resolving or authorizing it.

    Attributes
    ----------
    organization_id, series_id, edition_id
        Original same-owner route chain; commands must resolve and lock it again.
    """

    organization_id: UUID
    series_id: UUID
    edition_id: UUID


@dataclass(frozen=True, slots=True)
class ProgrammeStarterIntent:
    """Propose the fixed starter for a different person's own decision.

    Attributes
    ----------
    approver_id
        Original selected person, not approval, authority or an email lookup.
    reason
        Bounded administrative rationale without unrelated private content.
    """

    approver_id: UUID
    reason: str


class ProgrammeStarterAction(StrEnum):
    """Identify one deliberate terminal action on retained starter intent."""

    APPROVE = "approve"
    DECLINE = "decline"
    CANCEL = "cancel"


def _invalid() -> ValidationError:
    return ValidationError(
        "Use complete bounded Programme starter intent.",
        code="programme_starter_input_invalid",
    )


def _identifier(value: UUID) -> None:
    if not isinstance(value, UUID) or not value.int:
        raise _invalid()


def _scope(scope: ProgrammeStarterScope) -> dict[str, str]:
    if not isinstance(scope, ProgrammeStarterScope):
        raise _invalid()
    for value in (scope.organization_id, scope.series_id, scope.edition_id):
        _identifier(value)
    return {name: str(value) for name, value in asdict(scope).items()}


def _reason(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_RAW_REASON
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise _invalid()
    result = " ".join(unicodedata.normalize("NFC", value).split())
    if not result or len(result) > _MAX_REASON:
        raise _invalid()
    return result


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def normalize_programme_starter_intent(
    details: ProgrammeStarterIntent,
) -> ProgrammeStarterIntent:
    """Validate fixed-starter intent without selecting people or granting access.

    Parameters
    ----------
    details : ProgrammeStarterIntent
        Original named approver and rationale.

    Returns
    -------
    ProgrammeStarterIntent
        Normalized immutable values; no authority or eligibility is implied.

    Raises
    ------
    ValidationError
        For a malformed identity, excessive/control-bearing or empty reason.
    """
    if not isinstance(details, ProgrammeStarterIntent):
        raise ValidationError(
            "Use complete bounded Programme starter intent.",
            code="programme_starter_input_invalid",
        )
    _identifier(details.approver_id)
    return replace(details, reason=_reason(details.reason))


def programme_starter_intent_digest(
    *, scope: ProgrammeStarterScope, details: ProgrammeStarterIntent
) -> str:
    """Bind a retry to exact context, named approver and fixed definition.

    Parameters
    ----------
    scope : ProgrammeStarterScope
        Exact owner/series/edition chain, not a resolved authorization target.
    details : ProgrammeStarterIntent
        Intent normalized again before deriving its retry identity.

    Returns
    -------
    str
        SHA-256; actor/key and current admission are independently enforced later.
    """
    normalized = normalize_programme_starter_intent(details)
    return _digest(
        {
            "contract": "workforce.programme-starter.request@1",
            "scope": _scope(scope),
            "definition": PROGRAMME_STARTER_DEFINITION.digest,
            "approver_id": str(normalized.approver_id),
            "reason": normalized.reason,
        }
    )


def programme_starter_decision_digest(
    *,
    scope: ProgrammeStarterScope,
    request_id: UUID,
    action: ProgrammeStarterAction,
    reason: str,
) -> str:
    """Bind a terminal retry to its original request, exact action and reason.

    Parameters
    ----------
    scope : ProgrammeStarterScope
        Original exact adoption context.
    request_id : UUID
        Retained intent identifier, never a substitute scope or permission.
    action : ProgrammeStarterAction
        Closed terminal action; arbitrary string operations are refused.
    reason : str
        The actual deciding person's bounded rationale.

    Returns
    -------
    str
        Canonical retry digest; no storage or authority changes occur.

    Raises
    ------
    ValidationError
        For malformed identifiers, unsupported action or invalid rationale.
    """
    _identifier(request_id)
    if not isinstance(action, ProgrammeStarterAction):
        raise ValidationError(
            "Use complete bounded Programme starter intent.",
            code="programme_starter_input_invalid",
        )
    return _digest(
        {
            "contract": "workforce.programme-starter.decision@1",
            "scope": _scope(scope),
            "request_id": str(request_id),
            "action": action.value,
            "reason": _reason(reason),
        }
    )


def _validate_context(key: UUID, correlation_id: UUID, source_channel: str) -> None:
    _identifier(key)
    _identifier(correlation_id)
    if (
        not isinstance(source_channel, str)
        or re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", source_channel) is None
    ):
        raise _invalid()
