"""Pure bounded normalization for logistics commands."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Never

from django.core.exceptions import ValidationError
from django.utils.text import slugify

from .models import MAX_LOGISTICS_REASON_LENGTH

MAX_SOURCE_CHANNEL_LENGTH = 32
MAX_LOGISTICS_CODE_LENGTH = 96
SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
LABEL_CODE_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9._:-]{2,95}\Z")


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
    if not isinstance(value, str):
        _field_error(field, "Enter text for this field.", "logistics_text_invalid")
    if any(unicodedata.category(character) == "Cc" for character in value):
        _field_error(
            field,
            "Control characters are not allowed.",
            "logistics_control_character",
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if collapse:
        normalized = " ".join(normalized.split())
    if required and not normalized:
        _field_error(field, "This field is required.", "logistics_value_required")
    if len(normalized) > maximum:
        _field_error(
            field,
            f"Ensure this value has at most {maximum} characters.",
            "logistics_value_too_long",
        )
    return normalized


def normalized_reason(value: str) -> str:
    return normalized_text(
        value,
        field="reason",
        maximum=MAX_LOGISTICS_REASON_LENGTH,
        required=True,
        collapse=True,
    )


def normalized_code(value: str, *, field: str = "code") -> str:
    raw = normalized_text(
        value,
        field=field,
        maximum=240,
        required=True,
        collapse=True,
    )
    result = slugify(raw)[:MAX_LOGISTICS_CODE_LENGTH].strip("-")
    if not result:
        _field_error(field, "Enter a stable code.", "logistics_code_invalid")
    return result


def normalized_label_code(value: str) -> str:
    normalized = normalized_text(
        value,
        field="label_code",
        maximum=MAX_LOGISTICS_CODE_LENGTH,
        required=True,
        collapse=True,
    ).upper()
    if LABEL_CODE_PATTERN.fullmatch(normalized) is None:
        _field_error(
            "label_code",
            "Use a bounded uppercase label code.",
            "logistics_label_code_invalid",
        )
    return normalized


def normalized_source_channel(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_SOURCE_CHANNEL_LENGTH
        or SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        _field_error(
            "source_channel",
            "Use a registered source channel.",
            "logistics_source_channel_invalid",
        )
    return value


def canonical_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
