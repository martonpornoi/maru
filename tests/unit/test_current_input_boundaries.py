"""Current-domain text and local-time contracts without historical database setup."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from django import forms
from django.core.exceptions import ValidationError

from maru.applications.forms import EditionLocalDateTimeField
from maru.logistics.forms import CanonicalLocalDateTimeField
from maru.logistics.inputs import normalized_text as logistics_text
from maru.venues.inputs import normalized_text as venue_text
from maru.workforce.forms import WorkforceEditionLocalDateTimeField


@pytest.mark.parametrize(
    "field_type",
    [
        EditionLocalDateTimeField,
        CanonicalLocalDateTimeField,
        WorkforceEditionLocalDateTimeField,
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        42,
        datetime(2027, 1, 1, tzinfo=UTC),
        "2027-02-30T12:00",
        "2027-01-01T25:00",
        "2027-01-01T12:00Z",
        " 2027-01-01T12:00",
    ],
)
def test_local_time_fields_reject_nonlocal_or_invalid_civil_minutes(
    field_type: type[forms.Field], value: object
) -> None:
    field = field_type(zone_name="Europe/Budapest")
    with pytest.raises(ValidationError) as failure:
        field.clean(value)
    assert failure.value.code == "invalid"


@pytest.mark.parametrize(
    "field_type",
    [
        EditionLocalDateTimeField,
        CanonicalLocalDateTimeField,
        WorkforceEditionLocalDateTimeField,
    ],
)
def test_local_time_fields_preserve_optional_and_edition_zone_semantics(
    field_type: type[forms.Field],
) -> None:
    field = field_type(zone_name="Europe/Budapest", required=False)
    assert field.clean("") is None
    assert field.clean("2027-01-01T12:00").utcoffset() == timedelta(hours=1)
    assert field.clean("2027-07-01T12:00").utcoffset() == timedelta(hours=2)


def test_logistics_time_widget_uses_edition_time_and_retains_invalid_input() -> None:
    field = CanonicalLocalDateTimeField(zone_name="Europe/Budapest")
    assert (
        field.prepare_value(datetime(2027, 1, 1, 12, tzinfo=UTC)) == "2027-01-01T13:00"
    )
    naive = datetime(2027, 1, 1, 12)  # noqa: DTZ001 - widget may redisplay naive input
    assert field.prepare_value(naive) == "2027-01-01T12:00"
    assert field.prepare_value("invalid local input") == "invalid local input"


@pytest.mark.parametrize(
    ("normalizer", "prefix"), [(venue_text, "venue"), (logistics_text, "logistics")]
)
@pytest.mark.parametrize(
    ("value", "suffix"),
    [
        (None, "text_invalid"),
        ("unsafe\x00value", "control_character"),
        (" ", "value_required"),
        ("123456", "value_too_long"),
    ],
)
def test_resource_text_validation_reports_closed_field_errors(
    normalizer: Callable[..., str], prefix: str, value: object, suffix: str
) -> None:
    with pytest.raises(ValidationError) as failure:
        normalizer(value, field="name", maximum=5, required=True)
    assert set(failure.value.error_dict) == {"name"}
    assert failure.value.error_dict["name"][0].code == f"{prefix}_{suffix}"


@pytest.mark.parametrize("normalizer", [venue_text, logistics_text])
def test_resource_text_validation_keeps_normalization_and_exact_bounds(
    normalizer: Callable[..., str],
) -> None:
    assert (
        normalizer(
            "  Cafe\u0301  ", field="name", maximum=4, required=True, collapse=True
        )
        == "Café"
    )
    assert normalizer(" ", field="name", maximum=4, required=False) == ""
