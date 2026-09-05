"""Minimized closed event payloads for dormant Programme review transitions."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError

PROGRAMME_REVIEW_CHANGED_EVENT: Final = "applications.programme_review.changed.v1"
_MAX_VERSION_DIGITS: Final = 19
PROGRAMME_REVIEW_EVENT_ACTIONS: Final = frozenset(
    {
        "policy_created",
        "case_opened",
        "reviewer_assigned",
        "conflict_cleared",
        "reviewer_recused",
        "reviewer_removed",
        "scored",
        "discussed",
        "moderated",
        "stage_advanced",
        "stage_reopened",
        "decided",
        "acknowledged",
    }
)


def validate_programme_review_event(payload: dict[str, object]) -> None:
    """Reject private values, unknown actions, and malformed review identifiers.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted payload supplied to the central event registry.

    Raises
    ------
    ValidationError
        If the payload differs from the complete minimized version-one shape.
    """
    valid = set(payload) == {"action", "aggregate_id", "resulting_version"}
    if valid:
        action = payload["action"]
        aggregate_id = payload["aggregate_id"]
        version = payload["resulting_version"]
        valid = (
            isinstance(action, str)
            and action in PROGRAMME_REVIEW_EVENT_ACTIONS
            and isinstance(aggregate_id, str)
            and isinstance(version, str)
            and version.isascii()
            and version.isdecimal()
            and len(version) <= _MAX_VERSION_DIGITS
            and 0 < int(version) <= 2**63 - 1
            and str(int(version)) == version
        )
        if valid:
            try:
                valid = str(UUID(str(aggregate_id))) == aggregate_id
            except ValueError:
                valid = False
    if not valid:
        raise ValidationError(
            "Programme review event fields must match the registered schema.",
            code="invalid_domain_event_payload",
        )
