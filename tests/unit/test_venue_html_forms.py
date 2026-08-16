"""Closed browser-input and edition-local time contracts for Venues."""

from pathlib import Path
from uuid import uuid4

import pytest
from django.http import QueryDict

from maru.core.forms import StrictBase10IntegerField
from maru.venues.forms import (
    AccommodationInventoryForm,
    VenueAvailabilityForm,
    VenueBookingForm,
    VenueBookingStateForm,
    VenueCatalogPathForm,
    VenueLayoutAddForm,
)


@pytest.mark.parametrize("alias", ["+1", "01", " 1", "1 ", "1.0"])
def test_venue_command_versions_reject_noncanonical_integer_aliases(
    alias: str,
) -> None:
    form = VenueBookingStateForm(
        {
            "retry_key": str(uuid4()),
            "expected_version": alias,
            "reason": "Synthetic strict input regression.",
        }
    )

    assert form.is_valid() is False
    assert form.errors.as_data()["expected_version"][0].code == "invalid"


def test_venue_control_numbers_share_the_strict_integer_contract() -> None:
    for field in (
        VenueBookingStateForm.base_fields["expected_version"],
        VenueCatalogPathForm.base_fields["seated_capacity"],
        VenueCatalogPathForm.base_fields["fire_capacity"],
        VenueLayoutAddForm.base_fields["version"],
        AccommodationInventoryForm.base_fields["room_capacity"],
        VenueBookingForm.base_fields["expected_attendance"],
    ):
        assert isinstance(field, StrictBase10IntegerField)


def test_venue_command_form_rejects_duplicate_and_unknown_transport_values() -> None:
    data = QueryDict(mutable=True)
    data.update(
        {
            "retry_key": str(uuid4()),
            "expected_version": "1",
            "reason": "Synthetic strict input regression.",
            "unexpected": "preview principal",
        }
    )
    data.appendlist("expected_version", "1")

    form = VenueBookingStateForm(data)

    assert form.is_valid() is False
    assert {item.code for item in form.non_field_errors().as_data()} == {
        "invalid_input_cardinality"
    }

    unknown_form = VenueBookingStateForm(
        {
            "retry_key": str(uuid4()),
            "expected_version": "1",
            "reason": "Synthetic strict input regression.",
            "unexpected": "preview principal",
        }
    )
    assert unknown_form.is_valid() is False
    assert unknown_form.non_field_errors().as_data()[0].code == ("unknown_input_field")


@pytest.mark.parametrize(
    ("local_value", "expected_code"),
    [
        ("2026-03-29T02:30", "nonexistent"),
        ("2026-10-25T02:30", "ambiguous"),
    ],
)
def test_venue_availability_rejects_dst_gaps_and_folds(
    local_value: str,
    expected_code: str,
) -> None:
    form = VenueAvailabilityForm(
        {
            "retry_key": str(uuid4()),
            "expected_version": "1",
            "intervals_text": f"{local_value}|2026-10-26T12:00|Staff only",
            "reason": "Synthetic edition-zone regression.",
        },
        edition_time_zone="Europe/Budapest",
    )

    assert form.is_valid() is False
    assert form.errors.as_data()["intervals_text"][0].code == expected_code


def test_venue_templates_are_same_shell_and_free_of_mojibake() -> None:
    template_root = (
        Path(__file__).parents[2] / "src" / "maru" / "venues" / "templates" / "venues"
    )

    for template_path in template_root.glob("*.html"):
        source = template_path.read_text(encoding="utf-8")
        assert '{% extends "admin/base_site.html" %}' in source
        assert "\ufffd" not in source
        assert "\u00c2" not in source
        assert "\u00e2" not in source
