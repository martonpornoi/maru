"""Closed browser forms for the governed Registration setup workspace."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django import forms

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.registration.models import (
    ProfileExtensionAudience,
    ProfileExtensionWriter,
    QuestionClassification,
    QuestionFieldType,
    QuestionVisibility,
    RegistrationSetupOrigin,
)
from maru.registration.setup_commands import (
    MAX_PAYMENT_WINDOW_MINUTES,
    MAX_SETUP_CAPACITY,
    MAX_SETUP_MINIMUM_AGE,
    MAX_SETUP_NAME_LENGTH,
    MAX_SETUP_REASON_LENGTH,
    MIN_PAYMENT_WINDOW_MINUTES,
)
from maru.registration.setup_definition_commands import (
    MAX_CONDITION_VALUE_LENGTH,
    MAX_DEFINITION_REASON_LENGTH,
    MAX_MINOR_JURISDICTION_LENGTH,
    MAX_MINOR_NOTICE_VERSION_LENGTH,
    MAX_MINOR_REVIEW_REFERENCE_LENGTH,
    MAX_PRODUCT_DESCRIPTION_LENGTH,
    MAX_PRODUCT_ELIGIBILITY_LENGTH,
    MAX_PRODUCT_NAME_LENGTH,
    MAX_PRODUCT_PRICE_MINOR,
    MAX_QUESTION_HELP_LENGTH,
    MAX_QUESTION_LABEL_LENGTH,
    MAX_QUESTION_OPTION_LENGTH,
    MAX_QUESTION_OPTIONS,
    MAX_QUESTION_PURPOSE_LENGTH,
)
from maru.registration.setup_section_commands import (
    MAX_SECTION_DESCRIPTION_LENGTH,
    MAX_SECTION_KEY_LENGTH,
    MAX_SECTION_REASON_LENGTH,
    MAX_SECTION_TITLE_LENGTH,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

SetupSourceChoices = tuple[tuple[str, str], ...]
SectionPlacementChoices = tuple[tuple[str, str], ...]
DefinitionPlacementChoices = tuple[tuple[str, str], ...]

_LOCAL_DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}\Z")


def _normalized_text(
    value: str,
    *,
    maximum: int,
    required: bool,
) -> str:
    normalized = " ".join(unicodedata.normalize("NFC", value).split())
    if required and not normalized:
        raise forms.ValidationError("This value is required.", code="required")
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise forms.ValidationError(
            "Control characters are not allowed.",
            code="control_character",
        )
    if len(normalized) > maximum:
        raise forms.ValidationError(
            f"Use at most {maximum} characters.",
            code="max_length",
        )
    return normalized


def _clean_with(
    value: str,
    *,
    maximum: int,
    required: bool,
) -> str:
    return _normalized_text(value, maximum=maximum, required=required)


class EditionLocalDateTimeField(forms.Field):
    """Parse one unambiguous minute in the edition's IANA time zone."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a valid local date and time.",
        "ambiguous": (
            "Choose an unambiguous local time outside the daylight-saving clock change."
        ),
    }

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        """Initialize the EditionLocalDateTimeField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        zone_name : str, default='UTC'
            The human-readable zone name shown to authorized readers.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={"type": "datetime-local", "step": "60"},
            ),
        )
        super().__init__(*args, **kwargs)
        self.zone = ZoneInfo(zone_name)

    def set_zone(self, zone_name: str) -> None:
        self.zone = ZoneInfo(zone_name)

    def to_python(self, value: object) -> datetime | None:
        if value in self.empty_values:
            return None
        if not isinstance(value, str) or _LOCAL_DATE_TIME.fullmatch(value) is None:
            raise forms.ValidationError(self.error_messages["invalid"], code="invalid")
        try:
            first = datetime.strptime(value, "%Y-%m-%dT%H:%M").replace(
                tzinfo=self.zone,
                fold=0,
            )
        except ValueError as error:
            raise forms.ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            ) from error
        local = first.replace(tzinfo=None)
        second = local.replace(tzinfo=self.zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise forms.ValidationError(
                self.error_messages["ambiguous"],
                code="ambiguous",
            )
        round_trip = first.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None)
        if round_trip != local:
            raise forms.ValidationError(
                self.error_messages["ambiguous"],
                code="nonexistent",
            )
        return first

    def prepare_value(self, value: object) -> object:
        if isinstance(value, datetime):
            local = value
            if value.tzinfo is not None:
                local = value.astimezone(self.zone)
            return local.strftime("%Y-%m-%dT%H:%M")
        return value


class CanonicalUUIDChoiceField(CanonicalUUIDField):
    """Render a select and accept only a bounded server-projected UUID."""

    widget = forms.Select
    default_error_messages: ClassVar[dict[str, Any]] = {
        **CanonicalUUIDField.default_error_messages,
        "invalid_choice": "Choose an available record from this edition workspace.",
    }

    def __init__(
        self,
        *args: Any,
        choices: Iterable[tuple[str, str]] = (),
        **kwargs: Any,
    ) -> None:
        """Initialize the CanonicalUUIDChoiceField instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        choices : Iterable[tuple[str, str]], default=()
            The choices evaluated while canonical uuidchoice field.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        self.choices = tuple(choices)
        kwargs.setdefault("widget", self.widget(choices=self.choices))
        super().__init__(*args, **kwargs)

    def set_choices(self, choices: Iterable[tuple[str, str]]) -> None:
        self.choices = tuple(choices)
        self.widget.choices = self.choices

    def validate(self, value: UUID | None) -> None:
        super().validate(value)
        if value is None:
            return
        allowed = {candidate for candidate, _label in self.choices if candidate}
        if str(value) not in allowed:
            raise forms.ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
            )


