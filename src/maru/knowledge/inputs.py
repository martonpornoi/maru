"""Closed Guidance normalization with no invented rules or review dates."""

import hashlib
import json
import unicodedata
from dataclasses import asdict
from datetime import date
from urllib.parse import urlsplit
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .catalog import MAX_BODY, MAX_TITLE, PLACEMENTS
from .contracts import GuidanceDraftInput, GuidanceSettingsInput


def identifier(value: object) -> UUID:
    """Require an actual nonzero UUID, never a coercible substitute.

    Parameters
    ----------
    value : object
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    UUID
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if type(value) is not UUID or value.int == 0:
        raise ValidationError("Select a valid record.", code="invalid_identifier")
    return value


def version(value: object, *, initial: bool = False) -> int:
    """Require a bounded optimistic cursor; only initial settings admit zero.

    Parameters
    ----------
    value : object
        Value to normalize or validate against the closed input contract.
    initial : bool, default=False
        Whether the unconfigured settings cursor may be zero.

    Returns
    -------
    int
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if type(value) is not int or not (0 if initial else 1) <= value < 2**63 - 1:
        raise ValidationError("Reload the page before saving.", code="invalid_version")
    return value


def text(value: object, *, maximum: int, required: bool = True) -> str:
    """Normalize plain Unicode text without permitting hidden control characters.

    Parameters
    ----------
    value : object
        Value to normalize or validate against the closed input contract.
    maximum : int
        Inclusive permitted character count.
    required : bool, default=True
        Whether empty normalized text is forbidden.

    Returns
    -------
    str
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if type(value) is not str:
        raise ValidationError("Enter text.", code="invalid_text")
    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n")).strip()
    if (required and not normalized) or len(normalized) > maximum:
        raise ValidationError(
            "Check the required text and its length.", code="invalid_text"
        )
    if any(
        unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\t" for c in normalized
    ):
        raise ValidationError("Remove control characters.", code="invalid_text")
    return normalized


def safe_url(value: object) -> str:
    """Validate an optional public HTTPS reference without requesting its content.

    Parameters
    ----------
    value : object
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    str
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    result = text(value, maximum=2000, required=False)
    if result:
        URLValidator(schemes=["https"])(result)
        parts = urlsplit(result)
        if parts.username or parts.password:
            raise ValidationError(
                "Use a link without login details.", code="invalid_url"
            )
    return result


def normalize_settings(value: GuidanceSettingsInput) -> GuidanceSettingsInput:
    """Validate actual organizational rules without certifying legal sufficiency.

    Parameters
    ----------
    value : GuidanceSettingsInput
        Explicit readable rule confirmation supplied by the authorized organizer.

    Returns
    -------
    GuidanceSettingsInput
        Complete normalized rules with at least one usable reference or explanation.

    Raises
    ------
    ValidationError
        If confirmation, date or required bounded text is missing or invalid.
    """
    if type(value) is not GuidanceSettingsInput or value.confirmed is not True:
        raise ValidationError(
            "Confirm the record-keeping rules.", code="rules_unconfirmed"
        )
    if type(value.review_on) is not date:
        raise ValidationError("Enter a rules review date.", code="invalid_review_date")
    url = safe_url(value.policy_url)
    description = text(value.policy_description, maximum=2000, required=False)
    if not url and not description:
        raise ValidationError("Link to or describe your rules.", code="rules_missing")
    return GuidanceSettingsInput(
        policy_name=text(value.policy_name, maximum=200),
        record_owner=text(value.record_owner, maximum=200),
        review_on=value.review_on,
        confirmed=True,
        policy_url=url,
        policy_description=description,
    )


def normalize_draft(value: GuidanceDraftInput) -> GuidanceDraftInput:
    """Normalize one plain-text draft and its closed, explicitly chosen metadata.

    Parameters
    ----------
    value : GuidanceDraftInput
        Proposed complete version; current edition choices are checked under lock.

    Returns
    -------
    GuidanceDraftInput
        Deterministic normalized intent, retaining an unfinished blank review date.

    Raises
    ------
    ValidationError
        If the DTO, text, date or closed placement collection is malformed.
    """
    if type(value) is not GuidanceDraftInput:
        raise ValidationError("Use the guide form.", code="invalid_draft")
    if value.review_by is not None and type(value.review_by) is not date:
        raise ValidationError("Enter a review date.", code="invalid_review_date")
    if (
        type(value.placements) is not tuple
        or len(value.placements) > len(PLACEMENTS)
        or any(
            type(code) is not str or code not in PLACEMENTS for code in value.placements
        )
        or len(set(value.placements)) != len(value.placements)
    ):
        raise ValidationError(
            "Choose a supported task placement.", code="invalid_placement"
        )
    return GuidanceDraftInput(
        title=text(value.title, maximum=MAX_TITLE),
        body=text(value.body, maximum=MAX_BODY),
        language_code=text(value.language_code, maximum=35),
        review_by=value.review_by,
        placements=tuple(sorted(value.placements)),
    )


def canonical_json(value: object) -> bytes:
    """Encode bounded normalized data deterministically for evidence and downloads.

    Parameters
    ----------
    value : object
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    bytes
        The complete validated result; failures do not return partial evidence.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")


def digest(value: object) -> str:
    """Bind normalized intent without copying its content into audit metadata.

    Parameters
    ----------
    value : object
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    str
        The complete validated result; failures do not return partial evidence.
    """
    return hashlib.sha256(canonical_json(value)).hexdigest()


def draft_payload(value: GuidanceDraftInput) -> dict[str, object]:
    """Return the normalized DTO as a closed serializable intent.

    Parameters
    ----------
    value : GuidanceDraftInput
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    dict[str, object]
        The complete validated result; failures do not return partial evidence.
    """
    return asdict(value)
