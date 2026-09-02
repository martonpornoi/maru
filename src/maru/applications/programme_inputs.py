"""Closed, normalized inputs for dormant Programme calls and proposals."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from enum import StrEnum
from operator import attrgetter
from typing import Never, cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email
from django.utils import timezone

from maru.identity.queries import normalized_exact_login_email

MAX_PROGRAMME_CALL_TRACKS = 64
MAX_PROGRAMME_CALL_FORMATS = 32
MAX_PROGRAMME_CALL_CONTRIBUTOR_FIELDS = 4
MAX_PROGRAMME_CALL_SECTIONS = 100
MAX_PROGRAMME_CALL_QUESTIONS = 500
MAX_PROGRAMME_CALL_QUESTION_OPTIONS = 100
MAX_PROGRAMME_PROPOSAL_COLLABORATORS = 16
MAX_PROGRAMME_CALL_CODE_LENGTH = 80
MAX_PROGRAMME_LABEL_LENGTH = 160
MAX_PROGRAMME_DESCRIPTION_LENGTH = 4_000
MAX_PROGRAMME_POLICY_CODE_LENGTH = 120
MAX_PROGRAMME_PROFILE_BIOGRAPHY_LENGTH = 4_000
MAX_PROGRAMME_PROFILE_PRONOUNS_LENGTH = 160
MAX_PROGRAMME_PROFILE_WEBSITE_LENGTH = 500
MAX_PROGRAMME_INVITEE_EMAIL_LENGTH = 254
MAX_PROGRAMME_DURATION_MINUTES = 1_440
MAX_PROGRAMME_ANSWER_LENGTH = 65_536
MAX_PROGRAMME_SUBMISSIONS_PER_PERSON = 100
MIN_PROGRAMME_CHOICE_OPTIONS = 2
MAX_PROGRAMME_DECIMAL_DIGITS = 18
MAX_PROGRAMME_DECIMAL_PLACES = 4
MAX_PROGRAMME_OFFSET_HOURS = 14
MAX_PROGRAMME_OFFSET_MINUTES = 59
MIN_PROGRAMME_PHONE_LENGTH = 3
MAX_PROGRAMME_PHONE_LENGTH = 40

_LOWERCASE_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_POLICY_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{2,119}$")
_INSTANT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T"
    r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
    r"(?:\.\d{1,6})?"
    r"(?P<offset>Z|(?P<offset_sign>[+-])(?P<offset_hour>\d{2}):"
    r"(?P<offset_minute>\d{2}))$",
)
_REFERENCE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,79}$")


class ProgrammeContributorFieldCode(StrEnum):
    """Enumerate supported proposal-scoped public contributor fields."""

    PUBLIC_NAME = "public_name"
    BIOGRAPHY = "biography"
    PRONOUNS = "pronouns"
    WEBSITE = "website"


class ProgrammeContributorFieldRequirement(StrEnum):
    """Enumerate whether one contributor field is collected for a role."""

    HIDDEN = "hidden"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ProgrammeProposalRevisionResponseDecision(StrEnum):
    """Enumerate subject-owned responses to one exact sealed revision."""

    ACKNOWLEDGED = "acknowledged"
    DECLINED = "declined"


class ProgrammeCallClassification(StrEnum):
    """Enumerate classifications supported by proposal self-service."""

    INTERNAL = "C1"
    PERSONAL = "C2"
    RESTRICTED = "C3"


class ProgrammeCallQuestionType(StrEnum):
    """Enumerate typed fields available to a dedicated Programme call."""

    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    DATE = "date"
    TIME = "time"
    INSTANT = "instant"
    EMAIL = "email"
    PHONE = "phone"
    URL = "url"
    ADDRESS = "address"
    PERSON_REFERENCE = "person_reference"
    DOMAIN_REFERENCE = "domain_reference"
    SAFE_FILE = "safe_file"


class ProgrammeCallConditionOperator(StrEnum):
    """Enumerate supported earlier-answer condition operators."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"


def _field_error(field: str, message: str, code: str) -> Never:
    raise ValidationError({field: ValidationError(message, code=code)})


def normalized_programme_text(
    value: str,
    *,
    field: str,
    maximum: int,
    required: bool = False,
    collapse: bool = False,
    multiline: bool = False,
) -> str:
    """Return bounded NFC text with explicit whitespace semantics.

    Parameters
    ----------
    value : str
        Untrusted text to normalize.
    field : str
        Stable field name used in validation errors.
    maximum : int
        Inclusive normalized character ceiling.
    required : bool, default=False
        Whether normalized blank text is rejected.
    collapse : bool, default=False
        Whether whitespace runs are collapsed to one space.
    multiline : bool, default=False
        Whether line feeds are retained instead of rejected as controls.

    Returns
    -------
    str
        Normalized, bounded text.
    """
    if not isinstance(value, str):
        _field_error(
            field,
            "Enter text for this field.",
            "applications_programme_text_invalid",
        )
    normalized = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
    normalized = normalized.replace("\r", "\n")
    if any(
        unicodedata.category(character) == "Cc"
        and not (multiline and character == "\n")
        for character in normalized
    ):
        _field_error(
            field,
            "Control characters are not allowed.",
            "applications_programme_control_character",
        )
    normalized = normalized.strip()
    if collapse:
        normalized = " ".join(normalized.split())
    if required and not normalized:
        _field_error(
            field,
            "This field is required.",
            "applications_programme_value_required",
        )
    if len(normalized) > maximum:
        _field_error(
            field,
            f"Ensure this value has at most {maximum} characters.",
            "applications_programme_value_too_long",
        )
    return normalized


def normalized_programme_slug(value: str, *, field: str) -> str:
    """Return one bounded lower-case stable call, track, or format code.

    Parameters
    ----------
    value : str
        Candidate stable code.
    field : str
        Field name used for validation errors.

    Returns
    -------
    str
        Normalized lower-case slug.
    """
    normalized = normalized_programme_text(
        value,
        field=field,
        maximum=MAX_PROGRAMME_CALL_CODE_LENGTH,
        required=True,
    )
    if _LOWERCASE_SLUG_PATTERN.fullmatch(normalized) is None:
        _field_error(
            field,
            "Use lowercase letters, numbers, and single hyphens only.",
            "applications_programme_slug_invalid",
        )
    return normalized


