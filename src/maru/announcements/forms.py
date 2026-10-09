"""Closed native forms for manual Announcements, without JavaScript dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4, uuid5

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    HttpsURLField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.core.localization import language_labels

from .catalog import MAX_BODY, MAX_CHANNELS, MAX_HEADLINE, MAX_VARIANTS
from .contracts import (
    AnnouncementDraftInput,
    AnnouncementSettingsInput,
    AnnouncementSettingsView,
    AnnouncementVariantInput,
    ManualChannel,
)
from .inputs import channel_code, safe_url

if TYPE_CHECKING:
    from collections.abc import Iterable


class CommandForm(StrictInputForm):
    """Retain the exact source version and retry identity across corrections."""

    expected_version = StrictBase10IntegerField(
        widget=forms.HiddenInput,
        error_messages={
            "invalid": "This form is incomplete. Reopen this task.",
            "required": "This form is incomplete. Reopen this task.",
        },
    )
    idempotency_key = CanonicalUUIDField(
        widget=forms.HiddenInput,
        error_messages={
            "invalid": "This form is incomplete. Reopen this task.",
            "required": "This form is incomplete. Reopen this task.",
        },
    )


class DraftForm(CommandForm):
    """Write one message and deliberately select each channel/language copy."""

    transport_field_names = StrictInputForm.transport_field_names | {"add_copy"}
    headline = forms.CharField(label="Headline", max_length=MAX_HEADLINE)
    body = forms.CharField(
        label="Main message",
        max_length=MAX_BODY,
        widget=forms.Textarea(attrs={"rows": 8}),
    )
    language_code = forms.ChoiceField(label="Main message language")
    expected_settings_version = StrictBase10IntegerField(widget=forms.HiddenInput)
    copy_count = StrictBase10IntegerField(
        min_value=1, max_value=MAX_VARIANTS, widget=forms.HiddenInput
    )
    reason = forms.CharField(
        label="What changed and why?",
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(
        self,
        *args: Any,
        settings: AnnouncementSettingsView,
        copy_count: int,
        editing: bool = False,
        **kwargs: Any,
    ) -> None:
        """Build only bounded controls for current authorized channels and languages.

        Parameters
        ----------
        *args : Any
            Original submitted form data.
        settings : AnnouncementSettingsView
            Current authorized destination and language choices.
        copy_count : int
            Bounded number of explicitly requested copy rows.
        editing : bool, default=False
            Whether an explanation is required for a new revision.
        **kwargs : Any
            Standard form options.
        """
        super().__init__(*args, **kwargs)
        self.copy_rows = copy_count
        cast("forms.ChoiceField", self.fields["language_code"]).choices = [
            ("", "Choose a language"),
            *(
                (code, language_labels().get(code, code))
                for code in settings.language_codes
            ),
        ]
        self.fields["reason"].required = editing
        if not editing:
            self.fields["reason"].widget = forms.HiddenInput()
        for index in range(copy_count):
            prefix = f"copy_{index}_"
            label = f"Copy {index + 1}"
            self.fields[prefix + "channel"] = forms.ChoiceField(
                label=f"{label}: channel",
                required=False,
                choices=[
                    ("", "No channel selected"),
                    *((item.code, item.label) for item in settings.channels),
                ],
            )
            self.fields[prefix + "language"] = forms.ChoiceField(
                label=f"{label}: language",
                required=False,
                choices=[
                    ("", "Choose a language"),
                    *(
                        (code, language_labels().get(code, code))
                        for code in settings.language_codes
                    ),
                ],
            )
            self.fields[prefix + "mode"] = forms.ChoiceField(
                label=f"{label}: text",
                choices=[
                    ("main", "Use the main message"),
                    ("custom", "Use different text below"),
                ],
                help_text=(
                    "The main message can be reused only in its own language. "
                    "Enter translations yourself."
                ),
            )
            self.fields[prefix + "headline"] = forms.CharField(
                label=f"{label}: different headline",
                max_length=MAX_HEADLINE,
                required=False,
            )
            self.fields[prefix + "body"] = forms.CharField(
                label=f"{label}: different message",
                max_length=MAX_BODY,
                required=False,
                widget=forms.Textarea(attrs={"rows": 5}),
            )
            if not self.is_bound:
                self.initial.setdefault(prefix + "mode", "main")
                if len(settings.language_codes) == 1:
                    self.initial.setdefault(
                        prefix + "language", settings.language_codes[0]
                    )
        if not self.is_bound:
            self.initial.setdefault("copy_count", copy_count)
            if len(settings.language_codes) == 1:
                self.initial.setdefault("language_code", settings.language_codes[0])
        self._retain_original_choice("language_code", channel=False)
        for index in range(copy_count):
            self._retain_original_choice(f"copy_{index}_channel", channel=True)
            self._retain_original_choice(f"copy_{index}_language", channel=False)

    def _retain_original_choice(self, name: str, *, channel: bool) -> None:
        original = (self.data if self.is_bound else self.initial).get(name, "")
        if not isinstance(original, str) or not original:
            return
        if channel:
            try:
                channel_code(original)
            except forms.ValidationError:
                return
        elif original not in language_labels():
            return
        field = cast("forms.ChoiceField", self.fields[name])
        options = list(cast("Iterable[tuple[str, str]]", field.choices))
        if original not in {value for value, _label in options}:
            # Keeping a prior canonical selection is transport, never permission.
            # The owning command first resolves an exact retry; otherwise its
            # locked settings/version and availability checks still apply.
            label = (
                "Previous channel (no longer configured)"
                if channel
                else (f"{language_labels()[original]} (no longer configured)")
            )
            field.choices = [*options, (original, label)]

    def clean(self) -> dict[str, Any] | None:  # noqa: PLR0912 - validate each explicit copy without silently discarding input
        """Keep incomplete copies and accidental translation reuse visible.

        Returns
        -------
        dict[str, Any] | None
            Cleaned data with field-level corrections for every selected copy.
        """
        data = super().clean()
        if data is None:
            return None
        selected: set[tuple[str, str]] = set()
        for index in range(self.copy_rows):
            prefix = f"copy_{index}_"
            channel = data.get(prefix + "channel")
            language = data.get(prefix + "language")
            if not channel:
                if data.get(prefix + "headline") or data.get(prefix + "body"):
                    self.add_error(
                        prefix + "channel", "Choose where this text will be posted."
                    )
                continue
            if not language:
                self.add_error(prefix + "language", "Choose this copy's language.")
            pair = (channel, language or "")
            if pair in selected:
                self.add_error(
                    prefix + "channel",
                    "This channel and language are already selected.",
                )
            selected.add(pair)
            if data.get(prefix + "mode") == "main":
                if language != data.get("language_code"):
                    self.add_error(
                        prefix + "mode", "Enter different text for another language."
                    )
                if data.get(prefix + "headline") or data.get(prefix + "body"):
                    self.add_error(
                        prefix + "mode",
                        "Choose different text to keep the headline or message "
                        "you entered.",
                    )
            else:
                for field in ("headline", "body"):
                    if not data.get(prefix + field):
                        self.add_error(prefix + field, "Enter this copy's text.")
        if not selected:
            self.add_error("copy_0_channel", "Choose at least one channel.")
        return data

    def draft_input(self) -> AnnouncementDraftInput:
        """Return the complete exact message and selected copies after validation.

        Returns
        -------
        AnnouncementDraftInput
            Canonical text with explicit bounded channel/language variants.
        """
        data = self.cleaned_data
        variants = []
        for index in range(self.copy_rows):
            prefix = f"copy_{index}_"
            if not data[prefix + "channel"]:
                continue
            main = data[prefix + "mode"] == "main"
            variants.append(
                AnnouncementVariantInput(
                    data[prefix + "channel"],
                    data[prefix + "language"],
                    data["headline"] if main else data[prefix + "headline"],
                    data["body"] if main else data[prefix + "body"],
                )
            )
        return AnnouncementDraftInput(
            data["headline"], data["body"], data["language_code"], tuple(variants)
        )


class SettingsForm(CommandForm):
    """Record the organizer's own rules and named manual destinations."""

    transport_field_names = StrictInputForm.transport_field_names | {"add_channel"}
    policy_name = forms.CharField(label="Record-keeping rules name", max_length=200)
    record_owner = forms.CharField(
        label="Who is responsible for these records?", max_length=200
    )
    review_on = forms.DateField(
        label="Review these rules on", widget=forms.DateInput(attrs={"type": "date"})
    )
    policy_url = HttpsURLField(
        label="Link to the rules", max_length=2000, required=False
    )
    policy_description = forms.CharField(
        label="Record-keeping rules",
        max_length=2000,
        required=False,
        help_text=(
            "Link to the rules above or describe them here, including how long "
            "records are kept and who may access them. This records your "
            "organization's decision; Maru does not approve it or delete "
            "records automatically."
        ),
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    confirmed = forms.BooleanField(
        label="I confirm these are our current record-keeping rules."
    )
    channel_count = StrictBase10IntegerField(
        min_value=1, max_value=MAX_CHANNELS, widget=forms.HiddenInput
    )

    def __init__(self, *args: Any, channel_count: int, **kwargs: Any) -> None:
        """Build a bounded list of channels with retained technical identities.

        Parameters
        ----------
        *args : Any
            Original submitted form data.
        channel_count : int
            Bounded number of explicitly requested destination rows.
        **kwargs : Any
            Standard form options.
        """
        super().__init__(*args, **kwargs)
        self.channel_rows = channel_count
        for index in range(channel_count):
            prefix = f"channel_{index}_"
            self.fields[prefix + "code"] = forms.CharField(
                max_length=40, widget=forms.HiddenInput
            )
            self.fields[prefix + "original_label"] = forms.CharField(
                max_length=100, required=False, widget=forms.HiddenInput
            )
            self.fields[prefix + "original_url"] = forms.CharField(
                max_length=2000, required=False, widget=forms.HiddenInput
            )
            self.fields[prefix + "label"] = forms.CharField(
                label=f"Channel {index + 1}: name",
                max_length=100,
                required=False,
                help_text="Name the exact destination, for example "
                "MaruCon news on Telegram.",
            )
            self.fields[prefix + "url"] = HttpsURLField(
                label=f"Channel {index + 1}: link",
                max_length=2000,
                required=False,
                help_text="Optional public HTTPS link. "
                "Do not enter passwords or access tokens.",
            )
            if not self.is_bound:
                self.initial.setdefault(prefix + "code", f"channel_{uuid4().hex[:16]}")
                self.initial.setdefault(
                    prefix + "original_label", self.initial.get(prefix + "label", "")
                )
                self.initial.setdefault(
                    prefix + "original_url", self.initial.get(prefix + "url", "")
                )
        if not self.is_bound:
            self.initial.setdefault("channel_count", channel_count)

    def clean(self) -> dict[str, Any] | None:
        """Require usable rules and channel names without silently discarding links.

        Returns
        -------
        dict[str, Any] | None
            Cleaned values with visible actionable corrections.
        """
        data = super().clean()
        if data is None:
            return None
        if not data.get("policy_url") and not data.get("policy_description"):
            self.add_error(
                "policy_description", "Link to or describe your record-keeping rules."
            )
        names = 0
        for index in range(self.channel_rows):
            prefix = f"channel_{index}_"
            if data.get(prefix + "label"):
                names += 1
            elif data.get(prefix + "url"):
                self.add_error(prefix + "label", "Name this destination.")
            _validate_url(self, prefix + "url", data)
        _validate_url(self, "policy_url", data)
        if not names:
            self.add_error("channel_0_label", "Name at least one manual channel.")
        return data

    def settings_input(self) -> AnnouncementSettingsInput:
        """Return only the organizer's explicit rules and named destinations.

        Returns
        -------
        AnnouncementSettingsInput
            Complete proposed settings, without inferred policy approval.
        """
        data = self.cleaned_data
        channels = tuple(
            ManualChannel(
                self._channel_identity(i),
                data[f"channel_{i}_label"],
                data[f"channel_{i}_url"],
            )
            for i in range(self.channel_rows)
            if data[f"channel_{i}_label"]
        )
        return AnnouncementSettingsInput(
            data["policy_name"],
            data["record_owner"],
            data["review_on"],
            data["confirmed"],
            channels,
            data["policy_url"],
            data["policy_description"],
        )

    def _channel_identity(self, index: int) -> str:
        data = self.cleaned_data
        prefix = f"channel_{index}_"
        original = data[prefix + "original_label"]
        if (
            original
            and not data[prefix + "original_url"]
            and original != data[prefix + "label"]
        ):
            identity = uuid5(
                data["idempotency_key"],
                data[prefix + "code"] + "\n" + data[prefix + "label"],
            )
            return f"channel_{identity.hex[:16]}"
        return str(data[prefix + "code"])


def _validate_url(form: forms.Form, name: str, data: dict[str, Any]) -> None:
    try:
        safe_url(data.get(name, ""))
    except forms.ValidationError as error:
        form.add_error(name, error)


class RequestReviewForm(CommandForm):
    """Request another person's review of the exact currently displayed revision."""

    confirmed = forms.BooleanField(
        label="I checked the text for every channel and am ready to ask for review."
    )


class ReviewForm(CommandForm):
    """Keep approval and requested changes explicit and separate from publication."""

    revision_id = CanonicalUUIDField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(
        label="Your decision",
        choices=[
            ("", "Choose a decision"),
            ("approve", "Approve this version"),
            ("changes_requested", "Request changes"),
        ],
        widget=forms.RadioSelect,
    )
    note = forms.CharField(
        label="Feedback for the author",
        max_length=1000,
        required=False,
        help_text="These private notes are not included in text copied for posting.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    confirmed = forms.BooleanField(
        label="I checked the main message and the text for every channel."
    )

    def clean(self) -> dict[str, Any] | None:
        """Require actionable feedback when the reviewer requests changes.

        Returns
        -------
        dict[str, Any] | None
            Original values with a visible missing-feedback error if needed.
        """
        data = super().clean()
        if (
            data
            and data.get("decision") == "changes_requested"
            and not data.get("note")
        ):
            self.add_error("note", "Explain what needs to change.")
        return data


class PublicationForm(CommandForm):
    """Record one human claim about exact approved copy posted elsewhere."""

    variant_id = CanonicalUUIDField(label="Channel and language", widget=forms.Select)
    published_at = forms.DateTimeField(
        label="When did you post it?",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    publication_url = HttpsURLField(
        label="Link to the published post", max_length=2000, required=False
    )
    confirmed = forms.BooleanField(
        label="I posted the approved text shown for this channel and language."
    )

    def __init__(
        self, *args: Any, choices: Iterable[tuple[str, str]], **kwargs: Any
    ) -> None:
        """Bind only approved channel copies to the report selector.

        Parameters
        ----------
        *args : Any
            Original submitted form data.
        choices : Iterable[tuple[str, str]]
            Exact currently approved variant locators and safe labels.
        **kwargs : Any
            Standard form options.
        """
        super().__init__(*args, **kwargs)
        options = list(choices)
        original = self.data.get("variant_id", "") if self.is_bound else ""
        try:
            canonical = str(UUID(str(original))) == original
        except ValueError:
            canonical = False
        if canonical and original not in {value for value, _label in options}:
            options.append((str(original), "Original selection (no longer current)"))
        cast("forms.Select", self.fields["variant_id"].widget).choices = [
            ("", "Choose the text you posted"),
            *options,
        ]

    def clean_publication_url(self) -> str:
        """Accept only public HTTPS references without embedded login details.

        Returns
        -------
        str
            Validated optional link; the server never fetches it.
        """
        return safe_url(self.cleaned_data["publication_url"])


class ReasonForm(CommandForm):
    """Explain a consequential change before recording it."""

    reason = forms.CharField(
        label="Reason", max_length=1000, widget=forms.Textarea(attrs={"rows": 4})
    )
    confirmed = forms.BooleanField(label="I understand the effect described above.")


class CorrectReportForm(ReasonForm):
    """Amend mistaken report evidence without rewriting the original report."""

    withdrawn = forms.ChoiceField(
        label="What was wrong?",
        choices=[
            ("", "Choose a correction"),
            ("yes", "This post was never made"),
            ("no", "The post was made, but its date or link was wrong"),
        ],
        widget=forms.RadioSelect,
    )
    published_at = forms.DateTimeField(
        label="Correct publication date and time",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    publication_url = HttpsURLField(
        label="Correct link to the post", max_length=2000, required=False
    )

    def clean(self) -> dict[str, Any] | None:
        """Require the actual timestamp when keeping a corrected publication claim.

        Returns
        -------
        dict[str, Any] | None
            Original values with visible correction errors if incomplete.
        """
        data = super().clean()
        if data:
            _validate_url(self, "publication_url", data)
            if data.get("withdrawn") == "no" and not data.get("published_at"):
                self.add_error("published_at", "Enter when the publication happened.")
        return data
