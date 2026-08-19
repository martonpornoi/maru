"""Closed browser inputs for scoped access and read-only preview actions."""

from __future__ import annotations

from typing import Any

from django import forms

from maru.core.forms import CanonicalUUIDField, StrictInputForm


class _ActionForm(StrictInputForm):
    expected_action = ""

    action = forms.CharField(widget=forms.HiddenInput)

    def clean_action(self) -> str:
        value = str(self.cleaned_data["action"])
        if value != self.expected_action:
            raise forms.ValidationError("Choose a supported access action.")
        return value


class PageAccessAssignmentForm(_ActionForm):
    """Collect and validate page access assignment input."""

    expected_action = "assign"

    person_email = forms.EmailField(max_length=254, label="Existing person email")
    role_version_id = CanonicalUUIDField(label="Immutable group version")
    approver_email = forms.EmailField(
        max_length=254,
        label="Independent approver email",
    )
    expires_at = forms.DateTimeField(required=False, label="Expires (optional)")
    reason = forms.CharField(max_length=240)


class PageAccessRevokeForm(_ActionForm):
    """Collect and validate page access revoke input."""

    expected_action = "revoke"

    assignment_id = CanonicalUUIDField()
    reason = forms.CharField(max_length=240)


class PageAccessPersonPreviewForm(_ActionForm):
    """Collect and validate page access person preview input."""

    expected_action = "preview_person"

    person_email = forms.EmailField(max_length=254, label="Exact person email")


class PageAccessRolePreviewForm(_ActionForm):
    """Collect and validate page access role preview input."""

    expected_action = "preview_role"

    role_version_id = CanonicalUUIDField(label="Immutable group version")


class UnsupportedPageAccessActionForm(_ActionForm):
    """Closed fallback used before dispatching an untrusted action value."""

    expected_action = "unsupported"

    def clean(self) -> dict[str, Any] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any] | None
            A mapping containing the resolved clean data.

        Raises
        ------
        forms.ValidationError
            If the submitted state or input violates a domain invariant.
        """
        super().clean()
        raise forms.ValidationError("Choose a supported access action.")
