"""Pure, bounded normalization for Programme commands."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import StrEnum
from typing import TYPE_CHECKING, Never
from uuid import UUID

from django.core.exceptions import ValidationError

from .catalogs import (
    MAX_PROGRAMME_REASON_LENGTH,
    MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

SOURCE_CHANNEL_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


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
    """Return NFC text after enforcing a field's explicit ceiling.

    Parameters
    ----------
    value : str
        Untrusted text supplied to a Programme command.
    field : str
        Canonical field name used in validation errors.
    maximum : int
        Inclusive character ceiling.
    required : bool, default=False
        Whether an empty normalized value is rejected.
    collapse : bool, default=False
        Whether all whitespace runs are replaced by single spaces.

    Returns
    -------
    str
        Normalized, bounded text.
    """
    if not isinstance(value, str):
        _field_error(field, "Enter text for this field.", "programme_text_invalid")
    if any(unicodedata.category(character) == "Cc" for character in value):
        _field_error(
            field,
            "Control characters are not allowed.",
            "programme_control_character",
        )
    normalized = unicodedata.normalize("NFC", value).strip()
    if collapse:
        normalized = " ".join(normalized.split())
    if required and not normalized:
        _field_error(field, "This field is required.", "programme_value_required")
    if len(normalized) > maximum:
        _field_error(
            field,
            f"Ensure this value has at most {maximum} characters.",
            "programme_value_too_long",
        )
    return normalized


def normalized_reason(value: str) -> str:
    """Return one required, retained Programme command rationale.

    Parameters
    ----------
    value : str
        Untrusted reason supplied to a Programme command.

    Returns
    -------
    str
        NFC-normalized, whitespace-collapsed reason.
    """
    return normalized_text(
        value,
        field="reason",
        maximum=MAX_PROGRAMME_REASON_LENGTH,
        required=True,
        collapse=True,
    )


def normalized_source_channel(value: str) -> str:
    """Return a bounded lower-case registered-channel identifier.

    Parameters
    ----------
    value : str
        Untrusted source-channel identifier.

    Returns
    -------
    str
        The accepted identifier without lossy normalization.
    """
    if (
        not isinstance(value, str)
        or len(value) > MAX_PROGRAMME_SOURCE_CHANNEL_LENGTH
        or SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        _field_error(
            "source_channel",
            "Use a registered lower-case source channel.",
            "programme_source_channel_invalid",
        )
    return value


def normalized_closed_code[ChoiceT: StrEnum](
    value: str | ChoiceT,
    *,
    field: str,
    enum_type: type[ChoiceT],
) -> ChoiceT:
    """Resolve one value from a named closed enum without coercion.

    Parameters
    ----------
    value : str | ChoiceT
        Submitted literal or member of the requested enum.
    field : str
        Canonical field name used in validation errors.
    enum_type : type[ChoiceT]
        Closed enum that owns the accepted literals.

    Returns
    -------
    ChoiceT
        The matching enum member.
    """
    try:
        return enum_type(value)
    except (TypeError, ValueError):
        _field_error(
            field,
            "Choose a supported Programme value.",
            "programme_closed_value_invalid",
        )


def require_uuid(value: UUID, *, field: str) -> UUID:
    """Require an already parsed UUID rather than a free-form identity.

    Parameters
    ----------
    value : UUID
        Candidate typed identity.
    field : str
        Canonical field name used in validation errors.

    Returns
    -------
    UUID
        The accepted UUID.
    """
    if not isinstance(value, UUID):
        _field_error(
            field,
            "Enter a typed UUID for this field.",
            "programme_uuid_invalid",
        )
    return value


def require_expected_version(value: int, *, field: str = "expected_version") -> int:
    """Require a strict non-negative optimistic-concurrency version.

    Parameters
    ----------
    value : int
        Candidate version, where zero represents an absent first aggregate.
    field : str, default='expected_version'
        Canonical field name used in validation errors.

    Returns
    -------
    int
        Accepted non-negative version.
    """
    if type(value) is not int or value < 0:
        _field_error(
            field,
            "Enter a non-negative whole-number version.",
            "programme_version_invalid",
        )
    return value


def require_positive_version(value: int, *, field: str) -> int:
    """Require a strict positive source or evidence version.

    Parameters
    ----------
    value : int
        Candidate positive version.
    field : str
        Canonical field name used in validation errors.

    Returns
    -------
    int
        Accepted positive version.
    """
    if type(value) is not int or value <= 0:
        _field_error(
            field,
            "Enter a positive whole-number version.",
            "programme_positive_version_invalid",
        )
    return value


def canonical_request_json(payload: Mapping[str, object]) -> bytes:
    """Return deterministic UTF-8 JSON for a normalized command payload.

    Parameters
    ----------
    payload : Mapping[str, object]
        Already-normalized command payload.

    Returns
    -------
    bytes
        Canonical JSON bytes.
    """
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def canonical_digest(payload: Mapping[str, object]) -> str:
    """Return a lower-case SHA-256 digest for a normalized payload.

    Parameters
    ----------
    payload : Mapping[str, object]
        Already-normalized command payload.

    Returns
    -------
    str
        Lower-case hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(canonical_request_json(payload)).hexdigest()


def require_sha256(value: str, *, field: str = "request_digest") -> str:
    """Require an exact lower-case hexadecimal SHA-256 digest.

    Parameters
    ----------
    value : str
        Candidate digest.
    field : str, default='request_digest'
        Canonical field name used in validation errors.

    Returns
    -------
    str
        Accepted digest.
    """
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        _field_error(
            field,
            "Use a lower-case SHA-256 digest.",
            "programme_digest_invalid",
        )
    return value


__all__ = [
    "SHA256_PATTERN",
    "SOURCE_CHANNEL_PATTERN",
    "canonical_digest",
    "canonical_request_json",
    "normalized_closed_code",
    "normalized_reason",
    "normalized_source_channel",
    "normalized_text",
    "require_expected_version",
    "require_positive_version",
    "require_sha256",
    "require_uuid",
]
