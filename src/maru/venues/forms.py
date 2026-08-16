"""Closed browser forms for venue catalog and operational schedule commands."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, ClassVar, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import (
    CanonicalUUIDField,
    HttpsURLField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.venues.models import (
    AccommodationRoomType,
    EditionVenueSelection,
    VenueBooking,
    VenueLayoutVersion,
    VenueProperty,
    VenuePropertyMedia,
    VenueSpace,
    VenueSpaceCombination,
    VenueSpaceConfiguration,
)
from maru.venues.services import (
    VenueAvailabilityInterval,
    VenueBookingEnvelope,
    VenueCapacityProfile,
)
from maru.workforce.models import Department

_DATE_TIME_FORMAT = "%Y-%m-%dT%H:%M"
_LOCAL_DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_AVAILABILITY_WINDOWS = 64
_MINIMUM_COMBINATION_MEMBERS = 2
_INTERVAL_PARTS_WITH_RESTRICTION = 3


def _parse_edition_local(value: str, *, zone: ZoneInfo) -> datetime:
    if _LOCAL_DATE_TIME.fullmatch(value) is None:
        raise ValidationError("Enter YYYY-MM-DDTHH:MM.", code="invalid")
    try:
        first = datetime.strptime(value, _DATE_TIME_FORMAT).replace(
            tzinfo=zone,
            fold=0,
        )
    except ValueError as error:
        raise ValidationError(
            "Enter a valid local date and time.",
            code="invalid",
        ) from error
    local = first.replace(tzinfo=None)
    second = local.replace(tzinfo=zone, fold=1)
    first_valid = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local
    second_valid = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == local
    if not first_valid and not second_valid:
        raise ValidationError(
            "Choose a real local time outside the daylight-saving gap.",
            code="nonexistent",
        )
    if first_valid and second_valid and first.utcoffset() != second.utcoffset():
        raise ValidationError(
            "Choose an unambiguous local time outside the daylight-saving fold.",
            code="ambiguous",
        )
    return first if first_valid else second


class EditionLocalDateTimeField(forms.Field):
    """Parse one real, unambiguous minute in one explicit edition time zone."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a valid local date and time.",
    }

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                format=_DATE_TIME_FORMAT,
                attrs={"type": "datetime-local", "step": "60"},
            ),
        )
        super().__init__(*args, **kwargs)
        self.zone = ZoneInfo(zone_name)

    def set_zone(self, zone_name: str) -> None:
        self.zone = ZoneInfo(zone_name)

    def to_python(self, value: object) -> datetime | None:
        if value in self.empty_values:
            return None
        if not isinstance(value, str):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return _parse_edition_local(value, zone=self.zone)

    def prepare_value(self, value: object) -> object:
        if isinstance(value, datetime):
            local = value.astimezone(self.zone) if value.tzinfo else value
            return local.strftime(_DATE_TIME_FORMAT)
        return value


class VenueRetryForm(StrictInputForm):
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)


class VenueVersionedForm(VenueRetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )


class VenueReasonForm(VenueRetryForm):
    reason = forms.CharField(max_length=1_000)


