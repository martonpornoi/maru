"""Ordinary closed controls for unsaved review stages and deliberate policy save."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import StrictBase10IntegerField

from .forms import RetryForm
from .programme_review_documents import decode_review_policy, decode_review_stage
from .programme_review_inputs import (
    DECISION_OUTCOMES,
    MAX_REVIEW_STAGES,
    MAX_RUBRIC_CRITERIA,
    ProgrammeDecisionTemplateInput,
    _template,
)

if TYPE_CHECKING:
    from .programme_review_inputs import ProgrammeReviewPolicyInput
    from .programme_review_setup_queries import ReviewSetupQuestion

MAX_REVIEW_STATE = 512 * 1024
_YES_NO = (("", "Choose explicitly"), ("yes", "Yes"), ("no", "No"))
_CODE = r"^[a-z][a-z0-9_-]{0,39}$"
OUTCOME_LABELS = {
    "accepted": "Accepted",
    "rejected": "Rejected",
    "waitlisted": "Wait-listed",
    "revision_requested": "Revision requested",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def decode_proposed_review(value: str) -> dict[str, Any]:
    """Validate bounded unsaved state while allowing incomplete stage/template sets.

    Parameters
    ----------
    value : str
        Untrusted request-carried JSON; neither persistence nor authority.

    Returns
    -------
    dict[str, Any]
        Closed normalized stages/templates lists suitable for hidden transport.

    Raises
    ------
    ValidationError
        If shape, bounds, duplicate keys or any completed component is invalid.
    """
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_REVIEW_STATE:
        raise ValidationError("The unsaved policy state is too large.")
    try:
        document = json.loads(value, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as error:
        raise ValidationError("Use the complete unsaved policy state.") from error
    if (
        not isinstance(document, dict)
        or set(document) != {"stages", "templates"}
        or not isinstance(document["stages"], list)
        or len(document["stages"]) > MAX_REVIEW_STAGES
        or not isinstance(document["templates"], list)
        or len(document["templates"]) not in {0, len(DECISION_OUTCOMES)}
    ):
        raise ValidationError("Use the complete bounded unsaved policy state.")
    stages = [decode_review_stage(stage) for stage in document["stages"]]
    if len({stage.code for stage in stages}) != len(stages):
        raise ValidationError("Each review stage needs its own stable code.")
    templates = []
    for row in document["templates"]:
        if not isinstance(row, dict) or set(row) != {
            "outcome",
            "text",
            "acknowledgement_required",
        }:
            raise ValidationError("Use complete explicit decision templates.")
        templates.append(_template(ProgrammeDecisionTemplateInput(**row)))
    if templates and {item.outcome for item in templates} != DECISION_OUTCOMES:
        raise ValidationError("Define exactly one template for each outcome.")
    return cast(
        "dict[str, Any]",
        json.loads(
            json.dumps(
                {
                    "stages": [asdict(stage) for stage in stages],
                    "templates": [asdict(item) for item in templates],
                }
            )
        ),
    )


class ReviewProposedForm(RetryForm):
    """Retain the original optimistic intent and strictly bounded unsaved policy."""

    transport_field_names = RetryForm.transport_field_names | {"action"}
    expected_version = StrictBase10IntegerField(
        min_value=0, max_value=2**63 - 2, widget=forms.HiddenInput
    )
    proposed = forms.CharField(
        max_length=MAX_REVIEW_STATE, widget=forms.HiddenInput, strip=False
    )

    def clean_proposed(self) -> dict[str, Any]:
        """Validate request-carried components without creating any owner record.

        Returns
        -------
        dict[str, Any]
            Closed normalized proposed policy, possibly incomplete.
        """
        return decode_proposed_review(self.cleaned_data["proposed"])


class ReviewStageForm(ReviewProposedForm):
    """Collect one explicit stage with bounded rubric and labelled question choices."""

    stage_index = StrictBase10IntegerField(
        min_value=0, max_value=7, widget=forms.HiddenInput
    )
    code = forms.RegexField(_CODE, max_length=40, label="Stable stage code")
    required_reviews = StrictBase10IntegerField(
        min_value=1, max_value=16, label="Required independent reviews"
    )
    anonymous = forms.ChoiceField(
        choices=_YES_NO, label="Withhold structured contributor identity?"
    )
    discussion = forms.ChoiceField(
        choices=_YES_NO,
        label="Allow discussion after the reviewer's own complete score?",
    )
    question_keys = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple, label="Questions visible in this stage"
    )

    def __init__(
        self, *args: Any, questions: tuple[ReviewSetupQuestion, ...], **kwargs: Any
    ) -> None:
        """Bind only independently authorized configuration choices.

        Parameters
        ----------
        *args : Any
            Framework positional arguments including optional submitted data.
        questions : tuple[ReviewSetupQuestion, ...]
            Complete scoped question metadata, never submitted answers.
        **kwargs : Any
            Framework keywords including original proposed state and proof.
        """
        super().__init__(*args, **kwargs)
        self.fields["question_keys"] = forms.MultipleChoiceField(
            choices=[
                (
                    row.key,
                    f"{row.label} ({row.key}; {row.field_type}; {row.classification})",
                )
                for row in questions
            ],
            widget=forms.CheckboxSelectMultiple,
            label="Questions visible in this stage",
        )
        for index in range(MAX_RUBRIC_CRITERIA):
            prefix = f"criterion_{index}"
            self.fields[f"{prefix}_code"] = forms.RegexField(
                _CODE, max_length=40, required=False, label="Stable criterion code"
            )
            self.fields[f"{prefix}_label"] = forms.CharField(
                max_length=200, required=False, label="Criterion label"
            )
            for bound in ("minimum", "maximum"):
                self.fields[f"{prefix}_{bound}"] = StrictBase10IntegerField(
                    min_value=0,
                    max_value=10_000,
                    required=False,
                    label=f"Inclusive {bound}",
                )

    def clean(self) -> dict[str, Any] | None:
        """Validate all populated rubric rows with the canonical stage contract.

        Returns
        -------
        dict[str, Any] | None
            Clean fields plus a validated immutable stage when complete.

        Raises
        ------
        ValidationError
            If a row is partial, bounds conflict or no rubric is supplied.
        """
        values = super().clean()
        if values is None or self.errors:
            return values
        criteria = []
        for index in range(MAX_RUBRIC_CRITERIA):
            row = {
                key: values[f"criterion_{index}_{key}"]
                for key in ("code", "label", "minimum", "maximum")
            }
            if all(value in (None, "") for value in row.values()):
                continue
            if any(value in (None, "") for value in row.values()):
                raise ValidationError(
                    f"Complete every field in criterion {index + 1}, "
                    "or leave the entire row empty."
                )
            criteria.append(row)
        values["stage"] = decode_review_stage(
            {
                "code": values["code"],
                "required_reviews": values["required_reviews"],
                "criteria": criteria,
                "question_keys": values["question_keys"],
                "anonymous": values["anonymous"] == "yes",
                "discussion": values["discussion"] == "yes",
            }
        )
        return values


class ReviewTemplatesForm(ReviewProposedForm):
    """Require deliberate plain text and an explicit receipt policy per outcome."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Add closed outcome controls without template or boolean defaults.

        Parameters
        ----------
        *args : Any
            Framework positional arguments, including optional data.
        **kwargs : Any
            Framework keywords with retained proposed state and proof.
        """
        super().__init__(*args, **kwargs)
        for outcome, label in OUTCOME_LABELS.items():
            self.fields[f"{outcome}_text"] = forms.CharField(
                max_length=3000,
                widget=forms.Textarea,
                label=f"{label}: recipient template",
            )
            self.fields[f"{outcome}_receipt"] = forms.ChoiceField(
                choices=_YES_NO, label=f"{label}: request receipt acknowledgement?"
            )


class ReviewPolicySaveForm(ReviewProposedForm):
    """Confirm one complete policy through the existing immutable owner command."""

    reason = forms.CharField(
        max_length=2000, widget=forms.Textarea, label="Reason for this policy version"
    )
    confirm = forms.BooleanField(
        label="Save this complete policy for deliberately opened future review cases"
    )

    def policy(self) -> ProgrammeReviewPolicyInput:
        """Decode the complete already-cleaned proposed policy for canonical save.

        Returns
        -------
        ProgrammeReviewPolicyInput
            Complete immutable validated stage and template choices.
        """
        return decode_review_policy(self.cleaned_data["proposed"])
