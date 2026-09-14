"""Closed personal intake forms using the existing Programme typed inputs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import StrictBase10IntegerField

from .programme_call_forms import ProgrammeCallTaskForm, _apply_errors
from .programme_inputs import (
    ProgrammeProposalContributorProfileInput,
    ProgrammeProposalSelectionInput,
)

if TYPE_CHECKING:
    from .programme_queries import AvailableProgrammeCallProjection

_PROFILE_FIELDS = {
    "public_name": ("My proposed public name", 160),
    "biography": ("My proposed biography", 4000),
    "pronouns": ("My proposed pronouns", 160),
    "website": ("My proposed website", 500),
}


class ProgrammeProposalStartForm(ProgrammeCallTaskForm):
    """Start only the current person's private proposal against an exact call."""

    expected_version = StrictBase10IntegerField(
        min_value=0, max_value=0, widget=forms.HiddenInput
    )
    expected_call_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )
    expected_definition_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )
    track = forms.ChoiceField(label="Track")
    format = forms.ChoiceField(label="Format")
    duration = StrictBase10IntegerField(
        label="Requested duration in whole minutes", min_value=1, max_value=1440
    )
    publication_choice = forms.ChoiceField(
        label="Do I propose my populated profile values for later publication?",
        choices=(
            ("", "Choose explicitly"),
            ("no", "No — save a blank, non-public profile for now"),
            ("yes", "Yes — propose my values for later review"),
        ),
    )
    consent_acknowledged = forms.BooleanField(required=False)
    confirm = forms.BooleanField(label="Start my private draft, not a submission")

    def __init__(
        self, *args: Any, source: AvailableProgrammeCallProjection, **kwargs: Any
    ) -> None:
        """Build labelled choices and only the call's lead-visible profile fields.

        Parameters
        ----------
        *args : Any
            Framework arguments including optional bound input.
        source : AvailableProgrammeCallProjection
            Independently authorized immutable call collection policy.
        **kwargs : Any
            Framework keywords including original command evidence.

        Raises
        ------
        ValueError
            If the supplied profile field catalog is unknown or duplicated.
        """
        super().__init__(*args, **kwargs)
        self.source = source
        self.selection: ProgrammeProposalSelectionInput | None = None
        self.profile: ProgrammeProposalContributorProfileInput | None = None
        cast("forms.ChoiceField", self.fields["track"]).choices = (
            ("", "Choose the track"),
            *(
                (str(row.track_id), f"{row.label} ({row.code})")
                for row in source.tracks
            ),
        )
        cast("forms.ChoiceField", self.fields["format"]).choices = (
            ("", "Choose the format"),
            *(
                (str(row.format_id), f"{row.label} ({row.code})")
                for row in source.formats
            ),
        )
        self.fields["consent_acknowledged"].label = (
            "I have reviewed and acknowledge the organizer-supplied contributor "
            f"policy {source.contributor_consent_policy_code}"
        )
        visible = []
        for row in source.contributor_fields:
            if row.lead_requirement == "hidden":
                continue
            if row.field_code not in _PROFILE_FIELDS or row.field_code in visible:
                raise ValueError
            label, maximum = _PROFILE_FIELDS[row.field_code]
            self.fields[row.field_code] = forms.CharField(
                label=label,
                max_length=maximum,
                required=False,
                widget=forms.Textarea(attrs={"rows": 4})
                if row.field_code == "biography"
                else forms.TextInput,
                help_text=(
                    "Required before sealing; a blank private draft is allowed."
                    if row.lead_requirement == "required"
                    else "Optional proposed-public value, not your account profile."
                ),
            )
            visible.append(row.field_code)
        self.order_fields(
            [
                "track",
                "format",
                "duration",
                *visible,
                "publication_choice",
                "consent_acknowledged",
                "reason",
                "confirm",
            ]
        )

    def clean(self) -> dict[str, Any]:
        """Normalize selection and subject-owned consent without inventing values.

        Returns
        -------
        dict[str, Any]
            Validated fields while retaining original bound input on refusal.
        """
        values = super().clean() or {}
        if self.errors:
            return values
        selected = next(
            row for row in self.source.formats if str(row.format_id) == values["format"]
        )
        if not (
            selected.minimum_duration_minutes
            <= values["duration"]
            <= selected.maximum_duration_minutes
        ):
            self.add_error(
                "duration",
                f"Use {selected.minimum_duration_minutes} to "
                f"{selected.maximum_duration_minutes} whole minutes for this format.",
            )
            return values
        try:
            self.selection = ProgrammeProposalSelectionInput(
                UUID(values["track"]), UUID(values["format"]), values["duration"]
            )
            self.profile = ProgrammeProposalContributorProfileInput(
                **{name: values.get(name, "") for name in _PROFILE_FIELDS},
                proposed_for_publication=values["publication_choice"] == "yes",
                consent_acknowledged=values["consent_acknowledged"],
                consent_policy_code=self.source.contributor_consent_policy_code,
            )
        except ValidationError as error:
            _apply_errors(self, error)
        return values


__all__ = ["ProgrammeProposalStartForm"]
