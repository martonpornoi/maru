"""Domain-neutral form contracts shared by controlled browser workflows."""

from __future__ import annotations

from typing import Any

from django import forms

MAX_REPORTED_UNKNOWN_FIELDS = 5
MAX_REPORTED_FIELD_NAME_LENGTH = 60


class StrictInputForm(forms.Form):
    """Reject undeclared request keys instead of silently discarding them."""

    transport_field_names = frozenset({"csrfmiddlewaretoken"})

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        unknown = sorted(
            str(field_name)
            for field_name in self.data
            if field_name not in self.fields
            and field_name not in self.transport_field_names
        )
        if unknown:
            visible = ", ".join(
                field_name[:MAX_REPORTED_FIELD_NAME_LENGTH]
                for field_name in unknown[:MAX_REPORTED_UNKNOWN_FIELDS]
            )
            if len(unknown) > MAX_REPORTED_UNKNOWN_FIELDS:
                visible = (
                    f"{visible}, and {len(unknown) - MAX_REPORTED_UNKNOWN_FIELDS} more"
                )
            raise forms.ValidationError(
                f"Remove unsupported input fields: {visible}.",
                code="unknown_input_field",
            )
        return cleaned


class HttpsURLField(forms.URLField):
    """Use Django 6's secure URL default explicitly on every supported version."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("assume_scheme", "https")
        super().__init__(*args, **kwargs)
