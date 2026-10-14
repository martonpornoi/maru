"""Content-free Knowledge events carry no reader activity or private text."""

from django.core.exceptions import ValidationError

from .catalog import OPERATIONS


def validate_guidance_changed_payload(payload: dict[str, object]) -> None:
    """Require exactly one closed owner operation without text or person labels.

    Parameters
    ----------
    payload : dict[str, object]
        Minimal committed domain fact submitted to the Effects registry.

    Raises
    ------
    ValidationError
        If extra fields or an unregistered operation are present.
    """
    if (
        type(payload) is not dict
        or set(payload) != {"operation"}
        or type(payload["operation"]) is not str
        or payload["operation"] not in OPERATIONS
    ):
        raise ValidationError(
            "Use a registered Guidance operation.", code="invalid_domain_event_payload"
        )