class RegistrationSetupStartForm(StrictInputForm):
    """Start one edition setup from one exact bounded source choice."""

    source_kind = forms.ChoiceField(
        label="Starting point",
        choices=(
            (RegistrationSetupOrigin.BLANK, "Blank registration"),
            (
                RegistrationSetupOrigin.PLATFORM_STARTER,
                "Platform convention-registration starter",
            ),
            (
                RegistrationSetupOrigin.PUBLISHED_TEMPLATE,
                "Published registration template",
            ),
            (RegistrationSetupOrigin.PRIOR_EDITION, "Prior edition registration"),
        ),
        help_text=(
            "A source is copied into this edition. Later edits never change the "
            "platform starter, template, or prior edition."
        ),
    )
    source_id = CanonicalUUIDChoiceField(
        label="Exact source version",
        required=False,
        choices=(("", "No source record — start blank"),),
        help_text=(
            "Choose one authorized immutable version. Leave this at no source "
            "only when starting blank."
        ),
    )
    name = forms.CharField(
        label="Configuration name",
        strip=False,
        max_length=MAX_SETUP_NAME_LENGTH,
        help_text="A recognizable name for this edition's registration form version.",
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_SETUP_NAME_LENGTH}
        ),
    )
    opens_at = EditionLocalDateTimeField(
        label="Registration opens",
        required=False,
        help_text="Local time in this edition's configured time zone.",
    )
    closes_at = EditionLocalDateTimeField(
        label="Registration closes",
        required=False,
        help_text="Must be later than the opening time.",
    )
    capacity = StrictBase10IntegerField(
        label="Overall capacity",
        required=False,
        min_value=1,
        max_value=MAX_SETUP_CAPACITY,
        help_text="The initial effective admission capacity.",
        widget=forms.NumberInput(
            attrs={"min": "1", "max": str(MAX_SETUP_CAPACITY), "step": "1"}
        ),
    )
    capacity_ceiling = StrictBase10IntegerField(
        label="Overall hard ceiling",
        required=False,
        min_value=1,
        max_value=MAX_SETUP_CAPACITY,
        help_text=(
            "The maximum a governed live adjustment may reach. It cannot be "
            "below the initial capacity."
        ),
        widget=forms.NumberInput(
            attrs={"min": "1", "max": str(MAX_SETUP_CAPACITY), "step": "1"}
        ),
    )
    currency = forms.ChoiceField(
        label="Currency",
        required=False,
        choices=(("", "Use the prior edition value"),),
        help_text="Choose one of this edition's configured ISO 4217 currencies.",
    )
    minimum_age = StrictBase10IntegerField(
        label="Minimum age",
        required=False,
        min_value=0,
        max_value=MAX_SETUP_MINIMUM_AGE,
        help_text=(
            "A value below 18 needs a complete reviewed minor policy before activation."
        ),
        widget=forms.NumberInput(attrs={"min": "0", "max": "120", "step": "1"}),
    )
    default_payment_window_minutes = StrictBase10IntegerField(
        label="Default payment window in minutes",
        required=False,
        min_value=MIN_PAYMENT_WINDOW_MINUTES,
        max_value=MAX_PAYMENT_WINDOW_MINUTES,
        help_text="Use 15 through 43,200 minutes.",
        widget=forms.NumberInput(
            attrs={
                "min": str(MIN_PAYMENT_WINDOW_MINUTES),
                "max": str(MAX_PAYMENT_WINDOW_MINUTES),
                "step": "1",
            }
        ),
    )
    waitlist_enabled = forms.ChoiceField(
        label="Wait-list policy",
        required=False,
        choices=(
            ("", "Use the prior edition value"),
            ("true", "Allow a wait-list"),
            ("false", "Do not allow a wait-list"),
        ),
        help_text="Choose explicitly for blank or template-based setup.",
    )
    automatic_waitlist_promotion = forms.ChoiceField(
        label="Automatic wait-list promotion",
        required=False,
        choices=(
            ("", "Use the prior edition value"),
            ("true", "Promote eligible entries automatically"),
            ("false", "Require a later controlled offer action"),
        ),
        help_text="Automatic promotion is unavailable when wait-listing is disabled.",
    )
    expected_version = StrictBase10IntegerField(
        min_value=0,
        max_value=0,
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(
        label="Administrative reason",
        strip=False,
        max_length=MAX_SETUP_REASON_LENGTH,
        help_text=(
            "Explain why registration setup is being started. This rationale "
            "is retained but is not published to attendees."
        ),
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": MAX_SETUP_REASON_LENGTH}),
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)

    def __init__(
        self,
        *args: Any,
        source_choices: SetupSourceChoices,
        source_kinds_by_id: dict[UUID, str],
        currency_codes: Iterable[str],
        edition_time_zone: str,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationSetupStartForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        source_choices : SetupSourceChoices
            The authorized source choices presented for validated selection.
        source_kinds_by_id : dict[UUID, str]
            The source kinds by identifier within the requested scope.
        currency_codes : Iterable[str]
            The closed set of currency codes accepted by the domain catalog.
        edition_time_zone : str
            The IANA time-zone name used for localization and validation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", "id_registration_setup_start_%s")
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("source_kind", RegistrationSetupOrigin.BLANK)
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)
        self.source_kinds_by_id = source_kinds_by_id
        source_field = cast("CanonicalUUIDChoiceField", self.fields["source_id"])
        source_field.set_choices(
            (("", "No source record — start blank"), *source_choices)
        )
        cast("forms.ChoiceField", self.fields["currency"]).choices = (
            ("", "Use the prior edition value"),
            *((str(code).upper(), str(code).upper()) for code in currency_codes),
        )
        cast("EditionLocalDateTimeField", self.fields["opens_at"]).set_zone(
            edition_time_zone
        )
        cast("EditionLocalDateTimeField", self.fields["closes_at"]).set_zone(
            edition_time_zone
        )

    def clean_name(self) -> str:
        """Validate and normalize the name field.

        Returns
        -------
        str
            The validated and normalized name.
        """
        return _clean_with(
            str(self.cleaned_data["name"]),
            maximum=MAX_SETUP_NAME_LENGTH,
            required=True,
        )

    def clean_reason(self) -> str:
        """Validate and normalize the reason field.

        Returns
        -------
        str
            The validated and normalized reason.
        """
        return _clean_with(
            str(self.cleaned_data["reason"]),
            maximum=MAX_SETUP_REASON_LENGTH,
            required=True,
        )

    def clean_currency(self) -> str | None:
        """Validate and normalize the currency field.

        Returns
        -------
        str | None
            The validated and normalized currency.
        """
        value = str(self.cleaned_data.get("currency", ""))
        return value.upper() if value else None

    def _clean_optional_boolean(self, field_name: str) -> bool | None:
        value = str(self.cleaned_data.get(field_name, ""))
        if not value:
            return None
        return value == "true"

    def clean_waitlist_enabled(self) -> bool | None:
        """Validate and normalize the waitlist enabled field.

        Returns
        -------
        bool | None
            The validated and normalized waitlist enabled.
        """
        return self._clean_optional_boolean("waitlist_enabled")

    def clean_automatic_waitlist_promotion(self) -> bool | None:
        """Validate and normalize the automatic waitlist promotion field.

        Returns
        -------
        bool | None
            The validated and normalized automatic waitlist promotion.
        """
        return self._clean_optional_boolean("automatic_waitlist_promotion")

    def clean(self) -> dict[str, Any] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any] | None
            A mapping containing the resolved clean data.
        """
        cleaned = super().clean()
        if cleaned is None:
            return None
        source_kind = cleaned.get("source_kind")
        source_id = cleaned.get("source_id")
        if source_kind == RegistrationSetupOrigin.BLANK:
            if source_id is not None:
                self.add_error("source_id", "Blank setup cannot use a source record.")
        elif isinstance(source_id, UUID):
            if self.source_kinds_by_id.get(source_id) != source_kind:
                self.add_error(
                    "source_id",
                    "Choose a source from the selected starting-point category.",
                )
        else:
            self.add_error("source_id", "Choose an exact source version.")

        can_inherit_metadata = source_kind == RegistrationSetupOrigin.PRIOR_EDITION
        if not can_inherit_metadata:
            for field_name in (
                "opens_at",
                "closes_at",
                "capacity",
                "currency",
                "minimum_age",
                "default_payment_window_minutes",
                "waitlist_enabled",
                "automatic_waitlist_promotion",
            ):
                if cleaned.get(field_name) is None:
                    self.add_error(
                        field_name,
                        (
                            "Enter this value for a blank, starter, or "
                            "template-based setup."
                        ),
                    )
        opens_at = cleaned.get("opens_at")
        closes_at = cleaned.get("closes_at")
        if (
            isinstance(opens_at, datetime)
            and isinstance(closes_at, datetime)
            and closes_at <= opens_at
        ):
            self.add_error("closes_at", "Closing time must be after opening time.")
        capacity = cleaned.get("capacity")
        capacity_ceiling = cleaned.get("capacity_ceiling")
        if (
            isinstance(capacity, int)
            and isinstance(capacity_ceiling, int)
            and capacity_ceiling < capacity
        ):
            self.add_error(
                "capacity_ceiling",
                "The hard ceiling cannot be below the initial capacity.",
            )
        waitlist = cleaned.get("waitlist_enabled")
        automatic = cleaned.get("automatic_waitlist_promotion")
        if waitlist is False and automatic is True:
            self.add_error(
                "automatic_waitlist_promotion",
                "Automatic promotion requires an enabled wait-list.",
            )
        return cleaned


class _RegistrationSectionReasonForm(StrictInputForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Administrative reason",
        strip=False,
        max_length=MAX_SECTION_REASON_LENGTH,
        help_text=(
            "Explain why this draft form change is needed. The reason is "
            "retained but never published as registration wording."
        ),
        widget=forms.Textarea(
            attrs={"rows": 3, "maxlength": MAX_SECTION_REASON_LENGTH}
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        auto_id: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the _RegistrationSectionReasonForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The setup version used for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The key used to deduplicate a retried command.
        auto_id : str
            The form identifier used by the dynamic setup page.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", auto_id)
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_reason(self) -> str:
        return _clean_with(
            str(self.cleaned_data["reason"]),
            maximum=MAX_SECTION_REASON_LENGTH,
            required=True,
        )


class _RegistrationSectionDetailsForm(_RegistrationSectionReasonForm):
    key = forms.SlugField(
        label="Section key",
        strip=False,
        max_length=MAX_SECTION_KEY_LENGTH,
        help_text=(
            "Stable lowercase key using letters, numbers, and single hyphens. "
            "Renaming is recorded as a versioned draft change."
        ),
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
                "maxlength": MAX_SECTION_KEY_LENGTH,
            }
        ),
    )
    title = forms.CharField(
        label="Attendee-facing title",
        strip=False,
        max_length=MAX_SECTION_TITLE_LENGTH,
        help_text="Plain text shown as the section heading in registration.",
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "maxlength": MAX_SECTION_TITLE_LENGTH}
        ),
    )
    description = forms.CharField(
        label="Attendee-facing description",
        required=False,
        strip=False,
        max_length=MAX_SECTION_DESCRIPTION_LENGTH,
        help_text=(
            "Optional plain text. Do not place private attendee data or internal "
            "administrative reasons here."
        ),
        widget=forms.Textarea(
            attrs={"rows": 4, "maxlength": MAX_SECTION_DESCRIPTION_LENGTH}
        ),
    )

    def clean_key(self) -> str:
        return unicodedata.normalize("NFC", str(self.cleaned_data["key"])).strip()

    def clean_title(self) -> str:
        return _clean_with(
            str(self.cleaned_data["title"]),
            maximum=MAX_SECTION_TITLE_LENGTH,
            required=True,
        )

    def clean_description(self) -> str:
        return _clean_with(
            str(self.cleaned_data.get("description", "")),
            maximum=MAX_SECTION_DESCRIPTION_LENGTH,
            required=False,
        )


class RegistrationSectionCreateForm(_RegistrationSectionDetailsForm):
    """Collect and validate registration section create input."""

    after_section_id = CanonicalUUIDChoiceField(
        label="Placement",
        required=False,
        choices=(("", "First section"),),
        help_text=(
            "Choose one current section as the preceding anchor. Maru safely "
            "renumbers the complete list."
        ),
    )

    def __init__(
        self,
        *args: Any,
        placement_choices: SectionPlacementChoices,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationSectionCreateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        placement_choices : SectionPlacementChoices
            The authorized placement choices presented for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id="id_registration_section_create_%s",
            **kwargs,
        )
        self.set_placement_choices(placement_choices)

    def set_placement_choices(self, choices: SectionPlacementChoices) -> None:
        """Set placement choices.

        Parameters
        ----------
        choices : SectionPlacementChoices
            The authorized choices available for validated selection.
        """
        field = cast("CanonicalUUIDChoiceField", self.fields["after_section_id"])
        field.set_choices((("", "First section"), *choices))


class RegistrationSectionUpdateForm(_RegistrationSectionDetailsForm):
    """Collect and validate registration section update input."""

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationSectionUpdateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_section_{ordinal}_update_%s",
            **kwargs,
        )


class RegistrationSectionMoveForm(_RegistrationSectionReasonForm):
    """Collect and validate registration section move input."""

    after_section_id = CanonicalUUIDChoiceField(
        label="New placement",
        required=False,
        choices=(("", "First section"),),
        help_text=(
            "Choose the section that should immediately precede this one. "
            "Dragging is not required."
        ),
    )

    def __init__(
        self,
        *args: Any,
        placement_choices: SectionPlacementChoices,
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationSectionMoveForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        placement_choices : SectionPlacementChoices
            The authorized placement choices presented for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_section_{ordinal}_move_%s",
            **kwargs,
        )
        self.set_placement_choices(placement_choices)

    def set_placement_choices(self, choices: SectionPlacementChoices) -> None:
        """Set placement choices.

        Parameters
        ----------
        choices : SectionPlacementChoices
            The authorized choices available for validated selection.
        """
        field = cast("CanonicalUUIDChoiceField", self.fields["after_section_id"])
        field.set_choices((("", "First section"), *choices))


class RegistrationSectionDeleteForm(_RegistrationSectionReasonForm):
    """Collect and validate registration section delete input."""

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationSectionDeleteForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_section_{ordinal}_delete_%s",
            **kwargs,
        )


class _RegistrationDefinitionReasonForm(StrictInputForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)
    reason = forms.CharField(
        label="Administrative reason",
        strip=False,
        max_length=MAX_DEFINITION_REASON_LENGTH,
        help_text=(
            "Explain this draft definition change. The rationale is retained "
            "as restricted administrative evidence."
        ),
        widget=forms.Textarea(
            attrs={"rows": 3, "maxlength": MAX_DEFINITION_REASON_LENGTH}
        ),
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        auto_id: str,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the _RegistrationDefinitionReasonForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The setup version used for optimistic concurrency control.
        auto_id : str
            The form identifier used by the dynamic setup page.
        retry_key : UUID | None, default=None
            The key used to deduplicate a retried command.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        kwargs.setdefault("auto_id", auto_id)
        initial = dict(kwargs.pop("initial", {}) or {})
        initial.setdefault("expected_version", expected_version)
        initial.setdefault("retry_key", retry_key or uuid4())
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)

    def clean_reason(self) -> str:
        return _clean_with(
            str(self.cleaned_data["reason"]),
            maximum=MAX_DEFINITION_REASON_LENGTH,
            required=True,
        )


class _TypedDefinitionForm(_RegistrationDefinitionReasonForm):
    key = forms.SlugField(
        label="Stable key",
        strip=False,
        max_length=80,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "off",
                "autocapitalize": "none",
                "spellcheck": "false",
                "maxlength": "80",
            }
        ),
    )
    label = forms.CharField(
        label="Label",
        strip=False,
        max_length=MAX_QUESTION_LABEL_LENGTH,
        widget=forms.TextInput(attrs={"maxlength": MAX_QUESTION_LABEL_LENGTH}),
    )
    help_text = forms.CharField(
        label="Help text",
        required=False,
        strip=False,
        max_length=MAX_QUESTION_HELP_LENGTH,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": MAX_QUESTION_HELP_LENGTH}),
    )
    field_type = forms.ChoiceField(
        label="Answer type",
        choices=QuestionFieldType.choices,
    )
    options = forms.CharField(
        label="Choice options",
        required=False,
        strip=False,
        max_length=64 * (MAX_QUESTION_OPTION_LENGTH + 1),
        help_text=(
            "For single- or multiple-choice fields, enter one unique option per "
            "line. Leave empty for every other type."
        ),
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    purpose = forms.CharField(
        label="Purpose",
        strip=False,
        max_length=MAX_QUESTION_PURPOSE_LENGTH,
        help_text="Explain why Maru needs this data.",
        widget=forms.Textarea(
            attrs={"rows": 2, "maxlength": MAX_QUESTION_PURPOSE_LENGTH}
        ),
    )
    classification = forms.ChoiceField(
        label="Data classification",
        choices=QuestionClassification.choices,
    )
    required = forms.TypedChoiceField(
        label="Requiredness",
        choices=(("false", "Optional"), ("true", "Required")),
        coerce=lambda value: value == "true",
    )

    def clean_key(self) -> str:
        return unicodedata.normalize("NFC", str(self.cleaned_data["key"])).strip()

    def clean_label(self) -> str:
        return _clean_with(
            str(self.cleaned_data["label"]),
            maximum=MAX_QUESTION_LABEL_LENGTH,
            required=True,
        )

    def clean_help_text(self) -> str:
        return _clean_with(
            str(self.cleaned_data.get("help_text", "")),
            maximum=MAX_QUESTION_HELP_LENGTH,
            required=False,
        )

    def clean_options(self) -> list[str]:
        raw = str(self.cleaned_data.get("options", ""))
        options = [
            _clean_with(
                item,
                maximum=MAX_QUESTION_OPTION_LENGTH,
                required=True,
            )
            for item in raw.splitlines()
            if item.strip()
        ]
        if len(options) > MAX_QUESTION_OPTIONS:
            raise forms.ValidationError(
                "Choose no more than 64 options.",
                code="max_options",
            )
        if len(set(options)) != len(options):
            raise forms.ValidationError(
                "Option labels must be unique.",
                code="duplicate_options",
            )
        return options

    def clean_purpose(self) -> str:
        return _clean_with(
            str(self.cleaned_data["purpose"]),
            maximum=MAX_QUESTION_PURPOSE_LENGTH,
            required=True,
        )


class _RegistrationQuestionDetailsForm(_TypedDefinitionForm):
    visibility = forms.ChoiceField(
        label="Visibility",
        choices=QuestionVisibility.choices,
    )
    section_id = CanonicalUUIDChoiceField(
        label="Section",
        required=False,
        choices=(("", "No section"),),
    )
    condition_question_key = forms.ChoiceField(
        label="Show after answer to",
        required=False,
        choices=(("", "Always show"),),
    )
    condition_value = forms.CharField(
        label="Required answer value",
        required=False,
        strip=False,
        max_length=MAX_CONDITION_VALUE_LENGTH,
        widget=forms.TextInput(attrs={"maxlength": MAX_CONDITION_VALUE_LENGTH}),
    )

    def set_definition_choices(
        self,
        *,
        section_choices: DefinitionPlacementChoices,
        condition_choices: Iterable[tuple[str, str]],
    ) -> None:
        cast("CanonicalUUIDChoiceField", self.fields["section_id"]).set_choices(
            (("", "No section"), *section_choices)
        )
        cast("forms.ChoiceField", self.fields["condition_question_key"]).choices = (
            ("", "Always show"),
            *condition_choices,
        )

    def clean_condition_value(self) -> str:
        return _clean_with(
            str(self.cleaned_data.get("condition_value", "")),
            maximum=MAX_CONDITION_VALUE_LENGTH,
            required=False,
        )


class RegistrationQuestionCreateForm(_RegistrationQuestionDetailsForm):
    """Collect and validate registration question create input."""

    after_question_id = CanonicalUUIDChoiceField(
        label="Placement",
        required=False,
        choices=(("", "First question"),),
    )

    def __init__(
        self,
        *args: Any,
        section_choices: DefinitionPlacementChoices,
        question_choices: DefinitionPlacementChoices,
        condition_choices: Iterable[tuple[str, str]],
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationQuestionCreateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        section_choices : DefinitionPlacementChoices
            The authorized section choices presented for validated selection.
        question_choices : DefinitionPlacementChoices
            The authorized question choices presented for validated selection.
        condition_choices : Iterable[tuple[str, str]]
            The authorized condition choices available for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id="id_registration_question_create_%s",
            **kwargs,
        )
        self.set_definition_choices(
            section_choices=section_choices,
            condition_choices=condition_choices,
        )
        cast("CanonicalUUIDChoiceField", self.fields["after_question_id"]).set_choices(
            (("", "First question"), *question_choices)
        )


class RegistrationQuestionUpdateForm(_RegistrationQuestionDetailsForm):
    """Collect and validate registration question update input."""

    def __init__(
        self,
        *args: Any,
        section_choices: DefinitionPlacementChoices,
        condition_choices: Iterable[tuple[str, str]],
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationQuestionUpdateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        section_choices : DefinitionPlacementChoices
            The authorized section choices presented for validated selection.
        condition_choices : Iterable[tuple[str, str]]
            The authorized condition choices available for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_question_{ordinal}_update_%s",
            **kwargs,
        )
        self.set_definition_choices(
            section_choices=section_choices,
            condition_choices=condition_choices,
        )


class RegistrationQuestionMoveForm(_RegistrationDefinitionReasonForm):
    """Collect and validate registration question move input."""

    after_question_id = CanonicalUUIDChoiceField(
        label="New placement",
        required=False,
        choices=(("", "First question"),),
    )

    def __init__(
        self,
        *args: Any,
        placement_choices: DefinitionPlacementChoices,
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationQuestionMoveForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        placement_choices : DefinitionPlacementChoices
            The authorized placement choices presented for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_question_{ordinal}_move_%s",
            **kwargs,
        )
        cast("CanonicalUUIDChoiceField", self.fields["after_question_id"]).set_choices(
            (("", "First question"), *placement_choices)
        )


class RegistrationDefinitionDeleteForm(_RegistrationDefinitionReasonForm):
    """Collect and validate registration definition delete input."""

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        ordinal: int,
        kind: str,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationDefinitionDeleteForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        kind : str
            The closed discriminator selecting the requested behavior.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_{kind}_{ordinal}_remove_%s",
            **kwargs,
        )


class _RegistrationProductDetailsForm(_RegistrationDefinitionReasonForm):
    code = forms.SlugField(label="Product code", strip=False, max_length=80)
    name = forms.CharField(
        label="Attendee-facing name",
        strip=False,
        max_length=MAX_PRODUCT_NAME_LENGTH,
    )
    description = forms.CharField(
        label="Description",
        required=False,
        strip=False,
        max_length=MAX_PRODUCT_DESCRIPTION_LENGTH,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    price_minor = StrictBase10IntegerField(
        label="Price in minor currency units",
        min_value=0,
        max_value=MAX_PRODUCT_PRICE_MINOR,
        widget=forms.NumberInput(
            attrs={"min": "0", "max": str(MAX_PRODUCT_PRICE_MINOR), "step": "1"}
        ),
    )
    capacity = StrictBase10IntegerField(
        label="Capacity",
        min_value=1,
        max_value=1_000_000,
    )
    capacity_ceiling = StrictBase10IntegerField(
        label="Hard capacity ceiling",
        required=False,
        min_value=1,
        max_value=MAX_SETUP_CAPACITY,
        help_text=(
            "Maximum governed live capacity. Leave blank to keep the current "
            "ceiling when editing, or use the initial capacity when creating."
        ),
    )
    entitlement_code = forms.SlugField(
        label="Entitlement code",
        strip=False,
        max_length=80,
    )
    entitlement_name = forms.CharField(
        label="Entitlement name",
        strip=False,
        max_length=MAX_PRODUCT_NAME_LENGTH,
    )
    sales_open_at = EditionLocalDateTimeField(
        label="Product sales open",
        required=False,
    )
    sales_close_at = EditionLocalDateTimeField(
        label="Product sales close",
        required=False,
    )
    required_capacity_codes = forms.MultipleChoiceField(
        label="Required participation capacities",
        required=False,
        choices=(),
        widget=forms.CheckboxSelectMultiple,
    )
    eligibility_explanation = forms.CharField(
        label="Eligibility explanation",
        required=False,
        strip=False,
        max_length=MAX_PRODUCT_ELIGIBILITY_LENGTH,
    )
    waitlist_enabled = forms.TypedChoiceField(
        label="Product wait-list",
        choices=(("true", "Allow waiting"), ("false", "Do not allow waiting")),
        coerce=lambda value: value == "true",
    )
    payment_window_minutes = StrictBase10IntegerField(
        label="Payment window in minutes",
        required=False,
        min_value=MIN_PAYMENT_WINDOW_MINUTES,
        max_value=MAX_PAYMENT_WINDOW_MINUTES,
    )

    def __init__(
        self,
        *args: Any,
        capacity_code_choices: Iterable[tuple[str, str]],
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        """Initialize the _RegistrationProductDetailsForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        capacity_code_choices : Iterable[tuple[str, str]]
            The capacity codes that may be required by the product.
        edition_time_zone : str
            The IANA time zone used to interpret local sales timestamps.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        cast(
            "forms.MultipleChoiceField",
            self.fields["required_capacity_codes"],
        ).choices = tuple(capacity_code_choices)
        cast("EditionLocalDateTimeField", self.fields["sales_open_at"]).set_zone(
            edition_time_zone
        )
        cast("EditionLocalDateTimeField", self.fields["sales_close_at"]).set_zone(
            edition_time_zone
        )

    def clean_code(self) -> str:
        return unicodedata.normalize("NFC", str(self.cleaned_data["code"])).strip()

    def clean_entitlement_code(self) -> str:
        return unicodedata.normalize(
            "NFC", str(self.cleaned_data["entitlement_code"])
        ).strip()

    def clean_name(self) -> str:
        return _clean_with(
            str(self.cleaned_data["name"]),
            maximum=MAX_PRODUCT_NAME_LENGTH,
            required=True,
        )

    def clean_description(self) -> str:
        return _clean_with(
            str(self.cleaned_data.get("description", "")),
            maximum=MAX_PRODUCT_DESCRIPTION_LENGTH,
            required=False,
        )

    def clean_entitlement_name(self) -> str:
        return _clean_with(
            str(self.cleaned_data["entitlement_name"]),
            maximum=MAX_PRODUCT_NAME_LENGTH,
            required=True,
        )

    def clean_eligibility_explanation(self) -> str:
        return _clean_with(
            str(self.cleaned_data.get("eligibility_explanation", "")),
            maximum=MAX_PRODUCT_ELIGIBILITY_LENGTH,
            required=False,
        )

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return None
        capacity = cleaned.get("capacity")
        ceiling = cleaned.get("capacity_ceiling")
        if (
            isinstance(capacity, int)
            and isinstance(ceiling, int)
            and ceiling < capacity
        ):
            self.add_error(
                "capacity_ceiling",
                "The hard ceiling cannot be below the initial capacity.",
            )
        return cleaned