class VenuePropertyCreateForm(VenueReasonForm):
    slug = forms.SlugField(max_length=80)
    kind = forms.ChoiceField(choices=VenueProperty.Kind.choices)
    legal_name = forms.CharField(max_length=240)
    public_name = forms.CharField(max_length=200)
    provider_name = forms.CharField(max_length=240, required=False)
    public_description = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    internal_notes = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    location_name = forms.CharField(max_length=240)
    postal_address = forms.CharField(
        max_length=1_000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    country_code = forms.RegexField(r"[A-Za-z]{2}\Z", max_length=2)
    website_url = HttpsURLField(required=False)
    public_contact = forms.CharField(max_length=240, required=False)
    contact_name = forms.CharField(max_length=240, required=False)
    contact_email = forms.EmailField(required=False)
    contact_phone = forms.CharField(max_length=16, required=False)


class VenuePropertyUpdateForm(VenueVersionedForm):
    legal_name = forms.CharField(max_length=240)
    public_name = forms.CharField(max_length=200)
    provider_name = forms.CharField(max_length=240, required=False)
    public_description = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    internal_notes = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    location_name = forms.CharField(max_length=240)
    postal_address = forms.CharField(
        max_length=1_000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    country_code = forms.RegexField(r"[A-Za-z]{2}\Z", max_length=2)
    website_url = HttpsURLField(required=False)
    public_contact = forms.CharField(max_length=240, required=False)
    contact_name = forms.CharField(max_length=240, required=False)
    contact_email = forms.EmailField(required=False)
    contact_phone = forms.CharField(max_length=16, required=False)
    lifecycle = forms.ChoiceField(choices=VenueProperty.Lifecycle.choices)
    reason = forms.CharField(max_length=1_000)

    @property
    def changes(self) -> dict[str, str]:
        return {
            field_name: str(self.cleaned_data[field_name])
            for field_name in self.fields
            if field_name not in {"retry_key", "expected_version", "reason"}
        }


class VenueCatalogPathForm(VenueReasonForm):
    site_code = forms.SlugField(max_length=80)
    site_name = forms.CharField(max_length=200)
    building_code = forms.SlugField(max_length=80)
    building_name = forms.CharField(max_length=200)
    space_code = forms.SlugField(max_length=80)
    space_name = forms.CharField(max_length=200)
    space_kind = forms.ChoiceField(choices=VenueSpace.Kind.choices)
    configuration_code = forms.SlugField(max_length=80)
    configuration_name = forms.CharField(max_length=200)
    seated_capacity = StrictBase10IntegerField(min_value=0)
    standing_capacity = StrictBase10IntegerField(min_value=0)
    table_capacity = StrictBase10IntegerField(min_value=0)
    fire_capacity = StrictBase10IntegerField(min_value=1)
    public_description = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    accessibility_features = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    known_barriers = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    equipment_facts = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )


class VenueCombinationForm(VenueReasonForm):
    code = forms.SlugField(max_length=80)
    name = forms.CharField(max_length=200)
    member_space_ids = forms.MultipleChoiceField(
        choices=(),
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args: Any, spaces: Iterable[VenueSpace], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = cast(forms.MultipleChoiceField, self.fields["member_space_ids"])
        field.choices = tuple((str(item.id), item.name) for item in spaces)

    def clean_member_space_ids(self) -> tuple[UUID, ...]:
        values = tuple(UUID(value) for value in self.cleaned_data["member_space_ids"])
        if len(set(values)) < _MINIMUM_COMBINATION_MEMBERS:
            raise ValidationError("Select at least two distinct physical spaces.")
        return values


class VenueMediaAddForm(VenueReasonForm):
    kind = forms.ChoiceField(choices=VenuePropertyMedia.Kind.choices)
    source_reference = forms.CharField(max_length=1_000)
    owner_name = forms.CharField(max_length=240)
    license_basis = forms.CharField(max_length=500)
    usage_scope = forms.CharField(max_length=500)
    attribution = forms.CharField(max_length=500, required=False)
    expires_at = EditionLocalDateTimeField(required=False)

    def __init__(
        self,
        *args: Any,
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(EditionLocalDateTimeField, self.fields["expires_at"]).set_zone(
            edition_time_zone
        )


class VenueReviewForm(VenueVersionedForm):
    public_reference = forms.CharField(max_length=1_000, required=False)
    reason = forms.CharField(max_length=1_000)


class VenueLayoutAddForm(VenueReasonForm):
    space_id = forms.ChoiceField(choices=())
    layout_code = forms.SlugField(max_length=80)
    version = StrictBase10IntegerField(min_value=1)
    title = forms.CharField(max_length=200)
    visibility = forms.ChoiceField(choices=VenueLayoutVersion.Visibility.choices)
    source_reference = forms.CharField(max_length=1_000)
    checksum_sha256 = forms.RegexField(_SHA256, max_length=64)
    notes = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(self, *args: Any, spaces: Iterable[VenueSpace], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        field = cast(forms.ChoiceField, self.fields["space_id"])
        field.choices = tuple((str(item.id), item.name) for item in spaces)

    def clean_space_id(self) -> UUID:
        return UUID(self.cleaned_data["space_id"])


class AccommodationRoomTypeForm(VenueReasonForm):
    code = forms.SlugField(max_length=80)
    public_name = forms.CharField(max_length=200)
    description = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    accessible_features = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    minimum_occupants = StrictBase10IntegerField(min_value=1)
    maximum_occupants = StrictBase10IntegerField(min_value=1)
    provider_reference = forms.CharField(max_length=240, required=False)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        minimum = cleaned.get("minimum_occupants")
        maximum = cleaned.get("maximum_occupants")
        if minimum is not None and maximum is not None and maximum < minimum:
            self.add_error(
                "maximum_occupants",
                "Maximum occupants must be at least the minimum.",
            )
        return cleaned


class AccommodationInventoryForm(VenueRetryForm):
    room_type_id = forms.ChoiceField(choices=())
    night = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    room_capacity = StrictBase10IntegerField(min_value=0)
    release_at = EditionLocalDateTimeField()
    provider_reference = forms.CharField(max_length=240, required=False)
    expected_version = StrictBase10IntegerField(min_value=1, required=False)
    reason = forms.CharField(max_length=1_000)

    def __init__(
        self,
        *args: Any,
        room_types: Iterable[AccommodationRoomType],
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        field = cast(forms.ChoiceField, self.fields["room_type_id"])
        field.choices = tuple((str(item.id), item.public_name) for item in room_types)
        cast(EditionLocalDateTimeField, self.fields["release_at"]).set_zone(
            edition_time_zone
        )

    def clean_room_type_id(self) -> UUID:
        return UUID(self.cleaned_data["room_type_id"])


class VenueEditionSelectionForm(VenueReasonForm):
    property_id = forms.ChoiceField(choices=())
    responsible_department_id = forms.ChoiceField(choices=())
    local_name = forms.CharField(max_length=200)
    public_description_override = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    public_contact_override = forms.CharField(max_length=240, required=False)
    opening_restrictions = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(
        self,
        *args: Any,
        properties: Iterable[VenueProperty],
        departments: Iterable[Department],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        property_field = cast(forms.ChoiceField, self.fields["property_id"])
        property_field.choices = tuple(
            (str(item.id), item.public_name) for item in properties
        )
        department_field = cast(
            forms.ChoiceField,
            self.fields["responsible_department_id"],
        )
        department_field.choices = tuple(
            (str(item.id), item.name) for item in departments
        )

    def clean_property_id(self) -> UUID:
        return UUID(self.cleaned_data["property_id"])

    def clean_responsible_department_id(self) -> UUID:
        return UUID(self.cleaned_data["responsible_department_id"])


class VenueSpaceSelectionForm(VenueReasonForm):
    venue_selection_id = forms.ChoiceField(choices=())
    source_space_id = forms.ChoiceField(choices=(), required=False)
    source_combination_id = forms.ChoiceField(choices=(), required=False)
    selected_configuration_id = forms.ChoiceField(choices=(), required=False)
    local_name = forms.CharField(max_length=200)
    override_capacity = forms.BooleanField(required=False)
    configuration_name = forms.CharField(max_length=200, required=False)
    seated_capacity = StrictBase10IntegerField(min_value=0, required=False)
    standing_capacity = StrictBase10IntegerField(min_value=0, required=False)
    table_capacity = StrictBase10IntegerField(min_value=0, required=False)
    fire_capacity = StrictBase10IntegerField(min_value=1, required=False)
    public_access_info = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    opening_restrictions = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    def __init__(
        self,
        *args: Any,
        venue_selections: Iterable[EditionVenueSelection],
        spaces: Iterable[VenueSpace],
        combinations: Iterable[VenueSpaceCombination],
        configurations: Iterable[VenueSpaceConfiguration],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        choices = {
            "venue_selection_id": tuple(
                (str(item.id), item.local_name) for item in venue_selections
            ),
            "source_space_id": (
                ("", "Choose a physical space"),
                *((str(item.id), item.name) for item in spaces),
            ),
            "source_combination_id": (
                ("", "Choose a combination"),
                *((str(item.id), item.name) for item in combinations),
            ),
            "selected_configuration_id": (
                ("", "Use a capacity override"),
                *(
                    (str(item.id), f"{item.space.name} / {item.name} v{item.version}")
                    for item in configurations
                ),
            ),
        }
        for field_name, field_choices in choices.items():
            cast(forms.ChoiceField, self.fields[field_name]).choices = field_choices

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        source_space = cleaned.get("source_space_id")
        source_combination = cleaned.get("source_combination_id")
        if bool(source_space) == bool(source_combination):
            self.add_error(
                "source_space_id",
                "Select exactly one physical space or combination.",
            )
        override_fields = (
            "configuration_name",
            "seated_capacity",
            "standing_capacity",
            "table_capacity",
            "fire_capacity",
        )
        if cleaned.get("override_capacity") and any(
            cleaned.get(field_name) in (None, "") for field_name in override_fields
        ):
            self.add_error(
                "configuration_name",
                "Complete every capacity override field.",
            )
        if not cleaned.get("override_capacity") and not cleaned.get(
            "selected_configuration_id"
        ):
            self.add_error(
                "selected_configuration_id",
                "Choose a source configuration or provide a capacity override.",
            )
        return cleaned

    @staticmethod
    def _optional_uuid(value: object) -> UUID | None:
        return UUID(str(value)) if value else None

    def clean_venue_selection_id(self) -> UUID:
        return UUID(self.cleaned_data["venue_selection_id"])

    def clean_source_space_id(self) -> UUID | None:
        return self._optional_uuid(self.cleaned_data.get("source_space_id"))

    def clean_source_combination_id(self) -> UUID | None:
        return self._optional_uuid(self.cleaned_data.get("source_combination_id"))

    def clean_selected_configuration_id(self) -> UUID | None:
        return self._optional_uuid(self.cleaned_data.get("selected_configuration_id"))

    @property
    def capacity(self) -> VenueCapacityProfile | None:
        if not self.cleaned_data.get("override_capacity"):
            return None
        return VenueCapacityProfile(
            configuration_name=str(self.cleaned_data["configuration_name"]),
            seated_capacity=int(self.cleaned_data["seated_capacity"]),
            standing_capacity=int(self.cleaned_data["standing_capacity"]),
            table_capacity=int(self.cleaned_data["table_capacity"]),
            fire_capacity=int(self.cleaned_data["fire_capacity"]),
        )


class VenueAvailabilityForm(VenueVersionedForm):
    intervals_text = forms.CharField(
        max_length=20_000,
        help_text=(
            "One local window per line: start|end|optional opening restriction."
        ),
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    reason = forms.CharField(max_length=1_000)

    def __init__(
        self,
        *args: Any,
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.zone = ZoneInfo(edition_time_zone)
        self.intervals: tuple[VenueAvailabilityInterval, ...] = ()

    def clean_intervals_text(self) -> str:
        raw = str(self.cleaned_data["intervals_text"])
        intervals: list[VenueAvailabilityInterval] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            parts = tuple(item.strip() for item in line.split("|", 2))
            if len(parts) not in {2, 3}:
                raise ValidationError(
                    "Use start|end|optional restriction on each line.",
                    code="invalid_interval",
                )
            starts_at = _parse_edition_local(parts[0], zone=self.zone)
            ends_at = _parse_edition_local(parts[1], zone=self.zone)
            if starts_at >= ends_at:
                raise ValidationError(
                    "Every availability end must follow its start.",
                    code="invalid_interval_order",
                )
            intervals.append(
                VenueAvailabilityInterval(
                    starts_at=starts_at,
                    ends_at=ends_at,
                    opening_restriction=(
                        parts[2]
                        if len(parts) == _INTERVAL_PARTS_WITH_RESTRICTION
                        else ""
                    ),
                )
            )
        if not intervals or len(intervals) > _MAX_AVAILABILITY_WINDOWS:
            raise ValidationError(
                "Provide from one through 64 availability windows.",
                code="invalid_interval_count",
            )
        self.intervals = tuple(intervals)
        return raw


class VenueBookingForm(VenueRetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        required=False,
        widget=forms.HiddenInput,
    )
    kind = forms.ChoiceField(choices=VenueBooking.Kind.choices)
    external_reference = forms.CharField(max_length=240, required=False)
    internal_title = forms.CharField(max_length=240)
    public_title = forms.CharField(max_length=240, required=False)
    public_description = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    capacity_mode = forms.ChoiceField(choices=VenueBooking.CapacityMode.choices)
    expected_attendance = StrictBase10IntegerField(min_value=1)
    setup_starts_at = EditionLocalDateTimeField()
    effective_starts_at = EditionLocalDateTimeField()
    effective_ends_at = EditionLocalDateTimeField()
    teardown_ends_at = EditionLocalDateTimeField()
    public_layout_id = forms.ChoiceField(choices=(), required=False)
    reason = forms.CharField(max_length=1_000)

    def __init__(
        self,
        *args: Any,
        layouts: Iterable[VenueLayoutVersion],
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        for field_name in (
            "setup_starts_at",
            "effective_starts_at",
            "effective_ends_at",
            "teardown_ends_at",
        ):
            cast(EditionLocalDateTimeField, self.fields[field_name]).set_zone(
                edition_time_zone
            )
        field = cast(forms.ChoiceField, self.fields["public_layout_id"])
        field.choices = (
            ("", "No public layout"),
            *((str(item.id), f"{item.title} v{item.version}") for item in layouts),
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        points = tuple(
            cleaned.get(field_name)
            for field_name in (
                "setup_starts_at",
                "effective_starts_at",
                "effective_ends_at",
                "teardown_ends_at",
            )
        )
        if all(isinstance(value, datetime) for value in points):
            setup, effective_start, effective_end, teardown = cast(
                tuple[datetime, datetime, datetime, datetime],
                points,
            )
            if not setup <= effective_start < effective_end <= teardown:
                self.add_error(
                    "setup_starts_at",
                    "Use ordered setup, effective, and teardown times.",
                )
        return cleaned

    @property
    def envelope(self) -> VenueBookingEnvelope:
        return VenueBookingEnvelope(
            setup_starts_at=cast(datetime, self.cleaned_data["setup_starts_at"]),
            effective_starts_at=cast(
                datetime,
                self.cleaned_data["effective_starts_at"],
            ),
            effective_ends_at=cast(datetime, self.cleaned_data["effective_ends_at"]),
            teardown_ends_at=cast(datetime, self.cleaned_data["teardown_ends_at"]),
        )

    def clean_public_layout_id(self) -> UUID | None:
        value = self.cleaned_data.get("public_layout_id")
        return UUID(str(value)) if value else None


class VenueBookingStateForm(VenueVersionedForm):
    reason = forms.CharField(max_length=1_000)


def inventory_initial(
    *,
    room_type: AccommodationRoomType,
    night: date,
    release_at: datetime,
    room_capacity: int,
    provider_reference: str,
    expected_version: int | None,
) -> dict[str, object]:
    return {
        "room_type_id": str(room_type.id),
        "night": night,
        "release_at": release_at,
        "room_capacity": room_capacity,
        "provider_reference": provider_reference,
        "expected_version": expected_version,
    }
