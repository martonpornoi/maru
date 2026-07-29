"""Code-owned locale, country, time-zone, and telephone presentation choices."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo, available_timezones

import phonenumbers
import pycountry
from django.core.exceptions import ValidationError

PINNED_LANGUAGE_CODE = "en"
DEFAULT_PHONE_REGION = "US"

_LANGUAGE_REGIONS: tuple[tuple[str, frozenset[str]], ...] = (
    (
        "Europe",
        frozenset(
            {
                "be",
                "bg",
                "bs",
                "ca",
                "cs",
                "cy",
                "da",
                "de",
                "el",
                "es",
                "et",
                "eu",
                "fi",
                "fo",
                "fr",
                "ga",
                "gd",
                "gl",
                "hr",
                "hu",
                "hy",
                "is",
                "it",
                "lb",
                "lt",
                "lv",
                "mk",
                "mt",
                "nl",
                "no",
                "pl",
                "pt",
                "ro",
                "ru",
                "sk",
                "sl",
                "sq",
                "sr",
                "sv",
                "tr",
                "uk",
            }
        ),
    ),
    (
        "Asia",
        frozenset(
            {
                "ar",
                "az",
                "bn",
                "bo",
                "fa",
                "gu",
                "he",
                "hi",
                "id",
                "ja",
                "ka",
                "kk",
                "km",
                "kn",
                "ko",
                "ku",
                "ky",
                "lo",
                "ml",
                "mn",
                "mr",
                "ms",
                "my",
                "ne",
                "pa",
                "ps",
                "si",
                "ta",
                "te",
                "th",
                "tk",
                "ur",
                "uz",
                "vi",
                "zh",
            }
        ),
    ),
    (
        "Africa",
        frozenset(
            {
                "aa",
                "af",
                "ak",
                "am",
                "bm",
                "ee",
                "ff",
                "ha",
                "ig",
                "kg",
                "ki",
                "lg",
                "ln",
                "mg",
                "ny",
                "om",
                "rw",
                "sn",
                "so",
                "st",
                "sw",
                "ti",
                "tn",
                "ts",
                "wo",
                "xh",
                "yo",
                "zu",
            }
        ),
    ),
    (
        "Americas",
        frozenset(
            {
                "ay",
                "ch",
                "cr",
                "gn",
                "ht",
                "iu",
                "nv",
                "oj",
                "qu",
            }
        ),
    ),
    (
        "Oceania and Pacific",
        frozenset({"bi", "fj", "ho", "mh", "mi", "na", "sm", "to", "ty"}),
    ),
)

_TIME_ZONE_REGIONS = (
    "Africa",
    "America",
    "Antarctica",
    "Arctic",
    "Asia",
    "Atlantic",
    "Australia",
    "Europe",
    "Indian",
    "Pacific",
)


def _flag(region_code: str) -> str:
    return "".join(chr(127397 + ord(character)) for character in region_code)


@lru_cache(maxsize=1)
def language_labels() -> dict[str, str]:
    """Return ISO 639-1 codes with stable English labels."""

    return {
        str(language.alpha_2).lower(): str(language.name)
        for language in pycountry.languages
        if hasattr(language, "alpha_2") and hasattr(language, "name")
    }


@lru_cache(maxsize=1)
def grouped_language_choices() -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Group language suggestions for discovery without changing ISO meaning."""

    labels = language_labels()
    groups: list[tuple[str, tuple[tuple[str, str], ...]]] = [
        (
            "Pinned",
            (
                (
                    PINNED_LANGUAGE_CODE,
                    f"{PINNED_LANGUAGE_CODE} ({labels[PINNED_LANGUAGE_CODE]})",
                ),
            ),
        )
    ]
    assigned = {PINNED_LANGUAGE_CODE}
    for group_label, group_codes in _LANGUAGE_REGIONS:
        choices = tuple(
            (code, f"{code} ({labels[code]})")
            for code in sorted(group_codes, key=lambda item: labels.get(item, item))
            if code in labels and code not in assigned
        )
        groups.append((group_label, choices))
        assigned.update(code for code, _ in choices)
    other = tuple(
        (code, f"{code} ({label})")
        for code, label in sorted(labels.items(), key=lambda item: item[1])
        if code not in assigned
    )
    groups.append(("International and other ISO languages", other))
    return tuple(groups)


