"""Labelled same-call selection and explicit original-target confirmation."""

from django import forms

from maru.core.forms import CanonicalUUIDField

from .programme_domain_references import MAX_DOMAIN_SELECTION_BYTES
from .programme_personal_forms import ProgrammePersonalTaskForm


class ProgrammeDomainReferenceForm(ProgrammePersonalTaskForm):
    """Retain original source fences and a signed target without code matching."""

    transport_field_names = frozenset({"csrfmiddlewaretoken", "phase"})
    mode = forms.ChoiceField(
        choices=(
            ("select", "Select an entry from this call"),
            ("clear", "Clear this answer"),
        ),
        label="Change to prepare",
    )
    target = CanonicalUUIDField(required=False, widget=forms.HiddenInput)
    token = forms.CharField(
        required=False, max_length=MAX_DOMAIN_SELECTION_BYTES, widget=forms.HiddenInput
    )


class ProgrammeDomainLookupForm(ProgrammeDomainReferenceForm):
    """Present a native labelled chooser; the owning query validates membership."""

    target = CanonicalUUIDField(
        label="Additional private call reference",
        required=False,
        widget=forms.Select(choices=(("", "Choose an entry"),)),
        help_text=(
            "Preview explains this entry. "
            "It does not change the proposal's main selection."
        ),
    )
    reason = forms.CharField(required=False, max_length=500, widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        required=False, widget=forms.HiddenInput, initial=False
    )

    def clean_reason(self) -> str:
        """Keep optional preparation text without requiring a mutation rationale.

        Returns
        -------
        str
            Empty text or the existing normalized command rationale.
        """
        return super().clean_reason() if self.cleaned_data["reason"] else ""
