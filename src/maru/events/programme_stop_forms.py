"""Strict original-preview confirmation for the dormant Stop Programme page."""

from typing import Any
from uuid import UUID

from django import forms

from .programme_stop_inputs import ProgrammeStopInput, normalize_programme_stop_input


class ProgrammeStopForm(forms.Form):
    """Preserve original intent and acknowledgement across uncertain retries."""

    expected_aggregate_version = forms.RegexField(
        r"\A[1-9][0-9]{0,9}\Z", max_length=10, strip=False, widget=forms.HiddenInput
    )
    expected_lifecycle_version = forms.RegexField(
        r"\A(?:0|[1-9][0-9]{0,9})\Z",
        max_length=10,
        strip=False,
        widget=forms.HiddenInput,
    )
    preview_fingerprint = forms.RegexField(
        r"\A[0-9a-f]{64}\Z", max_length=64, strip=False, widget=forms.HiddenInput
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Reason for stopping Programme",
        max_length=240,
        strip=False,
        help_text="Keep this reason brief; do not include private personal details.",
    )
    confirm = forms.BooleanField(
        label=(
            "I understand that Programme will stop, its timetable will be withdrawn, "
            "and retained history and commitments will not be erased or completed."
        )
    )

    def clean_idempotency_key(self) -> UUID:
        """Require a non-nil original retry identity.

        Returns
        -------
        UUID
            Submitted original confirmation identity.

        Raises
        ------
        forms.ValidationError
            If the form carries the nil identity.
        """
        key: UUID = self.cleaned_data["idempotency_key"]
        if not key.int:
            raise forms.ValidationError("Reload the complete stop preview.")
        return key

    def clean(self) -> dict[str, Any]:
        """Apply the same bounded original-intent rules as the application command.

        Returns
        -------
        dict[str, Any]
            Validated form fields plus typed normalized details when complete.
        """
        data = super().clean() or {}
        if not self.errors:
            data["details"] = normalize_programme_stop_input(
                ProgrammeStopInput(
                    int(data["expected_aggregate_version"]),
                    int(data["expected_lifecycle_version"]),
                    data["preview_fingerprint"],
                    data["reason"],
                )
            )
        return data
