"""Explicit own conflict, complete rubric and separate discussion forms."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms

from maru.core.forms import StrictBase10IntegerField

from .forms import RetryForm
from .programme_review_inputs import MAX_DECISION_TEXT, MAX_REVIEW_REASON

if TYPE_CHECKING:
    from .programme_review_inputs import ProgrammeReviewStageInput


class ReviewerActionForm(RetryForm):
    """Retain original proof and require a deliberate reasoned confirmation."""

    transport_field_names = RetryForm.transport_field_names | {"action"}
    expected_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 1, widget=forms.HiddenInput
    )
    reason = forms.CharField(
        label="Private rationale",
        max_length=MAX_REVIEW_REASON,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Retained review evidence, not a recipient message or peer discussion."
        ),
    )
    confirm = forms.BooleanField(label="I confirm this exact review action")

    def __init__(
        self, *args: Any, task: str, rubric: ProgrammeReviewStageInput, **kwargs: Any
    ) -> None:
        """Build only the selected action's original immutable stage fields.

        Parameters
        ----------
        *args : Any
            Ordinary Django bound form arguments.
        task : str
            Closed clear, recuse, score or discuss route action.
        rubric : ProgrammeReviewStageInput
            Exact URL-selected assignment's original immutable stage.
        **kwargs : Any
            Ordinary Django initial values and presentation arguments.
        """
        super().__init__(*args, **kwargs)
        self.fields["confirm"].label = {
            "clear": "I declare that I have no conflict of interest for this review",
            "recuse": "I recuse myself; this assignment cannot be reactivated",
            "score": "I confirm this complete independent rubric and private rationale",
            "discuss": "I confirm this discussion text may be read by eligible peers",
        }[task]
        if task == "score":
            for criterion in rubric.criteria:
                self.fields[f"score_{criterion.code}"] = StrictBase10IntegerField(
                    label=criterion.label,
                    min_value=criterion.minimum,
                    max_value=criterion.maximum,
                    widget=forms.NumberInput(
                        attrs={
                            "min": criterion.minimum,
                            "max": criterion.maximum,
                            "step": 1,
                        }
                    ),
                    help_text=(
                        f"{criterion.code}: whole number from {criterion.minimum} "
                        f"through {criterion.maximum}, inclusive. No default score."
                    ),
                )
        elif task == "discuss":
            self.fields["text"] = forms.CharField(
                label="Peer discussion text",
                max_length=MAX_DECISION_TEXT,
                widget=forms.Textarea(attrs={"rows": 5}),
                help_text=(
                    "Avoid identifying yourself or contributors in anonymous stages."
                ),
            )
        self.order_fields(
            [
                "retry_key",
                "expected_version",
                *(name for name in self.fields if name.startswith("score_")),
                "text",
                "reason",
                "confirm",
            ]
        )
