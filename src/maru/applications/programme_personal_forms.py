"""Closed task forms for proposal editing and explicit relationship decisions."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.core.forms import CanonicalUUIDField, StrictBase10IntegerField

from .forms import _answer_field
from .programme_call_forms import ProgrammeCallTaskForm, _apply_errors
from .programme_inputs import (
    ProgrammeProposalContributorProfileInput,
    ProgrammeProposalInvitationInput,
    ProgrammeProposalSelectionInput,
)
from .programme_proposal_forms import _PROFILE_FIELDS

if TYPE_CHECKING:
    from .models import ApplicationQuestion
    from .programme_personal_queries import ProgrammePersonalWorkflow
    from .programme_queries import (
        ProgrammeProposalDetailProjection,
        ProgrammeQuestionProjection,
    )

_REFERENCE_TYPES = frozenset({"person_reference", "domain_reference", "safe_file"})
_ADDRESS_FIELDS = {
    "line_1": "Address line 1",
    "line_2": "Address line 2",
    "locality": "City or locality",
    "region": "Region",
    "postal_code": "Postal code",
    "country_code": "Two-letter country code",
}


class ProgrammePersonalTaskForm(ProgrammeCallTaskForm):
    """Retain original proposal and call-source fences with explicit confirmation."""

    expected_version = StrictBase10IntegerField(min_value=1, widget=forms.HiddenInput)
    expected_call_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )
    expected_definition_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )
    confirm = forms.BooleanField(label="Confirm this exact change")


class ProgrammePersonalSelectionForm(ProgrammePersonalTaskForm):
    """Collect a lead's labelled selection without changing other proposal layers."""

    track = forms.ChoiceField(label="Track")
    format = forms.ChoiceField(label="Format")
    duration = StrictBase10IntegerField(
        label="Duration in whole minutes", min_value=1, max_value=1440
    )

    def __init__(
        self, *args: Any, context: ProgrammePersonalWorkflow, **kwargs: Any
    ) -> None:
        """Use only the independently authorized exact call's complete choices.

        Parameters
        ----------
        *args : Any
            Framework arguments, including original bound request input.
        context : ProgrammePersonalWorkflow
            Lead-only authorized catalog and source versions.
        **kwargs : Any
            Framework keywords, including initial evidence.
        """
        super().__init__(*args, **kwargs)
        self.context = context
        self.selection: ProgrammeProposalSelectionInput | None = None
        cast("forms.ChoiceField", self.fields["track"]).choices = (
            ("", "Choose the track"),
            *(
                (str(row.track_id), f"{row.label} ({row.code})")
                for row in context.tracks
            ),
        )
        cast("forms.ChoiceField", self.fields["format"]).choices = (
            ("", "Choose the format"),
            *(
                (str(row.format_id), f"{row.label} ({row.code})")
                for row in context.formats
            ),
        )

    def clean(self) -> dict[str, Any]:
        """Normalize the selected typed owner input and exact format bounds.

        Returns
        -------
        dict[str, Any]
            Validated fields; original input remains bound after refusal.
        """
        values = super().clean() or {}
        if self.errors:
            return values
        selected = next(
            row
            for row in self.context.formats
            if str(row.format_id) == values["format"]
        )
        if (
            not selected.minimum_duration_minutes
            <= values["duration"]
            <= selected.maximum_duration_minutes
        ):
            self.add_error(
                "duration",
                f"Use {selected.minimum_duration_minutes} to "
                f"{selected.maximum_duration_minutes} whole minutes for this format.",
            )
            return values
        self.selection = ProgrammeProposalSelectionInput(
            UUID(values["track"]), UUID(values["format"]), values["duration"]
        )
        return values


class ProgrammePersonalSubmitForm(ProgrammePersonalTaskForm):
    """Confirm submission of one exact displayed seal, never the latest implicitly."""

    revision_id = CanonicalUUIDField(widget=forms.HiddenInput)