def normalized_programme_policy_code(value: str, *, field: str) -> str:
    """Return one explicit stable versioned policy code.

    Parameters
    ----------
    value : str
        Candidate eligibility or retention-policy code.
    field : str
        Field name used for validation errors.

    Returns
    -------
    str
        Normalized versioned policy code.
    """
    normalized = normalized_programme_text(
        value,
        field=field,
        maximum=MAX_PROGRAMME_POLICY_CODE_LENGTH,
        required=True,
    )
    if _POLICY_CODE_PATTERN.fullmatch(normalized) is None:
        _field_error(
            field,
            "Use a stable versioned policy code.",
            "applications_programme_policy_code_invalid",
        )
    return normalized


def normalized_programme_email(value: str, *, field: str = "invitee_email") -> str:
    """Return the exact normalized login-email form used by Identity.

    Parameters
    ----------
    value : str
        Candidate collaborator login email.
    field : str, default='invitee_email'
        Field name used for validation errors.

    Returns
    -------
    str
        Normalized exact-login email.
    """
    if not isinstance(value, str):
        _field_error(
            field,
            "Enter a valid email address.",
            "applications_programme_email_invalid",
        )
    normalized = normalized_exact_login_email(value)
    if normalized is None or len(normalized) > MAX_PROGRAMME_INVITEE_EMAIL_LENGTH:
        _field_error(
            field,
            "Enter a valid email address.",
            "applications_programme_email_invalid",
        )
    return normalized


def normalized_programme_instant(  # noqa: DOC502 - helper owns validation
    value: str,
    *,
    field: str,
) -> datetime:
    """Return one strict explicit-offset instant normalized to UTC.

    Parameters
    ----------
    value : str
        Candidate ``YYYY-MM-DDTHH:MM:SS[.ffffff](Z|+/-HH:MM)`` instant.
    field : str
        Stable field name used in validation errors.

    Returns
    -------
    datetime
        Timezone-aware instant normalized to UTC.

    Raises
    ------
    ValidationError
        If the spelling, calendar value, or civil offset is invalid. Numeric
        offsets are bounded to ``-14:00`` through ``+14:00`` and the ambiguous
        RFC 3339 unknown-local-offset spelling ``-00:00`` is rejected.
    """
    match = _INSTANT_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        _field_error(
            field,
            "Use an exact date-time with an explicit valid offset.",
            "applications_programme_instant_invalid",
        )
    if match.group("offset") != "Z":
        offset_hour = int(match.group("offset_hour"))
        offset_minute = int(match.group("offset_minute"))
        if (
            offset_minute > MAX_PROGRAMME_OFFSET_MINUTES
            or offset_hour > MAX_PROGRAMME_OFFSET_HOURS
            or (offset_hour == MAX_PROGRAMME_OFFSET_HOURS and offset_minute != 0)
            or (
                match.group("offset_sign") == "-"
                and offset_hour == 0
                and offset_minute == 0
            )
        ):
            _field_error(
                field,
                "Use an exact date-time with an explicit valid offset.",
                "applications_programme_instant_invalid",
            )
    try:
        parsed = datetime.fromisoformat(value)
        normalized = parsed.astimezone(UTC)
    except (OverflowError, ValueError):
        _field_error(
            field,
            "Use an exact date-time with an explicit valid offset.",
            "applications_programme_instant_invalid",
        )
    return normalized


def require_programme_uuid(value: UUID, *, field: str) -> UUID:
    """Require an already parsed UUID instead of a free-text identity.

    Parameters
    ----------
    value : UUID
        Candidate typed identifier.
    field : str
        Field name used for validation errors.

    Returns
    -------
    UUID
        The validated identifier.
    """
    if not isinstance(value, UUID):
        _field_error(
            field,
            "Enter a typed UUID for this field.",
            "applications_programme_uuid_invalid",
        )
    return value


def require_programme_positive_integer(
    value: int,
    *,
    field: str,
    maximum: int | None = None,
) -> int:
    """Require a strict positive bounded integer.

    Parameters
    ----------
    value : int
        Candidate integer.
    field : str
        Field name used for validation errors.
    maximum : int | None, default=None
        Optional inclusive upper bound.

    Returns
    -------
    int
        The validated positive integer.
    """
    if (
        type(value) is not int
        or value <= 0
        or (maximum is not None and value > maximum)
    ):
        _field_error(
            field,
            "Enter a positive whole number within the supported bound.",
            "applications_programme_positive_integer_invalid",
        )
    return value


def require_programme_expected_version(value: int) -> int:
    """Require a strict non-negative optimistic aggregate version.

    Parameters
    ----------
    value : int
        Candidate aggregate version.

    Returns
    -------
    int
        The validated non-negative version.
    """
    if type(value) is not int or value < 0:
        _field_error(
            "expected_version",
            "Enter a non-negative whole-number version.",
            "applications_programme_version_invalid",
        )
    return value


def _closed_value[ChoiceT: StrEnum](
    value: str | ChoiceT,
    *,
    field: str,
    choices: type[ChoiceT],
) -> ChoiceT:
    try:
        return choices(value)
    except (TypeError, ValueError):
        _field_error(
            field,
            "Choose a supported value.",
            "applications_programme_closed_value_invalid",
        )


@dataclass(frozen=True, slots=True)
class ProgrammeCallTrackInput:
    """Define one ordered stable Programme call track.

    Attributes
    ----------
    code : str
        Stable lower-case track code.
    label : str
        Bounded applicant-facing track label.
    description : str
        Optional bounded track guidance.
    position : int
        One-based contiguous position in the call.
    """

    code: str
    label: str
    description: str
    position: int

    def __post_init__(self) -> None:
        """Normalize and validate the immutable track input."""
        object.__setattr__(
            self,
            "code",
            normalized_programme_slug(self.code, field="code"),
        )
        object.__setattr__(
            self,
            "label",
            normalized_programme_text(
                self.label,
                field="label",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
            ),
        )
        object.__setattr__(
            self,
            "description",
            normalized_programme_text(
                self.description,
                field="description",
                maximum=MAX_PROGRAMME_DESCRIPTION_LENGTH,
                multiline=True,
            ),
        )
        require_programme_positive_integer(
            self.position,
            field="position",
            maximum=MAX_PROGRAMME_CALL_TRACKS,
        )