class RegistrationProductCreateForm(_RegistrationProductDetailsForm):
    """Collect and validate registration product create input."""

    after_product_id = CanonicalUUIDChoiceField(
        label="Placement",
        required=False,
        choices=(("", "First product"),),
    )

    def __init__(
        self,
        *args: Any,
        placement_choices: DefinitionPlacementChoices,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationProductCreateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        placement_choices : DefinitionPlacementChoices
            The authorized placement choices presented for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id="id_registration_product_create_%s",
            **kwargs,
        )
        cast("CanonicalUUIDChoiceField", self.fields["after_product_id"]).set_choices(
            (("", "First product"), *placement_choices)
        )


class RegistrationProductUpdateForm(_RegistrationProductDetailsForm):
    """Collect and validate registration product update input."""

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationProductUpdateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_product_{ordinal}_update_%s",
            **kwargs,
        )


class RegistrationProductMoveForm(_RegistrationDefinitionReasonForm):
    """Collect and validate registration product move input."""

    after_product_id = CanonicalUUIDChoiceField(
        label="New placement",
        required=False,
        choices=(("", "First product"),),
    )

    def __init__(
        self,
        *args: Any,
        placement_choices: DefinitionPlacementChoices,
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationProductMoveForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        placement_choices : DefinitionPlacementChoices
            The authorized placement choices presented for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_product_{ordinal}_move_%s",
            **kwargs,
        )
        cast("CanonicalUUIDChoiceField", self.fields["after_product_id"]).set_choices(
            (("", "First product"), *placement_choices)
        )


