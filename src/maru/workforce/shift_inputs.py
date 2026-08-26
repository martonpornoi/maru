"""Strict normalization for organizer Shift and person commitment commands."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.workforce.models import (
    MAX_SHIFT_BREAK_MINUTES,
    MAX_SHIFT_HEADCOUNT,
    MAX_SHIFT_REST_MINUTES,
)

if TYPE_CHECKING:
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

_WHITESPACE = re.compile(r"\s+")
MAX_SHIFT_TITLE_LENGTH = 160
MAX_SHIFT_LOCATION_LENGTH = 160
MAX_SHIFT_BRIEFING_LENGTH = 1_000
MAX_SHIFT_SUPERVISION_LENGTH = 500
MAX_SHIFT_REASON_LENGTH = 240


def normalize_shift_text(
    value: str,
    *,
    field_name: str,
    maximum_length: int,
    required: bool = True,
) -> str:
    """Return one whitespace-normalized Shift text value.

    Parameters
    ----------
    value : str
        Raw adapter value.
    field_name : str
        Stable field key used for validation errors.
    maximum_length : int
        Maximum normalized character count.
    required : bool, default=True
        Whether an empty normalized value is rejected.

    Returns
    -------
    str
        Normalized plain text.

    Raises
    ------
    ValidationError
        If the value is not text, is empty when required, or is too long.
    """
    if not isinstance(value, str):
        raise ValidationError(
            {field_name: ValidationError("Enter text.", code="shift_text_invalid")}
        )
    normalized = _WHITESPACE.sub(" ", value).strip()
    if required and not normalized:
        raise ValidationError(
            {
                field_name: ValidationError(
                    "This field is required.",
                    code="shift_text_required",
                )
            }
        )
    if len(normalized) > maximum_length:
        raise ValidationError(
            {
                field_name: ValidationError(
                    f"Use at most {maximum_length} characters.",
                    code="shift_text_too_long",
                )
            }
        )
    return normalized


def normalize_shift_reason(value: str) -> str:
    """Return a required, bounded command reason.

    Parameters
    ----------
    value : str
        Raw organizer rationale.

    Returns
    -------
    str
        Whitespace-normalized retained rationale.
    """
    return normalize_shift_text(
        value,
        field_name="reason",
        maximum_length=MAX_SHIFT_REASON_LENGTH,
    )


def normalize_shift_interval(
    *,
    starts_at: datetime,
    ends_at: datetime,
    starts_on: date,
    ends_on: date,
    zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    """Validate a Shift interval and return canonical UTC instants.

    Parameters
    ----------
    starts_at : datetime
        Inclusive aware start instant.
    ends_at : datetime
        Exclusive aware end instant.
    starts_on : date
        First local calendar date of the edition.
    ends_on : date
        Last local calendar date of the edition.
    zone : ZoneInfo
        Canonical edition time zone.

    Returns
    -------
    tuple[datetime, datetime]
        Start and end converted to UTC.

    Raises
    ------
    ValidationError
        If awareness, order, precision, or edition horizon is invalid.
    """
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise ValidationError(
            {"starts_at": ValidationError("Use an aware time.", code="shift_tz")}
        )
    if ends_at.tzinfo is None or ends_at.utcoffset() is None:
        raise ValidationError(
            {"ends_at": ValidationError("Use an aware time.", code="shift_tz")}
        )
    normalized_start = starts_at.astimezone(UTC)
    normalized_end = ends_at.astimezone(UTC)
    if normalized_end <= normalized_start:
        raise ValidationError(
            {
                "ends_at": ValidationError(
                    "The Shift must end after it starts.",
                    code="shift_time_order",
                )
            }
        )
    local_start = normalized_start.astimezone(zone)
    local_end = normalized_end.astimezone(zone)
    if local_start.date() < starts_on or local_end.date() > ends_on:
        raise ValidationError(
            {
                "starts_at": ValidationError(
                    "Keep the Shift within the edition dates.",
                    code="shift_outside_edition",
                )
            }
        )
    return normalized_start, normalized_end


def validate_shift_numbers(
    *,
    required_headcount: int,
    break_minutes: int,
    minimum_rest_minutes: int,
    starts_at: datetime,
    ends_at: datetime,
) -> None:
    """Validate demand capacity, break, and post-shift rest values.

    Parameters
    ----------
    required_headcount : int
        Number of people required for accountable coverage.
    break_minutes : int
        Planned break duration within the Shift.
    minimum_rest_minutes : int
        Minimum blocked rest period after the Shift.
    starts_at : datetime
        Canonical inclusive Shift start.
    ends_at : datetime
        Canonical exclusive Shift end.

    Raises
    ------
    ValidationError
        If a value exceeds the bounded Shift planning contract.
    """
    errors: dict[str, ValidationError] = {}
    if type(required_headcount) is not int or not (
        1 <= required_headcount <= MAX_SHIFT_HEADCOUNT
    ):
        errors["required_headcount"] = ValidationError(
            f"Choose between 1 and {MAX_SHIFT_HEADCOUNT} people.",
            code="shift_headcount_invalid",
        )
    if type(break_minutes) is not int or not (
        0 <= break_minutes <= MAX_SHIFT_BREAK_MINUTES
    ):
        errors["break_minutes"] = ValidationError(
            "Enter a supported break duration.",
            code="shift_break_invalid",
        )
    if type(minimum_rest_minutes) is not int or not (
        0 <= minimum_rest_minutes <= MAX_SHIFT_REST_MINUTES
    ):
        errors["minimum_rest_minutes"] = ValidationError(
            "Enter a supported post-shift rest duration.",
            code="shift_rest_invalid",
        )
    if (
        type(break_minutes) is int
        and break_minutes >= (ends_at - starts_at).total_seconds() / 60
    ):
        errors["break_minutes"] = ValidationError(
            "Break time must be shorter than the Shift.",
            code="shift_break_too_long",
        )
    if errors:
        raise ValidationError(errors)


def shift_command_digest(*, action: str, payload: dict[str, object]) -> str:
    """Return a stable SHA-256 command fingerprint for idempotent retries.

    Parameters
    ----------
    action : str
        Stable command action code.
    payload : dict[str, object]
        Canonical minimized command input.

    Returns
    -------
    str
        Lowercase hexadecimal SHA-256 digest.
    """
    encoded = json.dumps(
        {"action": action, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