@dataclass(frozen=True, slots=True)
class ProgrammeCallFormatInput:
    """Define one ordered Programme format and its duration bounds.

    Attributes
    ----------
    code : str
        Stable lower-case format code.
    label : str
        Bounded applicant-facing format label.
    description : str
        Optional bounded format guidance.
    position : int
        One-based contiguous position in the call.
    minimum_duration_minutes : int
        Smallest selectable duration in whole minutes.
    default_duration_minutes : int
        Preselected duration within the format bounds.
    maximum_duration_minutes : int
        Largest selectable duration in whole minutes.
    """

    code: str
    label: str
    description: str
    position: int
    minimum_duration_minutes: int
    default_duration_minutes: int
    maximum_duration_minutes: int

    def __post_init__(self) -> None:
        """Normalize and validate the immutable format input."""
        object.__setattr__(
            self,
            "code",
            normalized_programme_slug(self.code, field="code"),
        )
        object.__setattr__(
            self,
            "label",
            normalized_programme_text(
                self.label,
                field="label",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
            ),
        )
        object.__setattr__(
            self,
            "description",
            normalized_programme_text(
                self.description,
                field="description",
                maximum=MAX_PROGRAMME_DESCRIPTION_LENGTH,
                multiline=True,
            ),
        )
        require_programme_positive_integer(
            self.position,
            field="position",
            maximum=MAX_PROGRAMME_CALL_FORMATS,
        )
        durations = (
            self.minimum_duration_minutes,
            self.default_duration_minutes,
            self.maximum_duration_minutes,
        )
        for field, duration in zip(
            (
                "minimum_duration_minutes",
                "default_duration_minutes",
                "maximum_duration_minutes",
            ),
            durations,
            strict=True,
        ):
            require_programme_positive_integer(
                duration,
                field=field,
                maximum=MAX_PROGRAMME_DURATION_MINUTES,
            )
        if not (
            self.minimum_duration_minutes
            <= self.default_duration_minutes
            <= self.maximum_duration_minutes
        ):
            _field_error(
                "default_duration_minutes",
                "Keep minimum, default, and maximum duration in order.",
                "applications_programme_duration_order_invalid",
            )


@dataclass(frozen=True, slots=True)
class ProgrammeCallContributorFieldInput:
    """Configure one proposal-scoped public contributor field.

    Attributes
    ----------
    field_code : ProgrammeContributorFieldCode | str
        Closed proposed-public profile field.
    lead_requirement : ProgrammeContributorFieldRequirement | str
        Visibility or requirement rule for the proposal lead.
    collaborator_requirement : ProgrammeContributorFieldRequirement | str
        Visibility or requirement rule for collaborators.
    position : int
        One-based contiguous presentation position.
    """

    field_code: ProgrammeContributorFieldCode | str
    lead_requirement: ProgrammeContributorFieldRequirement | str
    collaborator_requirement: ProgrammeContributorFieldRequirement | str
    position: int

    def __post_init__(self) -> None:
        """Resolve closed values and reject an unused field declaration."""
        field_code = _closed_value(
            self.field_code,
            field="field_code",
            choices=ProgrammeContributorFieldCode,
        )
        lead_requirement = _closed_value(
            self.lead_requirement,
            field="lead_requirement",
            choices=ProgrammeContributorFieldRequirement,
        )
        collaborator_requirement = _closed_value(
            self.collaborator_requirement,
            field="collaborator_requirement",
            choices=ProgrammeContributorFieldRequirement,
        )
        object.__setattr__(self, "field_code", field_code)
        object.__setattr__(self, "lead_requirement", lead_requirement)
        object.__setattr__(self, "collaborator_requirement", collaborator_requirement)
        require_programme_positive_integer(
            self.position,
            field="position",
            maximum=MAX_PROGRAMME_CALL_CONTRIBUTOR_FIELDS,
        )
        if (
            lead_requirement is ProgrammeContributorFieldRequirement.HIDDEN
            and collaborator_requirement is ProgrammeContributorFieldRequirement.HIDDEN
        ):
            _field_error(
                "field_code",
                "Do not configure a contributor field hidden from every role.",
                "applications_programme_contributor_field_unused",
            )


