"""Pure, bounded input handling for platform account invitations.

Adapters are responsible for rejecting unknown command fields.  These helpers
give HTML, API, and application-service callers one normalization contract
before uniqueness checks, idempotency comparison, or persistence.  Nothing in
this module reads or writes the database.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from maru.identity.managers import AccountManager

MAX_INVITATION_EMAIL_LENGTH = 254
MAX_INVITATION_LOGIN_HANDLE_LENGTH = 120
MAX_INVITATION_DISPLAY_NAME_LENGTH = 120
MAX_INVITATION_LANGUAGE_CODE_LENGTH = 35
MAX_INVITATION_REASON_LENGTH = 240
MAX_INVITATION_SOURCE_CHANNEL_LENGTH = 40

DEFAULT_INVITATION_LANGUAGE_CODE = "en"
# Maru currently ships only the English interface locale.  Convention and
# attendee language catalogs are deliberately broader and are not UI locales.
SUPPORTED_INVITATION_LANGUAGE_CODES = (DEFAULT_INVITATION_LANGUAGE_CODE,)

INVITATION_SOURCE_CHANNEL_PATTERN = re.compile(
    rf"^[a-z][a-z0-9_-]{{0,{MAX_INVITATION_SOURCE_CHANNEL_LENGTH - 1}}}$"
)

_SECRET_DIGEST_KEYS = frozenset(
    {
        "acceptance_code",
        "authorization",
        "bearer",
        "bearer_token",
        "invitation_secret",
        "invitation_token",
        "password",
        "password1",
        "password2",
        "password_confirmation",
        "raw_token",
    }
)
_FORBIDDEN_UNICODE_CATEGORIES = frozenset({"Cc", "Cf", "Cs"})


def _raise_field_error(
    *,
    field_name: str,
    message: str,
    code: str,
) -> Never:
    raise ValidationError(
        {field_name: ValidationError(message, code=code)},
    )


def _text_without_controls(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        _raise_field_error(
            field_name=field_name,
            message="Enter text for this field.",
            code="invitation_text_invalid",
        )
    if any(
        unicodedata.category(character) in _FORBIDDEN_UNICODE_CATEGORIES
        for character in value
    ):
        _raise_field_error(
            field_name=field_name,
            message="Control and format characters are not allowed.",
            code="invitation_control_character",
        )
    return value


def normalize_invitation_email(value: object) -> str:
    """Return the platform account manager's validated email spelling.

    Parameters
    ----------
    value : object
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for normalize invitation email.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not isinstance(value, str):
        _raise_field_error(
            field_name="email",
            message="Enter a valid email address.",
            code="invitation_email_invalid",
        )
    normalized = AccountManager.normalize_login_email(value)
    if not normalized:
        _raise_field_error(
            field_name="email",
            message="Enter an email address.",
            code="invitation_email_required",
        )
    if len(normalized) > MAX_INVITATION_EMAIL_LENGTH:
        _raise_field_error(
            field_name="email",
            message=(
                "Ensure this value has at most "
                f"{MAX_INVITATION_EMAIL_LENGTH} characters."
            ),
            code="invitation_email_too_long",
        )
    try:
        validate_email(normalized)
    except ValidationError as error:
        raise ValidationError(
            {
                "email": ValidationError(
                    "Enter a valid email address.",
                    code="invitation_email_invalid",
                )
            }
        ) from error
    return normalized


def normalize_invitation_login_handle(value: object | None) -> str | None:
    """Validate an optional handle without silently changing its spelling.

    Parameters
    ----------
    value : object | None
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str | None
        The normalized text for normalize invitation login handle.
    """
    if value is None or value == "":
        return None
    normalized = _text_without_controls(value, field_name="login_handle")
    if normalized != normalized.strip():
        _raise_field_error(
            field_name="login_handle",
            message="Remove leading or trailing whitespace.",
            code="invitation_login_handle_outer_whitespace",
        )
    if len(normalized) > MAX_INVITATION_LOGIN_HANDLE_LENGTH:
        _raise_field_error(
            field_name="login_handle",
            message=(
                "Ensure this value has at most "
                f"{MAX_INVITATION_LOGIN_HANDLE_LENGTH} characters."
            ),
            code="invitation_login_handle_too_long",
        )
    if "@" in normalized:
        _raise_field_error(
            field_name="login_handle",
            message="A login username cannot contain @.",
            code="invitation_login_handle_email_ambiguity",
        )
    return normalized


def invitation_login_handle_comparison_key(value: str) -> str:
    """Return the case-insensitive uniqueness key without changing display text.

    Parameters
    ----------
    value : str
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for invitation login handle comparison key.
    """
    normalized = normalize_invitation_login_handle(value)
    if normalized is None:
        return ""
    return normalized.casefold()


def normalize_invitation_display_name(value: object | None) -> str | None:
    """Normalize an optional human label to NFC and ordinary single spaces.

    Parameters
    ----------
    value : object | None
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str | None
        The normalized text for normalize invitation display name.
    """
    if value is None or value == "":
        return None
    submitted = _text_without_controls(value, field_name="display_name")
    normalized = " ".join(unicodedata.normalize("NFC", submitted).split())
    if not normalized:
        return None
    if len(normalized) > MAX_INVITATION_DISPLAY_NAME_LENGTH:
        _raise_field_error(
            field_name="display_name",
            message=(
                "Ensure this value has at most "
                f"{MAX_INVITATION_DISPLAY_NAME_LENGTH} characters."
            ),
            code="invitation_display_name_too_long",
        )
    return normalized


