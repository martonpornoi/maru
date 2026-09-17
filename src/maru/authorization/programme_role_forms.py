"""Closed own-person decision input, never an author-supplied approver identity."""

from __future__ import annotations

from typing import Any, cast

from django import forms

from maru.core.forms import CanonicalUUIDField, StrictInputForm


class ProgrammeRoleDecisionForm(StrictInputForm):
    """Bind deliberate outcome, rationale and confirmation to one original retry."""

    action = forms.ChoiceField(label="Your decision", choices=())
    reason = forms.CharField(
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=(
            "Retained with your decision. Do not include unrelated private information."
        ),
    )
    confirmed = forms.BooleanField(
        label="I reviewed this exact person, scope, role, interval and consequence."
    )
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self, *args: Any, is_author: bool, allow_approve: bool = True, **kwargs: Any
    ) -> None:
        """Offer the authenticated person's own terminal actions only.

        Parameters
        ----------
        *args : Any
            Standard Django form data and positional options.
        is_author : bool
            Server-resolved original author relationship, never submitted authority.
        allow_approve : bool, default=True
            Whether to offer approval in this observed state; commands reauthorize.
        **kwargs : Any
            Standard form options including the original retry identity.
        """
        super().__init__(*args, **kwargs)
        choices = (
            (("cancel", "Cancel my request — grant nothing"),)
            if is_author
            else (
                ("", "Choose deliberately"),
                ("approve", "Approve this exact access"),
                ("decline", "Decline — grant nothing"),
            )
        )
        cast("forms.ChoiceField", self.fields["action"]).choices = tuple(
            choice for choice in choices if allow_approve or choice[0] != "approve"
        )
