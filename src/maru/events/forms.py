"""Bounded event-edition forms shared by the controlled administration pages."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any, cast
from uuid import uuid4

from django import forms

from maru.core.forms import StrictInputForm
from maru.core.localization import grouped_language_choices, grouped_time_zone_choices
from maru.core.validators import validate_currency_codes, validate_language_codes
from maru.events.models import MAX_EDITION_SPAN_DAYS, EventEdition
from maru.events.services import EventEditionDetails
from maru.organizations.models import ConventionSeries, Organization

_CURRENCY_SEPARATOR = re.compile(r"[\s,]+")


class EventEditionDetailsForm(StrictInputForm):
    name = forms.CharField(
        label="Edition name",
        max_length=160,
        strip=True,
        help_text="The recognizable name for this dated convention occurrence.",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    starts_on = forms.DateField(
        label="Starts on",
        help_text="The first official convention date.",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    ends_on = forms.DateField(
        label="Ends on",
        help_text="The final official date, no more than 31 days after the start.",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    time_zone = forms.ChoiceField(
        label="Time zone",
        choices=grouped_time_zone_choices,
        help_text=(
            "The IANA time zone used to interpret this edition's local schedule."
        ),
    )
    language_codes = forms.MultipleChoiceField(
        label="Official languages",
        choices=grouped_language_choices,
        help_text="Choose at least one and no more than 16 official languages.",
        widget=forms.SelectMultiple(attrs={"size": 10}),
    )
    currency_codes = forms.CharField(
        label="Currencies",
        max_length=39,
        strip=True,
        help_text=(
            "Enter one to eight ISO 4217 codes separated by commas, such as EUR "
            "or EUR, USD. The first is the primary operating currency."
        ),
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "placeholder": "EUR",
                "spellcheck": "false",
            }
        ),
    )

    def clean_name(self) -> str:
        return " ".join(self.cleaned_data["name"].split())

    def clean_language_codes(self) -> list[str]:
        values = [str(code).lower() for code in self.cleaned_data["language_codes"]]
        validate_language_codes(values)
        return values

    def clean_currency_codes(self) -> list[str]:
        raw = str(self.cleaned_data["currency_codes"])
        values = [value.upper() for value in _CURRENCY_SEPARATOR.split(raw) if value]
        validate_currency_codes(values)
        return values

    def clean(self) -> dict[str, object] | None:
        cleaned = super().clean()
        if cleaned is None:
            return None
        starts_on = cleaned.get("starts_on")
        ends_on = cleaned.get("ends_on")
        if isinstance(starts_on, date) and isinstance(ends_on, date):
            if ends_on < starts_on:
                self.add_error(
                    "ends_on",
                    "The end date cannot be before the start date.",
                )
            elif (ends_on - starts_on).days > MAX_EDITION_SPAN_DAYS:
                self.add_error(
                    "ends_on",
                    (
                        "An edition date range cannot exceed "
                        f"{MAX_EDITION_SPAN_DAYS} days."
                    ),
                )
        return cleaned

    def edition_details(self) -> EventEditionDetails:
        if not self.is_valid():
            raise ValueError("Validate the edition form before reading details.")
        return EventEditionDetails(
            name=cast(str, self.cleaned_data["name"]),
            starts_on=cast(date, self.cleaned_data["starts_on"]),
            ends_on=cast(date, self.cleaned_data["ends_on"]),
            time_zone=cast(str, self.cleaned_data["time_zone"]),
            language_codes=tuple(cast(list[str], self.cleaned_data["language_codes"])),
            currency_codes=tuple(cast(list[str], self.cleaned_data["currency_codes"])),
        )


class EventEditionCreationForm(EventEditionDetailsForm):
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    @classmethod
    def for_series(
        cls,
        *,
        organization: Organization,
        series: ConventionSeries,
        data: Mapping[str, Any] | None = None,
    ) -> EventEditionCreationForm:
        del series
        form = cls(
            data=data,
            initial={
                "time_zone": organization.default_time_zone,
                "language_codes": organization.default_language_codes,
                "idempotency_key": uuid4(),
            },
        )
        form.fields["name"].widget.attrs["autofocus"] = True
        return form


class EventEditionUpdateForm(EventEditionDetailsForm):
    expected_aggregate_version = forms.IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )

    @classmethod
    def for_edition(
        cls,
        edition: EventEdition,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> EventEditionUpdateForm:
        return cls(
            data=data,
            initial={
                "name": edition.name,
                "starts_on": edition.starts_on,
                "ends_on": edition.ends_on,
                "time_zone": edition.time_zone,
                "language_codes": edition.language_codes,
                "currency_codes": ", ".join(edition.currency_codes),
                "expected_aggregate_version": edition.aggregate_version,
            },
        )
