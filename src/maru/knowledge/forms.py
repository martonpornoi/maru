"""Closed native Guidance inputs with visible choices and retained retry intent."""

from __future__ import annotations

from typing import Any, cast

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    HttpsURLField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.core.localization import language_labels

from .catalog import MAX_BODY, MAX_NOTE, MAX_TITLE, PLACEMENTS
from .contracts import GuidanceDraftInput, GuidanceOptions, GuidanceSettingsInput

PLACEMENT_LABELS = {
    "knowledge.compose": "Writing guides",
    "announcements.compose": "Writing announcements",
}


class RequestForm(StrictInputForm):
    """Carry one actor's retry identity without accepting actor or scope input."""

    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)


class CommandForm(RequestForm):
    """Keep the item or settings version from the original rendered form."""

    expected_version = StrictBase10IntegerField(widget=forms.HiddenInput)


class DraftForm(CommandForm):
    """Write plain text with fixed ownership and optional unfinished review date."""

    title = forms.CharField(label="Title", max_length=MAX_TITLE)
    body = forms.CharField(
        label="Guide text",
        max_length=MAX_BODY,
        widget=forms.Textarea(attrs={"rows": 12}),
    )
    language_code = forms.ChoiceField(label="Language")
    review_by = forms.DateField(
        label="Review by",
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="You can save without a date. Set one before asking for review.",
    )
    placements = forms.MultipleChoiceField(
        label="Where to show this guide",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=(
            "Optional. Approved guides are always available in the Guides library."
        ),
    )
    expected_settings_version = StrictBase10IntegerField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="What changed and why?",
        max_length=MAX_NOTE,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args: Any,
        options: GuidanceOptions,
        editing: bool = False,
        **kwargs: Any,
    ) -> None:
        """Use only current admitted choices while retaining original retry values.

        Parameters
        ----------
        *args : Any
            Original submitted values, if any.
        options : GuidanceOptions
            Owner-admitted locale and placement choices.
        editing : bool, default=False
            Whether a saved revision requires an explanation.
        **kwargs : Any
            Standard form options, including original initial values.
        """
        super().__init__(*args, **kwargs)
        names = language_labels()
        languages = [(code, names.get(code, code)) for code in options.language_codes]
        original = (self.data if self.is_bound else self.initial).get(
            "language_code", ""
        )
        if original and original not in options.language_codes and original in names:
            languages.append((original, f"{names[original]} (no longer configured)"))
        cast("forms.ChoiceField", self.fields["language_code"]).choices = [
            ("", "Choose a language"),
            *languages,
        ]
        if editing or (
            len(options.language_codes) == 1
            and original in ("", options.language_codes[0])
        ):
            self.fields["language_code"].widget = forms.HiddenInput()
            if not self.is_bound and len(options.language_codes) == 1:
                self.initial.setdefault("language_code", options.language_codes[0])
        choices = [(code, PLACEMENT_LABELS[code]) for code in options.placement_codes]
        if self.is_bound:
            retained = (
                self.data.getlist("placements")
                if hasattr(self.data, "getlist")
                else self.data.get("placements", ())
            )
        else:
            retained = self.initial.get("placements", ())
        choices.extend(
            (code, f"{PLACEMENT_LABELS[code]} (no longer available)")
            for code in retained
            if code in PLACEMENTS and code not in options.placement_codes
        )
        cast("forms.MultipleChoiceField", self.fields["placements"]).choices = choices
        self.fields["reason"].required = editing
        if not editing:
            self.fields["reason"].widget = forms.HiddenInput()

    def clean_placements(self) -> list[str]:
        """Reject repeated selections instead of changing the caller's intent.

        Returns
        -------
        list[str]
            Explicit selected placements, in submitted order.

        Raises
        ------
        forms.ValidationError
            If one placement is submitted more than once.
        """
        values = cast("list[str]", self.cleaned_data["placements"])
        if len(values) != len(set(values)):
            raise forms.ValidationError("Choose each task only once.")
        return values

    def draft_input(self) -> GuidanceDraftInput:
        """Return the explicit draft without inferred ownership or approval.

        Returns
        -------
        GuidanceDraftInput
            Validated plain text and reviewed metadata.
        """
        data = self.cleaned_data
        return GuidanceDraftInput(
            title=data["title"],
            body=data["body"],
            language_code=data["language_code"],
            review_by=data["review_by"],
            placements=tuple(data["placements"]),
        )


