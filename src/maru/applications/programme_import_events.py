"""Minimized domain-event contract for dormant Programme import evidence."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError

APPLICATIONS_PROGRAMME_IMPORT_CHANGED_EVENT: Final = (
    "applications.programme_import.changed.v1"
)
APPLICATIONS_PROGRAMME_IMPORT_EVENT_SCHEMA_VERSION: Final = 1
_ACTIONS: Final = frozenset(
    {
        "batch_staged",
        "batch_reassigned",
        "batch_previewed",
        "call_committed",
        "proposal_claimed",
        "batch_discarded",
    }
)
_BATCH_STATES: Final = frozenset({"staged", "discarded"})
_ITEM_STATES: Final = frozenset({"", "staged", "applied", "discarded"})
_MAX_ITEM_VERSION: Final = 2
_FIELDS: Final = frozenset(
    {
        "action",
        "batch_id",
        "batch_state",
        "batch_version",
        "item_id",
        "item_state",
        "item_version",
    }
)


def _uuid_text(value: object, *, optional: bool = False) -> bool:
    if optional and value == "":
        return True
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except (TypeError, ValueError):
        return False
    return value == str(parsed)


def validate_programme_import_changed_payload(payload: dict[str, object]) -> None:
    """Reject values outside the closed, value-minimized event shape.

    Parameters
    ----------
    payload : dict[str, object]
        Candidate event payload containing only aggregate identifiers, states,
        versions, and the closed action.

    Raises
    ------
    ValidationError
        If the mapping has an unknown or missing field, invalid closed value,
        malformed identifier, or inconsistent item absence markers.
    """
    if (
        not isinstance(payload, dict)
        or set(payload) != _FIELDS
        or payload["action"] not in _ACTIONS
        or not _uuid_text(payload["batch_id"])
        or payload["batch_state"] not in _BATCH_STATES
        or type(payload["batch_version"]) is not int
        or payload["batch_version"] < 1
        or not _uuid_text(payload["item_id"], optional=True)
        or payload["item_state"] not in _ITEM_STATES
        or type(payload["item_version"]) is not int
        or not 0 <= payload["item_version"] <= _MAX_ITEM_VERSION
        or ((payload["item_id"] == "") != (payload["item_state"] == ""))
        or ((payload["item_id"] == "") != (payload["item_version"] == 0))
    ):
        raise ValidationError(
            "Programme import event payload is invalid.",
            code="invalid_domain_event_payload",
        )


def programme_import_changed_payload(
    *,
    action: str,
    batch_id: UUID,
    batch_state: str,
    batch_version: int,
    item_id: UUID | None = None,
    item_state: str = "",
    item_version: int = 0,
) -> dict[str, object]:
    """Build one validated event payload without source or personal values.

    Parameters
    ----------
    action : str
        Closed Programme import command action.
    batch_id : UUID
        Exact affected import batch identifier.
    batch_state : str
        Closed resulting batch state.
    batch_version : int
        Resulting optimistic batch version.
    item_id : UUID | None, default=None
        Optional exact affected item identifier.
    item_state : str, default=''
        Closed resulting item state, blank when no item is affected.
    item_version : int, default=0
        Resulting item version, zero when no item is affected.

    Returns
    -------
    dict[str, object]
        Validated minimized domain-event payload.
    """
    payload: dict[str, object] = {
        "action": str(action),
        "batch_id": str(batch_id).lower(),
        "batch_state": str(batch_state),
        "batch_version": batch_version,
        "item_id": "" if item_id is None else str(item_id).lower(),
        "item_state": item_state,
        "item_version": item_version,
    }
    validate_programme_import_changed_payload(payload)
    return payload


__all__ = [
    "APPLICATIONS_PROGRAMME_IMPORT_CHANGED_EVENT",
    "APPLICATIONS_PROGRAMME_IMPORT_EVENT_SCHEMA_VERSION",
    "programme_import_changed_payload",
    "validate_programme_import_changed_payload",
]
