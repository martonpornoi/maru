"""Closed human-task forms with exact authorized choices and no scope overrides."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .catalogs import (
    MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH,
    MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
    MAX_PROGRAMME_PUBLIC_CONTENT_NOTE_LENGTH,
    MAX_PROGRAMME_REASON_LENGTH,
    MAX_PROGRAMME_SUMMARY_LENGTH,
    MAX_PROGRAMME_TITLE_LENGTH,
    PROGRAMME_OPERATOR_ATTESTATION_SOURCE,
    ProgrammeReadinessConcern,
    ProgrammeReadinessDisposition,
    ProgrammeReadinessEvidenceState,
)

if TYPE_CHECKING:
    from .workbench_sources import (
        ProgrammeEvidenceSourceChoice,
        ProgrammeWithdrawalChoice,
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


class ProgrammeDiscussionForm(ProgrammeWorkbenchForm):
    """Append one retained private Department decision entry, not general chat."""

    body = forms.CharField(
        label="Department discussion entry",
        max_length=MAX_PROGRAMME_PRIVATE_TEXT_LENGTH,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    field_order = ("body", "reason")


class ProgrammeEvidenceForm(ProgrammeWorkbenchForm):
    """Bind readiness intent to an explicitly selected authorized source."""

    concern = forms.ChoiceField(
        choices=(
            ("", "Choose the concern"),
            *(
                (value.value, value.name.replace("_", " ").title())
                for value in ProgrammeReadinessConcern
            ),
        )
    )
    state = forms.ChoiceField(
        choices=(
            ("", "Choose the evidence outcome"),
            *(
                (value.value, value.name.replace("_", " ").title())
                for value in ProgrammeReadinessEvidenceState
            ),
        )
    )
    source = forms.ChoiceField(label="Evidence source")
    evidence_note = forms.CharField(
        required=False,
        max_length=MAX_PROGRAMME_EVIDENCE_NOTE_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    field_order = ("concern", "state", "source", "evidence_note", "reason")

    def __init__(
        self,
        *args: Any,
        sources: tuple[ProgrammeEvidenceSourceChoice, ...],
        **kwargs: Any,
    ) -> None:
        """Offer only code-owned attestation and independently authorized exact sources.

        Parameters
        ----------
        *args : Any
            Standard Django form binding arguments.
        sources : tuple[ProgrammeEvidenceSourceChoice, ...]
            Current owner-approved exact references, not submitted choice claims.
        **kwargs : Any
            Standard initial values and form options.
        """
        super().__init__(*args, **kwargs)
        self.source_refs = {
            "operator": (PROGRAMME_OPERATOR_ATTESTATION_SOURCE, None, None),
            **{
                source.key: (source.code, source.object_id, source.version)
                for source in sources
            },
        }
        self.fields["source"] = forms.ChoiceField(
            label="Evidence source",
            choices=(
                ("", "Choose the evidence source"),
                ("operator", "Explicit operator attestation — not a source document"),
                *((source.key, source.label) for source in sources),
            ),
            help_text=(
                "Source choices depend on your independent layer access. "
                "An expired source is not replaced automatically."
            ),
        )

    def clean(self) -> dict[str, Any]:
        """Resolve a validated choice without accepting arbitrary source coordinates.

        Returns
        -------
        dict[str, Any]
            Closed evidence command fields, retaining the original item version.
        """
        data = super().clean() or {}
        selected = data.pop("source", None)
        if selected is not None:
            code, object_id, version = self.source_refs[selected]
            data.update(
                source_code=code, source_object_id=object_id, source_version=version
            )
        return data


class ProgrammeWithdrawalForm(ProgrammeWorkbenchForm):
    """Explicitly confirm withdrawal of one readable retained rendition."""

    rendition_id = forms.ChoiceField(label="Retained rendition to withdraw")
    confirm_withdrawal = forms.BooleanField(
        label=(
            "Withdraw disclosure of this exact rendition, including retained releases"
        ),
        help_text=(
            "This does not replace the timetable or restore older copy. "
            "The reason remains in private history."
        ),
    )
    field_order = ("rendition_id", "confirm_withdrawal", "reason")

    def __init__(
        self, *args: Any, choices: tuple[ProgrammeWithdrawalChoice, ...], **kwargs: Any
    ) -> None:
        """Populate complete authorized historical choices without selecting the latest.

        Parameters
        ----------
        *args : Any
            Standard Django form binding arguments.
        choices : tuple[ProgrammeWithdrawalChoice, ...]
            Complete not-yet-withdrawn references from the authorized owner query.
        **kwargs : Any
            Standard initial values and form options.
        """
        super().__init__(*args, **kwargs)
        self.rendition_refs = {
            str(choice.rendition_id): choice.rendition_id for choice in choices
        }
        self.fields["rendition_id"] = forms.ChoiceField(
            label="Retained rendition to withdraw",
            choices=(
                ("", "Choose a retained rendition"),
                *(
                    (
                        str(choice.rendition_id),
                        f"Rendition {choice.number} — {choice.title}",
                    )
                    for choice in choices
                ),
            ),
        )

    def clean(self) -> dict[str, Any]:
        """Convert only an authorized exact choice into the existing command intent.

        Returns
        -------
        dict[str, Any]
            Exact typed rendition and reason; the confirmation is not a domain field.
        """
        data = super().clean() or {}
        selected = data.get("rendition_id")
        if selected is not None:
            data["rendition_id"] = self.rendition_refs[selected]
        data.pop("confirm_withdrawal", None)
        return data
