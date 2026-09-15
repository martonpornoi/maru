"""Explicit known-person selection and confirmation with original source evidence."""

from django import forms

from .programme_person_references import MAX_PERSON_SELECTION_BYTES
from .programme_personal_forms import ProgrammePersonalTaskForm


class ProgrammePersonReferenceForm(ProgrammePersonalTaskForm):
    """Keep contact discovery separate from the signed original-person command."""

    transport_field_names = frozenset({"csrfmiddlewaretoken", "phase"})

    mode = forms.ChoiceField(
        choices=(
            ("select", "Select a known Maru person"),
            ("clear", "Clear this answer"),
        ),
        label="Change to prepare",
    )
    email = forms.EmailField(
        label="Known Maru login email",
        max_length=254,
        required=False,
        help_text=(
            "Exact known address only, not a directory search. "
            "It is not saved in the answer."
        ),
    )
    token = forms.CharField(
        required=False, max_length=MAX_PERSON_SELECTION_BYTES, widget=forms.HiddenInput
    )


class ProgrammePersonLookupForm(ProgrammePersonReferenceForm):
    """Prepare a selection without changing the answer or requiring confirmation."""

    reason = forms.CharField(required=False, max_length=500, widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        required=False, widget=forms.HiddenInput, initial=False
    )

    def clean_reason(self) -> str:
        """Keep an optional lookup rationale without demanding a mutation reason.

        Returns
        -------
        str
            Empty lookup rationale or the same normalized bounded command text.
        """
        return super().clean_reason() if self.cleaned_data["reason"] else ""
