"""Closed notice controls with no caller-provided authority or message body."""

from __future__ import annotations

from typing import Any

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .catalogs import MAX_REASON_LENGTH
from .change_catalogs import ChangeRecipientPurpose
from .change_inputs import ChangeRecipientSelection
from .inputs import normalized_text


class NoticeSelectionForm(StrictInputForm):
    """Select a retained package or exact release without exposing a directory."""

    notice = CanonicalUUIDField(required=False, label="Exact notice reference")
    release = CanonicalUUIDField(required=False, label="Filter by exact release")
    task = forms.ChoiceField(required=False, choices=(("hosts", "Notify a host"),))
    occurrence = CanonicalUUIDField(required=False, widget=forms.HiddenInput)


class NoticePreviewForm(StrictInputForm):
    """Select an exact occurrence and purpose before preparing any communication."""

    action = forms.ChoiceField(
        choices=(("preview", "Preview"),), widget=forms.HiddenInput
    )
    release_id = CanonicalUUIDField(label="Released timetable reference")
    occurrence_id = CanonicalUUIDField(label="Affected occurrence reference")
    purpose = forms.ChoiceField(
        choices=tuple(
            (value.value, value.name.title()) for value in ChangeRecipientPurpose
        )
    )
    target_id = CanonicalUUIDField(label="Host, work or operator scope reference")
    operator_account_id = CanonicalUUIDField(
        required=False,
        label="Operator account reference",
        help_text=(
            "Only for room, Department or edition operators; "
            "leave blank for hosts or work."
        ),
    )

    def clean(self) -> dict[str, Any] | None:
        """Validate that a person selector cannot replace a host/work relationship.

        Returns
        -------
        dict[str, Any] | None
            Closed parsed input, retaining ordinary field errors when incomplete.

        Notes
        -----
        Canonical selection validation propagates as a non-field form error.
        """
        data = super().clean()
        if data and not self.errors:
            ChangeRecipientSelection(
                ChangeRecipientPurpose(data["purpose"]),
                data["target_id"],
                data["operator_account_id"],
            ).validated()
        return data


class NoticePrepareForm(NoticePreviewForm):
    """Bind preparation to a displayed exact preview and an explicit rationale."""

    action = forms.ChoiceField(
        choices=(("prepare", "Prepare"),), widget=forms.HiddenInput
    )
    expected_pointer_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 2, widget=forms.HiddenInput
    )
    snapshot_digest = forms.RegexField(r"\A[0-9a-f]{64}\Z", widget=forms.HiddenInput)
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Reason for this notice", max_length=MAX_REASON_LENGTH
    )

    def clean_reason(self) -> str:
        """Normalize required organizer rationale without retaining control text.

        Returns
        -------
        str
            Nonempty bounded single-line rationale.

        Notes
        -----
        Shared text validation errors become field errors.
        """
        return normalized_text(self.cleaned_data["reason"], maximum=MAX_REASON_LENGTH)


class NoticeEvidenceForm(StrictInputForm):
    """Common exact evidence selection without another person's identity."""

    action = forms.ChoiceField(
        choices=tuple(
            (value, value.title()) for value in ("approve", "reject", "handoff")
        ),
        widget=forms.HiddenInput,
    )
    notice_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_version = StrictBase10IntegerField(
        min_value=1, max_value=2**63 - 2, widget=forms.HiddenInput
    )
    snapshot_digest = forms.RegexField(r"\A[0-9a-f]{64}\Z", widget=forms.HiddenInput)
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)


class NoticeDecisionForm(NoticeEvidenceForm):
    """Require organizer rationale for independent review and manual handoff."""

    reason = forms.CharField(
        label="Reason for this action", max_length=MAX_REASON_LENGTH
    )

    def clean_reason(self) -> str:
        """Normalize the required independently attributable action rationale.

        Returns
        -------
        str
            Nonempty bounded single-line rationale.

        Notes
        -----
        Shared text validation errors become field errors.
        """
        return normalized_text(self.cleaned_data["reason"], maximum=MAX_REASON_LENGTH)


class NoticeAcknowledgeForm(NoticeEvidenceForm):
    """A genuine personal acknowledgement collects no organizer explanation."""

    action = forms.ChoiceField(
        choices=(("acknowledge", "Acknowledge this exact change"),),
        widget=forms.HiddenInput,
    )
