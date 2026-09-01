"""Minimized events for dormant Programme calls and proposal revisions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, cast
from uuid import UUID

from django.core.exceptions import ValidationError

APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT: Final = (
    "applications.programme_call.changed.v1"
)
APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT: Final = (
    "applications.programme_proposal.changed.v1"
)
APPLICATIONS_PROGRAMME_EVENT_SCHEMA_VERSION: Final = 1

PROGRAMME_CALL_EVENT_FIELDS: Final = frozenset(
    {"action", "call_id", "lifecycle", "resulting_version"}
)
PROGRAMME_PROPOSAL_EVENT_FIELDS: Final = frozenset(
    {"action", "layer", "proposal_id", "state", "resulting_version"}
)

_CALL_ACTION_LIFECYCLES: Final = MappingProxyType(
    {
        "call_created": "draft",
        "call_configured": "draft",
        "call_activated": "active",
        "call_retired": "retired",
        "call_successor_created": "draft",
    }
)
_PROPOSAL_ACTION_STATE_AND_LAYER: Final = MappingProxyType(
    {
        "proposal_started": ("draft", "proposal"),
        "proposal_selection_revised": ("draft", "selection"),
        "proposal_answer_revised": ("draft", "answer"),
        "collaborator_invited": ("draft", "collaboration"),
        "collaborator_accepted": ("draft", "collaboration"),
        "collaborator_declined": ("draft", "collaboration"),
        "collaborator_left": ("draft", "collaboration"),
        "collaborator_removed": ("draft", "collaboration"),
        "collaborator_reinvited": ("draft", "collaboration"),
        "contributor_profile_revised": ("draft", "contributor_profile"),
        "proposal_sealed": ("sealed", "revision"),
        "proposal_reopened": ("draft", "proposal"),
        "revision_acknowledged": ("sealed", "response"),
        "revision_declined": ("sealed", "response"),
        "proposal_submitted": ("submitted", "proposal"),
        "proposal_withdrawn": ("withdrawn", "proposal"),
    }
)


def _require_exact_string_fields(
    payload: dict[str, object],
    *,
    fields: frozenset[str],
) -> None:
    if set(payload) != fields or any(
        not isinstance(payload[field], str) or not payload[field] for field in fields
    ):
        raise ValidationError(
            "Programme application event fields must match the registered schema.",
            code="invalid_domain_event_payload",
        )


def _require_lowercase_uuid(value: object) -> None:
    if not isinstance(value, str):
        raise ValidationError(
            "Programme application event identifiers must be lowercase UUIDs.",
            code="invalid_domain_event_payload",
        )
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValidationError(
            "Programme application event identifiers must be lowercase UUIDs.",
            code="invalid_domain_event_payload",
        ) from error
    if str(parsed) != value:
        raise ValidationError(
            "Programme application event identifiers must be lowercase UUIDs.",
            code="invalid_domain_event_payload",
        )


def _require_positive_version(value: object) -> None:
    if not isinstance(value, str) or not (
        value.isascii() and value.isdecimal() and int(value) >= 1
    ):
        raise ValidationError(
            "Programme application event versions must be positive.",
            code="invalid_domain_event_payload",
        )


def validate_programme_call_changed_payload(payload: dict[str, object]) -> None:
    """Validate one exact content-free Programme call event payload.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted event payload proposed for durable delivery.

    Raises
    ------
    ValidationError
        If the shape, identifier, version, or action transition is invalid.
    """
    _require_exact_string_fields(payload, fields=PROGRAMME_CALL_EVENT_FIELDS)
    _require_lowercase_uuid(payload["call_id"])
    _require_positive_version(payload["resulting_version"])
    if (
        _CALL_ACTION_LIFECYCLES.get(cast("str", payload["action"]))
        != payload["lifecycle"]
    ):
        raise ValidationError(
            "Programme call event values do not match a registered action.",
            code="invalid_domain_event_payload",
        )


def validate_programme_proposal_changed_payload(payload: dict[str, object]) -> None:
    """Validate one exact content-free Programme proposal event payload.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted event payload proposed for durable delivery.

    Raises
    ------
    ValidationError
        If the shape, identifier, version, or action transition is invalid.
    """
    _require_exact_string_fields(payload, fields=PROGRAMME_PROPOSAL_EVENT_FIELDS)
    _require_lowercase_uuid(payload["proposal_id"])
    _require_positive_version(payload["resulting_version"])
    expected = _PROPOSAL_ACTION_STATE_AND_LAYER.get(cast("str", payload["action"]))
    if expected != (payload["state"], payload["layer"]):
        raise ValidationError(
            "Programme proposal event values do not match a registered action.",
            code="invalid_domain_event_payload",
        )


@dataclass(frozen=True, slots=True)
class ProgrammeCallChanged:
    """Freeze one minimized Programme call change before outbox delivery.

    Attributes
    ----------
    action : str
        Registered call-change action.
    call_id : UUID
        Exact changed-call identifier.
    lifecycle : str
        Resulting closed call lifecycle.
    resulting_version : int
        Positive call aggregate version after the change.
    """

    action: str
    call_id: UUID
    lifecycle: str
    resulting_version: int

    def __post_init__(self) -> None:
        """Reject an invalid combination at the typed boundary.

        Raises
        ------
        ValidationError
            If the identifier, version, action, or lifecycle is invalid.
        """
        if not isinstance(self.call_id, UUID) or (
            type(self.resulting_version) is not int or self.resulting_version < 1
        ):
            raise ValidationError(
                "Programme call event input must use typed identity and version.",
                code="invalid_domain_event_payload",
            )
        validate_programme_call_changed_payload(self.as_payload())

    def as_payload(self) -> dict[str, object]:
        """Return a fresh exact version-one call payload.

        Returns
        -------
        dict[str, object]
            The strict identifier-, code-, and version-only payload.
        """
        return {
            "action": self.action,
            "call_id": str(self.call_id).lower(),
            "lifecycle": self.lifecycle,
            "resulting_version": str(self.resulting_version),
        }


@dataclass(frozen=True, slots=True)
class ProgrammeProposalChanged:
    """Freeze one minimized collaborative proposal change for delivery.

    Attributes
    ----------
    action : str
        Registered proposal-change action.
    proposal_id : UUID
        Exact changed-proposal identifier.
    state : str
        Resulting closed proposal state.
    resulting_version : int
        Positive proposal aggregate version after the change.
    """

    action: str
    proposal_id: UUID
    state: str
    resulting_version: int

    def __post_init__(self) -> None:
        """Reject an invalid combination at the typed boundary.

        Raises
        ------
        ValidationError
            If the identifier, version, action, state, or layer is invalid.
        """
        if not isinstance(self.proposal_id, UUID) or (
            type(self.resulting_version) is not int or self.resulting_version < 1
        ):
            raise ValidationError(
                "Programme proposal event input must use typed identity and version.",
                code="invalid_domain_event_payload",
            )
        validate_programme_proposal_changed_payload(self.as_payload())

    def as_payload(self) -> dict[str, object]:
        """Return a fresh exact version-one proposal payload.

        Returns
        -------
        dict[str, object]
            The strict identifier-, code-, and version-only payload.
        """
        layer = _PROPOSAL_ACTION_STATE_AND_LAYER.get(self.action, ("", ""))[1]
        return {
            "action": self.action,
            "layer": layer,
            "proposal_id": str(self.proposal_id).lower(),
            "state": self.state,
            "resulting_version": str(self.resulting_version),
        }


def programme_call_changed_payload(
    *,
    action: str,
    call_id: UUID,
    lifecycle: str,
    resulting_version: int,
) -> dict[str, object]:
    """Build a strict minimized call payload for the registered action.

    Parameters
    ----------
    action : str
        Registered Programme call action.
    call_id : UUID
        Exact changed-call identifier.
    lifecycle : str
        Resulting call lifecycle.
    resulting_version : int
        Positive aggregate version after the change.

    Returns
    -------
    dict[str, object]
        Fresh minimized version-one event payload.
    """
    return ProgrammeCallChanged(
        action=action,
        call_id=call_id,
        lifecycle=lifecycle,
        resulting_version=resulting_version,
    ).as_payload()


def programme_proposal_changed_payload(
    *,
    action: str,
    proposal_id: UUID,
    state: str,
    resulting_version: int,
) -> dict[str, object]:
    """Build a strict minimized proposal payload for the registered action.

    Parameters
    ----------
    action : str
        Registered Programme proposal action.
    proposal_id : UUID
        Exact changed-proposal identifier.
    state : str
        Resulting proposal lifecycle state.
    resulting_version : int
        Positive aggregate version after the change.

    Returns
    -------
    dict[str, object]
        Fresh minimized version-one event payload.
    """
    return ProgrammeProposalChanged(
        action=action,
        proposal_id=proposal_id,
        state=state,
        resulting_version=resulting_version,
    ).as_payload()


__all__ = [
    "APPLICATIONS_PROGRAMME_CALL_CHANGED_EVENT",
    "APPLICATIONS_PROGRAMME_EVENT_SCHEMA_VERSION",
    "APPLICATIONS_PROGRAMME_PROPOSAL_CHANGED_EVENT",
    "PROGRAMME_CALL_EVENT_FIELDS",
    "PROGRAMME_PROPOSAL_EVENT_FIELDS",
    "ProgrammeCallChanged",
    "ProgrammeProposalChanged",
    "programme_call_changed_payload",
    "programme_proposal_changed_payload",
    "validate_programme_call_changed_payload",
    "validate_programme_proposal_changed_payload",
]
