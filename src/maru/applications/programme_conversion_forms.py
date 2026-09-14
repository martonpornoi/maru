"""Exact accepted-source conversion with explicit private copy and original intent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django import forms

from maru.core.forms import StrictBase10IntegerField

from .forms import RetryForm
from .programme_conversion_inputs import ProgrammeConversionInput
from .programme_inputs import normalized_programme_text

if TYPE_CHECKING:
    from uuid import UUID


class ProgrammeConversionForm(RetryForm):
    """Keep both original aggregate versions without inferring private source text."""

    transport_field_names = RetryForm.transport_field_names | {"action"}
    revision_id = forms.UUIDField(widget=forms.HiddenInput)
    expected_review_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 2, widget=forms.HiddenInput
    )
    expected_programme_version = StrictBase10IntegerField(
        min_value=0, max_value=2**63 - 2, widget=forms.HiddenInput
    )
    internal_title = forms.CharField(
        label="Private Programme working title",
        max_length=240,
        help_text="Enter deliberately. No proposal answer is copied automatically.",
    )
    working_summary = forms.CharField(
        label="Private working summary",
        required=False,
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    reason = forms.CharField(
        label="Reason for this conversion",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirm = forms.BooleanField(
        label=(
            "I confirm creating one private item from this exact acceptance, "
            "with readiness still unresolved"
        )
    )

    def clean_reason(self) -> str:
        """Normalize rationale with the unchanged canonical command semantics.

        Returns
        -------
        str
            Required bounded collapsed-whitespace rationale.
        """
        return normalized_programme_text(
            self.cleaned_data["reason"],
            field="reason",
            maximum=1000,
            required=True,
            collapse=True,
        )

    def to_command(self, decision_id: UUID) -> ProgrammeConversionInput:
        """Normalize deliberate private copy bound to the route-selected decision.

        Parameters
        ----------
        decision_id : UUID
            Exact selected acceptance, never supplied by an editable form field.

        Returns
        -------
        ProgrammeConversionInput
            Closed canonical original source, two-version and private-copy intent.
        """
        return ProgrammeConversionInput(
            decision_id=decision_id,
            **{
                field: self.cleaned_data[field]
                for field in (
                    "revision_id",
                    "expected_review_version",
                    "expected_programme_version",
                    "internal_title",
                    "working_summary",
                )
            },
        ).normalized()
