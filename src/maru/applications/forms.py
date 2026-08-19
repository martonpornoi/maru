"""Closed server-rendered forms for the typed applications studio."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any, ClassVar, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from django import forms
from django.core.exceptions import ValidationError

from maru.applications.models import (
    ApplicationClassification,
    ApplicationDefinition,
    ApplicationEligibilityKind,
    ApplicationQuestion,
    ApplicationQuestionType,
    ReviewDecisionKind,
)
from maru.authorization.models import RoleBundle
from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)
from maru.identity.models import Account
from maru.workforce.models import Department

_SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,79}$")
_POLICY_PATTERN = r"^[a-z][a-z0-9_.:-]{2,119}$"
_DATE_TIME_FORMAT = "%Y-%m-%dT%H:%M"
_MAX_REVIEWERS = 32
_OPTION_PARTS = 2
_MAX_OPTION_LABEL_LENGTH = 160
_MAX_OPTIONS = 100
_LOCAL_DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}\Z")


class RetryForm(StrictInputForm):
    retry_key = CanonicalUUIDField(widget=forms.HiddenInput)


class EditionLocalDateTimeField(forms.Field):
    """Parse one real, unambiguous minute in an explicit edition zone."""

    default_error_messages: ClassVar[dict[str, Any]] = {
        "invalid": "Enter a valid local date and time.",
        "ambiguous": (
            "Choose an unambiguous local time outside the daylight-saving change."
        ),
    }

    def __init__(self, *args: Any, zone_name: str = "UTC", **kwargs: Any) -> None:
        kwargs.setdefault(
            "widget",
            forms.DateTimeInput(
                format=_DATE_TIME_FORMAT,
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
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        try:
            first = datetime.strptime(value, _DATE_TIME_FORMAT).replace(
                tzinfo=self.zone,
                fold=0,
            )
        except ValueError as error:
            raise ValidationError(
                self.error_messages["invalid"],
                code="invalid",
            ) from error
        local = first.replace(tzinfo=None)
        second = local.replace(tzinfo=self.zone, fold=1)
        first_round_trip = (
            first.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None)
        )
        second_round_trip = (
            second.astimezone(UTC).astimezone(self.zone).replace(tzinfo=None)
        )
        first_valid = first_round_trip == local
        second_valid = second_round_trip == local
        if not first_valid and not second_valid:
            raise ValidationError(
                self.error_messages["ambiguous"],
                code="nonexistent",
            )
        if first_valid and second_valid and first.utcoffset() != second.utcoffset():
            raise ValidationError(
                self.error_messages["ambiguous"],
                code="ambiguous",
            )
        return first if first_valid else second

    def prepare_value(self, value: object) -> object:
        if isinstance(value, datetime):
            local = value.astimezone(self.zone) if value.tzinfo else value
            return local.strftime(_DATE_TIME_FORMAT)
        return value


def _date_time_field(label: str) -> EditionLocalDateTimeField:
    return EditionLocalDateTimeField(label=label)


class StarterCopyForm(RetryForm):
    opens_at = _date_time_field("Opens")
    closes_at = _date_time_field("Closes")
    applicant_edit_until = _date_time_field("Applicant edit deadline")

    def __init__(
        self,
        *args: Any,
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        for name in ("opens_at", "closes_at", "applicant_edit_until"):
            cast(EditionLocalDateTimeField, self.fields[name]).set_zone(
                edition_time_zone
            )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        opens_at = cleaned.get("opens_at")
        closes_at = cleaned.get("closes_at")
        edit_until = cleaned.get("applicant_edit_until")
        if opens_at and closes_at and opens_at >= closes_at:
            self.add_error("closes_at", "Closing must follow opening.")
        if edit_until and closes_at and edit_until > closes_at:
            self.add_error(
                "applicant_edit_until",
                "The edit deadline cannot follow closing.",
            )
        return cleaned


class DefinitionConfigureForm(RetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    name = forms.CharField(max_length=160)
    description = forms.CharField(
        max_length=4_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    purpose = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}))
    classification = forms.ChoiceField(choices=ApplicationClassification.choices)
    eligibility_kind = forms.ChoiceField(choices=ApplicationEligibilityKind.choices)
    maximum_submissions = StrictBase10IntegerField(min_value=1, max_value=100)
    opens_at = _date_time_field("Opens")
    closes_at = _date_time_field("Closes")
    applicant_edit_until = _date_time_field("Applicant edit deadline")
    minimum_age = StrictBase10IntegerField(min_value=0, max_value=120)
    audience_policy_code = forms.RegexField(
        _POLICY_PATTERN,
        required=False,
        max_length=120,
    )
    retention_policy_code = forms.RegexField(
        _POLICY_PATTERN,
        required=False,
        max_length=120,
    )
    age_policy_code = forms.RegexField(
        _POLICY_PATTERN,
        required=False,
        max_length=120,
    )
    owner_department_ids = forms.MultipleChoiceField(
        choices=(),
        widget=forms.CheckboxSelectMultiple,
    )
    reviewer_role_bundle_ids = forms.MultipleChoiceField(
        choices=(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    reviewer_emails = forms.CharField(
        required=False,
        max_length=8_000,
        help_text="Enter exact active-person emails, one per line.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    reason = forms.CharField(max_length=240)

    def __init__(
        self,
        *args: Any,
        departments: Iterable[Department],
        roles: Iterable[RoleBundle],
        edition_time_zone: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        owner_department_field = cast(
            forms.MultipleChoiceField,
            self.fields["owner_department_ids"],
        )
        owner_department_field.choices = tuple(
            (str(item.id), item.name) for item in departments
        )
        cast(
            forms.MultipleChoiceField,
            self.fields["reviewer_role_bundle_ids"],
        ).choices = tuple(
            (str(item.id), f"{item.name} v{item.version}") for item in roles
        )
        for name in ("opens_at", "closes_at", "applicant_edit_until"):
            cast(EditionLocalDateTimeField, self.fields[name]).set_zone(
                edition_time_zone
            )
        self.reviewer_account_ids: tuple[UUID, ...] = ()

    def clean_reviewer_emails(self) -> str:
        raw = str(self.cleaned_data.get("reviewer_emails", ""))
        emails = tuple(
            dict.fromkeys(
                item.strip().lower()
                for item in raw.replace(",", "\n").splitlines()
                if item.strip()
            )
        )
        if len(emails) > _MAX_REVIEWERS:
            raise ValidationError("Choose at most 32 exact named reviewers.")
        people = tuple(
            Account.objects.filter(
                email__in=emails,
                is_active=True,
                account_kind=Account.Kind.PERSON,
            ).order_by("email", "id")
        )
        if len(people) != len(emails):
            raise ValidationError(
                "Every reviewer email must exactly match an active person."
            )
        by_email = {item.email.lower(): item.id for item in people}
        self.reviewer_account_ids = tuple(by_email[email] for email in emails)
        return "\n".join(emails)

    def clean_owner_department_ids(self) -> tuple[UUID, ...]:
        return tuple(UUID(value) for value in self.cleaned_data["owner_department_ids"])

    def clean_reviewer_role_bundle_ids(self) -> tuple[UUID, ...]:
        return tuple(
            UUID(value)
            for value in self.cleaned_data.get("reviewer_role_bundle_ids", ())
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        opens_at = cleaned.get("opens_at")
        closes_at = cleaned.get("closes_at")
        edit_until = cleaned.get("applicant_edit_until")
        if opens_at and closes_at and opens_at >= closes_at:
            self.add_error("closes_at", "Closing must follow opening.")
        if edit_until and closes_at and edit_until > closes_at:
            self.add_error(
                "applicant_edit_until",
                "The edit deadline cannot follow closing.",
            )
        return cleaned


class SectionAddForm(RetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    key = forms.SlugField(max_length=80)
    title = forms.CharField(max_length=160)
    help_text = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    reason = forms.CharField(max_length=240)


class QuestionAddForm(RetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    section_id = forms.ChoiceField(choices=())
    key = forms.SlugField(max_length=80)
    field_type = forms.ChoiceField(choices=ApplicationQuestionType.choices)
    label = forms.CharField(max_length=200)
    help_text = forms.CharField(
        max_length=2_000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    required = forms.BooleanField(required=False)
    options_text = forms.CharField(
        required=False,
        max_length=20_000,
        help_text="For choice fields: one code|Label option per line.",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    minimum_length = StrictBase10IntegerField(min_value=0, required=False)
    maximum_length = StrictBase10IntegerField(
        min_value=1,
        max_value=65_536,
        required=False,
    )
    minimum_value = forms.DecimalField(
        max_digits=18,
        decimal_places=4,
        required=False,
    )
    maximum_value = forms.DecimalField(
        max_digits=18,
        decimal_places=4,
        required=False,
    )
    maximum_choices = StrictBase10IntegerField(
        min_value=1,
        max_value=100,
        required=False,
    )
    reference_kind = forms.RegexField(
        r"^[a-z][a-z0-9_.:-]{0,79}$",
        required=False,
        max_length=80,
    )
    condition_question_key = forms.SlugField(max_length=80, required=False)
    condition_operator = forms.ChoiceField(
        choices=(
            ("", "No condition"),
            ("equals", "Equals"),
            ("not_equals", "Does not equal"),
            ("contains", "Contains"),
        ),
        required=False,
    )
    condition_value = forms.JSONField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    purpose = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}))
    classification = forms.ChoiceField(choices=ApplicationClassification.choices)
    applicant_visible = forms.BooleanField(required=False, initial=True)
    applicant_writable = forms.BooleanField(required=False, initial=True)
    staff_visible = forms.BooleanField(required=False, initial=True)
    staff_writable = forms.BooleanField(required=False)
    reviewer_visible = forms.BooleanField(required=False, initial=True)
    public_after_approval = forms.BooleanField(required=False)
    api_projection = forms.BooleanField(required=False, initial=True)
    retention_policy_code = forms.RegexField(
        _POLICY_PATTERN,
        required=False,
        max_length=120,
    )
    reason = forms.CharField(max_length=240)

    def __init__(
        self,
        *args: Any,
        definition: ApplicationDefinition,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        cast(forms.ChoiceField, self.fields["section_id"]).choices = tuple(
            (str(item.id), item.title)
            for item in definition.sections.order_by("position", "id")
        )

    def clean_section_id(self) -> UUID:
        return UUID(self.cleaned_data["section_id"])

    def clean_options_text(self) -> list[dict[str, str]]:
        raw = str(self.cleaned_data.get("options_text", ""))
        options: list[dict[str, str]] = []
        seen: set[str] = set()
        for line in raw.splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 1)
            if len(parts) != _OPTION_PARTS:
                raise ValidationError("Use one code|Label option per line.")
            code, label = (item.strip() for item in parts)
            if (
                not _SLUG_PATTERN.fullmatch(code)
                or not label
                or len(label) > _MAX_OPTION_LABEL_LENGTH
                or code in seen
            ):
                raise ValidationError(
                    "Option codes and labels must be unique and bounded."
                )
            seen.add(code)
            options.append({"code": code, "label": label})
        if len(options) > _MAX_OPTIONS:
            raise ValidationError("Choose at most 100 options.")
        return options

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        condition_fields = (
            cleaned.get("condition_question_key"),
            cleaned.get("condition_operator"),
            cleaned.get("condition_value"),
        )
        if any(value not in (None, "") for value in condition_fields) and not all(
            value not in (None, "") for value in condition_fields
        ):
            self.add_error(
                "condition_question_key",
                "Complete all condition fields or leave all three blank.",
            )
        return cleaned

    @property
    def condition(self) -> dict[str, object]:
        if not self.cleaned_data.get("condition_question_key"):
            return {}
        return {
            "question_key": self.cleaned_data["condition_question_key"],
            "operator": self.cleaned_data["condition_operator"],
            "value": self.cleaned_data["condition_value"],
        }


class DefinitionLifecycleForm(RetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(max_length=240)


class DefinitionSuccessorForm(RetryForm):
    reason = forms.CharField(max_length=240)


class StartSubmissionForm(RetryForm):
    pass


class SubmitApplicationForm(RetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )


class ReviewDecisionForm(RetryForm):
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )
    decision = forms.ChoiceField(
        choices=ReviewDecisionKind.choices,
        widget=forms.HiddenInput,
    )
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}))


def _boolean_value(value: str) -> bool | None:
    return {"true": True, "false": False}.get(value)


def _answer_field(  # noqa: PLR0911, PLR0912
    question: ApplicationQuestion,
) -> forms.Field:
    common: dict[str, Any] = {
        "label": question.label,
        "help_text": question.help_text,
        "required": question.required,
    }
    if question.field_type == ApplicationQuestionType.LONG_TEXT:
        return forms.CharField(
            **common,
            min_length=question.minimum_length,
            max_length=question.maximum_length,
            widget=forms.Textarea(attrs={"rows": 5}),
        )
    if question.field_type == ApplicationQuestionType.SHORT_TEXT:
        return forms.CharField(
            **common,
            min_length=question.minimum_length,
            max_length=question.maximum_length,
        )
    if question.field_type == ApplicationQuestionType.INTEGER:
        return forms.IntegerField(**common)
    if question.field_type == ApplicationQuestionType.DECIMAL:
        return forms.DecimalField(
            **common,
            max_digits=18,
            decimal_places=4,
            min_value=question.minimum_value,
            max_value=question.maximum_value,
        )
    if question.field_type == ApplicationQuestionType.BOOLEAN:
        return forms.TypedChoiceField(
            **common,
            choices=(("", "Choose"), ("true", "Yes"), ("false", "No")),
            coerce=_boolean_value,
            empty_value=None,
        )
    if question.field_type == ApplicationQuestionType.SINGLE_CHOICE:
        return forms.ChoiceField(
            **common,
            choices=tuple((item["code"], item["label"]) for item in question.options),
        )
    if question.field_type == ApplicationQuestionType.MULTIPLE_CHOICE:
        return forms.MultipleChoiceField(
            **common,
            choices=tuple((item["code"], item["label"]) for item in question.options),
            widget=forms.CheckboxSelectMultiple,
        )
    if question.field_type == ApplicationQuestionType.DATE:
        return forms.DateField(**common, widget=forms.DateInput(attrs={"type": "date"}))
    if question.field_type == ApplicationQuestionType.TIME:
        return forms.TimeField(**common, widget=forms.TimeInput(attrs={"type": "time"}))
    if question.field_type == ApplicationQuestionType.INSTANT:
        return forms.DateTimeField(
            **common,
            widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        )
    if question.field_type == ApplicationQuestionType.EMAIL:
        return forms.EmailField(**common)
    if question.field_type == ApplicationQuestionType.URL:
        return forms.URLField(**common)
    if question.field_type in {
        ApplicationQuestionType.PERSON_REFERENCE,
        ApplicationQuestionType.DOMAIN_REFERENCE,
        ApplicationQuestionType.SAFE_FILE,
    }:
        return CanonicalUUIDField(**common)
    if question.field_type == ApplicationQuestionType.ADDRESS:
        return forms.JSONField(
            **common,
            widget=forms.Textarea(attrs={"rows": 5}),
        )
    return forms.CharField(**common)


class ApplicantAnswerForm(RetryForm):
    question_id = CanonicalUUIDField(widget=forms.HiddenInput)
    expected_version = StrictBase10IntegerField(
        min_value=1,
        widget=forms.HiddenInput,
    )

    def __init__(
        self,
        *args: Any,
        question: ApplicationQuestion,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.question = question
        self.fields["value"] = _answer_field(question)

    def clean_question_id(self) -> UUID:
        question_id = cast(UUID, self.cleaned_data["question_id"])
        if question_id != self.question.id:
            raise ValidationError("The application question is unavailable.")
        return question_id

    def clean_value(self) -> object:
        value = self.cleaned_data.get("value")
        if isinstance(value, (Decimal, UUID)):
            return str(value)
        if isinstance(value, (date, datetime, time)):
            return value.isoformat()
        return value


def answer_initial_value(value: object) -> object:
    """Format one normalized current answer for its bound Django field."""

    if isinstance(value, bool):
        return "true" if value else "false"
    return value
