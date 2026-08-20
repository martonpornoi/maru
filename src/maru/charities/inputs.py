"""Pure, bounded normalization for charity commands."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import TYPE_CHECKING, Never

from django.core.exceptions import ValidationError
from django.utils.text import slugify

from .models import MAX_CHARITY_COMMENT_LENGTH, MAX_CHARITY_REASON_LENGTH

if TYPE_CHECKING:
    from collections.abc import Mapping

MAX_SOURCE_CHANNEL_LENGTH = 32
MAX_PARTNER_SLUG_LENGTH = 80
SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")


def _field_error(field: str, message: str, code: str) -> Never:
    raise ValidationError({field: ValidationError(message, code=code)})


def normalized_text(
    value: str,
    *,
    field: str,
    maximum: int,
    required: bool = False,
    collapse: bool = False,
) -> str:
    """Return normalized text.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.
    field : str
        The model or form field whose contract is being evaluated.
    maximum : int
        The inclusive upper bound.
    required : bool, default=False
        Whether the input is required.
    collapse : bool, default=False
        Whether nested results should be collapsed for presentation.

    Returns
    -------
    str
        The normalized text for normalized text.
    """
    if not isinstance(value, str):
        _field_error(field, "Enter text for this field.", "charity_text_invalid")
    if any(unicodedata.category(character) == "Cc" for character in value):
        _field_error(
            field,
            "Control characters are not allowed.",
            "charity_control_character",
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if collapse:
        normalized = " ".join(normalized.split())
    if required and not normalized:
        _field_error(field, "This field is required.", "charity_value_required")
    if len(normalized) > maximum:
        _field_error(
            field,
            f"Ensure this value has at most {maximum} characters.",
            "charity_value_too_long",
        )
    return normalized


def normalized_reason(value: str) -> str:
    """Return normalized reason.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.

    Returns
    -------
    str
        The normalized text for normalized reason.
    """
    return normalized_text(
        value,
        field="reason",
        maximum=MAX_CHARITY_REASON_LENGTH,
        required=True,
        collapse=True,
    )


def normalized_private_comment(value: str) -> str:
    """Return normalized private comment.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.

    Returns
    -------
    str
        The normalized text for normalized private comment.
    """
    return normalized_text(
        value,
        field="private_comment",
        maximum=MAX_CHARITY_COMMENT_LENGTH,
        required=True,
    )


def normalized_slug(value: str, *, fallback: str = "") -> str:
    """Return normalized slug.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.
    fallback : str, default=''
        The disclosure-safe fallback used when no value is available.

    Returns
    -------
    str
        The normalized text for normalized slug.
    """
    raw = normalized_text(
        value or fallback,
        field="slug",
        maximum=240,
        required=True,
        collapse=True,
    )
    result = slugify(raw)[:MAX_PARTNER_SLUG_LENGTH].strip("-")
    if not result:
        _field_error("slug", "Enter a stable slug.", "charity_slug_invalid")
    return result


def normalized_source_channel(value: str) -> str:
    """Return normalized source channel.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.

    Returns
    -------
    str
        The normalized text for normalized source channel.
    """
    if (
        not isinstance(value, str)
        or len(value) > MAX_SOURCE_CHANNEL_LENGTH
        or SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        _field_error(
            "source_channel",
            "Use a registered source channel.",
            "charity_source_channel_invalid",
        )
    return value


def canonical_digest(payload: Mapping[str, object]) -> str:
    """Return canonical digest.

    Parameters
    ----------
    payload : Mapping[str, object]
        The validated payload to process.

    Returns
    -------
    str
        The normalized text for canonical digest.
    """
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
