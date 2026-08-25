"""Pure, bounded input handling for edition workforce-structure commands.

HTML forms, API serializers, and application services must converge on these
helpers before they compare idempotency payloads or persist organizer-entered
values.  Nothing in this module reads or writes the database.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import TYPE_CHECKING, Never

from django.core.exceptions import ValidationError
from django.utils.text import slugify

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

MAX_DEPARTMENT_NAME_LENGTH = 160
MAX_DEPARTMENT_DESCRIPTION_LENGTH = 1_000
MAX_STRUCTURE_REASON_LENGTH = 240
MAX_DEPARTMENT_CODE_LENGTH = 80
MAX_DEPARTMENT_CODE_CANDIDATES = 256
MAX_POSITION_TITLE_LENGTH = 160
MAX_POSITION_DESCRIPTION_LENGTH = 2_000
MAX_OPPORTUNITY_HEADLINE_LENGTH = 200
MAX_OPPORTUNITY_DESCRIPTION_LENGTH = 2_000
MIN_POSITION_HEADCOUNT = 1
MAX_POSITION_HEADCOUNT = 500
MAX_POSITION_CODE_LENGTH = 80
MAX_POSITION_CODE_CANDIDATES = 256
MIN_DEPARTMENT_DISPLAY_ORDER = 0
MAX_DEPARTMENT_DISPLAY_ORDER = 65_535

# JSON Schema-compatible spelling shared by the runtime validators and OpenAPI.
# Do not replace the anchors with Python-only ``\Z``: API consumers need to be
# able to apply this expression without translation.
CANONICAL_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)

_HYPHEN_RUN = re.compile(r"-+")


def _raise_field_error(
    *,
    field_name: str,
    message: str,
    code: str,
) -> Never:
    raise ValidationError(
        {field_name: ValidationError(message, code=code)},
    )


def _nfc_without_control_characters(value: str, *, field_name: str) -> str:
    """Reject controls in the submitted value, then return its NFC form.

    Parameters
    ----------
    value : str
        The untrusted input to normalize, validate, or compare.
    field_name : str
        The canonical field name whose policy or value is requested.

    Returns
    -------
    str
        The normalized text for nfc without control characters.
    """
    if not isinstance(value, str):
        _raise_field_error(
            field_name=field_name,
            message="Enter text for this field.",
            code="structure_text_invalid",
        )
    # This check deliberately precedes trimming and normalization.  A caller
    # must not make a forbidden control character disappear before validation.
    if any(unicodedata.category(character) == "Cc" for character in value):
        _raise_field_error(
            field_name=field_name,
            message="Control characters are not allowed.",
            code="structure_control_character",
        )
    return unicodedata.normalize("NFC", value)


def normalize_department_name(value: str) -> str:
    """Normalize one required Department name to the accepted closed form.

    Parameters
    ----------
    value : str
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for normalize department name.
    """
    normalized = " ".join(
        _nfc_without_control_characters(value, field_name="name").split()
    )
    if not normalized:
        _raise_field_error(
            field_name="name",
            message="Enter a Department name.",
            code="structure_name_required",
        )
    if len(normalized) > MAX_DEPARTMENT_NAME_LENGTH:
        _raise_field_error(
            field_name="name",
            message=(
                "Ensure this value has at most "
                f"{MAX_DEPARTMENT_NAME_LENGTH} characters."
            ),
            code="structure_name_too_long",
        )
    return normalized


def normalize_department_description(value: str) -> str:
    """Normalize optional description Unicode while preserving inner spacing.

    Parameters
    ----------
    value : str
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for normalize department description.
    """
    normalized = _nfc_without_control_characters(
        value,
        field_name="description",
    ).strip()
    if len(normalized) > MAX_DEPARTMENT_DESCRIPTION_LENGTH:
        _raise_field_error(
            field_name="description",
            message=(
                "Ensure this value has at most "
                f"{MAX_DEPARTMENT_DESCRIPTION_LENGTH} characters."
            ),
            code="structure_description_too_long",
        )
    return normalized


def normalize_structure_reason(value: str) -> str:
    """Normalize one required, retained administrative rationale.

    Parameters
    ----------
    value : str
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    str
        The normalized text for normalize structure reason.
    """
    normalized = " ".join(
        _nfc_without_control_characters(value, field_name="reason").split()
    )
    if not normalized:
        _raise_field_error(
            field_name="reason",
            message="Enter a reason for this structure change.",
            code="structure_reason_required",
        )
    if len(normalized) > MAX_STRUCTURE_REASON_LENGTH:
        _raise_field_error(
            field_name="reason",
            message=(
                "Ensure this value has at most "
                f"{MAX_STRUCTURE_REASON_LENGTH} characters."
            ),
            code="structure_reason_too_long",
        )
    return normalized


def _normalize_required_structure_text(
    value: str,
    *,
    field_name: str,
    human_label: str,
    max_length: int,
) -> str:
    normalized = " ".join(
        _nfc_without_control_characters(value, field_name=field_name).split()
    )
    if not normalized:
        _raise_field_error(
            field_name=field_name,
            message=f"Enter {human_label}.",
            code=f"structure_{field_name}_required",
        )
    if len(normalized) > max_length:
        _raise_field_error(
            field_name=field_name,
            message=f"Ensure this value has at most {max_length} characters.",
            code=f"structure_{field_name}_too_long",
        )
    return normalized


def normalize_position_title(value: str) -> str:
    """Normalize one required human-readable Position title.

    Parameters
    ----------
    value : str
        Untrusted title supplied by a browser, API, or service caller.

    Returns
    -------
    str
        NFC-normalized, whitespace-collapsed bounded title.
    """
    return _normalize_required_structure_text(
        value,
        field_name="title",
        human_label="a Position title",
        max_length=MAX_POSITION_TITLE_LENGTH,
    )


def normalize_position_description(value: str) -> str:
    """Normalize one required Position purpose statement.

    Parameters
    ----------
    value : str
        Untrusted purpose and responsibilities text.

    Returns
    -------
    str
        NFC-normalized, whitespace-collapsed bounded description.
    """
    return _normalize_required_structure_text(
        value,
        field_name="description",
        human_label="a Position description",
        max_length=MAX_POSITION_DESCRIPTION_LENGTH,
    )


def normalize_opportunity_headline(value: str) -> str:
    """Normalize one required applicant-facing opportunity headline.

    Parameters
    ----------
    value : str
        Untrusted public recruitment headline.

    Returns
    -------
    str
        NFC-normalized, whitespace-collapsed bounded headline.
    """
    return _normalize_required_structure_text(
        value,
        field_name="headline",
        human_label="an opportunity headline",
        max_length=MAX_OPPORTUNITY_HEADLINE_LENGTH,
    )


def normalize_opportunity_description(value: str) -> str:
    """Normalize one required applicant-facing opportunity description.

    Parameters
    ----------
    value : str
        Untrusted public recruitment description.

    Returns
    -------
    str
        NFC-normalized, whitespace-collapsed bounded description.
    """
    return _normalize_required_structure_text(
        value,
        field_name="description",
        human_label="an opportunity description",
        max_length=MAX_OPPORTUNITY_DESCRIPTION_LENGTH,
    )


def validate_position_headcount(value: int) -> int:
    """Accept only a strict integer within the approved Position range.

    Parameters
    ----------
    value : int
        Untrusted approved-headcount value.

    Returns
    -------
    int
        Strict integer from the configured minimum through maximum.
    """
    if type(value) is not int or not (
        MIN_POSITION_HEADCOUNT <= value <= MAX_POSITION_HEADCOUNT
    ):
        _raise_field_error(
            field_name="headcount",
            message=(
                f"Enter a whole number from {MIN_POSITION_HEADCOUNT} through "
                f"{MAX_POSITION_HEADCOUNT}."
            ),
            code="structure_headcount_invalid",
        )
    return value


def position_code_candidates(template_code: str) -> tuple[str, ...]:
    """Return deterministic code candidates derived from an immutable template.

    Parameters
    ----------
    template_code : str
        Validated immutable Position-template code.

    Returns
    -------
    tuple[str, ...]
        Stable bounded base and suffixed Position-code candidates.
    """
    base = template_code[:MAX_POSITION_CODE_LENGTH].rstrip("-") or "position"
    candidates: list[str] = []
    for attempt in range(1, MAX_POSITION_CODE_CANDIDATES + 1):
        suffix = "" if attempt == 1 else f"-{attempt}"
        stem = base[: MAX_POSITION_CODE_LENGTH - len(suffix)].rstrip("-")
        candidates.append(f"{stem}{suffix}")
    return tuple(candidates)


def generate_position_code(
    template_code: str,
    *,
    existing_codes: Iterable[str] = (),
) -> str:
    """Choose the first unused code derived from a published template code.

    Parameters
    ----------
    template_code : str
        Validated immutable Position-template code.
    existing_codes : Iterable[str], default=()
        Exact-edition Position codes already in use.

    Returns
    -------
    str
        First deterministic candidate not used case-insensitively.

    Raises
    ------
    ValidationError
        If every bounded candidate is already occupied.
    """
    occupied = frozenset(code.casefold() for code in existing_codes)
    for candidate in position_code_candidates(template_code):
        if candidate.casefold() not in occupied:
            return candidate
    raise ValidationError(
        {
            "template_id": ValidationError(
                "This template has reached the Position code limit in this edition.",
                code="structure_position_code_exhausted",
            )
        }
    )


def validate_exact_confirmation(value: str, *, expected: str) -> str:
    """Require byte-for-byte-equivalent text without normalizing either side.

    Parameters
    ----------
    value : str
        The untrusted input to normalize, validate, or compare.
    expected : str
        The expected evaluated while validate exact confirmation.

    Returns
    -------
    str
        The normalized text for validate exact confirmation.
    """
    if not isinstance(value, str) or value != expected:
        _raise_field_error(
            field_name="confirmation_name",
            message="Enter the exact current name to confirm this action.",
            code="structure_confirmation_mismatch",
        )
    return value


def validate_department_display_order(value: int) -> int:
    """Accept only a strict integer in the structure display-order range.

    Parameters
    ----------
    value : int
        The untrusted input to normalize, validate, or compare.

    Returns
    -------
    int
        The resolved int for validate department display order.
    """
    if type(value) is not int or not (
        MIN_DEPARTMENT_DISPLAY_ORDER <= value <= MAX_DEPARTMENT_DISPLAY_ORDER
    ):
        _raise_field_error(
            field_name="display_order",
            message=(
                "Enter a whole number from "
                f"{MIN_DEPARTMENT_DISPLAY_ORDER} through "
                f"{MAX_DEPARTMENT_DISPLAY_ORDER}."
            ),
            code="structure_display_order_invalid",
        )
    return value


def canonical_request_json(payload: Mapping[str, object]) -> bytes:
    """Return deterministic UTF-8 JSON for an already-normalized command.

    Parameters
    ----------
    payload : Mapping[str, object]
        The untrusted payload to validate before domain use.

    Returns
    -------
    bytes
        The canonical byte representation for canonical request json.
    """
    return json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_request_digest(payload: Mapping[str, object]) -> str:
    """Return the lower-case SHA-256 digest of a normalized command payload.

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


