"""Closed role choices and actual human decisions for Guides access."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django import forms

from maru.core.forms import CanonicalUUIDField, StrictInputForm

if TYPE_CHECKING:
    from maru.authorization.guidance_access_queries import GuidanceAccessWorkspace

ROLE_LABELS = {
    "guidance-reader": "Read guides",
    "guidance-editor": "Write guides",
    "guidance-reviewer": "Review guides",
    "guidance-operator": "Run Guides",
    "guidance-access-controller": "Manage access to guides",
}
CAPABILITY_LABELS = {
    "knowledge.view_current": "Read approved guides and download their current text",
    "knowledge.view_working": "Read private drafts, feedback and history",
    "knowledge.compose": "Write guides and ask for review",
    "knowledge.review": "Review versions written by other people",
    "knowledge.withdraw": "Withdraw guides from readers",
    "knowledge.manage_settings": (
        "Confirm record-keeping rules and stop or resume Guides"
    ),
    "knowledge.export_evidence": "Download full history, including private feedback",
    "authorization.manage_guidance_access": (
        "Manage Guides access through separately approved requests"
    ),
}


class GuidanceAccessRequestForm(StrictInputForm):
    """Name an existing verified person and a separate actual approver."""

    recipient_email = forms.EmailField(
        label="Person's Maru account email",
        max_length=254,
        help_text=(
            "They must already have an active, verified Maru account. This "
            "form does not send an invitation."
        ),
    )
    recipe_code = forms.ChoiceField(
        label="What should they be able to do?", widget=forms.RadioSelect
    )
    approver_id = forms.ChoiceField(label="Who should approve this request?")
    expires_at = forms.DateTimeField(
        label="Access ends (optional)",
        required=False,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
        ),
        help_text=(
            "Leave blank for no planned end. The event's time zone is shown above."
        ),
    )
    reason = forms.CharField(
        label="Why is this access needed?",
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirmed = forms.BooleanField(
        label="I checked the person, responsibilities, end date and named approver."
    )
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self, *args: Any, workspace: GuidanceAccessWorkspace, **kwargs: Any
    ) -> None:
        """Use only owner-admitted roles and people while preserving exact retries.

        Parameters
        ----------
        *args : Any
            Original submitted form values, if any.
        workspace : GuidanceAccessWorkspace
            Current admitted role and approver choices for this exact event.
        **kwargs : Any
            Normal form configuration and original retry identity.
        """
        super().__init__(*args, **kwargs)
        cast("forms.ChoiceField", self.fields["recipe_code"]).choices = [
            (recipe.code, ROLE_LABELS[recipe.code]) for recipe in workspace.recipes
        ]
        choices = [
            ("", "Choose a person"),
            *((str(person.account_id), person.label) for person in workspace.approvers),
        ]
        if self.is_bound:
            value = self.data.get("approver_id", "")
            try:
                reference = UUID(value)
            except (ValueError, TypeError, AttributeError):
                reference = None
            if (
                reference
                and reference.int
                and str(reference) == value
                and value not in {choice[0] for choice in choices}
            ):
                choices.append(
                    (value, "Previously selected person (no longer available)")
                )
        cast("forms.ChoiceField", self.fields["approver_id"]).choices = choices


class GuidanceAccessAnswerForm(StrictInputForm):
    """Bind a named approver's personal answer to the exact retained request."""

    decision = forms.ChoiceField(
        label="Your decision",
        widget=forms.RadioSelect,
        choices=(("accept", "Approve this access"), ("decline", "Decline this access")),
    )
    confirmed = forms.BooleanField(
        label=(
            "I checked the person, event, responsibilities and end date in "
            "this request."
        )
    )
    expected_digest = forms.RegexField(
        regex=r"\A[0-9a-f]{64}\Z", widget=forms.HiddenInput
    )


class GuidanceAccessRevokeForm(StrictInputForm):
    """Confirm removal of one exact assignment, with an accountable reason."""

    reason = forms.CharField(
        label="Why are you removing this access?",
        max_length=240,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    confirmed = forms.BooleanField(
        label="Remove this exact assignment. Its history will be kept."
    )
