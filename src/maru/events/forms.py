"""Bounded event-edition forms shared by the controlled administration pages."""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from maru.core.forms import StrictInputForm
from maru.core.localization import grouped_language_choices, grouped_time_zone_choices
from maru.core.validators import validate_currency_codes, validate_language_codes
from maru.events.adoption import (
    PERSISTED_ADOPTION_PROFILE_CHOICES,
    SELECTABLE_ADOPTION_PROFILE_CHOICES,
    AdoptionProfileCode,
    profile_adopts_module,
)
from maru.events.models import (
    MAX_EDITION_SPAN_DAYS,
    EventEdition,
    WorkforceAdoptionSetupReceipt,
)
from maru.events.services import EventEditionDetails
from maru.events.workforce_adoption import WorkforceAdoptionSetupInput
from maru.organizations.models import ConventionSeries, Organization

if TYPE_CHECKING:
    from collections.abc import Mapping

_CURRENCY_SEPARATOR = re.compile(r"[\s,]+")


class RetainedAdoptionProfileChoiceField(forms.ChoiceField):
    """Display current setup choices while accepting exact retained retry codes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Configure the selectable presentation and retained validation set.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to Django's choice field.
        **kwargs : Any
            Keyword arguments forwarded to Django's choice field.
        """
        self.retained_values = frozenset(
            code for code, _label in PERSISTED_ADOPTION_PROFILE_CHOICES
        )
        super().__init__(*args, **kwargs)

    def validate(self, value: object) -> None:
        """Accept a persisted code even after it retires from new selection.

        Parameters
        ----------
        value : object
            Normalized submitted profile code.

        Raises
        ------
        ValidationError
            If the value is required or is not a retained profile code.
        """
        forms.Field.validate(self, value)
        if value and value not in self.retained_values:
            raise ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )


