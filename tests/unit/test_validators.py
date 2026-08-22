import pytest
from django.core.exceptions import ValidationError

from maru.core.validators import (
    validate_currency_codes,
    validate_language_codes,
    validate_lowercase_slug,
    validate_time_zone,
)
from maru.participation.models import validate_capacity_code


@pytest.mark.parametrize("value", ["maru", "marucon-2030", "event2"])
def test_lowercase_slug_accepts_stable_values(value: str) -> None:
    validate_lowercase_slug(value)


@pytest.mark.parametrize("value", ["Upper", "two words", "two--hyphens", "-edge"])
def test_lowercase_slug_rejects_ambiguous_values(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_lowercase_slug(value)


def test_time_zone_requires_iana_identifier() -> None:
    validate_time_zone("Europe/Budapest")

    for invalid_value in ("Convention/Local", "../etc/passwd"):
        with pytest.raises(ValidationError, match="IANA"):
            validate_time_zone(invalid_value)


@pytest.mark.parametrize("values", [[], ["en", "en"], ["english"]])
def test_language_codes_reject_empty_duplicate_or_invalid(values: list[str]) -> None:
    with pytest.raises(ValidationError):
        validate_language_codes(values)


def test_language_codes_accept_supported_bcp47_shape() -> None:
    validate_language_codes(["en", "de-AT", "sr-Latn", "zh-Hant-TW"])


@pytest.mark.parametrize("values", [[], ["EUR", "EUR"], ["eur"], ["EURO"]])
def test_currency_codes_reject_empty_duplicate_or_invalid(
    values: list[str],
) -> None:
    with pytest.raises(ValidationError):
        validate_currency_codes(values)


def test_currency_codes_accept_iso_shape() -> None:
    validate_currency_codes(["EUR", "GBP", "HUF"])


@pytest.mark.parametrize("value", ["volunteer", "stage.tech", "dealer-assistant"])
def test_capacity_code_accepts_namespaced_stable_values(value: str) -> None:
    validate_capacity_code(value)


@pytest.mark.parametrize("value", ["Staff", "two words", "_private"])
def test_capacity_code_rejects_display_labels(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_capacity_code(value)
