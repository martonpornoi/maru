from __future__ import annotations

from django import forms

from maru.social.models import SocialPost


class SocialPostForm(forms.ModelForm):
    embed_url = forms.URLField(required=False, assume_scheme="https")

    class Meta:
        model = SocialPost
        fields = ["title", "body", "embed_url", "media", "scheduled_for"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 10}),
            "scheduled_for": forms.DateTimeInput(
                attrs={"type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }
        labels = {
            "embed_url": "Embed URL",
            "media": "Image, GIF, or file",
            "scheduled_for": "Schedule publication for",
        }
        help_texts = {
            "embed_url": (
                "Use a public video, post, or GIF URL. Raw HTML is not accepted."
            ),
            "media": "Upload an image, GIF, or supporting file for this post.",
            "scheduled_for": "Leave empty to publish immediately.",
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["scheduled_for"].input_formats = ["%Y-%m-%dT%H:%M"]
