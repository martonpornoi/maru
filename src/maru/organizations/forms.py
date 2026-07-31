"""Organizer setup forms with bounded, searchable localization choices."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django import forms

from maru.core.localization import (
    country_choices,
    grouped_language_choices,
    grouped_time_zone_choices,
)
from maru.organizations.models import Organization
from maru.organizations.services import (
    ConventionSeriesCreationDetails,
    OrganizationCreationDetails,
)


class ConventionSeriesCreationForm(forms.Form):
    name = forms.CharField(
        label="Convention series name",
        max_length=160,
        strip=True,
        help_text=(
            "The recurring public convention name. This is the only required field."
        ),
        widget=forms.TextInput(attrs={"autocomplete": "off", "autofocus": True}),
    )
    description = forms.CharField(
        label="Public description",
        required=False,
        max_length=2000,
        help_text="A short description of this convention brand across editions.",
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    website_url = forms.URLField(
        label="Website",
        required=False,
        assume_scheme="https",
        help_text="The convention series website, including https://.",
    )
    contact_email = forms.EmailField(
        label="Public contact email",
        required=False,
        help_text="A general convention mailbox, not an account login.",
    )
    availability = forms.ChoiceField(
        required=False,
        choices=(("active", "Active"), ("inactive", "Inactive")),
        initial="active",
        help_text=(
            "Active makes the brand available for future editions. It does not "
            "publish anything or create an edition."
        ),
    )

    def clean_name(self) -> str:
        return " ".join(self.cleaned_data["name"].split())

    def creation_details(self) -> ConventionSeriesCreationDetails:
        """Return typed command input after successful form validation."""

        if not self.is_valid():
            raise ValueError("Validate the series form before reading details.")
        return ConventionSeriesCreationDetails(
            name=str(self.cleaned_data["name"]),
            description=str(self.cleaned_data.get("description", "")),
            website_url=str(self.cleaned_data.get("website_url", "")),
            contact_email=str(self.cleaned_data.get("contact_email", "")),
            is_active=self.cleaned_data.get("availability", "active") != "inactive",
        )


class OrganizationCreationForm(forms.Form):
    name = forms.CharField(
        label="Organization name",
        max_length=160,
        strip=True,
        help_text=(
            "The public name people recognize. This is the only required field."
        ),
        widget=forms.TextInput(
            attrs={
                "aria-describedby": "organization-name-help",
                "autocomplete": "off",
                "autofocus": True,
            }
        ),
    )
    description = forms.CharField(
        required=False,
        max_length=2000,
        help_text="A short public-facing description of the organizer.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    legal_name = forms.CharField(
        label="Registered legal name",
        required=False,
        max_length=200,
        help_text=(
            "Use the official registered name when it differs from the public name."
        ),
    )
    legal_address = forms.CharField(
        label="Legal address",
        required=False,
        max_length=1000,
        help_text=(
            "Enter the registered postal address as it should appear in legal notices."
        ),
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    legal_representative = forms.CharField(
        label="Responsible representative",
        required=False,
        max_length=200,
        help_text=(
            "A printable person or office label for the imprint. This does not "
            "appoint an Executive Board member."
        ),
    )
    registration_authority = forms.CharField(
        required=False,
        max_length=200,
        help_text="For example, the public register or registration authority.",
    )
    registration_identifier = forms.CharField(
        required=False,
        max_length=120,
        help_text="For example, an association, charity, company, or registry number.",
    )
    tax_identifier = forms.CharField(
        required=False,
        max_length=120,
        help_text=(
            "Only enter this when it belongs in the organization's legal profile."
        ),
    )
    imprint_text = forms.CharField(
        label="Additional imprint text",
        required=False,
        max_length=5000,
        help_text=(
            "Jurisdiction-specific public wording not covered above. Do not enter "
            "payment data, identity-document data, or private case information."
        ),
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    website_url = forms.URLField(
        label="Website",
        required=False,
        assume_scheme="https",
        help_text="The organization's public website, including https://.",
    )
    contact_email = forms.EmailField(
        required=False,
        help_text="A general organization mailbox, not an account login.",
    )
    contact_phone = forms.RegexField(
        label="Contact telephone",
        required=False,
        max_length=16,
        regex=r"^\+[1-9]\d{6,14}$",
        error_messages={"invalid": "Enter an international number such as +431234567."},
        help_text=(
            "Optional international number beginning with + and the country code."
        ),
        widget=forms.TextInput(attrs={"inputmode": "tel"}),
    )
    country_code = forms.ChoiceField(
        label="Primary operating country",
        required=False,
        choices=(("", "Choose a country"), *country_choices()),
        help_text="Used for sensible defaults; it does not replace the legal address.",
    )
    default_language_codes = forms.MultipleChoiceField(
        label="Default languages",
        required=False,
        choices=grouped_language_choices,
        initial=("en",),
        help_text=(
            "Suggested languages for new convention editions. English is the fallback."
        ),
        widget=forms.SelectMultiple(attrs={"size": 8}),
    )
    default_time_zone = forms.ChoiceField(
        label="Default time zone",
        required=False,
        choices=grouped_time_zone_choices,
        initial="UTC",
        help_text="Suggested IANA time zone for new editions. UTC is the fallback.",
    )

    def clean_name(self) -> str:
        return " ".join(self.cleaned_data["name"].split())

    def creation_details(self) -> OrganizationCreationDetails:
        """Return typed command input after successful form validation."""

        if not self.is_valid():
            raise ValueError("Validate the organization form before reading details.")
        return OrganizationCreationDetails(
            name=str(self.cleaned_data["name"]),
            description=str(self.cleaned_data.get("description", "")),
            legal_name=str(self.cleaned_data.get("legal_name", "")),
            legal_address=str(self.cleaned_data.get("legal_address", "")),
            legal_representative=str(self.cleaned_data.get("legal_representative", "")),
            registration_authority=str(
                self.cleaned_data.get("registration_authority", "")
            ),
            registration_identifier=str(
                self.cleaned_data.get("registration_identifier", "")
            ),
            tax_identifier=str(self.cleaned_data.get("tax_identifier", "")),
            imprint_text=str(self.cleaned_data.get("imprint_text", "")),
            website_url=str(self.cleaned_data.get("website_url", "")),
            contact_email=str(self.cleaned_data.get("contact_email", "")),
            contact_phone=str(self.cleaned_data.get("contact_phone", "")),
            country_code=str(self.cleaned_data.get("country_code", "")),
            default_language_codes=tuple(
                self.cleaned_data.get("default_language_codes") or ("en",)
            ),
            default_time_zone=str(self.cleaned_data.get("default_time_zone") or "UTC"),
        )

    @classmethod
    def for_organization(
        cls,
        organization: Organization,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> OrganizationCreationForm:
        """Build the shared complete-profile form for an existing record."""

        form = cls(
            data=data,
            initial={
                "name": organization.name,
                "description": organization.description,
                "legal_name": organization.legal_name,
                "legal_address": organization.legal_address,
                "legal_representative": organization.legal_representative,
                "registration_authority": organization.registration_authority,
                "registration_identifier": organization.registration_identifier,
                "tax_identifier": organization.tax_identifier,
                "imprint_text": organization.imprint_text,
                "website_url": organization.website_url,
                "contact_email": organization.contact_email,
                "contact_phone": organization.contact_phone,
                "country_code": organization.country_code,
                "default_language_codes": organization.default_language_codes,
                "default_time_zone": organization.default_time_zone,
            },
        )
        form.fields["name"].widget.attrs.pop("autofocus", None)
        return form


class OrganizationDeletionForm(forms.Form):
    confirmation_name = forms.CharField(
        label="Organization name",
        max_length=160,
        strip=False,
        help_text="Enter the current organization name exactly, including capitals.",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    acknowledge = forms.BooleanField(
        label="I understand this permanently deletes the empty Draft organization.",
    )

    def __init__(
        self,
        *args: Any,
        organization: Organization,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.organization = organization

    def clean_confirmation_name(self) -> str:
        confirmation_name = str(self.cleaned_data["confirmation_name"])
        if confirmation_name != self.organization.name:
            raise forms.ValidationError(
                "Enter the organization name exactly as shown above.",
                code="organization_delete_name_mismatch",
            )
        return confirmation_name


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
            "contact_phone",
            "legal_address",
            "legal_representative",
            "registration_authority",
            "registration_identifier",
            "tax_identifier",
            "imprint_text",
            "country_code",
            "default_language_codes",
            "default_time_zone",
        )
