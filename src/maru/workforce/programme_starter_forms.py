"""Strict fixed-template preview/request and actual-person decision input."""

from __future__ import annotations

from typing import Any, cast

from django import forms

from maru.core.forms import CanonicalUUIDField, StrictInputForm
from maru.workforce.programme_starter_selection import (
    MAX_PROGRAMME_STARTER_PROOF_BYTES,
    ProgrammeStarterDraft,
)


class ProgrammeStarterCreationForm(StrictInputForm):
    """Retain original selector, rationale and retry while separating confirmation."""

    approver_email = forms.EmailField(
        label="Independent approver's known email", max_length=254
    )
    reason = forms.CharField(
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Explain why the shared starter is needed. "
            "Do not include unrelated private information."
        ),
    )
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)
    selection_proof = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_STARTER_PROOF_BYTES,
        strip=False,
        widget=forms.HiddenInput,
    )
    action = forms.ChoiceField(
        choices=(("preview", "Preview"), ("confirm", "Confirm")),
        widget=forms.HiddenInput,
    )
    confirmed = forms.BooleanField(
        required=False,
        label=(
            "I reviewed the exact approver and shared definition. "
            "Submit a request only; nobody gains access."
        ),
    )

    def clean(self) -> dict[str, Any] | None:
        """Require original signed selection and deliberate confirmation only on submit.

        Returns
        -------
        dict[str, Any] | None
            Validated original values or ordinary field errors; no person lookup.
        """
        cleaned = super().clean()
        if cleaned is not None and cleaned.get("action") == "confirm":
            if not cleaned.get("selection_proof"):
                self.add_error(None, "Preview the original approver before confirming.")
            if not cleaned.get("confirmed"):
                self.add_error("confirmed", "Confirm the exact request deliberately.")
        return cleaned

    def draft(self) -> ProgrammeStarterDraft:
        """Return original owner input after successful form validation.

        Returns
        -------
        ProgrammeStarterDraft
            Original known selector, rationale and author-bound key, not approval.
        """
        return ProgrammeStarterDraft(
            self.cleaned_data["approver_email"],
            self.cleaned_data["reason"],
            self.cleaned_data["idempotency_key"],
        )


class ProgrammeStarterDecisionForm(StrictInputForm):
    """Offer only the actual person's deliberate terminal actions and original key."""

    action = forms.ChoiceField(label="Your decision", choices=())
    reason = forms.CharField(
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Your separate decision rationale. Avoid unrelated private information."
        ),
    )
    confirmed = forms.BooleanField(
        label=(
            "I reviewed the original people, shared definition, scope "
            "and consequences. "
            "This is my own decision."
        )
    )
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self, *args: Any, is_author: bool, allow_approve: bool = True, **kwargs: Any
    ) -> None:
        """Offer author cancellation or the named approver's appropriate decisions.

        Parameters
        ----------
        *args : Any
            Standard Django form input; no actor/scope override is accepted.
        is_author : bool
            Server-resolved original author relationship.
        allow_approve : bool, default=True
            Current observed eligibility hint; commands independently reauthorize.
        **kwargs : Any
            Standard form options, including the original retry key.
        """
        super().__init__(*args, **kwargs)
        choices = (
            (("cancel", "Cancel my request — create nothing"),)
            if is_author
            else (
                ("", "Choose deliberately"),
                ("approve", "Approve this shared definition"),
                ("decline", "Decline — create nothing"),
            )
        )
        cast("forms.ChoiceField", self.fields["action"]).choices = tuple(
            choice for choice in choices if allow_approve or choice[0] != "approve"
        )