class RegistrationMinorPolicyForm(_RegistrationDefinitionReasonForm):
    """Collect and validate registration minor policy input."""

    enabled = forms.TypedChoiceField(
        label="Minor registration",
        choices=(("false", "Disabled"), ("true", "Enabled")),
        coerce=lambda value: value == "true",
    )
    minor_age_threshold = StrictBase10IntegerField(
        label="Guardian threshold age",
        min_value=1,
        max_value=120,
    )
    guardian_notice_version = forms.CharField(
        label="Guardian notice version",
        required=False,
        strip=False,
        max_length=MAX_MINOR_NOTICE_VERSION_LENGTH,
    )
    jurisdiction_code = forms.CharField(
        label="Jurisdiction code",
        required=False,
        strip=False,
        max_length=MAX_MINOR_JURISDICTION_LENGTH,
    )
    review_reference = forms.CharField(
        label="Review reference",
        required=False,
        strip=False,
        max_length=MAX_MINOR_REVIEW_REFERENCE_LENGTH,
    )

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationMinorPolicyForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id="id_registration_minor_policy_%s",
            **kwargs,
        )

    def _clean_optional(self, name: str, maximum: int) -> str:
        return _clean_with(
            str(self.cleaned_data.get(name, "")),
            maximum=maximum,
            required=False,
        )

    def clean_guardian_notice_version(self) -> str:
        """Validate and normalize the guardian notice version field.

        Returns
        -------
        str
            The validated and normalized guardian notice version.
        """
        return self._clean_optional(
            "guardian_notice_version", MAX_MINOR_NOTICE_VERSION_LENGTH
        )

    def clean_jurisdiction_code(self) -> str:
        """Validate and normalize the jurisdiction code field.

        Returns
        -------
        str
            The validated and normalized jurisdiction code.
        """
        return self._clean_optional("jurisdiction_code", MAX_MINOR_JURISDICTION_LENGTH)

    def clean_review_reference(self) -> str:
        """Validate and normalize the review reference field.

        Returns
        -------
        str
            The validated and normalized review reference.
        """
        return self._clean_optional(
            "review_reference", MAX_MINOR_REVIEW_REFERENCE_LENGTH
        )