class SettingsForm(CommandForm):
    """Record actual organizational rules without inventing a disposal policy."""

    policy_name = forms.CharField(
        label="Name of the record-keeping rules", max_length=200
    )
    record_owner = forms.CharField(
        label="Who looks after these records?", max_length=200
    )
    review_on = forms.DateField(
        label="Review these rules by",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    policy_url = HttpsURLField(
        label="Link to the rules", max_length=2000, required=False
    )
    policy_description = forms.CharField(
        label="Record-keeping rules",
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=(
            "Link to the rules or describe how records, private feedback and "
            "exports are kept and who may access them."
        ),
    )
    confirmed = forms.BooleanField(
        label="I confirm these are our current record-keeping rules."
    )

    def clean(self) -> dict[str, Any] | None:
        """Keep a missing rules reference actionable at its visible input.

        Returns
        -------
        dict[str, Any] | None
            Original validated values with any associated field error.
        """
        data = super().clean()
        if (
            data is not None
            and not data.get("policy_url")
            and not data.get("policy_description")
        ):
            self.add_error(
                "policy_description", "Link to or describe your record-keeping rules."
            )
        return data

    def settings_input(self) -> GuidanceSettingsInput:
        """Return only the actual organizer confirmation.

        Returns
        -------
        GuidanceSettingsInput
            Complete rules statement, independent of the fixed content owner.
        """
        data = self.cleaned_data
        return GuidanceSettingsInput(
            **{
                key: data[key]
                for key in (
                    "policy_name",
                    "record_owner",
                    "review_on",
                    "confirmed",
                    "policy_url",
                    "policy_description",
                )
            }
        )


class RequestReviewForm(CommandForm):
    """Confirm readiness for another person's exact-version review."""

    confirmed = forms.BooleanField(
        label="This text and its review date are ready for someone else to check."
    )


class ReviewForm(CommandForm):
    """Make approval's reader effect explicit and keep feedback private."""

    revision_id = CanonicalUUIDField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(
        label="Your decision",
        widget=forms.RadioSelect,
        choices=[
            ("approve", "Approve and make available"),
            ("changes_requested", "Request changes"),
        ],
    )
    note = forms.CharField(
        label="Feedback for the writers",
        max_length=MAX_NOTE,
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Private feedback is not shown to people who only read guides.",
    )
    confirmed = forms.BooleanField(
        label="I checked the exact text, review date and where it will appear."
    )

    def clean(self) -> dict[str, Any] | None:
        """Require useful feedback when requesting changes.

        Returns
        -------
        dict[str, Any] | None
            Original values with an actionable missing-feedback error.
        """
        data = super().clean()
        if (
            data
            and data.get("decision") == "changes_requested"
            and not data.get("note")
        ):
            self.add_error("note", "Explain what needs to change.")
        return data


class WithdrawForm(CommandForm):
    """Explain withdrawal while preserving the original item version."""

    reason = forms.CharField(
        label="Why are you removing this guide from readers?",
        max_length=MAX_NOTE,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirmed = forms.BooleanField(
        label="Hide this guide from readers and task pages. Its history will be kept."
    )


class ControlForm(RequestForm):
    """Bind stop or resume to the original every-command workspace sequence."""

    expected_control_version = StrictBase10IntegerField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Reason for this change",
        max_length=MAX_NOTE,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirmed = forms.BooleanField(
        label=(
            "Hide all guides from readers and pause writing and review. "
            "History will be kept."
        )
    )


class ResumeForm(ControlForm):
    """Confirm exactly the retained versions previewed for reader availability."""

    preview_digest = forms.RegexField(
        regex=r"\A[0-9a-f]{64}\Z", widget=forms.HiddenInput
    )
    confirmed = forms.BooleanField(
        label=(
            "Make exactly the listed versions available again and resume "
            "writing and review."
        )
    )
