"""Closed native release intent; bound retries never refresh private source choices."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from django import forms
from django.core.exceptions import ValidationError

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .catalogs import MAX_CONFLICTS
from .planning_forms import PlanningCommandForm
from .release_inputs import ReleaseCandidateSelection

if TYPE_CHECKING:
    from uuid import UUID


def _version(*, initial: bool = False) -> StrictBase10IntegerField:
    return StrictBase10IntegerField(
        min_value=0 if initial else 1,
        max_value=2**63 - 2,
        widget=forms.HiddenInput,
    )


def _digest() -> forms.RegexField:
    return forms.RegexField(
        r"\A[0-9a-f]{64}\Z", min_length=64, max_length=64, widget=forms.HiddenInput
    )


class ReleaseCandidateForm(StrictInputForm):
    """Select one explicitly labelled alternative for a fresh read-only inspection."""

    action = forms.ChoiceField(
        choices=(("inspect", "Inspect complete release checks"),),
        widget=forms.HiddenInput,
    )
    candidate_id = CanonicalUUIDField(
        label="Private timetable candidate", widget=forms.Select
    )


class ReleaseApprovalSelectionForm(StrictInputForm):
    """Select one exact retained approval before preparing a publication intent."""

    action = forms.ChoiceField(
        choices=(("prepare", "Review this approval for publication"),),
        widget=forms.HiddenInput,
    )
    approval_id = CanonicalUUIDField(widget=forms.HiddenInput)


class ReleaseOlderApprovalsForm(StrictInputForm):
    """Request an explicit older page without putting private selection in a URL."""

    action = forms.ChoiceField(
        choices=(("older", "Older approvals"),), widget=forms.HiddenInput
    )
    before_id = CanonicalUUIDField(widget=forms.HiddenInput)


class ReleaseOlderHistoryForm(StrictInputForm):
    """Request an exclusive older pointer-history window."""

    action = forms.ChoiceField(
        choices=(("older", "Older release history"),), widget=forms.HiddenInput
    )
    before_version = _version()


class ReleaseCommandForm(PlanningCommandForm):
    """Require deliberate confirmation in addition to canonical retry and reason."""

    confirm = forms.BooleanField(
        label="I have reviewed this exact action and its consequences",
        required=True,
    )


class ReleaseSnapshotForm(ReleaseCommandForm):
    """Retain the original complete candidate/source observation on every retry."""

    candidate_id = CanonicalUUIDField(widget=forms.HiddenInput)
    candidate_revision_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_candidate_version = _version()
    source_snapshot_digest = _digest()

    def selection(self) -> ReleaseCandidateSelection:
        """Build exact typed intent only after the caller has validated this form.

        Returns
        -------
        ReleaseCandidateSelection
            Original caller-observed identifiers/version/digest, never refreshed.
        """
        return ReleaseCandidateSelection(
            self.cleaned_data["candidate_id"],
            self.cleaned_data["candidate_revision_id"],
            self.cleaned_data["expected_candidate_version"],
            self.cleaned_data["source_snapshot_digest"],
        ).validated()


class ReleaseWarningForm(ReleaseSnapshotForm):
    """Acknowledge only one exact owner-authenticated warning, never a hard finding."""

    field_order = ("finding_fingerprint", "reason", "confirm")

    action = forms.ChoiceField(
        choices=(("acknowledge", "Acknowledge this release warning"),),
        widget=forms.HiddenInput,
    )
    finding_fingerprint = forms.RegexField(
        r"\A[0-9a-f]{64}\Z",
        min_length=64,
        max_length=64,
        label="Release warning",
        widget=forms.Select,
    )


class ReleaseApproveForm(ReleaseSnapshotForm):
    """Confirm the exact displayed retained warning selection and independent review."""

    action = forms.ChoiceField(
        choices=(("approve", "Approve this exact timetable"),), widget=forms.HiddenInput
    )
    acknowledgement_ids = forms.CharField(
        max_length=MAX_CONFLICTS * 40 + 2,
        widget=forms.HiddenInput,
        strip=False,
    )

    def clean_acknowledgement_ids(self) -> tuple[UUID, ...]:
        """Parse a bounded closed array of canonical retained acknowledgement IDs.

        Returns
        -------
        tuple[UUID, ...]
            Explicit original references, not a new lookup of current evidence.

        Raises
        ------
        ValidationError
            If the array, cardinality, canonical identifiers or uniqueness fails.
        """
        try:
            values = json.loads(self.cleaned_data["acknowledgement_ids"])
        except (ValueError, RecursionError) as error:
            raise ValidationError(
                "Use the exact displayed warning evidence selection."
            ) from error
        if type(values) is not list or len(values) > MAX_CONFLICTS:
            raise ValidationError("Use a complete bounded warning evidence selection.")
        identifiers = tuple(CanonicalUUIDField().clean(value) for value in values)
        if len(set(identifiers)) != len(identifiers):
            raise ValidationError("Select each warning acknowledgement once.")
        return identifiers


class ReleasePublishForm(ReleaseCommandForm):
    """Publish exactly one retained approval against the originally observed pointer."""

    action = forms.ChoiceField(
        choices=(("publish", "Publish this exact approved timetable"),),
        widget=forms.HiddenInput,
    )
    approval_id = CanonicalUUIDField(widget=forms.HiddenInput)
    source_snapshot_digest = _digest()
    expected_active_release_id = CanonicalUUIDField(
        required=False, widget=forms.HiddenInput
    )
    expected_release_version = _version(initial=True)


class ReleaseWithdrawForm(ReleaseCommandForm):
    """Withdraw the exact active release without selecting or restoring content."""

    action = forms.ChoiceField(
        choices=(("withdraw", "Withdraw this active timetable"),),
        widget=forms.HiddenInput,
    )
    active_release_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_release_version = _version()


def restore_pending_warning_choice(form: ReleaseWarningForm) -> None:
    """Show a canonical original warning reference without reading current sources.

    Parameters
    ----------
    form : ReleaseWarningForm
        Already bound form; ordinary choices come from preflight on a fresh read.
    """
    field = form.fields["finding_fingerprint"]
    try:
        value = field.clean(form.data.get("finding_fingerprint"))
    except ValidationError:
        return
    field.widget = forms.Select(choices=((value, f"Original pending warning {value}"),))
