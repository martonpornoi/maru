"""Content-free event schema; an event never claims external delivery."""

from django.core.exceptions import ValidationError

from .catalog import OPERATIONS


def validate_announcement_changed_payload(payload: dict[str, object]) -> None:
    """Admit only one closed operation, without copy, notes or identities.

    Parameters
    ----------
    payload : dict[str, object]
        Explicit domain value used within the admitted command or query.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if (
        type(payload) is not dict
        or set(payload) != {"operation"}
        or payload["operation"] not in OPERATIONS
    ):
        raise ValidationError(
            "Use a registered announcement operation.",
            code="invalid_domain_event_payload",
        )
