"""Closed browser input for a recent privileged-session check."""

from django import forms

from maru.core.forms import StrictInputForm


class AccountStepUpForm(StrictInputForm):
    """Collect and validate account step up input."""

    password = forms.CharField(
        label="Current password",
        max_length=128,
        strip=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "current-password"},
        ),
        help_text="Re-enter your current Maru password to continue.",
    )
    next = forms.CharField(
        required=False,
        max_length=2_048,
        widget=forms.HiddenInput(),
    )
