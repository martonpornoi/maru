"""Closed Programme call task forms; no ORM lookups or generic call writers."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import StrictBase10IntegerField

from .forms import EditionLocalDateTimeField, RetryForm
from .programme_call_editor import ProgrammeCallEditorInputs
from .programme_inputs import (
    ProgrammeCallContributorFieldInput,
    ProgrammeCallFormatInput,
    ProgrammeCallTrackInput,
    normalized_programme_text,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

_POLICY_PATTERN = r"^[a-z][a-z0-9_.:-]{2,119}$"
_SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
_CLASSIFICATIONS = (
    ("", "Choose the information classification"),
    ("C1", "C1 - Internal"),
    ("C2", "C2 - Personal"),
    ("C3", "C3 - Restricted"),
)
_REQUIREMENTS = (
    ("", "Choose collection requirement"),
    ("hidden", "Do not collect"),
    ("optional", "Optional"),
    ("required", "Required"),
)


def _policy(label: str, *, required: bool = True) -> forms.RegexField:
    return forms.RegexField(
        _POLICY_PATTERN,
        label=label,
        max_length=120,
        required=required,
        help_text="Exact documented policy code; this does not create a policy.",
    )


def _apply_errors(form: forms.Form, error: ValidationError) -> None:
    if hasattr(error, "error_dict"):
        for name, errors in error.error_dict.items():
            form.add_error(name if name in form.fields else None, errors)
    else:
        form.add_error(None, error)


class ProgrammeCallTaskForm(RetryForm):
    """Retain original command evidence while rejecting hidden scope overrides."""

    expected_version = StrictBase10IntegerField(widget=forms.HiddenInput)
    reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Retained with this change. Avoid unnecessary personal information.",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Present task values before their rationale and final confirmation.

        Parameters
        ----------
        *args : Any
            Framework arguments including optional bound input.
        **kwargs : Any
            Framework keywords including original command evidence.
        """
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                *(name for name in self.fields if name not in {"reason", "confirm"}),
                "reason",
                "confirm",
            ]
        )

    def clean_reason(self) -> str:
        """Normalize the inspectable reason using the existing owner contract.

        Returns
        -------
        str
            Nonempty, bounded reason without unsupported controls.

        Raises
        ------
        ValidationError
            If the reason violates the owner's text contract.
        """
        try:
            return normalized_programme_text(
                self.cleaned_data["reason"],
                field="reason",
                maximum=500,
                required=True,
                collapse=True,
            )
        except ValidationError as error:
            raise ValidationError(error.error_dict["reason"]) from error


