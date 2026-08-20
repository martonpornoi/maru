"""Strict same-shell forms for authenticated logistics workflows."""

import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID
from zoneinfo import ZoneInfo

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .models import MAX_LOGISTICS_REASON_LENGTH, EquipmentOfferItem

_LOCAL_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\Z")


class CanonicalLocalDateTimeField(forms.Field):
    """Parse one exact, unambiguous minute in the edition IANA time zone."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a valid local date and time.",
        "ambiguous": "Choose a time outside the daylight-saving clock change.",
        "nonexistent": "Choose a local time that exists in this time zone.",
    }

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        """Initialize the CanonicalLocalDateTimeField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        zone_name : str, default='UTC'
            The human-readable zone name shown to authorized readers.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local", "step": "60"},
            ),
        )
        super().__init__(*args, **kwargs)
        self.zone = ZoneInfo(zone_name)

    def set_zone(self, zone_name: str) -> None:
        """Set zone.

        Parameters
        ----------
        zone_name : str
            The human-readable zone name shown to authorized readers.
        """
        self.zone = ZoneInfo(zone_name)

    def to_python(self, value: object) -> datetime | None:
        """Convert submitted input to its normalized Python representation.

        Parameters
        ----------
        value : object
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        datetime | None
            The canonical Python representation, or `None` for empty input.

        Raises
        ------
        forms.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        if value in self.empty_values:
            return None
        if not isinstance(value, str) or _LOCAL_DATE_TIME.fullmatch(value) is None:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        try:
            first = datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(
                tzinfo=self.zone,
                fold=0,
            )
        except ValueError as error:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            ) from error
        local = first.replace(tzinfo=None)
        second = local.replace(tzinfo=self.zone, fold=1)
        first_round_trip = (
            first.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None)
        )
        second_round_trip = (
            second.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None)
        )
        first_valid = first_round_trip == local
        second_valid = second_round_trip == local
        if not first_valid and not second_valid:
            raise forms.ValidationError(
                self.error_messages["nonexistent"],
                code="nonexistent",
            )
        if first_valid and second_valid and first.utcoffset() != second.utcoffset():
            raise forms.ValidationError(
                self.error_messages["ambiguous"],
                code="ambiguous",
            )
        return first if first_valid else second

    def prepare_value(self, value: object) -> object:
        """Prepare value.

        Parameters
        ----------
        value : object
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        object
            A widget-ready representation of the stored value.
        """
        if isinstance(value, datetime):
            local = value.astimezone(self.zone) if value.tzinfo else value
            return local.strftime("%Y-%m-%dT%H:%M")
        return value


class CanonicalUUIDChoiceField(forms.ChoiceField):
    """A bounded named choice that returns one canonical lower-case UUID."""

    def to_python(self, value: object) -> UUID | None:
        """Convert submitted input to its normalized Python representation.

        Parameters
        ----------
        value : object
            The untrusted input to normalize, validate, or compare.

        Returns
        -------
        UUID | None
            The canonical Python representation, or `None` for empty input.
        """
        if value in self.empty_values:
            return None
        parsed = CanonicalUUIDField().to_python(value)
        if parsed is None:
            return None
        return parsed


class LogisticsStrictForm(StrictInputForm):
    """Collect and validate logistics strict input."""

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        """Initialize the LogisticsStrictForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        zone_name : str, default='UTC'
            The human-readable zone name shown to authorized readers.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, CanonicalLocalDateTimeField):
                field.set_zone(zone_name)


class EquipmentOfferForm(LogisticsStrictForm):
    """Collect and validate equipment offer input."""

    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)
    title = forms.CharField(max_length=200)
    description = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    available_from = CanonicalLocalDateTimeField()
    available_until = CanonicalLocalDateTimeField()
    requested_return_at = CanonicalLocalDateTimeField(required=False)
    pickup_label = forms.CharField(max_length=200, initial="Pickup address")
    pickup_recipient_name = forms.CharField(max_length=240, required=False)
    pickup_postal_address = forms.CharField(
        max_length=1_000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    pickup_access_instructions = forms.CharField(
        max_length=5_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    pickup_retention_until = CanonicalLocalDateTimeField(
        help_text="The address is retained only until this time.",
    )
    item_kind = forms.ChoiceField(choices=EquipmentOfferItem.Kind.choices)
    item_name = forms.CharField(max_length=200)
    item_description = forms.CharField(
        max_length=MAX_LOGISTICS_REASON_LENGTH,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    item_quantity = StrictBase10IntegerField(
        min_value=1,
        max_value=1_000_000,
        initial=1,
    )
    manufacturer = forms.CharField(max_length=160, required=False)
    model_name = forms.CharField(max_length=160, required=False)
    serial_number = forms.CharField(max_length=200, required=False)
    condition = forms.CharField(max_length=120)
    value_class = forms.CharField(max_length=32, required=False)
    ownership_statement = forms.CharField(max_length=500)
    reason = forms.CharField(
        max_length=MAX_LOGISTICS_REASON_LENGTH,
        initial="Offer equipment for this edition.",
    )

    def clean(self) -> dict[str, object] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, object] | None
            A mapping containing the resolved clean data.
        """
        cleaned = super().clean()
        if not cleaned:
            return cleaned
        if (
            cleaned.get("item_kind") == EquipmentOfferItem.Kind.SERIALIZED
            and cleaned.get("item_quantity") != 1
        ):
            self.add_error(
                "item_quantity",
                "A serialized item has quantity one.",
            )
        return cleaned
