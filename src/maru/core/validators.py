"""Reusable validators for stable platform value types."""

import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pycountry
from django.core.exceptions import ValidationError

LOWERCASE_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LANGUAGE_CODE_PATTERN = re.compile(
    r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?$"
)
CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
MAX_EDITION_LANGUAGE_CODES = 16
MAX_EDITION_CURRENCY_CODES = 8


def validate_lowercase_slug(value: str) -> None:
    """Validate lowercase slug.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not LOWERCASE_SLUG_PATTERN.fullmatch(value):
        raise ValidationError(
            "Use lowercase letters, numbers, and single hyphens only.",
            code="invalid_slug",
        )


def validate_time_zone(value: str) -> None:
    """Validate time zone.

    Parameters
    ----------
    value : str
        The untrusted value to normalize against the documented contract.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as error:
        raise ValidationError(
            "Use a valid IANA time-zone identifier.",
            code="invalid_time_zone",
        ) from error


def validate_language_codes(values: list[str]) -> None:
    """Validate language codes.

    Parameters
    ----------
    values : list[str]
        The validated values to process.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not values:
        raise ValidationError(
            "At least one language is required.",
            code="language_required",
        )
    if len(values) != len(set(values)):
        raise ValidationError(
            "Language codes must be unique.",
            code="duplicate_language",
        )
    if len(values) > MAX_EDITION_LANGUAGE_CODES:
        raise ValidationError(
            f"Choose no more than {MAX_EDITION_LANGUAGE_CODES} languages.",
            code="too_many_languages",
        )
    invalid = [value for value in values if not LANGUAGE_CODE_PATTERN.fullmatch(value)]
    if invalid:
        raise ValidationError(
            f"Invalid language code: {invalid[0]}",
            code="invalid_language",
        )


def validate_currency_codes(values: list[str]) -> None:
    """Validate currency codes.

    Parameters
    ----------
    values : list[str]
        The validated values to process.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if not values:
        raise ValidationError(
            "At least one currency is required.",
            code="currency_required",
        )
    if len(values) != len(set(values)):
        raise ValidationError(
            "Currency codes must be unique.",
            code="duplicate_currency",
        )
    if len(values) > MAX_EDITION_CURRENCY_CODES:
        raise ValidationError(
            f"Choose no more than {MAX_EDITION_CURRENCY_CODES} currencies.",
            code="too_many_currencies",
        )
    invalid = [value for value in values if not CURRENCY_CODE_PATTERN.fullmatch(value)]
    if invalid:
        raise ValidationError(
            f"Invalid currency code: {invalid[0]}",
            code="invalid_currency",
        )
    unknown = [
        value for value in values if pycountry.currencies.get(alpha_3=value) is None
    ]
    if unknown:
        raise ValidationError(
            f"Unknown ISO 4217 currency code: {unknown[0]}",
            code="unknown_currency",
        )