class EventEditionDetailsForm(StrictInputForm):
    """Collect and validate event edition details input."""

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
        """Validate and normalize the name field.

        Returns
        -------
        str
            The validated and normalized name.
        """
        return " ".join(self.cleaned_data["name"].split())

    def clean_language_codes(self) -> list[str]:
        """Validate and normalize the language codes field.

        Returns
        -------
        list[str]
            The matching clean language codes records in deterministic order.
        """
        values = [str(code).lower() for code in self.cleaned_data["language_codes"]]
        validate_language_codes(values)
        return values

    def clean_currency_codes(self) -> list[str]:
        """Validate and normalize the currency codes field.

        Returns
        -------
        list[str]
            The matching clean currency codes records in deterministic order.
        """
        raw = str(self.cleaned_data["currency_codes"])
        values = [value.upper() for value in _CURRENCY_SEPARATOR.split(raw) if value]
        validate_currency_codes(values)
        return values

    def clean(self) -> dict[str, object] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, object] | None
            A mapping containing the resolved clean data.
        """
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
        """Return edition details.

        Returns
        -------
        EventEditionDetails
            The resolved EventEditionDetails for edition details.

        Raises
        ------
        ValueError
            If the supplied value cannot satisfy the documented contract.
        """
        if not self.is_valid():
            raise ValueError("Validate the edition form before reading details.")
        return EventEditionDetails(
            name=cast("str", self.cleaned_data["name"]),
            starts_on=cast("date", self.cleaned_data["starts_on"]),
            ends_on=cast("date", self.cleaned_data["ends_on"]),
            time_zone=cast("str", self.cleaned_data["time_zone"]),
            language_codes=tuple(
                cast("list[str]", self.cleaned_data["language_codes"])
            ),
            currency_codes=tuple(
                cast("list[str]", self.cleaned_data["currency_codes"])
            ),
        )


class EventEditionCreationForm(EventEditionDetailsForm):
    """Collect and validate event edition creation input."""

    adoption_profile_code = RetainedAdoptionProfileChoiceField(
        label="How will this edition use Maru?",
        choices=SELECTABLE_ADOPTION_PROFILE_CHOICES,
        help_text=(
            "Choose only the tools this convention is ready to adopt. This "
            "boundary cannot be changed casually after creation."
        ),
        widget=forms.RadioSelect,
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    @classmethod
    def for_series(
        cls,
        *,
        organization: Organization,
        series: ConventionSeries,
        data: Mapping[str, Any] | None = None,
    ) -> EventEditionCreationForm:
        """Return for series.

        Parameters
        ----------
        organization : Organization
            The organization that owns the requested resource.
        series : ConventionSeries
            The series used to configure and validate this form.
        data : Mapping[str, Any] | None, default=None
            The untrusted input payload to validate or transform.

        Returns
        -------
        EventEditionCreationForm
            The resolved EventEditionCreationForm for for series.
        """
        del series
        form = cls(
            data=data,
            initial={
                "adoption_profile_code": AdoptionProfileCode.FULL_CONVENTION,
                "time_zone": organization.default_time_zone,
                "language_codes": organization.default_language_codes,
                "idempotency_key": uuid4(),
            },
        )
        form.fields["name"].widget.attrs["autofocus"] = True
        return form


class EventEditionUpdateForm(EventEditionDetailsForm):
    """Collect and validate event edition update input."""

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
        """Return for edition.

        Parameters
        ----------
        edition : EventEdition
            The event edition that scopes the operation.
        data : Mapping[str, Any] | None, default=None
            The untrusted input payload to validate or transform.

        Returns
        -------
        EventEditionUpdateForm
            The resolved EventEditionUpdateForm for for edition.
        """
        form = cls(
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
        if not profile_adopts_module(
            edition.adoption_profile_code,
            edition.adoption_profile_version,
            "registration",
        ):
            currency_field = form.fields["currency_codes"]
            currency_field.disabled = True
            currency_field.widget = forms.HiddenInput()
            currency_field.help_text = ""
        return form


class WorkforceAdoptionSetupForm(StrictInputForm):
    """Collect the minimum deliberate foundation for Workforce-only use."""

    mode = forms.ChoiceField(
        label="What already exists in Maru?",
        choices=WorkforceAdoptionSetupReceipt.Mode.choices,
        widget=forms.RadioSelect,
        help_text=(
            "Reuse the highest matching foundation level. Maru will not "
            "duplicate an organization or convention series you select."
        ),
    )
    organization = forms.ModelChoiceField(
        label="Existing organization",
        queryset=Organization.objects.none(),
        required=False,
        empty_label="Choose an organization",
    )
    series = forms.ModelChoiceField(
        label="Existing convention series",
        queryset=ConventionSeries.objects.none(),
        required=False,
        empty_label="Choose a convention series",
    )
    organization_name = forms.CharField(
        label="Organization name",
        max_length=160,
        required=False,
        strip=True,
        help_text="The organizer or community responsible for this convention.",
    )
    series_name = forms.CharField(
        label="Convention name",
        max_length=160,
        required=False,
        strip=True,
        help_text="The recurring convention brand, without a year if possible.",
    )
    edition_name = forms.CharField(
        label="Edition name",
        max_length=160,
        strip=True,
        help_text="The dated occurrence people will recognize, such as MaruCon 2027.",
    )
    starts_on = forms.DateField(
        label="Starts on",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    ends_on = forms.DateField(
        label="Ends on",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    time_zone = forms.ChoiceField(
        label="Convention time zone",
        choices=grouped_time_zone_choices,
        help_text="Used for Availability and Shift times.",
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize bounded reuse choices and humane defaults.

        Parameters
        ----------
        *args : Any
            Positional form arguments.
        **kwargs : Any
            Keyword form arguments.
        """
        super().__init__(*args, **kwargs)
        reusable_organizations = Q(lifecycle=Organization.Lifecycle.DRAFT) | Q(
            lifecycle=Organization.Lifecycle.ACTIVE,
            representation__isnull=False,
        )
        organization_field = cast(
            "forms.ModelChoiceField[Organization]",
            self.fields["organization"],
        )
        organization_field.queryset = Organization.objects.filter(
            reusable_organizations
        ).order_by("name", "id")
        series_field = cast(
            "forms.ModelChoiceField[ConventionSeries]",
            self.fields["series"],
        )
        series_field.queryset = (
            ConventionSeries.objects.filter(
                is_active=True,
            )
            .filter(
                Q(organization__lifecycle=Organization.Lifecycle.DRAFT)
                | Q(
                    organization__lifecycle=Organization.Lifecycle.ACTIVE,
                    organization__representation__isnull=False,
                )
            )
            .select_related("organization")
            .order_by("organization__name", "name", "id")
        )
        if not self.is_bound:
            self.initial.setdefault(
                "mode",
                WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION,
            )
            self.initial.setdefault("time_zone", "UTC")
            self.initial.setdefault("idempotency_key", uuid4())
        self.fields["organization_name"].widget.attrs["autofocus"] = True

    def clean_organization_name(self) -> str:
        """Normalize the optional new organization name.

        Returns
        -------
        str
            The normalized organization name.
        """
        return " ".join(str(self.cleaned_data.get("organization_name", "")).split())

    def clean_series_name(self) -> str:
        """Normalize the optional new convention-series name.

        Returns
        -------
        str
            The normalized convention-series name.
        """
        return " ".join(str(self.cleaned_data.get("series_name", "")).split())

    def clean_edition_name(self) -> str:
        """Normalize the required edition name.

        Returns
        -------
        str
            The normalized event-edition name.
        """
        return " ".join(str(self.cleaned_data["edition_name"]).split())

    def clean(self) -> dict[str, object] | None:
        """Validate mode-specific foundation fields and the date range.

        Returns
        -------
        dict[str, object] | None
            The complete cleaned form mapping when valid.
        """
        cleaned = super().clean()
        if cleaned is None:
            return None
        mode = cleaned.get("mode")
        if mode == WorkforceAdoptionSetupReceipt.Mode.NEW_FOUNDATION:
            if not cleaned.get("organization_name"):
                self.add_error("organization_name", "Enter the organization name.")
            if not cleaned.get("series_name"):
                self.add_error("series_name", "Enter the convention name.")
        elif mode == WorkforceAdoptionSetupReceipt.Mode.EXISTING_ORGANIZATION:
            if cleaned.get("organization") is None:
                self.add_error("organization", "Choose the organization to reuse.")
            if not cleaned.get("series_name"):
                self.add_error("series_name", "Enter the convention name.")
        elif mode == WorkforceAdoptionSetupReceipt.Mode.EXISTING_SERIES:
            if cleaned.get("series") is None:
                self.add_error("series", "Choose the convention series to reuse.")

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

    def setup_input(self) -> WorkforceAdoptionSetupInput:
        """Return the complete service input after successful validation.

        Returns
        -------
        WorkforceAdoptionSetupInput
            The immutable guided-setup input.

        Raises
        ------
        ValueError
            If the form has not validated successfully.
        """
        if not self.is_valid():
            raise ValueError("Validate the Workforce setup form before using it.")
        organization = cast("Organization | None", self.cleaned_data["organization"])
        series = cast("ConventionSeries | None", self.cleaned_data["series"])
        return WorkforceAdoptionSetupInput(
            mode=cast("str", self.cleaned_data["mode"]),
            organization_id=organization.id if organization is not None else None,
            series_id=series.id if series is not None else None,
            organization_name=cast("str", self.cleaned_data["organization_name"]),
            series_name=cast("str", self.cleaned_data["series_name"]),
            edition_name=cast("str", self.cleaned_data["edition_name"]),
            starts_on=cast("date", self.cleaned_data["starts_on"]),
            ends_on=cast("date", self.cleaned_data["ends_on"]),
            time_zone=cast("str", self.cleaned_data["time_zone"]),
        )
