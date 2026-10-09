"""Explicit foundation choices for standalone Announcements setup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django import forms

from maru.core.forms import CanonicalUUIDField, StrictInputForm
from maru.core.localization import grouped_time_zone_choices, language_labels
from maru.events.announcements_setup_inputs import (
    AnnouncementsAdoptionSetupInput,
    AnnouncementsSetupMode,
)

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID


class AnnouncementsSetupForm(StrictInputForm):
    """Collect the selected foundation without accepting submitted actor or scope."""

    organization_name = forms.CharField(
        label="New organization name",
        max_length=160,
        required=False,
        help_text="The organizer or community responsible for this convention.",
    )
    series_name = forms.CharField(
        label="New convention name",
        max_length=160,
        required=False,
        help_text="The recurring convention name, without the year if possible.",
    )
    edition_name = forms.CharField(label="Edition name", max_length=160)
    starts_on = forms.DateField(
        label="Starts on", widget=forms.DateInput(attrs={"type": "date"})
    )
    ends_on = forms.DateField(
        label="Ends on", widget=forms.DateInput(attrs={"type": "date"})
    )
    time_zone = forms.ChoiceField(
        label="Convention time zone", choices=grouped_time_zone_choices
    )
    language_codes = forms.MultipleChoiceField(
        label="Announcement languages",
        choices=lambda: sorted(language_labels().items(), key=lambda item: item[1]),
        help_text=(
            "Choose one or more languages. Hold Ctrl or Command to select "
            "several on a computer. Maru does not translate messages "
            "automatically."
        ),
    )
    reason = forms.CharField(
        label="Reason for this setup",
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirmed = forms.BooleanField(
        label="I checked the foundation, dates, time zone and languages."
    )
    foundation_fingerprint = forms.CharField(
        required=False, max_length=64, widget=forms.HiddenInput
    )
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        mode: str,
        organization_id: UUID | None = None,
        series_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Bind the route-owned reuse choice and keep original submitted values.

        Parameters
        ----------
        *args : Any
            Standard form data.
        mode : str
            Closed creation mode selected by the route.
        organization_id : UUID | None, default=None
            Exact reused organization from the route.
        series_id : UUID | None, default=None
            Exact same-parent convention from the route.
        **kwargs : Any
            Standard form options.
        """
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.organization_id = organization_id
        self.series_id = series_id
        self.fields["organization_name"].required = mode == "new_foundation"
        self.fields["series_name"].required = mode != "existing_series"
        if mode != "new_foundation":
            self.fields["organization_name"].widget = forms.HiddenInput()
        if mode == "existing_series":
            self.fields["series_name"].widget = forms.HiddenInput()

    def clean(self) -> dict[str, Any] | None:
        """Keep required, date and incompatible reuse errors visible.

        Returns
        -------
        dict[str, Any] | None
            Validated values, retaining the original bound input on errors.
        """
        cleaned = super().clean()
        if cleaned is None:
            return None
        if (
            cleaned.get("starts_on")
            and cleaned.get("ends_on")
            and cleaned["ends_on"] < cleaned["starts_on"]
        ):
            self.add_error("ends_on", "The end date cannot be before the start date.")
        if self.mode != "new_foundation" and cleaned.get("organization_name"):
            self.add_error(None, "The existing organization cannot be renamed here.")
        if self.mode == "existing_series" and cleaned.get("series_name"):
            self.add_error(None, "The existing convention cannot be renamed here.")
        key = cleaned.get("idempotency_key")
        if key is not None and key.int == 0:
            self.add_error(None, "Reload this setup form before trying again.")
        return cleaned

    def setup_input(self) -> AnnouncementsAdoptionSetupInput:
        """Build the owner's explicit foundation input after form validation.

        Returns
        -------
        AnnouncementsAdoptionSetupInput
            Exact original creation intent and foundation snapshot.
        """
        data = self.cleaned_data
        return AnnouncementsAdoptionSetupInput(
            mode=AnnouncementsSetupMode(self.mode),
            organization_id=self.organization_id,
            series_id=self.series_id,
            organization_name=str(data["organization_name"]),
            series_name=str(data["series_name"]),
            edition_name=str(data["edition_name"]),
            starts_on=cast("date", data["starts_on"]),
            ends_on=cast("date", data["ends_on"]),
            time_zone=str(data["time_zone"]),
            reason=str(data["reason"]),
            language_codes=tuple(data["language_codes"]),
            foundation_fingerprint=str(data["foundation_fingerprint"]),
        )
