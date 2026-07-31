"""Organizer setup forms with bounded, searchable localization choices."""

from __future__ import annotations

from django import forms

from maru.core.localization import (
    country_choices,
    grouped_language_choices,
    grouped_time_zone_choices,
)
from maru.organizations.models import Organization


class OrganizationCreationForm(forms.Form):
    name = forms.CharField(
        label="Organization name",
        max_length=160,
        strip=True,
        help_text=(
            "Use the name people will recognize. Legal details can be added "
            "on the Organization page later."
        ),
        widget=forms.TextInput(
            attrs={
                "aria-describedby": "organization-name-help",
                "autocomplete": "off",
                "autofocus": True,
            }
        ),
    )

    def clean_name(self) -> str:
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Enter an organization name.")
        return name


class OrganizationAdminForm(forms.ModelForm):  # type: ignore[type-arg]
    default_language_codes = forms.MultipleChoiceField(
        label="Default languages",
        choices=grouped_language_choices,
        initial=("en",),
        help_text=(
            "Choose one or more ISO 639-1 languages. English is pinned as a "
            "common convention language; the regional groups are discovery aids."
        ),
        widget=forms.SelectMultiple(
            attrs={
                "size": 12,
                "data-filterable-select": "",
                "data-filter-placeholder": "Start typing a language or code",
            }
        ),
    )
    default_time_zone = forms.ChoiceField(
        choices=grouped_time_zone_choices,
        help_text=(
            "IANA time-zone identifier with current standard/DST UTC offsets. "
            "The stored identifier preserves future clock-change rules."
        ),
        widget=forms.Select(
            attrs={
                "data-filterable-select": "",
                "data-filter-placeholder": "Start typing a city, region, or UTC offset",
            }
        ),
    )
    country_code = forms.ChoiceField(
        label="Primary operating country",
        choices=(("", "Choose a country"), *country_choices()),
        help_text="Used to preselect country-aware fields such as telephone prefixes.",
    )

    class Meta:
        model = Organization
        fields = (
            "slug",
            "name",
            "lifecycle",
            "legal_name",
            "description",
            "website_url",
            "contact_email",
            "country_code",
            "default_language_codes",
            "default_time_zone",
        )
