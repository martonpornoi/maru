"""Accessible account recovery and human-facing authentication forms."""

from typing import Any

from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailVerificationForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput, max_length=200)


class AccountRecoveryForm(EmailVerificationForm):
    new_password = forms.CharField(
        label="New password",
        max_length=128,
        strip=False,
        widget=forms.PasswordInput,
    )
    confirm_password = forms.CharField(
        label="Confirm new password",
        max_length=128,
        strip=False,
        widget=forms.PasswordInput,
    )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean() or {}
        if cleaned.get("new_password") != cleaned.get("confirm_password"):
            self.add_error("confirm_password", "The passwords do not match.")
        return cleaned


class EmailOrHandleAuthenticationForm(AuthenticationForm):
    """Describe the login identifier Maru actually accepts."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Email address or username"
        self.fields["username"].widget.attrs["autocomplete"] = "username"