class ProgrammePersonalResponseForm(ProgrammePersonalSubmitForm):
    """Bind confirmation to the exact seal and subject-owned included profile."""

    contributor_id = CanonicalUUIDField(widget=forms.HiddenInput)
    profile_revision_id = CanonicalUUIDField(widget=forms.HiddenInput)


class ProgrammePersonalProfileForm(ProgrammePersonalTaskForm):
    """Collect only subject-owned, role-visible proposed-public profile values."""

    publication_choice = forms.ChoiceField(
        label="Do I propose these values for later publication?",
        choices=(
            ("", "Choose explicitly"),
            ("no", "No — retain a blank private profile"),
            ("yes", "Yes — propose my values for later review"),
        ),
    )
    consent_acknowledged = forms.BooleanField(required=False)

    def __init__(
        self, *args: Any, detail: ProgrammeProposalDetailProjection, **kwargs: Any
    ) -> None:
        """Build only exact-self configured fields without preselecting consent.

        Parameters
        ----------
        *args : Any
            Framework arguments, including original bound input.
        detail : ProgrammeProposalDetailProjection
            Exact-self profile requirements, current values and policy identity.
        **kwargs : Any
            Framework keywords, including source fences.

        Raises
        ------
        ValueError
            If complete exact-person profile policy is unavailable or malformed.
        """
        super().__init__(*args, **kwargs)
        if (
            detail.summary is None
            or detail.own_profile_requirements is None
            or not detail.contributor_consent_policy_code
        ):
            raise ValueError("Profile policy unavailable")
        if detail.summary.relationship not in {"lead", "collaborator"}:
            raise ValueError("Profile relationship unavailable")
        self.policy = detail.contributor_consent_policy_code
        self.profile: ProgrammeProposalContributorProfileInput | None = None
        self.fields[
            "consent_acknowledged"
        ].label = (
            f"I have reviewed and acknowledge organizer-supplied policy {self.policy}"
        )
        visible = []
        for row in detail.own_profile_requirements:
            requirement = (
                row.lead_requirement
                if detail.summary.relationship == "lead"
                else row.collaborator_requirement
            )
            if requirement == "hidden":
                continue
            if row.field_code not in _PROFILE_FIELDS or row.field_code in visible:
                raise ValueError("Invalid profile catalog")
            label, maximum = _PROFILE_FIELDS[row.field_code]
            self.fields[row.field_code] = forms.CharField(
                label=label,
                max_length=maximum,
                required=False,
                widget=forms.Textarea(attrs={"rows": 4})
                if row.field_code == "biography"
                else forms.TextInput,
                help_text="Required before sealing; blank drafts are allowed."
                if requirement == "required"
                else "Optional proposed-public value.",
            )
            visible.append(row.field_code)
        self.order_fields(
            [
                *visible,
                "publication_choice",
                "consent_acknowledged",
                "reason",
                "confirm",
            ]
        )

    def clean(self) -> dict[str, Any]:
        """Require deliberate current consent without silently erasing values.

        Returns
        -------
        dict[str, Any]
            Validated source fields, with retained input after refusal.
        """
        values = super().clean() or {}
        if self.errors:
            return values
        try:
            self.profile = ProgrammeProposalContributorProfileInput(
                **{code: values.get(code, "") for code in _PROFILE_FIELDS},
                proposed_for_publication=values["publication_choice"] == "yes",
                consent_acknowledged=values["consent_acknowledged"],
                consent_policy_code=self.policy,
            )
        except ValidationError as error:
            _apply_errors(self, error)
        return values