@dataclass(frozen=True, slots=True)
class ProgrammeCallQuestionOptionInput:
    """Define one normalized stable choice option.

    Attributes
    ----------
    code : str
        Stable lower-case option code stored in answer values.
    label : str
        Bounded applicant-facing option label.
    """

    code: str
    label: str

    def __post_init__(self) -> None:
        """Normalize the code and bounded applicant-facing label."""
        object.__setattr__(
            self,
            "code",
            normalized_programme_slug(self.code, field="code"),
        )
        object.__setattr__(
            self,
            "label",
            normalized_programme_text(
                self.label,
                field="label",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class ProgrammeCallQuestionConditionInput:
    """Condition one question on an earlier answer in the same form graph.

    Attributes
    ----------
    question_key : str
        Stable key of the earlier source question.
    operator : ProgrammeCallConditionOperator | str
        Closed comparison operator supported by the source type.
    value : str | bool | int
        Canonical bounded comparison value.
    """

    question_key: str
    operator: ProgrammeCallConditionOperator | str
    value: str | bool | int

    def __post_init__(self) -> None:
        """Normalize the dependency and reject open JSON values."""
        object.__setattr__(
            self,
            "question_key",
            normalized_programme_slug(
                self.question_key,
                field="question_key",
            ),
        )
        object.__setattr__(
            self,
            "operator",
            _closed_value(
                self.operator,
                field="operator",
                choices=ProgrammeCallConditionOperator,
            ),
        )
        if isinstance(self.value, str):
            normalized = unicodedata.normalize("NFC", self.value).replace(
                "\r\n",
                "\n",
            )
            normalized = normalized.replace("\r", "\n")
            if (
                not normalized
                or len(normalized) > MAX_PROGRAMME_LABEL_LENGTH
                or any(
                    unicodedata.category(character) == "Cc" and character != "\n"
                    for character in normalized
                )
            ):
                _field_error(
                    "value",
                    "Use a bounded canonical string condition value.",
                    "applications_programme_condition_value_invalid",
                )
            object.__setattr__(self, "value", normalized)
        elif type(self.value) not in {bool, int}:
            _field_error(
                "value",
                "Use a bounded text, boolean, or whole-number condition value.",
                "applications_programme_condition_value_invalid",
            )


@dataclass(frozen=True, slots=True)
class ProgrammeCallQuestionInput:
    """Define one closed typed question in a complete Programme call graph.

    Attributes
    ----------
    key : str
        Stable lower-case question key.
    field_type : ProgrammeCallQuestionType | str
        Closed answer-value type.
    label : str
        Required applicant-facing question label.
    help_text : str
        Optional bounded applicant guidance.
    position : int
        One-based contiguous position within the section.
    required : bool
        Whether an applicable answer is required before sealing.
    options : tuple[ProgrammeCallQuestionOptionInput, ...]
        Closed choice options, empty for non-choice questions.
    minimum_length : int | None
        Optional inclusive text-length minimum.
    maximum_length : int | None
        Optional inclusive text-length maximum.
    minimum_value : Decimal | None
        Optional inclusive numeric minimum.
    maximum_value : Decimal | None
        Optional inclusive numeric maximum.
    maximum_choices : int | None
        Optional maximum selections for a multiple-choice question.
    reference_kind : str
        Registered reference kind for reference-valued questions.
    condition : ProgrammeCallQuestionConditionInput | None
        Optional dependency on one earlier question.
    purpose : str
        Documented collection purpose for this answer.
    classification : ProgrammeCallClassification | str
        Closed information classification.
    retention_policy_code : str
        Optional exact answer-specific retention policy.
    """

    key: str
    field_type: ProgrammeCallQuestionType | str
    label: str
    help_text: str
    position: int
    required: bool
    options: tuple[ProgrammeCallQuestionOptionInput, ...]
    minimum_length: int | None
    maximum_length: int | None
    minimum_value: Decimal | None
    maximum_value: Decimal | None
    maximum_choices: int | None
    reference_kind: str
    condition: ProgrammeCallQuestionConditionInput | None
    purpose: str
    classification: ProgrammeCallClassification | str
    retention_policy_code: str

    @property
    def source_binding(self) -> str:
        """Return the intentionally unavailable generic source binding."""
        return ""

    @property
    def public_after_approval(self) -> bool:
        """Return the intentionally disabled generic public projection."""
        return False

    @property
    def applicant_visible(self) -> bool:
        """Return the dedicated proposal-author visibility rule."""
        return True

    @property
    def applicant_writable(self) -> bool:
        """Return the dedicated proposal-author draft-write rule."""
        return True

    @property
    def staff_visible(self) -> bool:
        """Return the pre-review staff-disclosure rule."""
        return False

    @property
    def staff_writable(self) -> bool:
        """Return the immutable subject-answer ownership rule."""
        return False

    @property
    def reviewer_visible(self) -> bool:
        """Return the deliberately dormant review-layer rule."""
        return False

    @property
    def api_projection(self) -> bool:
        """Return the deliberately dormant generic API projection rule."""
        return False

    def __post_init__(self) -> None:
        """Normalize one question and enforce type-specific closed bounds."""
        object.__setattr__(
            self,
            "key",
            normalized_programme_slug(self.key, field="key"),
        )
        field_type = _closed_value(
            self.field_type,
            field="field_type",
            choices=ProgrammeCallQuestionType,
        )
        classification = _closed_value(
            self.classification,
            field="classification",
            choices=ProgrammeCallClassification,
        )
        object.__setattr__(self, "field_type", field_type)
        object.__setattr__(self, "classification", classification)
        object.__setattr__(
            self,
            "label",
            normalized_programme_text(
                self.label,
                field="label",
                maximum=200,
                required=True,
                collapse=True,
            ),
        )
        object.__setattr__(
            self,
            "help_text",
            normalized_programme_text(
                self.help_text,
                field="help_text",
                maximum=2_000,
                multiline=True,
            ),
        )
        object.__setattr__(
            self,
            "purpose",
            normalized_programme_text(
                self.purpose,
                field="purpose",
                maximum=500,
                required=True,
                collapse=True,
            ),
        )
        require_programme_positive_integer(self.position, field="position")
        if type(self.required) is not bool:
            _field_error(
                "required",
                "Choose whether this question is required.",
                "applications_programme_required_choice_invalid",
            )
        if (
            not isinstance(self.options, tuple)
            or len(self.options) > (MAX_PROGRAMME_CALL_QUESTION_OPTIONS)
            or any(
                not isinstance(option, ProgrammeCallQuestionOptionInput)
                for option in self.options
            )
        ):
            _field_error(
                "options",
                "Provide a bounded tuple of typed question options.",
                "applications_programme_question_options_invalid",
            )
        choice_types = {
            ProgrammeCallQuestionType.SINGLE_CHOICE,
            ProgrammeCallQuestionType.MULTIPLE_CHOICE,
        }
        if field_type in choice_types:
            option_codes = {item.code for item in self.options}
            if len(self.options) < MIN_PROGRAMME_CHOICE_OPTIONS or len(
                option_codes
            ) != len(self.options):
                _field_error(
                    "options",
                    "Choice questions require at least two unique options.",
                    "applications_programme_question_options_invalid",
                )
        elif self.options:
            _field_error(
                "options",
                "Only choice questions may define options.",
                "applications_programme_question_options_invalid",
            )
        text_types = {
            ProgrammeCallQuestionType.SHORT_TEXT,
            ProgrammeCallQuestionType.LONG_TEXT,
            ProgrammeCallQuestionType.EMAIL,
            ProgrammeCallQuestionType.PHONE,
            ProgrammeCallQuestionType.URL,
        }
        _validate_length_bounds(
            self.minimum_length,
            self.maximum_length,
            enabled=field_type in text_types,
        )
        _validate_number_bounds(
            self.minimum_value,
            self.maximum_value,
            enabled=field_type
            in {ProgrammeCallQuestionType.INTEGER, ProgrammeCallQuestionType.DECIMAL},
        )
        if field_type is ProgrammeCallQuestionType.MULTIPLE_CHOICE:
            if type(
                self.maximum_choices
            ) is not int or not 1 <= self.maximum_choices <= len(self.options):
                _field_error(
                    "maximum_choices",
                    "Choose a maximum within the option set.",
                    "applications_programme_maximum_choices_invalid",
                )
        elif self.maximum_choices is not None:
            _field_error(
                "maximum_choices",
                "Only multiple-choice questions use this bound.",
                "applications_programme_maximum_choices_invalid",
            )
        reference_types = {
            ProgrammeCallQuestionType.PERSON_REFERENCE,
            ProgrammeCallQuestionType.DOMAIN_REFERENCE,
        }
        reference_kind = normalized_programme_text(
            self.reference_kind,
            field="reference_kind",
            maximum=80,
            required=field_type in reference_types,
        )
        if (field_type in reference_types) != bool(reference_kind) or (
            reference_kind and _REFERENCE_KIND_PATTERN.fullmatch(reference_kind) is None
        ):
            _field_error(
                "reference_kind",
                "Reference questions require one stable registered kind.",
                "applications_programme_reference_kind_invalid",
            )
        object.__setattr__(self, "reference_kind", reference_kind)
        if self.condition is not None and not isinstance(
            self.condition,
            ProgrammeCallQuestionConditionInput,
        ):
            _field_error(
                "condition",
                "Use one typed earlier-question condition.",
                "applications_programme_condition_invalid",
            )
        retention_policy_code = normalized_programme_text(
            self.retention_policy_code,
            field="retention_policy_code",
            maximum=MAX_PROGRAMME_POLICY_CODE_LENGTH,
        )
        if retention_policy_code:
            retention_policy_code = normalized_programme_policy_code(
                retention_policy_code,
                field="retention_policy_code",
            )
        object.__setattr__(
            self,
            "retention_policy_code",
            retention_policy_code,
        )


def _validate_length_bounds(
    minimum: int | None,
    maximum: int | None,
    *,
    enabled: bool,
) -> None:
    if not enabled:
        if minimum is not None or maximum is not None:
            _field_error(
                "maximum_length",
                "Only bounded text questions use length limits.",
                "applications_programme_length_bound_invalid",
            )
        return
    for field, value in (("minimum_length", minimum), ("maximum_length", maximum)):
        if value is not None and (
            type(value) is not int or not 0 <= value <= MAX_PROGRAMME_ANSWER_LENGTH
        ):
            _field_error(
                field,
                "Use a non-negative length within the answer bound.",
                "applications_programme_length_bound_invalid",
            )
    if minimum is not None and maximum is not None and minimum > maximum:
        _field_error(
            "maximum_length",
            "Maximum length must not be smaller than minimum length.",
            "applications_programme_length_bound_invalid",
        )


def _validate_number_bounds(
    minimum: Decimal | None,
    maximum: Decimal | None,
    *,
    enabled: bool,
) -> None:
    if not enabled:
        if minimum is not None or maximum is not None:
            _field_error(
                "maximum_value",
                "Only numeric questions use numeric limits.",
                "applications_programme_numeric_bound_invalid",
            )
        return
    for field, value in (("minimum_value", minimum), ("maximum_value", maximum)):
        exponent = (
            cast("int", value.as_tuple().exponent)
            if isinstance(value, Decimal) and value.is_finite()
            else 0
        )
        if value is not None and (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or exponent < -MAX_PROGRAMME_DECIMAL_PLACES
            or len(value.as_tuple().digits) + max(exponent, 0)
            > MAX_PROGRAMME_DECIMAL_DIGITS
        ):
            _field_error(
                field,
                "Use a finite decimal with at most 18 digits and 4 decimal places.",
                "applications_programme_numeric_bound_invalid",
            )
    if minimum is not None and maximum is not None and minimum > maximum:
        _field_error(
            "maximum_value",
            "Maximum value must not be smaller than minimum value.",
            "applications_programme_numeric_bound_invalid",
        )


@dataclass(frozen=True, slots=True)
class ProgrammeCallSectionInput:
    """Define one ordered section and its complete question collection.

    Attributes
    ----------
    key : str
        Stable lower-case section key.
    title : str
        Required applicant-facing section title.
    help_text : str
        Optional bounded section guidance.
    position : int
        One-based contiguous position in the definition.
    questions : tuple[ProgrammeCallQuestionInput, ...]
        Complete bounded ordered question collection.
    """

    key: str
    title: str
    help_text: str
    position: int
    questions: tuple[ProgrammeCallQuestionInput, ...]

    def __post_init__(self) -> None:
        """Normalize the section and enforce bounded contiguous questions."""
        object.__setattr__(
            self,
            "key",
            normalized_programme_slug(self.key, field="key"),
        )
        object.__setattr__(
            self,
            "title",
            normalized_programme_text(
                self.title,
                field="title",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
            ),
        )
        object.__setattr__(
            self,
            "help_text",
            normalized_programme_text(
                self.help_text,
                field="help_text",
                maximum=2_000,
                multiline=True,
            ),
        )
        require_programme_positive_integer(
            self.position,
            field="position",
            maximum=MAX_PROGRAMME_CALL_SECTIONS,
        )
        _require_exact_tuple(
            self.questions,
            field="questions",
            expected_type=ProgrammeCallQuestionInput,
            maximum=MAX_PROGRAMME_CALL_QUESTIONS,
        )
        _require_unique_ordered(self.questions, field="questions", code_attribute="key")


def _validate_condition_compatibility(  # noqa: PLR0912
    *,
    question: ProgrammeCallQuestionInput,
    source: ProgrammeCallQuestionInput,
) -> None:
    """Keep stored condition semantics closed over one earlier source type.

    Parameters
    ----------
    question : ProgrammeCallQuestionInput
        Conditional question being validated.
    source : ProgrammeCallQuestionInput
        Earlier question referenced by the condition.
    """
    condition = question.condition
    if condition is None:
        return
    operator = cast("ProgrammeCallConditionOperator", condition.operator)
    source_type = cast("ProgrammeCallQuestionType", source.field_type)
    value = condition.value
    option_codes = {option.code for option in source.options}
    canonical_value = value
    if operator is ProgrammeCallConditionOperator.CONTAINS:
        valid = (
            source_type is ProgrammeCallQuestionType.MULTIPLE_CHOICE
            and type(value) is str
            and value in option_codes
        )
    elif source_type is ProgrammeCallQuestionType.BOOLEAN:
        valid = type(value) is bool
    elif source_type is ProgrammeCallQuestionType.INTEGER:
        valid = type(value) is int and -(2**31) <= value < 2**31
    elif source_type is ProgrammeCallQuestionType.SINGLE_CHOICE:
        valid = type(value) is str and value in option_codes
    elif source_type in {
        ProgrammeCallQuestionType.SHORT_TEXT,
        ProgrammeCallQuestionType.LONG_TEXT,
        ProgrammeCallQuestionType.EMAIL,
        ProgrammeCallQuestionType.PHONE,
        ProgrammeCallQuestionType.URL,
    }:
        if type(value) is not str:
            valid = False
        else:
            default_maximum = (
                240 if source_type is ProgrammeCallQuestionType.SHORT_TEXT else 16_384
            )
            valid = (
                (source.minimum_length or 0)
                <= len(value)
                <= (source.maximum_length or default_maximum)
            )
            try:
                if source_type is ProgrammeCallQuestionType.EMAIL:
                    validate_email(value)
                elif source_type is ProgrammeCallQuestionType.URL:
                    URLValidator(schemes=("https",))(value)
            except ValidationError:
                valid = False
            if source_type is ProgrammeCallQuestionType.PHONE:
                valid = valid and (
                    MIN_PROGRAMME_PHONE_LENGTH
                    <= len(value)
                    <= MAX_PROGRAMME_PHONE_LENGTH
                )
    else:
        valid = False
    if not valid:
        _field_error(
            "condition",
            "Use an operator and value supported by the earlier question type.",
            "applications_programme_condition_semantics_invalid",
        )
    object.__setattr__(condition, "value", canonical_value)


@dataclass(frozen=True, slots=True)
class ProgrammeCallDefinitionInput:
    """Define a complete usable typed form for one Programme call version.

    Attributes
    ----------
    code : str
        Stable lower-case code shared by one call lineage.
    name : str
        Required applicant-facing call name.
    description : str
        Bounded applicant-facing call guidance.
    purpose : str
        Documented collection purpose for the proposal.
    classification : ProgrammeCallClassification | str
        Closed default information classification.
    maximum_submissions_per_person : int
        Exact per-person proposal limit for the call version.
    opens_at : datetime
        Inclusive aware instant when proposal creation begins.
    closes_at : datetime
        Exclusive aware instant when response and submission close.
    applicant_edit_until : datetime
        Inclusive aware instant when draft editing ends.
    audience_policy_code : str
        Exact policy controlling call audience eligibility.
    retention_policy_code : str
        Default exact retention policy for proposal content.
    sections : tuple[ProgrammeCallSectionInput, ...]
        Complete immutable ordered form graph.
    """

    code: str
    name: str
    description: str
    purpose: str
    classification: ProgrammeCallClassification | str
    maximum_submissions_per_person: int
    opens_at: datetime
    closes_at: datetime
    applicant_edit_until: datetime
    audience_policy_code: str
    retention_policy_code: str
    sections: tuple[ProgrammeCallSectionInput, ...]

    @property
    def target_adapter_kind(self) -> str:
        """Return the dedicated non-legacy Programme target kind."""
        return "programme_item"

    @property
    def eligibility_kind(self) -> str:
        """Return the only admitted eligibility kind for this workflow."""
        return "authenticated_person"

    @property
    def minimum_age(self) -> int:
        """Return the deliberately absent generic age gate."""
        return 0

    def __post_init__(self) -> None:
        """Normalize and validate the complete immutable form graph."""
        object.__setattr__(
            self,
            "code",
            normalized_programme_slug(self.code, field="code"),
        )
        object.__setattr__(
            self,
            "name",
            normalized_programme_text(
                self.name,
                field="name",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
            ),
        )
        object.__setattr__(
            self,
            "description",
            normalized_programme_text(
                self.description,
                field="description",
                maximum=MAX_PROGRAMME_DESCRIPTION_LENGTH,
                multiline=True,
            ),
        )
        object.__setattr__(
            self,
            "purpose",
            normalized_programme_text(
                self.purpose,
                field="purpose",
                maximum=500,
                required=True,
                collapse=True,
            ),
        )
        classification = _closed_value(
            self.classification,
            field="classification",
            choices=ProgrammeCallClassification,
        )
        object.__setattr__(self, "classification", classification)
        require_programme_positive_integer(
            self.maximum_submissions_per_person,
            field="maximum_submissions_per_person",
            maximum=MAX_PROGRAMME_SUBMISSIONS_PER_PERSON,
        )
        _require_aware_datetime(self.opens_at, field="opens_at")
        _require_aware_datetime(self.closes_at, field="closes_at")
        _require_aware_datetime(
            self.applicant_edit_until,
            field="applicant_edit_until",
        )
        if not (
            self.opens_at <= self.applicant_edit_until <= self.closes_at
            and self.opens_at < self.closes_at
        ):
            _field_error(
                "closes_at",
                "Keep opening, applicant edit, and closing times in order.",
                "applications_programme_window_order_invalid",
            )
        for field in ("audience_policy_code", "retention_policy_code"):
            value = normalized_programme_text(
                getattr(self, field),
                field=field,
                maximum=MAX_PROGRAMME_POLICY_CODE_LENGTH,
            )
            if value:
                value = normalized_programme_policy_code(value, field=field)
            object.__setattr__(self, field, value)
        if classification is ProgrammeCallClassification.RESTRICTED and (
            not self.audience_policy_code or not self.retention_policy_code
        ):
            _field_error(
                "retention_policy_code",
                "Restricted proposal forms require explicit audience and retention.",
                "applications_programme_sensitive_policy_required",
            )
        _require_exact_tuple(
            self.sections,
            field="sections",
            expected_type=ProgrammeCallSectionInput,
            maximum=MAX_PROGRAMME_CALL_SECTIONS,
        )
        _require_unique_ordered(self.sections, field="sections", code_attribute="key")
        questions = tuple(
            question for section in self.sections for question in section.questions
        )
        if len(questions) > MAX_PROGRAMME_CALL_QUESTIONS or len(
            {question.key for question in questions}
        ) != len(questions):
            _field_error(
                "sections",
                "Use at most 500 questions with globally unique stable keys.",
                "applications_programme_question_graph_invalid",
            )
        classification_rank = {
            ProgrammeCallClassification.INTERNAL: 1,
            ProgrammeCallClassification.PERSONAL: 2,
            ProgrammeCallClassification.RESTRICTED: 3,
        }
        earlier_questions: dict[str, ProgrammeCallQuestionInput] = {}
        for question in questions:
            question_classification = cast(
                "ProgrammeCallClassification",
                question.classification,
            )
            if (
                classification_rank[question_classification]
                > classification_rank[classification]
            ):
                _field_error(
                    "classification",
                    "A question cannot exceed the definition classification.",
                    "applications_programme_question_classification_invalid",
                )
            if (
                question.classification is ProgrammeCallClassification.RESTRICTED
                and not (question.retention_policy_code or self.retention_policy_code)
            ):
                _field_error(
                    "retention_policy_code",
                    "Every restricted question requires explicit retention.",
                    "applications_programme_sensitive_policy_required",
                )
            if question.condition is not None:
                source = earlier_questions.get(question.condition.question_key)
                if source is None:
                    _field_error(
                        "condition",
                        "Conditions may reference only an earlier question.",
                        "applications_programme_condition_dependency_invalid",
                    )
                _validate_condition_compatibility(
                    question=question,
                    source=source,
                )
            earlier_questions[question.key] = question


def _require_aware_datetime(value: datetime, *, field: str) -> None:
    if not isinstance(value, datetime) or not timezone.is_aware(value):
        _field_error(
            field,
            "Use a timezone-aware date and time.",
            "applications_programme_datetime_invalid",
        )


@dataclass(frozen=True, slots=True)
class ProgrammeCallConfigurationInput:
    """Group the complete Programme-specific facet of one call draft.

    Attributes
    ----------
    owner_department_id : UUID
        Exact current Department responsible for the call.
    maximum_collaborators : int
        Maximum non-lead collaborators admitted to each proposal.
    content_policy_code : str
        Exact policy governing submitted proposal content.
    contributor_consent_policy_code : str
        Exact policy contributors must acknowledge for public-profile intent.
    collaboration_retention_policy_code : str
        Exact policy governing collaboration evidence retention.
    tracks : tuple[ProgrammeCallTrackInput, ...]
        Complete ordered call track catalog.
    formats : tuple[ProgrammeCallFormatInput, ...]
        Complete ordered call format catalog.
    contributor_fields : tuple[ProgrammeCallContributorFieldInput, ...]
        Complete ordered proposed-public contributor field policy.
    """

    owner_department_id: UUID
    maximum_collaborators: int
    content_policy_code: str
    contributor_consent_policy_code: str
    collaboration_retention_policy_code: str
    tracks: tuple[ProgrammeCallTrackInput, ...]
    formats: tuple[ProgrammeCallFormatInput, ...]
    contributor_fields: tuple[ProgrammeCallContributorFieldInput, ...]

    def __post_init__(self) -> None:
        """Validate cardinality, ordering, uniqueness, and required policy."""
        require_programme_uuid(self.owner_department_id, field="owner_department_id")
        if (
            type(self.maximum_collaborators) is not int
            or not 0
            <= self.maximum_collaborators
            <= MAX_PROGRAMME_PROPOSAL_COLLABORATORS
        ):
            _field_error(
                "maximum_collaborators",
                "Choose a collaborator limit within the supported bound.",
                "applications_programme_collaborator_limit_invalid",
            )
        for field in (
            "content_policy_code",
            "contributor_consent_policy_code",
            "collaboration_retention_policy_code",
        ):
            object.__setattr__(
                self,
                field,
                normalized_programme_policy_code(getattr(self, field), field=field),
            )
        _require_exact_tuple(
            self.tracks,
            field="tracks",
            expected_type=ProgrammeCallTrackInput,
            maximum=MAX_PROGRAMME_CALL_TRACKS,
        )
        _require_exact_tuple(
            self.formats,
            field="formats",
            expected_type=ProgrammeCallFormatInput,
            maximum=MAX_PROGRAMME_CALL_FORMATS,
        )
        _require_exact_tuple(
            self.contributor_fields,
            field="contributor_fields",
            expected_type=ProgrammeCallContributorFieldInput,
            maximum=MAX_PROGRAMME_CALL_CONTRIBUTOR_FIELDS,
        )
        _require_unique_ordered(self.tracks, field="tracks")
        _require_unique_ordered(self.formats, field="formats")
        _require_unique_ordered(
            self.contributor_fields,
            field="contributor_fields",
            code_attribute="field_code",
        )
        public_name = next(
            (
                item
                for item in self.contributor_fields
                if item.field_code is ProgrammeContributorFieldCode.PUBLIC_NAME
            ),
            None,
        )
        if (
            public_name is None
            or public_name.lead_requirement
            is not ProgrammeContributorFieldRequirement.REQUIRED
        ):
            _field_error(
                "contributor_fields",
                "The lead public name must be configured as required.",
                "applications_programme_lead_public_name_required",
            )


def _require_exact_tuple(
    value: object,
    *,
    field: str,
    expected_type: type[object],
    maximum: int,
) -> None:
    if (
        not isinstance(value, tuple)
        or not value
        or len(value) > maximum
        or any(not isinstance(item, expected_type) for item in value)
    ):
        _field_error(
            field,
            "Provide a non-empty bounded tuple of typed values.",
            "applications_programme_collection_invalid",
        )


def _require_unique_ordered(
    values: tuple[object, ...],
    *,
    field: str,
    code_attribute: str = "code",
) -> None:
    codes = tuple(str(getattr(value, code_attribute)) for value in values)
    position_of = attrgetter("position")
    positions = tuple(int(position_of(value)) for value in values)
    if len(codes) != len(set(codes)) or positions != tuple(range(1, len(values) + 1)):
        _field_error(
            field,
            "Use unique stable codes and contiguous positions starting at one.",
            "applications_programme_collection_order_invalid",
        )


@dataclass(frozen=True, slots=True)
class ProgrammeProposalSelectionInput:
    """Select one exact track and format for a proposal revision.

    Attributes
    ----------
    track_id : UUID
        Exact call-owned track identifier.
    format_id : UUID
        Exact call-owned format identifier.
    requested_duration_minutes : int
        Requested whole-minute duration within the selected format bounds.
    """

    track_id: UUID
    format_id: UUID
    requested_duration_minutes: int

    def __post_init__(self) -> None:
        """Require typed identifiers for both selected call children."""
        require_programme_uuid(self.track_id, field="track_id")
        require_programme_uuid(self.format_id, field="format_id")
        require_programme_positive_integer(
            self.requested_duration_minutes,
            field="requested_duration_minutes",
            maximum=MAX_PROGRAMME_DURATION_MINUTES,
        )


@dataclass(frozen=True, slots=True)
class ProgrammeProposalInvitationInput:
    """Normalize one purpose-bounded existing-person invitation request.

    Attributes
    ----------
    invitee_email : str
        Normalized exact Identity login email used only for resolution.
    expires_at : datetime
        Aware instant when the invitation stops conferring a relationship.
    """

    invitee_email: str
    expires_at: datetime

    def __post_init__(self) -> None:
        """Normalize exact email and require an aware expiry instant."""
        object.__setattr__(
            self,
            "invitee_email",
            normalized_programme_email(self.invitee_email),
        )
        if not isinstance(self.expires_at, datetime) or not timezone.is_aware(
            self.expires_at
        ):
            _field_error(
                "expires_at",
                "Use a timezone-aware invitation expiry.",
                "applications_programme_invitation_expiry_invalid",
            )


@dataclass(frozen=True, slots=True)
class ProgrammeProposalContributorProfileInput:
    """Carry one subject-owned proposed-public-profile revision.

    Attributes
    ----------
    public_name : str
        Subject-proposed public display name.
    biography : str
        Subject-proposed public biography.
    pronouns : str
        Subject-proposed public pronouns.
    website : str
        Subject-proposed HTTPS website.
    proposed_for_publication : bool
        Explicit choice to propose the populated values for publication.
    consent_acknowledged : bool
        Explicit acknowledgement of the exact contributor policy.
    consent_policy_code : str
        Exact versioned policy acknowledged by the subject.
    """

    public_name: str
    biography: str
    pronouns: str
    website: str
    proposed_for_publication: bool
    consent_acknowledged: bool
    consent_policy_code: str

    def __post_init__(self) -> None:
        """Normalize bounded fields and preserve an explicit publication choice."""
        if type(self.proposed_for_publication) is not bool:
            _field_error(
                "proposed_for_publication",
                "Choose whether these values are proposed for publication.",
                "applications_programme_publication_choice_invalid",
            )
        if type(self.consent_acknowledged) is not bool:
            _field_error(
                "consent_acknowledged",
                "Choose whether the exact contributor policy was acknowledged.",
                "applications_programme_consent_choice_invalid",
            )
        object.__setattr__(
            self,
            "public_name",
            normalized_programme_text(
                self.public_name,
                field="public_name",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=self.proposed_for_publication,
                collapse=True,
            ),
        )
        object.__setattr__(
            self,
            "biography",
            normalized_programme_text(
                self.biography,
                field="biography",
                maximum=MAX_PROGRAMME_PROFILE_BIOGRAPHY_LENGTH,
                multiline=True,
            ),
        )
        object.__setattr__(
            self,
            "pronouns",
            normalized_programme_text(
                self.pronouns,
                field="pronouns",
                maximum=MAX_PROGRAMME_PROFILE_PRONOUNS_LENGTH,
                collapse=True,
            ),
        )
        object.__setattr__(
            self,
            "website",
            normalized_programme_text(
                self.website,
                field="website",
                maximum=MAX_PROGRAMME_PROFILE_WEBSITE_LENGTH,
            ),
        )
        object.__setattr__(
            self,
            "consent_policy_code",
            normalized_programme_policy_code(
                self.consent_policy_code,
                field="consent_policy_code",
            ),
        )
        if not self.proposed_for_publication and any(
            (self.public_name, self.biography, self.pronouns, self.website)
        ):
            _field_error(
                "proposed_for_publication",
                "Clear proposed public values when publication is declined.",
                "applications_programme_unpublished_profile_not_blank",
            )
        if self.proposed_for_publication and not self.consent_acknowledged:
            _field_error(
                "consent_acknowledged",
                "Acknowledge the exact policy before proposing public values.",
                "applications_programme_public_consent_required",
            )


@dataclass(frozen=True, slots=True)
class ProgrammeProposalRevisionResponseInput:
    """Bind a subject response to one exact sealed revision and profile.

    Attributes
    ----------
    revision_id : UUID
        Exact sealed proposal revision being reviewed.
    contributor_id : UUID
        Exact included contributor relationship identifier.
    profile_revision_id : UUID
        Exact subject-owned profile revision frozen into the proposal revision.
    decision : ProgrammeProposalRevisionResponseDecision | str
        Closed acknowledgement or decline decision.
    """

    revision_id: UUID
    contributor_id: UUID
    profile_revision_id: UUID
    decision: ProgrammeProposalRevisionResponseDecision | str

    def __post_init__(self) -> None:
        """Resolve exact typed identifiers and the closed response decision."""
        require_programme_uuid(self.revision_id, field="revision_id")
        require_programme_uuid(self.contributor_id, field="contributor_id")
        require_programme_uuid(self.profile_revision_id, field="profile_revision_id")
        object.__setattr__(
            self,
            "decision",
            _closed_value(
                self.decision,
                field="decision",
                choices=ProgrammeProposalRevisionResponseDecision,
            ),
        )


def _canonical_value(value: object) -> object:  # noqa: PLR0911, PLR0912
    if value is None or type(value) in {bool, int}:
        return value
    if isinstance(value, StrEnum):
        return unicodedata.normalize("NFC", value.value)
    if isinstance(value, UUID):
        return str(value).lower()
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("Canonical Programme JSON rejects non-finite numbers.")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Canonical Programme JSON rejects non-finite decimals.")
        return format(value, "f")
    if isinstance(value, datetime):
        if not timezone.is_aware(value):
            raise ValueError("Canonical Programme JSON requires aware datetimes.")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        if value.tzinfo is None:
            raise ValueError("Canonical Programme JSON requires aware times.")
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Canonical Programme JSON requires string keys.")
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValueError("Canonical Programme JSON keys must remain unique.")
            normalized[normalized_key] = _canonical_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise TypeError(f"Unsupported canonical Programme JSON value: {type(value)!r}")


def canonical_programme_json(payload: Mapping[str, object]) -> bytes:
    """Return deterministic strict UTF-8 JSON for normalized Programme input.

    Parameters
    ----------
    payload : Mapping[str, object]
        Normalized Programme value graph.

    Returns
    -------
    bytes
        Strict canonical UTF-8 JSON bytes.
    """
    canonical = _canonical_value(payload)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_programme_digest(payload: Mapping[str, object]) -> str:
    """Return the lower-case SHA-256 digest of canonical Programme JSON.

    Parameters
    ----------
    payload : Mapping[str, object]
        Normalized Programme value graph.

    Returns
    -------
    str
        Lower-case hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(canonical_programme_json(payload)).hexdigest()


__all__ = [
    "MAX_PROGRAMME_CALL_CONTRIBUTOR_FIELDS",
    "MAX_PROGRAMME_CALL_FORMATS",
    "MAX_PROGRAMME_CALL_QUESTIONS",
    "MAX_PROGRAMME_CALL_QUESTION_OPTIONS",
    "MAX_PROGRAMME_CALL_SECTIONS",
    "MAX_PROGRAMME_CALL_TRACKS",
    "MAX_PROGRAMME_PROPOSAL_COLLABORATORS",
    "ProgrammeCallClassification",
    "ProgrammeCallConditionOperator",
    "ProgrammeCallConfigurationInput",
    "ProgrammeCallContributorFieldInput",
    "ProgrammeCallDefinitionInput",
    "ProgrammeCallFormatInput",
    "ProgrammeCallQuestionConditionInput",
    "ProgrammeCallQuestionInput",
    "ProgrammeCallQuestionOptionInput",
    "ProgrammeCallQuestionType",
    "ProgrammeCallSectionInput",
    "ProgrammeCallTrackInput",
    "ProgrammeContributorFieldCode",
    "ProgrammeContributorFieldRequirement",
    "ProgrammeProposalContributorProfileInput",
    "ProgrammeProposalInvitationInput",
    "ProgrammeProposalRevisionResponseDecision",
    "ProgrammeProposalRevisionResponseInput",
    "ProgrammeProposalSelectionInput",
    "canonical_programme_digest",
    "canonical_programme_json",
    "normalized_programme_email",
    "normalized_programme_instant",
    "normalized_programme_policy_code",
    "normalized_programme_slug",
    "normalized_programme_text",
    "require_programme_expected_version",
    "require_programme_positive_integer",
    "require_programme_uuid",
]