class ProgrammeCallDetailsForm(ProgrammeCallTaskForm):
    """Edit metadata and policy while retaining the entire authorized form graph."""

    name = forms.CharField(label="Call name", max_length=160)
    description = forms.CharField(
        label="Call guidance",
        max_length=4000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    purpose = forms.CharField(label="Why these proposals are collected", max_length=500)
    classification = forms.ChoiceField(choices=_CLASSIFICATIONS)
    maximum_submissions_per_person = StrictBase10IntegerField(
        min_value=1, max_value=100
    )
    audience_policy_code = _policy("Audience policy", required=False)
    retention_policy_code = _policy("Proposal retention policy", required=False)
    maximum_collaborators = StrictBase10IntegerField(min_value=0, max_value=16)
    content_policy_code = _policy("Proposal content policy")
    contributor_consent_policy_code = _policy("Contributor consent policy")
    collaboration_retention_policy_code = _policy(
        "Collaboration evidence retention policy"
    )

    def __init__(
        self,
        *args: Any,
        inputs: ProgrammeCallEditorInputs,
        **kwargs: Any,
    ) -> None:
        """Bind an exact complete source without changing its deadlines.

        Parameters
        ----------
        *args : Any
            Framework form arguments, including optional submitted input.
        inputs : ProgrammeCallEditorInputs
            Complete source already fenced to the original draft cursor.
        **kwargs : Any
            Framework keyword arguments, including initial command evidence.
        """
        self.source_inputs = inputs
        self.result: ProgrammeCallEditorInputs | None = None
        super().__init__(*args, **kwargs)
        for name in self.fields:
            for source in (inputs.definition, inputs.configuration):
                if hasattr(source, name):
                    self.initial.setdefault(name, getattr(source, name))

    def clean(self) -> dict[str, Any]:
        """Validate the whole resulting graph, not only individual form fields.

        Returns
        -------
        dict[str, Any]
            Strict submitted fields with original retry identity and cursor.
        """
        cleaned = super().clean() or {}
        if self.errors:
            return cleaned
        definition_names = (
            "name",
            "description",
            "purpose",
            "classification",
            "maximum_submissions_per_person",
            "audience_policy_code",
            "retention_policy_code",
        )
        configuration_names = (
            "maximum_collaborators",
            "content_policy_code",
            "contributor_consent_policy_code",
            "collaboration_retention_policy_code",
        )
        try:
            self.result = ProgrammeCallEditorInputs(
                replace(
                    self.source_inputs.definition,
                    **{name: cleaned[name] for name in definition_names},
                ),
                replace(
                    self.source_inputs.configuration,
                    **{name: cleaned[name] for name in configuration_names},
                ),
            )
        except ValidationError as error:
            _apply_errors(self, error)
        return cleaned


class ProgrammeCallWindowForm(ProgrammeCallTaskForm):
    """Deliberately replace all three call deadlines in the edition's local zone."""

    expected_edition_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )
    opens_at = EditionLocalDateTimeField(label="Opens (inclusive)")
    applicant_edit_until = EditionLocalDateTimeField(
        label="Applicant edit deadline (inclusive)"
    )
    closes_at = EditionLocalDateTimeField(label="Closes (exclusive)")
    confirm = forms.BooleanField(
        label="Replace these deadlines with the whole-minute times shown."
    )

    def __init__(
        self,
        *args: Any,
        inputs: ProgrammeCallEditorInputs,
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        """Bind explicit local-time controls to one complete draft source.

        Parameters
        ----------
        *args : Any
            Framework form arguments, including optional submitted input.
        inputs : ProgrammeCallEditorInputs
            Complete source already fenced to the original draft cursor.
        edition_time_zone : str
            Edition-owned IANA zone, never a submitted override.
        **kwargs : Any
            Framework keyword arguments and original command evidence.
        """
        self.source_inputs = inputs
        self.result: ProgrammeCallEditorInputs | None = None
        super().__init__(*args, **kwargs)
        for name in ("opens_at", "applicant_edit_until", "closes_at"):
            cast("EditionLocalDateTimeField", self.fields[name]).set_zone(
                edition_time_zone
            )
            self.initial.setdefault(name, getattr(inputs.definition, name))

    def clean(self) -> dict[str, Any]:
        """Validate the explicitly replaced window through the owner's graph.

        Returns
        -------
        dict[str, Any]
            Parsed local instants and original command evidence.
        """
        cleaned = super().clean() or {}
        if not self.errors:
            try:
                self.result = replace(
                    self.source_inputs,
                    definition=replace(
                        self.source_inputs.definition,
                        opens_at=cleaned["opens_at"],
                        applicant_edit_until=cleaned["applicant_edit_until"],
                        closes_at=cleaned["closes_at"],
                    ),
                )
            except ValidationError as error:
                _apply_errors(self, error)
        return cleaned


class ProgrammeCallTrackForm(ProgrammeCallTaskForm):
    """Describe one track with a stable code and explicit keyboard-editable order."""

    code = forms.RegexField(
        _SLUG_PATTERN,
        max_length=80,
        help_text="Stable lower-case code using words separated by hyphens.",
    )
    label = forms.CharField(label="Track name", max_length=160)
    description = forms.CharField(
        required=False, max_length=4000, widget=forms.Textarea(attrs={"rows": 3})
    )
    position = StrictBase10IntegerField(min_value=1, max_value=64)

    def clean(self) -> dict[str, Any]:
        """Validate one typed track before whole-catalog composition.

        Returns
        -------
        dict[str, Any]
            Validated transport and normalized track fields.
        """
        cleaned = super().clean() or {}
        if not self.errors:
            try:
                row = self.track_input(cleaned)
                for name in ("code", "label", "description", "position"):
                    cleaned[name] = getattr(row, name)
            except ValidationError as error:
                _apply_errors(self, error)
        return cleaned

    @staticmethod
    def track_input(values: Mapping[str, Any]) -> ProgrammeCallTrackInput:
        """Construct the owner's track value without adding scope or authority.

        Parameters
        ----------
        values : Mapping[str, Any]
            Parsed fields from this closed form.

        Returns
        -------
        ProgrammeCallTrackInput
            Immutable validated track with explicit requested position.
        """
        return ProgrammeCallTrackInput(
            values["code"], values["label"], values["description"], values["position"]
        )


class ProgrammeCallFormatForm(ProgrammeCallTrackForm):
    """Describe one format and its explicit minimum, default and maximum duration."""

    label = forms.CharField(label="Format name", max_length=160)
    position = StrictBase10IntegerField(min_value=1, max_value=32)
    minimum_duration_minutes = StrictBase10IntegerField(min_value=1, max_value=1440)
    default_duration_minutes = StrictBase10IntegerField(min_value=1, max_value=1440)
    maximum_duration_minutes = StrictBase10IntegerField(min_value=1, max_value=1440)

    def clean(self) -> dict[str, Any]:
        """Validate duration ordering through the existing typed format contract.

        Returns
        -------
        dict[str, Any]
            Normalized fields without inventing or clamping a duration.
        """
        cleaned = super().clean() or {}
        if not self.errors:
            try:
                self.format_input(cleaned)
            except ValidationError as error:
                _apply_errors(self, error)
        return cleaned

    @staticmethod
    def format_input(values: Mapping[str, Any]) -> ProgrammeCallFormatInput:
        """Construct the owner's immutable format from this form's fields.

        Parameters
        ----------
        values : Mapping[str, Any]
            Parsed fields from this closed form.

        Returns
        -------
        ProgrammeCallFormatInput
            Validated catalog entry with ordered duration bounds.
        """
        return ProgrammeCallFormatInput(
            values["code"],
            values["label"],
            values["description"],
            values["position"],
            values["minimum_duration_minutes"],
            values["default_duration_minutes"],
            values["maximum_duration_minutes"],
        )


class ProgrammeCallContributorFieldForm(ProgrammeCallTaskForm):
    """Configure collection policy, never another contributor's own profile."""

    field_code = forms.ChoiceField(
        choices=(
            ("", "Choose proposed-public field"),
            ("public_name", "Public display name"),
            ("biography", "Biography"),
            ("pronouns", "Pronouns"),
            ("website", "Website"),
        )
    )
    lead_requirement = forms.ChoiceField(choices=_REQUIREMENTS)
    collaborator_requirement = forms.ChoiceField(choices=_REQUIREMENTS)
    position = StrictBase10IntegerField(min_value=1, max_value=4)

    def clean(self) -> dict[str, Any]:
        """Reject unsupported or entirely hidden declarations.

        Returns
        -------
        dict[str, Any]
            Closed contributor policy fields; whole-graph checks still follow.
        """
        cleaned = super().clean() or {}
        if not self.errors:
            try:
                self.contributor_field_input(cleaned)
            except ValidationError as error:
                _apply_errors(self, error)
        return cleaned

    @staticmethod
    def contributor_field_input(
        values: Mapping[str, Any],
    ) -> ProgrammeCallContributorFieldInput:
        """Construct a collection-policy declaration without any person's values.

        Parameters
        ----------
        values : Mapping[str, Any]
            Parsed fields from this closed form.

        Returns
        -------
        ProgrammeCallContributorFieldInput
            Validated purpose field with independent lead/collaborator policy.
        """
        return ProgrammeCallContributorFieldInput(
            values["field_code"],
            values["lead_requirement"],
            values["collaborator_requirement"],
            values["position"],
        )


class ProgrammeCallConfirmationForm(ProgrammeCallTaskForm):
    """Require a deliberate confirmation of the separately explained consequence."""

    confirm = forms.BooleanField(
        label="I confirm the action and consequence described above."
    )