def normalize_invitation_preferred_language(value: object | None) -> str:
    """Resolve omission to the code-owned default and reject unknown locales.

    Parameters
    ----------
    value : object | None
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for normalize invitation preferred language.
    """
    if value is None or value == "":
        return DEFAULT_INVITATION_LANGUAGE_CODE
    submitted = _text_without_controls(value, field_name="preferred_language")
    normalized = submitted.strip().casefold()
    if len(normalized) > MAX_INVITATION_LANGUAGE_CODE_LENGTH:
        _raise_field_error(
            field_name="preferred_language",
            message=(
                "Ensure this value has at most "
                f"{MAX_INVITATION_LANGUAGE_CODE_LENGTH} characters."
            ),
            code="invitation_preferred_language_too_long",
        )
    if normalized not in SUPPORTED_INVITATION_LANGUAGE_CODES:
        _raise_field_error(
            field_name="preferred_language",
            message="Choose a supported language.",
            code="invitation_preferred_language_unsupported",
        )
    return normalized


def normalize_invitation_reason(value: object) -> str:
    """Normalize the required retained rationale to its canonical form.

    Parameters
    ----------
    value : object
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for normalize invitation reason.
    """
    submitted = _text_without_controls(value, field_name="reason")
    normalized = " ".join(unicodedata.normalize("NFC", submitted).split())
    if not normalized:
        _raise_field_error(
            field_name="reason",
            message="Enter a reason for this invitation.",
            code="invitation_reason_required",
        )
    if len(normalized) > MAX_INVITATION_REASON_LENGTH:
        _raise_field_error(
            field_name="reason",
            message=(
                "Ensure this value has at most "
                f"{MAX_INVITATION_REASON_LENGTH} characters."
            ),
            code="invitation_reason_too_long",
        )
    return normalized


def validate_invitation_expected_version(value: object) -> int:
    """Accept only a real non-negative integer, never a bool coercion.

    Parameters
    ----------
    value : object
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    int
        The resolved int for validate invitation expected version.
    """
    if type(value) is not int or value < 0:
        _raise_field_error(
            field_name="expected_version",
            message="Enter a whole number of 0 or greater.",
            code="invitation_expected_version_invalid",
        )
    return value


def _validate_uuid(value: object, *, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        _raise_field_error(
            field_name=field_name,
            message="Enter a UUID.",
            code=f"invitation_{field_name}_invalid",
        )
    return value


def validate_retry_key(value: object) -> UUID:
    """Require an adapter-parsed UUID idempotency key.

    Parameters
    ----------
    value : object
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    UUID
        The resolved UUID for validate retry key.
    """
    return _validate_uuid(value, field_name="retry_key")


def validate_correlation_id(value: object) -> UUID:
    """Require an adapter- or middleware-parsed UUID correlation identifier.

    Parameters
    ----------
    value : object
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    UUID
        The resolved UUID for validate correlation id.
    """
    return _validate_uuid(value, field_name="correlation_id")


def validate_source_channel(value: object) -> str:
    """Accept only bounded, lower-case evidence channel codes.

    Parameters
    ----------
    value : object
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for validate source channel.
    """
    if (
        not isinstance(value, str)
        or INVITATION_SOURCE_CHANNEL_PATTERN.fullmatch(value) is None
    ):
        _raise_field_error(
            field_name="source_channel",
            message="Enter a supported source-channel code.",
            code="invitation_source_channel_invalid",
        )
    return value


def _is_secret_digest_key(key: str) -> bool:
    comparable = key.casefold().replace("-", "_")
    return comparable in _SECRET_DIGEST_KEYS


def _canonical_json_value(value: object, *, active_containers: set[int]) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in active_containers:
            raise TypeError("Circular mappings are not supported in request digests.")
        active_containers.add(container_id)
        try:
            normalized: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("Request digest object keys must be strings.")
                if _is_secret_digest_key(key):
                    continue
                normalized[key] = _canonical_json_value(
                    item,
                    active_containers=active_containers,
                )
            return normalized
        finally:
            active_containers.remove(container_id)
    if isinstance(value, list):
        container_id = id(value)
        if container_id in active_containers:
            raise TypeError("Circular lists are not supported in request digests.")
        active_containers.add(container_id)
        try:
            return [
                _canonical_json_value(item, active_containers=active_containers)
                for item in value
            ]
        finally:
            active_containers.remove(container_id)
    raise TypeError(f"Unsupported request digest value type: {type(value).__name__}.")


def canonical_request_json(payload: Mapping[str, object]) -> bytes:
    """Return compact, deterministic UTF-8 JSON without bearer secrets.

    Parameters
    ----------
    payload : Mapping[str, object]
        The untrusted payload to validate before domain use.

    Returns
    -------
    bytes
        The canonical byte representation for canonical request json.

    Raises
    ------
    TypeError
        If the caller supplies an object of an unsupported type.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("A request digest payload must be a mapping.")
    normalized = _canonical_json_value(payload, active_containers=set())
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_request_digest(payload: Mapping[str, object]) -> str:
    """Return the lower-case SHA-256 digest of normalized command input.

    Parameters
    ----------
    payload : Mapping[str, object]
        The untrusted payload to validate before domain use.

    Returns
    -------
    str
        The normalized text for canonical request digest.
    """
    return hashlib.sha256(canonical_request_json(payload)).hexdigest()