class ProgrammePersonalInvitationForm(ProgrammePersonalTaskForm):
    """Use a deliberate known email and an explicit offset-aware expiry."""

    email = forms.EmailField(label="Exact known Maru login email", max_length=254)
    expires_at = forms.CharField(
        label="Invitation expiry with UTC offset",
        max_length=80,
        help_text=(
            "Use YYYY-MM-DDTHH:MM+HH:MM, for example 2026-09-14T18:00+02:00. "
            "The call's edit deadline still applies."
        ),
    )

    def clean_expires_at(self) -> datetime:
        """Reject unzoned instants instead of inventing server-local time.

        Returns
        -------
        datetime
            Explicit aware invitation expiry, normalized to UTC.

        Raises
        ------
        ValidationError
            If the instant is invalid or lacks a UTC offset.
        """
        try:
            value = datetime.fromisoformat(self.cleaned_data["expires_at"])
        except ValueError as error:
            raise ValidationError("Enter a date-time with a UTC offset.") from error
        if not timezone.is_aware(value):
            raise ValidationError("Include the UTC offset; no time zone is assumed.")
        return value.astimezone(UTC)

    def invitation(self) -> ProgrammeProposalInvitationInput:
        """Build the existing typed owner input after successful form validation.

        Returns
        -------
        ProgrammeProposalInvitationInput
            Exact normalized email and aware expiry for owner revalidation.
        """
        return ProgrammeProposalInvitationInput(
            self.cleaned_data["email"], self.cleaned_data["expires_at"]
        )


class ProgrammePersonalAnswerForm(ProgrammePersonalTaskForm):
    """Reuse typed fields for one currently applicable shared applicant answer."""

    def __init__(
        self, *args: Any, question: ProgrammeQuestionProjection, **kwargs: Any
    ) -> None:
        """Create ordinary typed fields, never a raw reference-identifier editor.

        Parameters
        ----------
        *args : Any
            Framework arguments, including original bound request input.
        question : ProgrammeQuestionProjection
            Independently authorized current applicable question metadata.
        **kwargs : Any
            Framework keywords, including initial value and original evidence.

        Raises
        ------
        ValueError
            If the question needs an as-yet unavailable authorized picker.
        """
        super().__init__(*args, **kwargs)
        if question.field_type in _REFERENCE_TYPES:
            raise ValueError("An authorized reference or file chooser is required.")
        self.question = question
        self.answer: object = None
        if question.field_type == "address":
            for code, label in _ADDRESS_FIELDS.items():
                self.fields[code] = forms.CharField(
                    label=label, max_length=200, required=False
                )
        elif question.field_type == "instant":
            self.fields["value"] = forms.CharField(
                label=question.label,
                max_length=80,
                required=False,
                help_text=(
                    "Include the UTC offset, for example 2026-09-14T18:00+02:00. "
                    "No time zone is assumed."
                ),
            )
        else:
            spec = SimpleNamespace(**(asdict(question) | {"required": False}))
            self.fields["value"] = _answer_field(cast("ApplicationQuestion", spec))
            if question.field_type == "single_choice":
                cast("forms.ChoiceField", self.fields["value"]).choices = (
                    ("", "Not answered"),
                    *((row.code, row.label) for row in question.options),
                )
        self.order_fields(
            [
                *(_ADDRESS_FIELDS if question.field_type == "address" else ("value",)),
                "reason",
                "confirm",
            ]
        )

    def clean(self) -> dict[str, Any]:
        """Prepare canonical transport types; the existing owner validates values.

        Returns
        -------
        dict[str, Any]
            Bound validated fields and a typed answer ready for the owner command.
        """
        values = super().clean() or {}
        if self.errors:
            return values
        if self.question.field_type == "address":
            address = {code: values.get(code, "") for code in _ADDRESS_FIELDS}
            self.answer = address if any(address.values()) else None
            return values
        value = values.get("value")
        if value == "":
            value = None
        if isinstance(value, (Decimal, UUID)):
            value = str(value)
        elif isinstance(value, (date, datetime, time)):
            value = value.isoformat()
        self.answer = value
        return values


__all__ = [
    "ProgrammePersonalAnswerForm",
    "ProgrammePersonalInvitationForm",
    "ProgrammePersonalProfileForm",
    "ProgrammePersonalResponseForm",
    "ProgrammePersonalSelectionForm",
    "ProgrammePersonalSubmitForm",
    "ProgrammePersonalTaskForm",
]
