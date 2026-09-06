"""Minimized event contract for one atomic accepted Programme conversion."""

from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError

PROGRAMME_CONVERSION_COMPLETED_EVENT: Final = (
    "applications.programme_conversion.completed.v1"
)


def validate_programme_conversion_event(payload: dict[str, object]) -> None:
    """Require exactly the two canonical, opaque conversion result identifiers.

    Parameters
    ----------
    payload : dict[str, object]
        Untrusted event payload; private source/content fields are forbidden.

    Raises
    ------
    ValidationError
        If any field, identifier shape, or additional value is invalid.
    """
    valid = set(payload) == {"transition_id", "programme_item_id"}
    if valid:
        for value in payload.values():
            try:
                if not isinstance(value, str) or str(UUID(value)) != value:
                    valid = False
            except ValueError:
                valid = False
    if not valid:
        raise ValidationError(
            "Programme conversion event fields must match the registered schema.",
            code="invalid_domain_event_payload",
        )


__all__ = [
    "PROGRAMME_CONVERSION_COMPLETED_EVENT",
    "validate_programme_conversion_event",
]
