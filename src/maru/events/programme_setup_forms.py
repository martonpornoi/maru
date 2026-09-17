"""Explicit original-intent Programme foundation creation form."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from django import forms

from maru.core.forms import CanonicalUUIDField, StrictInputForm
from maru.core.localization import grouped_time_zone_choices
from maru.events.programme_setup_inputs import (
    ProgrammeSetupInput,
    ProgrammeSetupMode,
    normalize_programme_setup_input,
)

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID


class ProgrammeSetupForm(StrictInputForm):
    """Collect deliberate creation without accepting a submitted actor or scope."""

    organization_name = forms.CharField(
        label="New organization name", max_length=160, required=False
    )
    series_name = forms.CharField(
        label="New convention name", max_length=160, required=False
    )
    edition_name = forms.CharField(label="New edition name", max_length=160)
    department_name = forms.CharField(
        label="First Programme Department name", max_length=160
    )
    starts_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    ends_on = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    time_zone = forms.ChoiceField(
        label="Convention time zone", choices=grouped_time_zone_choices
    )
    reason = forms.CharField(max_length=240, widget=forms.Textarea(attrs={"rows": 3}))
    confirmed = forms.BooleanField(
        label=(
            "I reviewed the foundation to reuse or create, dates and first Department. "
            "This does not grant Programme access."
        )
    )
    foundation_fingerprint = forms.CharField(
        required=False, max_length=64, widget=forms.HiddenInput
    )
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        mode: ProgrammeSetupMode,
        organization_id: UUID | None = None,
        series_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Bind code-owned route intent while retaining every original submitted value.

        Parameters
        ----------
        *args : Any
            Standard form data, never overwritten by current preview values.
        mode : ProgrammeSetupMode
            Closed route-owned creation/reuse mode.
        organization_id : UUID | None, default=None
            Exact reused parent, never inferred from a submitted choice.
        series_id : UUID | None, default=None
            Exact same-parent series selected by the route.
        **kwargs : Any
            Standard form options, including initial original source and retry key.
        """
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.organization_id = organization_id
        self.series_id = series_id
        self.fields["organization_name"].required = (
            mode == ProgrammeSetupMode.NEW_FOUNDATION
        )
        self.fields["series_name"].required = mode != ProgrammeSetupMode.EXISTING_SERIES
        if mode != ProgrammeSetupMode.NEW_FOUNDATION:
            self.fields["organization_name"].widget = forms.HiddenInput()
        if mode == ProgrammeSetupMode.EXISTING_SERIES:
            self.fields["series_name"].widget = forms.HiddenInput()

    def setup_input(self) -> ProgrammeSetupInput:
        """Produce closed normalized intent from a successfully validated form.

        Returns
        -------
        ProgrammeSetupInput
            The exact original request for the owning atomic setup command.
        """
        data = self.cleaned_data
        return normalize_programme_setup_input(
            ProgrammeSetupInput(
                mode=self.mode,
                edition_name=str(data["edition_name"]),
                department_name=str(data["department_name"]),
                starts_on=cast("date", data["starts_on"]),
                ends_on=cast("date", data["ends_on"]),
                time_zone=str(data["time_zone"]),
                reason=str(data["reason"]),
                organization_name=str(data["organization_name"]),
                series_name=str(data["series_name"]),
                organization_id=self.organization_id,
                series_id=self.series_id,
                foundation_fingerprint=str(data["foundation_fingerprint"]),
            )
        )

    def clean(self) -> dict[str, Any] | None:
        """Reject unsupported intervals and mode-inapplicable values before commands.

        Returns
        -------
        dict[str, Any] | None
            Standard cleaned values when complete, retaining original input on error.

        Raises
        ------
        forms.ValidationError
            For a nil retry identity or invalid closed creation intent.
        """
        cleaned = super().clean()
        if cleaned is not None and not self.errors:
            if cleaned["idempotency_key"].int == 0:
                raise forms.ValidationError(
                    {"idempotency_key": "Use a non-empty original retry identity."}
                )
            self.setup_input()
        return cleaned
