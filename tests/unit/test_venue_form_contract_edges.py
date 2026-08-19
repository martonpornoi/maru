"""Behavioral edge coverage for the closed Venues browser forms."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.venues.forms import (
    AccommodationInventoryForm,
    AccommodationRoomTypeForm,
    EditionLocalDateTimeField,
    VenueAvailabilityForm,
    VenueBookingForm,
    VenueCombinationForm,
    VenueEditionSelectionForm,
    VenueLayoutAddForm,
    VenuePropertyUpdateForm,
    VenueSpaceSelectionForm,
    inventory_initial,
)
from maru.venues.models import (
    AccommodationRoomType,
    EditionVenueSelection,
    VenueBooking,
    VenueLayoutVersion,
    VenueProperty,
    VenueSpace,
    VenueSpaceCombination,
    VenueSpaceConfiguration,
)
from maru.workforce.models import Department


def _controls(**overrides: str) -> dict[str, str]:
    values = {
        "retry_key": str(uuid4()),
        "reason": "Exercise a bounded venue form contract.",
    }
    values.update(overrides)
    return values


def _space(name: str = "Grand Hall") -> VenueSpace:
    return VenueSpace(id=uuid4(), name=name)


def test_edition_local_datetime_field_handles_shape_zone_and_rendering() -> None:
    field = EditionLocalDateTimeField(
        zone_name="Europe/Budapest",
        required=False,
    )
    parsed = field.clean("2031-08-10T09:30")
    assert parsed is not None
    assert parsed.utcoffset() is not None
    assert field.prepare_value(parsed) == "2031-08-10T09:30"
    naive = datetime(2031, 8, 10, 9, 30, tzinfo=UTC).replace(tzinfo=None)
    assert field.prepare_value(naive) == "2031-08-10T09:30"
    assert field.clean("") is None
    assert field.prepare_value("unchanged") == "unchanged"

    field.set_zone("UTC")
    assert field.clean("2031-08-10T09:30") == datetime(
        2031,
        8,
        10,
        9,
        30,
        tzinfo=UTC,
    )


@pytest.mark.parametrize("value", [1, "2031/08/10 09:30", "2031-02-30T09:30"])
def test_edition_local_datetime_field_rejects_malformed_values(value: object) -> None:
    field = EditionLocalDateTimeField()
    with pytest.raises(ValidationError) as caught:
        field.clean(value)
    assert caught.value.code == "invalid"


def test_property_update_exposes_only_normalized_business_changes() -> None:
    form = VenuePropertyUpdateForm(
        {
            **_controls(expected_version="3"),
            "legal_name": "Synthetic Venue Limited",
            "public_name": "Synthetic Venue",
            "provider_name": "Provider",
            "public_description": "Public copy",
            "internal_notes": "Restricted notes",
            "location_name": "Budapest",
            "postal_address": "1 Synthetic Street",
            "country_code": "HU",
            "website_url": "example.invalid",
            "public_contact": "Public desk",
            "contact_name": "Provider contact",
            "contact_email": "provider@example.invalid",
            "contact_phone": "+3612345678",
            "lifecycle": VenueProperty.Lifecycle.ACTIVE,
        }
    )
    assert form.is_valid(), form.errors
    assert form.changes["website_url"] == "https://example.invalid"
    assert set(form.changes).isdisjoint({"retry_key", "expected_version", "reason"})


def test_combination_requires_two_distinct_selected_spaces() -> None:
    first = _space("First")
    second = _space("Second")
    valid = VenueCombinationForm(
        {
            **_controls(),
            "code": "combined",
            "name": "Combined room",
            "member_space_ids": [str(first.id), str(second.id)],
        },
        spaces=(first, second),
    )
    assert valid.is_valid(), valid.errors
    assert valid.cleaned_data["member_space_ids"] == (first.id, second.id)

    duplicate = VenueCombinationForm(
        {
            **_controls(),
            "code": "combined",
            "name": "Combined room",
            "member_space_ids": [str(first.id), str(first.id)],
        },
        spaces=(first, second),
    )
    assert not duplicate.is_valid()
    assert "at least two distinct" in str(duplicate.errors)


def test_layout_inventory_and_edition_selection_resolve_only_closed_uuid_choices() -> (
    None
):
    space = _space()
    layout = VenueLayoutAddForm(
        {
            **_controls(),
            "space_id": str(space.id),
            "layout_code": "public-floor-plan",
            "version": "1",
            "title": "Public floor plan",
            "visibility": VenueLayoutVersion.Visibility.PUBLIC,
            "source_reference": "storage://synthetic/layout",
            "checksum_sha256": "a" * 64,
            "notes": "Attendee-safe rendition source.",
        },
        spaces=(space,),
    )
    assert layout.is_valid(), layout.errors
    assert layout.cleaned_data["space_id"] == space.id

    room_type = AccommodationRoomType(id=uuid4(), public_name="Accessible double")
    inventory = AccommodationInventoryForm(
        {
            **_controls(expected_version=""),
            "room_type_id": str(room_type.id),
            "night": "2031-08-10",
            "room_capacity": "4",
            "release_at": "2031-08-01T12:00",
            "provider_reference": "block-1",
        },
        room_types=(room_type,),
        edition_time_zone="Europe/Budapest",
    )
    assert inventory.is_valid(), inventory.errors
    assert inventory.cleaned_data["room_type_id"] == room_type.id

    property_record = VenueProperty(id=uuid4(), public_name="Synthetic Venue")
    department = Department(id=uuid4(), name="Venue Operations")
    selection = VenueEditionSelectionForm(
        {
            **_controls(),
            "property_id": str(property_record.id),
            "responsible_department_id": str(department.id),
            "local_name": "Convention venue",
            "public_description_override": "Edition-safe description",
            "public_contact_override": "Convention desk",
            "opening_restrictions": "Published programme hours only",
        },
        properties=(property_record,),
        departments=(department,),
    )
    assert selection.is_valid(), selection.errors
    assert selection.cleaned_data["property_id"] == property_record.id
    assert selection.cleaned_data["responsible_department_id"] == department.id


def test_room_type_requires_ordered_occupancy_bounds() -> None:
    values = {
        **_controls(),
        "code": "accessible-double",
        "public_name": "Accessible double",
        "description": "Synthetic room type",
        "accessible_features": "Step-free route",
        "minimum_occupants": "3",
        "maximum_occupants": "2",
        "provider_reference": "room-type-1",
    }
    form = AccommodationRoomTypeForm(values)
    assert not form.is_valid()
    assert "at least the minimum" in str(form.errors["maximum_occupants"])

    values["maximum_occupants"] = "4"
    valid = AccommodationRoomTypeForm(values)
    assert valid.is_valid(), valid.errors


def _space_selection_dependencies() -> tuple[
    EditionVenueSelection,
    VenueSpace,
    VenueSpaceCombination,
    VenueSpaceConfiguration,
]:
    venue_selection = EditionVenueSelection(id=uuid4(), local_name="Main venue")
    space = _space()
    combination = VenueSpaceCombination(id=uuid4(), name="Combined halls")
    configuration = VenueSpaceConfiguration(
        id=uuid4(),
        space=space,
        name="Theatre",
        version=1,
    )
    return venue_selection, space, combination, configuration


def _space_selection_form(**overrides: str) -> VenueSpaceSelectionForm:
    venue_selection, space, combination, configuration = _space_selection_dependencies()
    values = {
        **_controls(),
        "venue_selection_id": str(venue_selection.id),
        "source_space_id": str(space.id),
        "source_combination_id": "",
        "selected_configuration_id": str(configuration.id),
        "local_name": "Main Stage",
        "override_capacity": "",
        "configuration_name": "",
        "seated_capacity": "",
        "standing_capacity": "",
        "table_capacity": "",
        "fire_capacity": "",
        "public_access_info": "Step-free lobby route",
        "opening_restrictions": "Published events only",
    }
    values.update(overrides)
    return VenueSpaceSelectionForm(
        values,
        venue_selections=(venue_selection,),
        spaces=(space,),
        combinations=(combination,),
        configurations=(configuration,),
    )


def test_space_selection_supports_source_configuration_and_complete_override() -> None:
    source = _space_selection_form()
    assert source.is_valid(), source.errors
    assert source.capacity is None
    assert isinstance(source.cleaned_data["source_space_id"], UUID)
    assert source.cleaned_data["source_combination_id"] is None

    venue_selection, space, combination, configuration = _space_selection_dependencies()
    override = VenueSpaceSelectionForm(
        {
            **_controls(),
            "venue_selection_id": str(venue_selection.id),
            "source_space_id": "",
            "source_combination_id": str(combination.id),
            "selected_configuration_id": "",
            "local_name": "Combined halls",
            "override_capacity": "on",
            "configuration_name": "Convention mode",
            "seated_capacity": "100",
            "standing_capacity": "150",
            "table_capacity": "60",
            "fire_capacity": "180",
            "public_access_info": "",
            "opening_restrictions": "",
        },
        venue_selections=(venue_selection,),
        spaces=(space,),
        combinations=(combination,),
        configurations=(configuration,),
    )
    assert override.is_valid(), override.errors
    assert override.capacity is not None
    assert override.capacity.configuration_name == "Convention mode"
    assert override.capacity.fire_capacity == 180


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_combination_id": "also-selected"},
        {"source_space_id": "", "selected_configuration_id": ""},
        {
            "override_capacity": "on",
            "selected_configuration_id": "",
            "configuration_name": "",
        },
    ],
)
def test_space_selection_rejects_ambiguous_or_incomplete_source(
    overrides: dict[str, str],
) -> None:
    form = _space_selection_form(**overrides)
    assert not form.is_valid()


def test_availability_parses_orders_and_rejects_malformed_windows() -> None:
    form = VenueAvailabilityForm(
        {
            **_controls(expected_version="2"),
            "intervals_text": (
                "2031-08-10T12:00|2031-08-10T14:00\n"
                "2031-08-10T09:00|2031-08-10T11:00|Staff access"
            ),
        },
        edition_time_zone="Europe/Budapest",
    )
    assert form.is_valid(), form.errors
    assert len(form.intervals) == 2
    assert form.intervals[0].opening_restriction == ""
    assert form.intervals[1].opening_restriction == "Staff access"

    malformed = VenueAvailabilityForm(
        {**_controls(expected_version="2"), "intervals_text": "one"},
        edition_time_zone="UTC",
    )
    assert not malformed.is_valid()
    assert malformed.errors.as_data()["intervals_text"][0].code == "invalid_interval"

    reversed_window = VenueAvailabilityForm(
        {
            **_controls(expected_version="2"),
            "intervals_text": "2031-08-10T12:00|2031-08-10T11:00",
        },
        edition_time_zone="UTC",
    )
    assert not reversed_window.is_valid()
    assert (
        reversed_window.errors.as_data()["intervals_text"][0].code
        == "invalid_interval_order"
    )

    too_many = VenueAvailabilityForm(
        {
            **_controls(expected_version="2"),
            "intervals_text": "\n".join(["2031-08-10T09:00|2031-08-10T10:00"] * 65),
        },
        edition_time_zone="UTC",
    )
    assert not too_many.is_valid()
    assert (
        too_many.errors.as_data()["intervals_text"][0].code == "invalid_interval_count"
    )


def _booking_form(**overrides: str) -> VenueBookingForm:
    layout = VenueLayoutVersion(id=uuid4(), title="Public layout", version=2)
    values = {
        **_controls(),
        "expected_version": "",
        "kind": VenueBooking.Kind.PANEL,
        "external_reference": "programme-1",
        "internal_title": "Internal opening panel",
        "public_title": "Opening panel",
        "public_description": "Welcome",
        "capacity_mode": VenueBooking.CapacityMode.SEATED,
        "expected_attendance": "80",
        "setup_starts_at": "2031-08-10T09:00",
        "effective_starts_at": "2031-08-10T09:30",
        "effective_ends_at": "2031-08-10T10:30",
        "teardown_ends_at": "2031-08-10T11:00",
        "public_layout_id": str(layout.id),
    }
    values.update(overrides)
    return VenueBookingForm(values, layouts=(layout,), edition_time_zone="UTC")


def test_booking_form_builds_ordered_envelope_and_optional_layout() -> None:
    form = _booking_form()
    assert form.is_valid(), form.errors
    assert form.envelope.setup_starts_at == datetime(2031, 8, 10, 9, tzinfo=UTC)
    assert isinstance(form.cleaned_data["public_layout_id"], UUID)

    without_layout = _booking_form(public_layout_id="")
    assert without_layout.is_valid(), without_layout.errors
    assert without_layout.cleaned_data["public_layout_id"] is None


def test_booking_form_rejects_unordered_operational_envelope() -> None:
    form = _booking_form(effective_starts_at="2031-08-10T08:30")
    assert not form.is_valid()
    assert "ordered setup" in str(form.errors["setup_starts_at"])


def test_inventory_initial_keeps_optional_version_and_typed_values() -> None:
    room_type = AccommodationRoomType(id=uuid4())
    release_at = datetime(2031, 8, 1, 12, tzinfo=UTC)
    assert inventory_initial(
        room_type=room_type,
        night=date(2031, 8, 10),
        release_at=release_at,
        room_capacity=4,
        provider_reference="block-1",
        expected_version=None,
    ) == {
        "room_type_id": str(room_type.id),
        "night": date(2031, 8, 10),
        "release_at": release_at,
        "room_capacity": 4,
        "provider_reference": "block-1",
        "expected_version": None,
    }
