"""Closed deliberate archive request and derived-custody disposal inputs."""

from uuid import UUID

from django import forms


class ProgrammeArchiveRequestForm(forms.Form):
    """Keep retry identity and private custody acknowledgement explicit."""

    request_key = forms.UUIDField(widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        label=(
            "I will keep this restricted archive private and dispose of my copy "
            "when no longer needed."
        )
    )

    def clean_request_key(self) -> UUID:
        """Refuse the nil UUID instead of creating an unrepeatable command.

        Returns
        -------
        UUID
            Exact validated nonzero idempotency identity.

        Raises
        ------
        forms.ValidationError
            If the submitted request key is nil.
        """
        key: UUID = self.cleaned_data["request_key"]
        if not key.int:
            raise forms.ValidationError("Reload this form to obtain a request key.")
        return key


class ProgrammeArchiveCancelForm(forms.Form):
    """Confirm disposal of only the currently observed task's derived bytes."""

    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        label=(
            "Cancel this request and remove its derived archive bytes; "
            "retain source records and evidence."
        )
    )
