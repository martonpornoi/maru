"""Closed, database-free inputs for the dormant Programme setup command.

Validation is not authority, foundation discovery, profile registration or setup.
The future owning command must independently admit and lock the exact foundation,
compare its snapshot fingerprint, and retain one atomic idempotent result.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum
from typing import Never
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.core.validators import validate_time_zone
from maru.events.models import MAX_EDITION_SPAN_DAYS
from maru.workforce.structure_inputs import normalize_department_name

_FINGERPRINT = re.compile(r"[0-9a-f]{64}", re.ASCII)
_MAX_RAW_TEXT = 4096
_MAX_NAME = 160
_MAX_REASON = 240


class ProgrammeSetupMode(StrEnum):
    """Select exactly which foundation is created or deliberately reused."""

    NEW_FOUNDATION = "new_foundation"
    EXISTING_ORGANIZATION = "existing_organization"
    EXISTING_SERIES = "existing_series"


@dataclass(frozen=True, slots=True)
class ProgrammeSetupInput:
    """Describe one explicit setup intent without granting access or creating data.

    Attributes
    ----------
    mode
        Closed new-foundation, existing-organization or existing-series choice.
    edition_name, department_name
        Required labels for the new edition and first Programme Department.
    starts_on, ends_on
        Inclusive edition dates, not datetime values or inferred service days.
    time_zone
        Explicit IANA edition time zone, also used for a new organization.
    reason
        Bounded accountable setup rationale; never a substitute for approval.
    organization_name, series_name
        Names only for the foundation levels this request creates.
    organization_id, series_id
        Exact reused owner identities; series reuse always binds its organization.
    foundation_fingerprint
        Original owner-produced source snapshot for reuse, not a bearer credential.
        Blank for a new foundation. The command must compare it under owner locks.
    """

    mode: ProgrammeSetupMode
    edition_name: str
    department_name: str
    starts_on: date
    ends_on: date
    time_zone: str
    reason: str
    organization_name: str = ""
    series_name: str = ""
    organization_id: UUID | None = None
    series_id: UUID | None = None
    foundation_fingerprint: str = ""


def _invalid(field: str, message: str, code: str) -> Never:
    raise ValidationError({field: ValidationError(message, code=code)})


def _text(value: str, *, field: str, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str) or len(value) > _MAX_RAW_TEXT:
        _invalid(field, "Enter bounded text.", "programme_setup_text_invalid")
    if any(unicodedata.category(character).startswith("C") for character in value):
        _invalid(
            field, "Control characters are not allowed.", "programme_setup_control"
        )
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if required and not normalized:
        _invalid(field, "Enter a value.", "programme_setup_required")
    if len(normalized) > maximum:
        _invalid(
            field, f"Use at most {maximum} characters.", "programme_setup_too_long"
        )
    return normalized


def _mode(value: ProgrammeSetupMode) -> ProgrammeSetupMode:
    if not isinstance(value, str):
        _invalid("mode", "Choose a setup mode.", "programme_setup_mode_invalid")
    try:
        return ProgrammeSetupMode(value)
    except ValueError as error:
        raise ValidationError(
            {
                "mode": ValidationError(
                    "Choose a setup mode.", code="programme_setup_mode_invalid"
                )
            }
        ) from error


def _foundation_names(
    details: ProgrammeSetupInput, mode: ProgrammeSetupMode
) -> dict[str, str]:
    names = {
        field: _text(
            getattr(details, field), field=field, maximum=_MAX_NAME, required=False
        )
        for field in ("organization_name", "series_name")
    }
    required_names = (
        ("organization_name", "series_name")
        if mode is ProgrammeSetupMode.NEW_FOUNDATION
        else (
            ("series_name",) if mode is ProgrammeSetupMode.EXISTING_ORGANIZATION else ()
        )
    )
    for field, value in names.items():
        if field in required_names and not value:
            _invalid(field, "Enter a name.", "programme_setup_required")
        if field not in required_names and value:
            _invalid(
                field,
                "Do not rename a reused foundation.",
                "programme_setup_unused_field",
            )
    required_ids = (
        ()
        if mode is ProgrammeSetupMode.NEW_FOUNDATION
        else (
            ("organization_id", "series_id")
            if mode is ProgrammeSetupMode.EXISTING_SERIES
            else ("organization_id",)
        )
    )
    for field in ("organization_id", "series_id"):
        value = getattr(details, field)
        if field in required_ids:
            if not isinstance(value, UUID) or value.int == 0:
                _invalid(
                    field,
                    "Choose an exact foundation.",
                    "programme_setup_identity_invalid",
                )
        elif value is not None:
            _invalid(
                field,
                "This mode creates that foundation.",
                "programme_setup_unused_field",
            )
    fingerprint = details.foundation_fingerprint
    if not isinstance(fingerprint, str):
        _invalid(
            "foundation_fingerprint",
            "Reload the foundation.",
            "programme_setup_snapshot_invalid",
        )
    if mode is ProgrammeSetupMode.NEW_FOUNDATION:
        if fingerprint:
            _invalid(
                "foundation_fingerprint",
                "New setup has no reused snapshot.",
                "programme_setup_unused_field",
            )
    elif _FINGERPRINT.fullmatch(fingerprint) is None:
        _invalid(
            "foundation_fingerprint",
            "Reload the foundation.",
            "programme_setup_snapshot_invalid",
        )
    return names


def normalize_programme_setup_input(
    details: ProgrammeSetupInput,
) -> ProgrammeSetupInput:
    """Validate one closed intent, including all mode-inapplicable fields.

    Parameters
    ----------
    details : ProgrammeSetupInput
        Untrusted submitted values. UUIDs and dates must already be typed.

    Returns
    -------
    ProgrammeSetupInput
        A new immutable normalized value with no database or permission lookup.

    Raises
    ------
    ValidationError
        If a value, mode, date interval or reuse binding is invalid or ambiguous.

    Notes
    -----
    No ignored fields may distinguish visually similar requests. An existing-series
    request binds both parent IDs and the original snapshot, never a guessed parent.
    No part of successful validation proves the chosen foundation exists or is safe.
    """
    if not isinstance(details, ProgrammeSetupInput):
        _invalid("setup", "Enter a complete setup request.", "programme_setup_invalid")
    mode = _mode(details.mode)
    for field in ("starts_on", "ends_on"):
        if type(getattr(details, field)) is not date:
            _invalid(field, "Enter a calendar date.", "programme_setup_date_invalid")
    span = (details.ends_on - details.starts_on).days
    if not 0 <= span <= MAX_EDITION_SPAN_DAYS:
        _invalid(
            "ends_on",
            f"Choose an end date within {MAX_EDITION_SPAN_DAYS} days of the start.",
            "programme_setup_date_range",
        )
    zone = _text(details.time_zone, field="time_zone", maximum=100)
    try:
        validate_time_zone(zone)
    except ValidationError as error:
        raise ValidationError({"time_zone": error.error_list}) from error
    names = _foundation_names(details, mode)
    department_name = _text(
        details.department_name, field="department_name", maximum=_MAX_NAME
    )
    try:
        department_name = normalize_department_name(department_name)
    except ValidationError as error:
        raise ValidationError({"department_name": error.messages}) from error
    return replace(
        details,
        mode=mode,
        organization_name=names["organization_name"],
        series_name=names["series_name"],
        edition_name=_text(
            details.edition_name, field="edition_name", maximum=_MAX_NAME
        ),
        department_name=department_name,
        time_zone=zone,
        reason=_text(details.reason, field="reason", maximum=_MAX_REASON),
    )


def programme_setup_request_digest(details: ProgrammeSetupInput) -> str:  # noqa: DOC502 - normalization owns validation errors
    """Bind every normalized setup fact to the exact future profile and intent v1.

    Parameters
    ----------
    details : ProgrammeSetupInput
        Complete request, normalized again before hashing to reject invalid input.

    Returns
    -------
    str
        Lowercase SHA-256 for exact-request comparison, not authority or approval.

    Raises
    ------
    ValidationError
        If the request cannot be normalized under the closed input contract.

    Notes
    -----
    The future receipt separately binds actor and idempotency key. Correlation IDs
    and transport channels are not semantic input and must not prevent recovery.
    No current adoption manifest is changed by this fixed intent discriminator.
    """
    normalized = normalize_programme_setup_input(details)
    payload = {
        "intent": "events.programme-setup@1",
        "profile": ["programme_operations", 1],
        "mode": normalized.mode.value,
        "organization_name": normalized.organization_name,
        "series_name": normalized.series_name,
        "edition_name": normalized.edition_name,
        "department_name": normalized.department_name,
        "organization_id": str(normalized.organization_id)
        if normalized.organization_id
        else None,
        "series_id": str(normalized.series_id) if normalized.series_id else None,
        "foundation_fingerprint": normalized.foundation_fingerprint,
        "starts_on": normalized.starts_on.isoformat(),
        "ends_on": normalized.ends_on.isoformat(),
        "time_zone": normalized.time_zone,
        "reason": normalized.reason,
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
