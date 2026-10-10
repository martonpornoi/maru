"""Closed normalization with no legal, channel or language defaults."""

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict
from datetime import date
from urllib.parse import urlsplit
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .catalog import MAX_BODY, MAX_CHANNELS, MAX_HEADLINE, MAX_VARIANTS
from .contracts import (
    AnnouncementDraftInput,
    AnnouncementSettingsInput,
    AnnouncementVariantInput,
    ManualChannel,
)


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


def channel_code(value: object) -> str:
    """Require a short stable channel key generated or selected by the adapter.

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
    if type(value) is not str or re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", value) is None:
        raise ValidationError("Choose a configured channel.", code="invalid_channel")
    return value


def normalize_settings(value: AnnouncementSettingsInput) -> AnnouncementSettingsInput:
    """Validate explicitly confirmed organizational rules and manual destinations.

    Parameters
    ----------
    value : AnnouncementSettingsInput
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    AnnouncementSettingsInput
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if type(value) is not AnnouncementSettingsInput or value.confirmed is not True:
        raise ValidationError(
            "Confirm the record-keeping rules.", code="rules_unconfirmed"
        )
    if type(value.review_on) is not date:
        raise ValidationError("Enter a review date.", code="invalid_review_date")
    if (
        type(value.channels) is not tuple
        or not 1 <= len(value.channels) <= MAX_CHANNELS
    ):
        raise ValidationError(
            "Set up between one and sixteen channels.", code="invalid_channels"
        )
    channels = []
    for item in value.channels:
        if type(item) is not ManualChannel:
            raise ValidationError(
                "Choose a configured channel.", code="invalid_channel"
            )
        channels.append(
            ManualChannel(
                channel_code(item.code),
                text(item.label, maximum=100),
                safe_url(item.url),
            )
        )
    if len({item.code for item in channels}) != len(channels):
        raise ValidationError(
            "Each channel needs its own name.", code="duplicate_channel"
        )
    url = safe_url(value.policy_url)
    description = text(value.policy_description, maximum=2000, required=False)
    if not url and not description:
        raise ValidationError(
            "Link to or describe the record-keeping rules.", code="rules_missing"
        )
    return AnnouncementSettingsInput(
        policy_name=text(value.policy_name, maximum=200),
        record_owner=text(value.record_owner, maximum=200),
        review_on=value.review_on,
        confirmed=True,
        channels=tuple(sorted(channels, key=lambda item: item.code)),
        policy_url=url,
        policy_description=description,
    )


def normalize_draft(value: AnnouncementDraftInput) -> AnnouncementDraftInput:
    """Normalize the complete proposed copy; scope checks resolve its selections.

    Parameters
    ----------
    value : AnnouncementDraftInput
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    AnnouncementDraftInput
        The complete validated result; failures do not return partial evidence.

    Raises
    ------
    ValidationError
        If scope, input, state or retained evidence fails the owning contract.
    """
    if type(value) is not AnnouncementDraftInput:
        raise ValidationError("Use the announcement form.", code="invalid_draft")
    if (
        type(value.variants) is not tuple
        or not 1 <= len(value.variants) <= MAX_VARIANTS
    ):
        raise ValidationError(
            "Select at least one channel and at most 32 copies.",
            code="invalid_variants",
        )
    variants = []
    for item in value.variants:
        if type(item) is not AnnouncementVariantInput:
            raise ValidationError("Check the channel copy.", code="invalid_variant")
        variants.append(
            AnnouncementVariantInput(
                channel_code(item.channel_code),
                text(item.language_code, maximum=35),
                text(item.headline, maximum=MAX_HEADLINE),
                text(item.body, maximum=MAX_BODY),
            )
        )
    if len({(item.channel_code, item.language_code) for item in variants}) != len(
        variants
    ):
        raise ValidationError(
            "Each channel and language needs one copy.", code="duplicate_variant"
        )
    return AnnouncementDraftInput(
        text(value.headline, maximum=MAX_HEADLINE),
        text(value.body, maximum=MAX_BODY),
        text(value.language_code, maximum=35),
        tuple(
            sorted(variants, key=lambda item: (item.channel_code, item.language_code))
        ),
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


def draft_payload(value: AnnouncementDraftInput) -> dict[str, object]:
    """Return the normalized DTO as a closed serializable intent.

    Parameters
    ----------
    value : AnnouncementDraftInput
        Value to normalize or validate against the closed input contract.

    Returns
    -------
    dict[str, object]
        The complete validated result; failures do not return partial evidence.
    """
    return asdict(value)