class _RegistrationProfileFieldDetailsForm(_TypedDefinitionForm):
    audience_policy = forms.ChoiceField(
        label="Who may read the current value",
        required=False,
        choices=ProfileExtensionAudience.choices,
        help_text=(
            "Choose one governed audience. This does not change who may edit the value."
        ),
    )
    audience_department_id = CanonicalUUIDChoiceField(
        label="Exact department or team",
        required=False,
        choices=(("", "No department — not a department audience"),),
    )
    writer_policy = forms.ChoiceField(
        label="Who may update the current value",
        choices=ProfileExtensionWriter.choices,
    )
    attendee_visible = forms.TypedChoiceField(
        required=False,
        choices=(("false", "Staff only"), ("true", "Visible to its owner")),
        coerce=lambda value: value == "true",
        widget=forms.HiddenInput,
    )

    def __init__(
        self,
        *args: Any,
        department_choices: DefinitionPlacementChoices,
        **kwargs: Any,
    ) -> None:
        """Initialize the _RegistrationProfileFieldDetailsForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        department_choices : DefinitionPlacementChoices
            The departments that may own the profile field audience.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(*args, **kwargs)
        cast(
            "CanonicalUUIDChoiceField", self.fields["audience_department_id"]
        ).set_choices(
            (("", "No department — not a department audience"), *department_choices)
        )

    def clean(self) -> dict[str, Any] | None:
        cleaned = super().clean()
        if cleaned is None:
            return None
        policy = cleaned.get("audience_policy")
        legacy_visibility = cleaned.get("attendee_visible")
        if not policy and legacy_visibility is not None:
            policy = (
                ProfileExtensionAudience.SELF
                if legacy_visibility
                else ProfileExtensionAudience.REGISTRATION_STAFF
            )
            cleaned["audience_policy"] = policy
        elif not policy:
            self.add_error("audience_policy", "Choose one governed audience.")
        elif legacy_visibility is not None:
            self.add_error(
                "attendee_visible",
                "Use audience policy instead of the legacy visibility input.",
            )
        department_id = cleaned.get("audience_department_id")
        if policy == ProfileExtensionAudience.DEPARTMENT and department_id is None:
            self.add_error(
                "audience_department_id",
                "Choose one exact active department for this audience.",
            )
        elif (
            policy != ProfileExtensionAudience.DEPARTMENT and department_id is not None
        ):
            self.add_error(
                "audience_department_id",
                "Only the department audience accepts a department.",
            )
        writer = cleaned.get("writer_policy")
        if writer in {
            ProfileExtensionWriter.ATTENDEE,
            ProfileExtensionWriter.ATTENDEE_AND_STAFF,
        } and policy not in {
            ProfileExtensionAudience.SELF,
            ProfileExtensionAudience.CONFIRMED_ATTENDEES,
            ProfileExtensionAudience.PUBLIC,
        }:
            self.add_error(
                "audience_policy",
                "An attendee-writable field must include its owner.",
            )
        return cleaned


class RegistrationProfileFieldCreateForm(_RegistrationProfileFieldDetailsForm):
    """Collect and validate registration profile field create input."""

    source_template_id = CanonicalUUIDChoiceField(
        label="Published-template provenance",
        required=False,
        choices=(("", "No template source"),),
    )
    source_prior_edition_id = CanonicalUUIDChoiceField(
        label="Prior-edition provenance",
        required=False,
        choices=(("", "No prior-edition source"),),
    )
    after_field_id = CanonicalUUIDChoiceField(
        label="Placement among draft fields",
        required=False,
        choices=(("", "First draft field"),),
    )

    def __init__(
        self,
        *args: Any,
        template_choices: DefinitionPlacementChoices,
        prior_edition_choices: DefinitionPlacementChoices,
        placement_choices: DefinitionPlacementChoices,
        department_choices: DefinitionPlacementChoices,
        expected_version: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationProfileFieldCreateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        template_choices : DefinitionPlacementChoices
            The authorized template choices presented for validated selection.
        prior_edition_choices : DefinitionPlacementChoices
            The authorized prior edition choices presented for validated selection.
        placement_choices : DefinitionPlacementChoices
            The authorized placement choices presented for validated selection.
        department_choices : DefinitionPlacementChoices
            The authorized department choices presented for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id="id_registration_profile_field_create_%s",
            department_choices=department_choices,
            **kwargs,
        )
        cast("CanonicalUUIDChoiceField", self.fields["source_template_id"]).set_choices(
            (("", "No template source"), *template_choices)
        )
        cast(
            "CanonicalUUIDChoiceField", self.fields["source_prior_edition_id"]
        ).set_choices((("", "No prior-edition source"), *prior_edition_choices))
        cast("CanonicalUUIDChoiceField", self.fields["after_field_id"]).set_choices(
            (("", "First draft field"), *placement_choices)
        )

    def clean(self) -> dict[str, Any] | None:
        """Validate and normalize the record.

        Returns
        -------
        dict[str, Any] | None
            A mapping containing the resolved clean data.
        """
        cleaned = super().clean()
        if (
            cleaned
            and cleaned.get("source_template_id")
            and cleaned.get("source_prior_edition_id")
        ):
            self.add_error(
                "source_prior_edition_id",
                "Choose either a template or a prior edition, not both.",
            )
        return cleaned


class RegistrationProfileFieldUpdateForm(_RegistrationProfileFieldDetailsForm):
    """Collect and validate registration profile field update input."""

    def __init__(
        self,
        *args: Any,
        expected_version: int,
        ordinal: int,
        department_choices: DefinitionPlacementChoices,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationProfileFieldUpdateForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        department_choices : DefinitionPlacementChoices
            The authorized department choices presented for validated selection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_profile_field_{ordinal}_update_%s",
            department_choices=department_choices,
            **kwargs,
        )


class RegistrationProfileFieldMoveForm(_RegistrationDefinitionReasonForm):
    """Collect and validate registration profile field move input."""

    after_field_id = CanonicalUUIDChoiceField(
        label="New placement among draft fields",
        required=False,
        choices=(("", "First draft field"),),
    )

    def __init__(
        self,
        *args: Any,
        placement_choices: DefinitionPlacementChoices,
        expected_version: int,
        ordinal: int,
        retry_key: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the RegistrationProfileFieldMoveForm instance.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        placement_choices : DefinitionPlacementChoices
            The authorized placement choices presented for validated selection.
        expected_version : int
            The aggregate version required for optimistic concurrency control.
        ordinal : int
            The deterministic display position within the owning collection.
        retry_key : UUID | None, default=None
            The stable key that makes an exact command retry idempotent.
        **kwargs : Any
            Keyword arguments forwarded to the framework implementation.
        """
        super().__init__(
            *args,
            expected_version=expected_version,
            retry_key=retry_key,
            auto_id=f"id_registration_profile_field_{ordinal}_move_%s",
            **kwargs,
        )
        cast("CanonicalUUIDChoiceField", self.fields["after_field_id"]).set_choices(
            (("", "First draft field"), *placement_choices)
        )


__all__ = [
    "DefinitionPlacementChoices",
    "RegistrationDefinitionDeleteForm",
    "RegistrationMinorPolicyForm",
    "RegistrationProductCreateForm",
    "RegistrationProductMoveForm",
    "RegistrationProductUpdateForm",
    "RegistrationProfileFieldCreateForm",
    "RegistrationProfileFieldMoveForm",
    "RegistrationProfileFieldUpdateForm",
    "RegistrationQuestionCreateForm",
    "RegistrationQuestionMoveForm",
    "RegistrationQuestionUpdateForm",
    "RegistrationSectionCreateForm",
    "RegistrationSectionDeleteForm",
    "RegistrationSectionMoveForm",
    "RegistrationSectionUpdateForm",
    "RegistrationSetupStartForm",
    "SectionPlacementChoices",
    "SetupSourceChoices",
]
