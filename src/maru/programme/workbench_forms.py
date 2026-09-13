"""Closed human-task forms without editable actor, tenant or source selectors."""

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .catalogs import (
    MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
    MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH,
    MAX_PROGRAMME_REASON_LENGTH,
    MAX_PROGRAMME_SUMMARY_LENGTH,
    MAX_PROGRAMME_TITLE_LENGTH,
    ProgrammeReadinessConcern,
    ProgrammeReadinessDisposition,
)


class ProgrammeWorkbenchForm(StrictInputForm):
    """Retain the originally displayed version and retry identity on failure."""

    expected_version = StrictBase10IntegerField(widget=forms.HiddenInput)
    idempotency_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        max_length=MAX_PROGRAMME_REASON_LENGTH,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=(
            "Retained with this decision. Do not include unnecessary personal data."
        ),
    )


class ProgrammeWorkingForm(ProgrammeWorkbenchForm):
    """Edit explicitly private working text, not public Programme copy."""

    field_order: tuple[str, ...] = ("internal_title", "working_summary", "reason")
    internal_title = forms.CharField(
        label="Working title", max_length=MAX_PROGRAMME_TITLE_LENGTH
    )
    working_summary = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_SUMMARY_LENGTH,
        widget=forms.Textarea(attrs={"rows": 5}),
    )


class ProgrammeCoreForm(ProgrammeWorkingForm):
    """Create organizer work without inventing an accepted submission."""

    field_order = (
        "kind",
        "internal_title",
        "working_summary",
        "reason",
    )
    kind = forms.ChoiceField(
        label="Item type",
        choices=(
            ("ceremony", "Ceremony"),
            ("break", "Break"),
            ("announcement", "Announcement"),
            ("organizer_core", "Other organizer core item"),
        ),
    )


class ProgrammeDeliveryForm(ProgrammeWorkbenchForm):
    """Edit complete delivery instructions under their independent ceiling."""

    field_order = (
        "technical_requirements",
        "accessibility_delivery",
        "media_consent_notes",
        "reason",
    )

    technical_requirements = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    accessibility_delivery = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Practical delivery instructions, not diagnoses or medical history.",
    )
    media_consent_notes = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )


class ProgrammeReadinessForm(ProgrammeWorkbenchForm):
    """Configure applicability without claiming evidence or a readiness score."""

    field_order = ("concern", "disposition", "reason")

    concern = forms.ChoiceField(
        choices=tuple(
            (value.value, value.name.replace("_", " ").title())
            for value in ProgrammeReadinessConcern
        )
    )
    disposition = forms.ChoiceField(
        choices=tuple(
            (value.value, value.name.replace("_", " ").title())
            for value in ProgrammeReadinessDisposition
        )
    )


class ProgrammePublicCopyForm(ProgrammeWorkbenchForm):
    """Review explicit public text against the originally displayed working source."""

    source_working_revision_id = CanonicalUUIDField(widget=forms.HiddenInput)
    public_title = forms.CharField(max_length=MAX_PROGRAMME_TITLE_LENGTH)
    public_summary = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_SUMMARY_LENGTH,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    public_content_note = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    field_order = (
        "public_title",
        "public_summary",
        "public_content_note",
        "reason",
    )
