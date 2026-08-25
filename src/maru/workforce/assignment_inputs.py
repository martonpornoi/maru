"""Pure bounded inputs shared by assignment forms, serializers, and commands."""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import TYPE_CHECKING, Never

from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.workforce.structure_inputs import canonical_request_digest

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_ASSIGNMENT_REASON_LENGTH = 240


def _raise_reason_error(message: str, *, code: str) -> Never:
    raise ValidationError(
        {"reason": ValidationError(message, code=code)},
    )


def normalize_assignment_reason(value: str) -> str:
    """Return one required NFC-normalized assignment rationale.

    Parameters
    ----------
    value : str
        Untrusted rationale text from an assignment command.

    Returns
    -------
    str
        The normalized, nonblank rationale.

    """
    if not isinstance(value, str):
        _raise_reason_error(
            "Enter text for this field.",
            code="assignment_text_invalid",
        )
    if any(unicodedata.category(character) == "Cc" for character in value):
        _raise_reason_error(
            "Control characters are not allowed.",
            code="assignment_control_character",
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if not normalized:
        _raise_reason_error(
            "Enter a reason for this assignment decision.",
            code="assignment_reason_required",
        )
    if len(normalized) > MAX_ASSIGNMENT_REASON_LENGTH:
        _raise_reason_error(
            f"Ensure this value has at most {MAX_ASSIGNMENT_REASON_LENGTH} characters.",
            code="assignment_reason_too_long",
        )
    return normalized


def validate_assignment_interval(
    *,
    effective_from: datetime,
    expires_at: datetime | None,
) -> None:
    """Require aware ordered assignment boundaries.

    Parameters
    ----------
    effective_from : datetime
        Aware instant at which the responsibility should begin.
    expires_at : datetime | None
        Optional aware instant at which the responsibility should end.

    Raises
    ------
    ValidationError
        If either instant is naive or the ending is not after the start.
    """
    if not isinstance(effective_from, datetime) or timezone.is_naive(effective_from):
        raise ValidationError(
            {"effective_from": "Enter an unambiguous date and time."},
            code="assignment_effective_time_invalid",
        )
    if expires_at is not None and (
        not isinstance(expires_at, datetime) or timezone.is_naive(expires_at)
    ):
        raise ValidationError(
            {"expires_at": "Enter an unambiguous date and time."},
            code="assignment_expiry_time_invalid",
        )
    if expires_at is not None and expires_at <= effective_from:
        raise ValidationError(
            {"expires_at": "Ending must be after the effective time."},
            code="assignment_interval_invalid",
        )


def assignment_command_digest(
    *,
    action: str,
    payload: Mapping[str, object],
) -> str:
    """Return a stable digest that includes the closed command action.

    Parameters
    ----------
    action : str
        Stable assignment command action.
    payload : Mapping[str, object]
        Closed normalized command payload.

    Returns
    -------
    str
        The canonical SHA-256 request digest.
    """
    return canonical_request_digest({"action": action, **payload})