def validate_language_code_list(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise ValidationError(
            "Choose at least one default language.",
            code="default_languages_required",
        )
    normalized = [str(code).lower() for code in value]
    if len(normalized) != len(set(normalized)):
        raise ValidationError(
            "Default language codes must be unique.",
            code="duplicate_default_language",
        )
    unknown = sorted(set(normalized) - set(language_labels()))
    if unknown:
        raise ValidationError(
            f"Unknown ISO 639-1 language code: {unknown[0]}.",
            code="unknown_default_language",
        )


def country_choices() -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            str(country.alpha_2),
            f"{country.alpha_2} ({_flag(str(country.alpha_2))} {country.name})",
        )
        for country in sorted(pycountry.countries, key=lambda item: str(item.name))
    )


def validate_country_code(value: str) -> None:
    if value and pycountry.countries.get(alpha_2=value.upper()) is None:
        raise ValidationError(
            "Choose a valid ISO 3166-1 country.",
            code="unknown_country_code",
        )


def _offset_text(seconds: int) -> str:
    sign = "+" if seconds >= 0 else "-"
    absolute = abs(seconds)
    hours, remainder = divmod(absolute, 3_600)
    minutes = remainder // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _time_zone_label(zone_name: str) -> tuple[int, str]:
    zone = ZoneInfo(zone_name)
    year = datetime.now(tz=UTC).year
    offsets = set()
    for month in (1, 7):
        offset = datetime(year, month, 1, tzinfo=UTC).astimezone(zone).utcoffset()
        offsets.add(int(offset.total_seconds()) if offset is not None else 0)
    ordered = sorted(offsets)
    offset_label = " / ".join(_offset_text(value) for value in ordered)
    city = zone_name.rsplit("/", 1)[-1].replace("_", " ")
    return min(ordered), f"({offset_label}) {city} — {zone_name}"


@lru_cache(maxsize=1)
def grouped_time_zone_choices() -> tuple[
    tuple[str, tuple[tuple[str, str], ...]],
    ...,
]:
    groups: list[tuple[str, tuple[tuple[str, str], ...]]] = [
        ("Universal", (("UTC", "(UTC+00:00) Coordinated Universal Time — UTC"),))
    ]
    zones = available_timezones()
    for region in _TIME_ZONE_REGIONS:
        values = []
        for zone_name in zones:
            if not zone_name.startswith(f"{region}/"):
                continue
            offset, label = _time_zone_label(zone_name)
            values.append((offset, label, zone_name))
        groups.append(
            (
                region,
                tuple(
                    (zone_name, label)
                    for _, label, zone_name in sorted(
                        values,
                        key=lambda item: (item[0], item[1]),
                    )
                ),
            )
        )
    return tuple(groups)


@lru_cache(maxsize=1)
def phone_region_choices() -> tuple[tuple[str, str], ...]:
    choices = []
    countries = {
        str(country.alpha_2): str(country.name) for country in pycountry.countries
    }
    for region_code in sorted(phonenumbers.SUPPORTED_REGIONS):
        calling_code = phonenumbers.country_code_for_region(region_code)
        country_name = countries.get(region_code, region_code)
        choices.append(
            (
                region_code,
                (
                    f"{region_code} {_flag(region_code)} (+{calling_code}) "
                    f"— {country_name}"
                ),
            )
        )
    return tuple(choices)


def parse_phone_number(*, region_code: str, national_number: str) -> str:
    try:
        parsed = phonenumbers.parse(national_number, region_code)
    except phonenumbers.NumberParseException as error:
        raise ValidationError(
            "Enter a possible telephone number for the selected country.",
            code="invalid_phone_number",
        ) from error
    if not phonenumbers.is_possible_number(parsed):
        raise ValidationError(
            "Enter a possible telephone number for the selected country.",
            code="invalid_phone_number",
        )
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def split_phone_number(value: str) -> tuple[str, str]:
    if not value:
        return DEFAULT_PHONE_REGION, ""
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException:
        return DEFAULT_PHONE_REGION, value
    region = phonenumbers.region_code_for_number(parsed) or DEFAULT_PHONE_REGION
    national = str(parsed.national_number)
    return region, national
