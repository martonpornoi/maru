"""Deliberate decision composition and exact-preview confirmation forms."""

from __future__ import annotations

from django import forms

from maru.core.forms import StrictBase10IntegerField

from .forms import RetryForm
from .programme_decider_preview import MAX_DECISION_PREVIEW_BYTES, DecisionIntent
from .programme_inputs import normalized_programme_text
from .programme_review_inputs import MAX_DECISION_TEXT, MAX_REVIEW_REASON

OUTCOME_LABELS = {
    "accepted": "Accept",
    "rejected": "Reject",
    "waitlisted": "Wait-list",
    "revision_requested": "Request a new revision",
}


class DecisionDraftForm(RetryForm):
    """Keep separate explicit outcome, recipient text and private rationale."""

    # Re-preview deliberately ignores the superseded confirmation proof/checkbox;
    # it cannot invoke a writer. Unknown fields remain rejected by StrictInputForm.
    transport_field_names = RetryForm.transport_field_names | {
        "action",
        "preview_proof",
        "confirm",
    }
    expected_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 2, widget=forms.HiddenInput
    )
    outcome = forms.ChoiceField(
        label="Decision outcome",
        choices=(("", "Choose an outcome deliberately"), *OUTCOME_LABELS.items()),
    )
    text = forms.CharField(
        label="Additional text for the exact recipients",
        max_length=MAX_DECISION_TEXT,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text=(
            "Appended to the pinned template. Do not put private review rationale here."
        ),
    )
    reason = forms.CharField(
        label="Private decision rationale",
        max_length=MAX_REVIEW_REASON,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Retained private evidence; never appended to the recipient message.",
    )

    def clean_text(self) -> str:
        """Normalize recipient text exactly as the canonical decision command.

        Returns
        -------
        str
            Explicit bounded NFC multiline recipient text.
        """
        return normalized_programme_text(
            self.cleaned_data["text"],
            field="text",
            maximum=MAX_DECISION_TEXT,
            required=True,
            multiline=True,
        )

    def clean_reason(self) -> str:
        """Normalize private rationale without mixing it into recipient text.

        Returns
        -------
        str
            Explicit bounded NFC multiline private rationale.
        """
        return normalized_programme_text(
            self.cleaned_data["reason"],
            field="reason",
            maximum=MAX_REVIEW_REASON,
            required=True,
            multiline=True,
        )

    def to_intent(self) -> DecisionIntent:
        """Read the original closed request after successful form validation.

        Returns
        -------
        DecisionIntent
            Separate normalized original version/retry/outcome/text/reason fields.
        """
        return DecisionIntent(
            **{
                name: self.cleaned_data[name]
                for name in (
                    "expected_version",
                    "retry_key",
                    "outcome",
                    "text",
                    "reason",
                )
            }
        )


class DecisionConfirmForm(DecisionDraftForm):
    """Require the exact preview proof and an explicit final confirmation."""

    preview_proof = forms.CharField(
        max_length=MAX_DECISION_PREVIEW_BYTES, widget=forms.HiddenInput
    )
    confirm = forms.BooleanField(
        label=(
            "I confirm this exact outcome and recipient message, "
            "separately from private rationale"
        ),
    )
