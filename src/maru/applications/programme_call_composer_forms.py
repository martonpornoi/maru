"""Structured closed controls for new calls and the existing question graph."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import StrictBase10IntegerField

from .forms import EditionLocalDateTimeField
from .programme_call_editor import ProgrammeCallEditorInputs
from .programme_call_forms import (
    _CLASSIFICATIONS,
    _SLUG_PATTERN,
    ProgrammeCallMetadataForm,
    _policy,
)
from .programme_inputs import (
    MAX_PROGRAMME_ANSWER_LENGTH,
    ProgrammeCallConditionOperator,
    ProgrammeCallConfigurationInput,
    ProgrammeCallContributorFieldInput,
    ProgrammeCallDefinitionInput,
    ProgrammeCallFormatInput,
    ProgrammeCallQuestionConditionInput,
    ProgrammeCallQuestionInput,
    ProgrammeCallQuestionOptionInput,
    ProgrammeCallQuestionType,
    ProgrammeCallSectionInput,
    ProgrammeCallTrackInput,
    ProgrammeContributorFieldCode,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID


class ProgrammeCallCreationForm(ProgrammeCallMetadataForm):
    """Create an explicit complete starting draft without a fake source graph."""

    expected_version = StrictBase10IntegerField(
        min_value=0, max_value=0, widget=forms.HiddenInput
    )
    expected_edition_version = StrictBase10IntegerField(
        min_value=1, widget=forms.HiddenInput
    )
    code = forms.RegexField(_SLUG_PATTERN, max_length=80, label="Stable call code")
    opens_at = EditionLocalDateTimeField(label="Opens (inclusive)")
    applicant_edit_until = EditionLocalDateTimeField(
        label="Applicant edit deadline (inclusive)"
    )
    closes_at = EditionLocalDateTimeField(label="Closes (exclusive)")
    track_code = forms.RegexField(
        _SLUG_PATTERN, max_length=80, label="Initial track code"
    )
    track_label = forms.CharField(max_length=160, label="Initial track name")
    format_code = forms.RegexField(
        _SLUG_PATTERN, max_length=80, label="Initial format code"
    )
    format_label = forms.CharField(max_length=160, label="Initial format name")
    minimum_duration_minutes = StrictBase10IntegerField(min_value=1, max_value=1440)
    default_duration_minutes = StrictBase10IntegerField(min_value=1, max_value=1440)
    maximum_duration_minutes = StrictBase10IntegerField(min_value=1, max_value=1440)
    confirm = forms.BooleanField(
        label=(
            "Create this draft with the displayed title/description questions "
            "and contributor-name policy."
        )
    )

    def __init__(self, *args: Any, edition_time_zone: str, **kwargs: Any) -> None:
        """Interpret new deadlines only in the independently resolved edition zone.

        Parameters
        ----------
        *args : Any
            Framework arguments, including optional submitted fields.
        edition_time_zone : str
            Trusted edition IANA zone, never supplied by the request.
        **kwargs : Any
            Framework keywords and original retry/edition evidence.
        """
        super().__init__(*args, **kwargs)
        for name in ("opens_at", "applicant_edit_until", "closes_at"):
            cast("EditionLocalDateTimeField", self.fields[name]).set_zone(
                edition_time_zone
            )

    def call_inputs(self, *, owner_department_id: UUID) -> ProgrammeCallEditorInputs:
        """Construct the explicitly confirmed initial owner graph.

        Parameters
        ----------
        owner_department_id : UUID
            Independently authorized route scope, not a submitted field.

        Returns
        -------
        ProgrammeCallEditorInputs
            Complete validated definition and configuration for one new Draft.

        """
        values = self.cleaned_data
        definition_names = (
            "code",
            "name",
            "description",
            "purpose",
            "classification",
            "maximum_submissions_per_person",
            "opens_at",
            "closes_at",
            "applicant_edit_until",
            "audience_policy_code",
            "retention_policy_code",
        )
        configuration_names = (
            "maximum_collaborators",
            "content_policy_code",
            "contributor_consent_policy_code",
            "collaboration_retention_policy_code",
        )
        questions = tuple(
            ProgrammeCallQuestionInput(
                key=key,
                label=label,
                field_type=field_type,
                position=position,
                help_text="",
                required=True,
                options=(),
                minimum_length=None,
                maximum_length=None,
                minimum_value=None,
                maximum_value=None,
                maximum_choices=None,
                reference_kind="",
                condition=None,
                purpose="Understand and review the proposed Programme item.",
                classification=values["classification"],
                retention_policy_code="",
            )
            for position, (key, label, field_type) in enumerate(
                (
                    ("title", "Proposed title", "short_text"),
                    ("description", "Proposal description", "long_text"),
                ),
                1,
            )
        )
        definition = ProgrammeCallDefinitionInput(
            **{name: values[name] for name in definition_names},
            sections=(
                ProgrammeCallSectionInput(
                    "programme-proposal", "Programme proposal", "", 1, questions
                ),
            ),
        )
        configuration = ProgrammeCallConfigurationInput(
            **{name: values[name] for name in configuration_names},
            owner_department_id=owner_department_id,
            tracks=(
                ProgrammeCallTrackInput(
                    values["track_code"], values["track_label"], "", 1
                ),
            ),
            formats=(
                ProgrammeCallFormatInput(
                    code=values["format_code"],
                    label=values["format_label"],
                    description="",
                    position=1,
                    minimum_duration_minutes=values["minimum_duration_minutes"],
                    default_duration_minutes=values["default_duration_minutes"],
                    maximum_duration_minutes=values["maximum_duration_minutes"],
                ),
            ),
            contributor_fields=(
                ProgrammeCallContributorFieldInput(
                    field_code=ProgrammeContributorFieldCode.PUBLIC_NAME,
                    lead_requirement="required",
                    collaborator_requirement="optional",
                    position=1,
                ),
            ),
        )
        return ProgrammeCallEditorInputs(definition, configuration)


class ProgrammeQuestionOptionForm(forms.Form):
    """Collect one choice option without delimiter or open-JSON parsing."""

    code = forms.RegexField(_SLUG_PATTERN, max_length=80, label="Stable option code")
    label = forms.CharField(max_length=160, label="Option label")


if TYPE_CHECKING:
    _OptionFormSetBase = forms.BaseFormSet[ProgrammeQuestionOptionForm]
else:
    _OptionFormSetBase = forms.BaseFormSet


class _ProgrammeQuestionOptionFormSet(_OptionFormSetBase):
    """Name draft-option removal before validation constructs bound controls."""

    def add_fields(self, form: ProgrammeQuestionOptionForm, index: int | None) -> None:
        """Keep Django's deletion semantics with an explicit task label.

        Parameters
        ----------
        form : ProgrammeQuestionOptionForm
            The option row receiving its framework-managed deletion field.
        index : int | None
            Its bounded offset, or no offset for an empty form template.
        """
        super().add_fields(form, index)
        form.fields["DELETE"].label = "Remove this option from the draft"


ProgrammeQuestionOptions = forms.formset_factory(
    ProgrammeQuestionOptionForm,
    formset=_ProgrammeQuestionOptionFormSet,
    extra=2,
    max_num=100,
    absolute_max=100,
    validate_max=True,
    can_delete=True,
)


class ProgrammeSectionForm(forms.Form):
    """Collect section metadata; existing questions are never transport fields."""

    key = forms.RegexField(_SLUG_PATTERN, max_length=80, label="Stable section key")
    title = forms.CharField(max_length=160, label="Section title")
    help_text = forms.CharField(
        max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    position = StrictBase10IntegerField(min_value=1, max_value=100)


class ProgrammeQuestionForm(forms.Form):
    """Collect one complete typed question using exact earlier-question choices."""

    key = forms.RegexField(_SLUG_PATTERN, max_length=80, label="Stable question key")
    field_type = forms.ChoiceField(
        label="Answer type",
        choices=[("", "Choose an answer type")]
        + [
            (item.value, item.name.replace("_", " ").title())
            for item in ProgrammeCallQuestionType
        ],
    )
    label = forms.CharField(max_length=200, label="Question label")
    help_text = forms.CharField(
        max_length=2000, required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    position = StrictBase10IntegerField(min_value=1, max_value=500)
    destination_section = forms.ChoiceField(
        required=False,
        choices=[("", "Keep this section")],
        help_text=(
            "Moving a question must leave its source section nonempty "
            "and preserve all earlier-answer conditions."
        ),
    )
    required = forms.BooleanField(
        required=False, label="An applicable answer is required"
    )
    purpose = forms.CharField(max_length=500, label="Why this answer is collected")
    classification = forms.ChoiceField(choices=_CLASSIFICATIONS)
    retention_policy_code = _policy("Answer retention policy", required=False)
    minimum_length = StrictBase10IntegerField(
        min_value=0, max_value=MAX_PROGRAMME_ANSWER_LENGTH, required=False
    )
    maximum_length = StrictBase10IntegerField(
        min_value=0, max_value=MAX_PROGRAMME_ANSWER_LENGTH, required=False
    )
    minimum_value = forms.DecimalField(max_digits=18, decimal_places=4, required=False)
    maximum_value = forms.DecimalField(max_digits=18, decimal_places=4, required=False)
    maximum_choices = StrictBase10IntegerField(
        min_value=1, max_value=100, required=False
    )
    reference_kind = forms.RegexField(
        r"^[a-z][a-z0-9_.:-]{0,79}$",
        max_length=80,
        required=False,
        help_text=(
            "Exact registered kind for a reference answer only; "
            "use programme.person for a person reference. This private mention "
            "creates no contributor, host or public-profile relationship. "
            "Other kinds require their own registered selection and viewer."
        ),
    )
    condition_question = forms.ChoiceField(
        required=False, label="Show only when an earlier answer matches"
    )
    condition_operator = forms.ChoiceField(
        required=False,
        choices=[("", "No condition")]
        + [
            (item.value, item.name.replace("_", " ").title())
            for item in ProgrammeCallConditionOperator
        ],
    )
    condition_value = forms.CharField(
        required=False,
        max_length=160,
        strip=False,
        help_text=(
            "Use the option's stable code, exact text, a whole number, "
            "or true/false for a boolean answer."
        ),
    )

    def __init__(
        self,
        *args: Any,
        earlier_questions: tuple[ProgrammeCallQuestionInput, ...],
        **kwargs: Any,
    ) -> None:
        """Bind condition choices from the authorized original graph only.

        Parameters
        ----------
        *args : Any
            Framework form arguments, including submitted values.
        earlier_questions : tuple[ProgrammeCallQuestionInput, ...]
            Exact candidate earlier sources; final graph validation rechecks order.
        **kwargs : Any
            Framework keywords, including prefix and original initial values.
        """
        super().__init__(*args, **kwargs)
        self.earlier_questions = {
            question.key: question for question in earlier_questions
        }
        field = self.fields["condition_question"]
        if isinstance(field, forms.ChoiceField):
            field.choices = [("", "Always show this question")] + [
                (question.key, f"{question.label} ({question.key})")
                for question in earlier_questions
                if question.field_type
                in {
                    "short_text",
                    "long_text",
                    "email",
                    "phone",
                    "url",
                    "boolean",
                    "integer",
                    "single_choice",
                    "multiple_choice",
                }
            ]

    def question_input(
        self, options: tuple[ProgrammeCallQuestionOptionInput, ...]
    ) -> ProgrammeCallQuestionInput:
        """Compose the closed owner input after both scalar and option validation.

        Parameters
        ----------
        options : tuple[ProgrammeCallQuestionOptionInput, ...]
            Complete validated option rows in their displayed order.

        Returns
        -------
        ProgrammeCallQuestionInput
            Typed question awaiting final whole-graph composition.

        """
        values = self.cleaned_data
        condition = _condition_input(values, self.earlier_questions)
        names = (
            "key",
            "field_type",
            "label",
            "help_text",
            "position",
            "required",
            "purpose",
            "classification",
            "retention_policy_code",
            "minimum_length",
            "maximum_length",
            "minimum_value",
            "maximum_value",
            "maximum_choices",
            "reference_kind",
        )
        return ProgrammeCallQuestionInput(
            **{name: values[name] for name in names},
            options=options,
            condition=condition,
        )


def _condition_input(
    values: Mapping[str, Any], earlier: Mapping[str, ProgrammeCallQuestionInput]
) -> ProgrammeCallQuestionConditionInput | None:
    key = values["condition_question"]
    operator = values["condition_operator"]
    raw = values["condition_value"]
    if not key:
        if operator or raw:
            raise ValidationError(
                "Choose an earlier question or clear all condition fields."
            )
        return None
    source = earlier.get(key)
    if source is None or not operator:
        raise ValidationError(
            "Choose one available earlier question and its comparison."
        )
    value: str | bool | int = raw
    if source.field_type == "boolean":
        if raw not in {"true", "false"}:
            raise ValidationError("A boolean condition must use exactly true or false.")
        value = raw == "true"
    elif source.field_type == "integer":
        if re.fullmatch(r"(?:0|-?[1-9][0-9]{0,9})", raw) is None:
            raise ValidationError("Use one canonical signed 32-bit whole number.")
        value = int(raw)
        if not -(2**31) <= value < 2**31:
            raise ValidationError("Use one canonical signed 32-bit whole number.")
    return ProgrammeCallQuestionConditionInput(key, operator, value)
