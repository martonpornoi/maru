from __future__ import annotations

from django import forms

from maru.accounts.auth import is_google_email, normalize_email
from maru.accounts.models import AccessGrant, UserProfile
from maru.domain import Role


class AccessGrantForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        choices=[(role.value, role.value) for role in Role],
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = AccessGrant
        fields = ["email", "active", "roles", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["roles"].initial = sorted(self.instance.role_names)

    def clean_email(self) -> str:
        email = normalize_email(self.cleaned_data["email"])
        if not is_google_email(email):
            raise forms.ValidationError("Use a Gmail or Googlemail address.")
        return email


class AccessGrantImportForm(forms.Form):
    csv_file = forms.FileField(label="CSV file")


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            "display_name",
            "profile_picture",
            "fursuit_picture",
            "fursuit_name",
            "telegram",
            "discord",
            "bio",
            "show_profile_publicly",
            "show_contact_handles",
            "show_fursuit_picture",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
        }
