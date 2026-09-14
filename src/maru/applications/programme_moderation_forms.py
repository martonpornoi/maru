"""Explicit moderation intents retaining original version and stage selection."""

from __future__ import annotations

from typing import Any

from django import forms

from maru.core.forms import StrictBase10IntegerField

from .forms import RetryForm
from .programme_review_inputs import MAX_REVIEW_REASON, MAX_REVIEW_STAGES


class ModerationActionForm(RetryForm):
    """Require a private reason and explicit confirmation without rebasing intent."""

    transport_field_names = RetryForm.transport_field_names | {"action"}
    expected_version = StrictBase10IntegerField(
        min_value=1,
        max_value=2**63 - 1,
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(
        label="Private moderation rationale",
        max_length=MAX_REVIEW_REASON,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Retained private evidence, not a recipient message or decision.",
    )
    confirm = forms.BooleanField(label="I confirm this exact moderation action")

    def __init__(self, *args: Any, task: str, **kwargs: Any) -> None:
        """Build only the closed task's fields without mutable fresh eligibility.

        Parameters
        ----------
        *args : Any
            Ordinary bound Django form arguments.
        task : str
            Closed moderate, advance or reopen route task.
        **kwargs : Any
            Ordinary initial values and presentation arguments.
        """
        super().__init__(*args, **kwargs)
        self.fields["confirm"].label = {
            "moderate": "I confirm my rationale against this exact evidence version",
            "advance": (
                "I confirm progression to the next configured stage, "
                "not a final decision"
            ),
            "reopen": (
                "I confirm reopening and invalidating moderation "
                "from the selected stage"
            ),
        }[task]
        if task == "reopen":
            # The widget supplies labels, but only the canonical writer decides
            # fresh eligibility. A later case stage cannot invalidate old receipts.
            self.fields["stage"] = StrictBase10IntegerField(
                label="Stage to reopen",
                min_value=0,
                max_value=MAX_REVIEW_STAGES - 1,
                widget=forms.Select,
            )
        self.order_fields(
            ["retry_key", "expected_version", "stage", "reason", "confirm"]
        )
