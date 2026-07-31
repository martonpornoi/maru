"""Small accessible reference forms for workforce self-service."""

from django import forms


class VolunteerApplicationForm(forms.Form):
    motivation = forms.CharField(
        label="Why would you like to help in this position?",
        max_length=2_000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=(
            "Describe relevant interests or experience. Do not include medical, "
            "conduct, identity-document, or unrelated sensitive information."
        ),
    )


class OnboardingDocumentUploadForm(forms.Form):
    document = forms.FileField(
        label="Signed PDF",
        help_text=(
            "PDF only, up to the limit shown for the request. The file remains "
            "private until retention removes it."
        ),
    )