def department_code_candidates(name: str) -> tuple[str, ...]:
    """Return the complete deterministic, bounded code-candidate sequence.

    Parameters
    ----------
    name : str
        The human-readable name to normalize or persist.

    Returns
    -------
    tuple[str, ...]
        The matching department code candidates records in deterministic order.
    """
    normalized_name = normalize_department_name(name)
    base = _HYPHEN_RUN.sub(
        "-",
        slugify(normalized_name, allow_unicode=False).replace("_", "-"),
    ).strip("-")
    base = base[:MAX_DEPARTMENT_CODE_LENGTH].rstrip("-") or "department"

    candidates: list[str] = []
    for attempt in range(1, MAX_DEPARTMENT_CODE_CANDIDATES + 1):
        suffix = "" if attempt == 1 else f"-{attempt}"
        stem = base[: MAX_DEPARTMENT_CODE_LENGTH - len(suffix)].rstrip("-")
        candidates.append(f"{stem}{suffix}")
    return tuple(candidates)


def generate_department_code(
    name: str,
    *,
    existing_codes: Iterable[str] = (),
) -> str:
    """Choose the first case-insensitively unused deterministic candidate.

    Parameters
    ----------
    name : str
        The human-readable name to normalize or persist.
    existing_codes : Iterable[str], default=()
        The closed set of existing codes accepted by the domain catalog.

    Returns
    -------
    str
        The normalized text for generate department code.
    """
    occupied = frozenset(code.casefold() for code in existing_codes)
    for candidate in department_code_candidates(name):
        if candidate.casefold() not in occupied:
            return candidate
    _raise_field_error(
        field_name="name",
        message="Maru could not generate an available Department code.",
        code="structure_code_unavailable",
    )
