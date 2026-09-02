"""Strict, preview-safe raw inputs for Programme call and proposal imports.

The parser in this module is deliberately independent from persistence and
authorization.  It accepts one bounded UTF-8 JSON document, closes its shape,
normalizes values through the public Programme input contract, and returns an
immutable value graph plus deterministic canonical bytes and SHA-256 digests.
No parser diagnostic includes a submitted value, source key, identifier, or
digest.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Literal, Never
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email

from .programme_inputs import (
    MAX_PROGRAMME_ANSWER_LENGTH,
    MAX_PROGRAMME_CALL_CONTRIBUTOR_FIELDS,
    MAX_PROGRAMME_CALL_FORMATS,
    MAX_PROGRAMME_CALL_QUESTION_OPTIONS,
    MAX_PROGRAMME_CALL_QUESTIONS,
    MAX_PROGRAMME_CALL_SECTIONS,
    MAX_PROGRAMME_CALL_TRACKS,
    MAX_PROGRAMME_DECIMAL_DIGITS,
    MAX_PROGRAMME_DECIMAL_PLACES,
    MAX_PROGRAMME_DESCRIPTION_LENGTH,
    MAX_PROGRAMME_DURATION_MINUTES,
    MAX_PROGRAMME_LABEL_LENGTH,
    MAX_PROGRAMME_PROPOSAL_COLLABORATORS,
    ProgrammeCallClassification,
    ProgrammeCallConditionOperator,
    ProgrammeCallConfigurationInput,
    ProgrammeCallContributorFieldInput,
    ProgrammeCallDefinitionInput,
    ProgrammeCallFormatInput,
    ProgrammeCallQuestionConditionInput,
    ProgrammeCallQuestionInput,
    ProgrammeCallQuestionOptionInput,
    ProgrammeCallQuestionType,
    ProgrammeCallSectionInput,
    ProgrammeCallTrackInput,
    canonical_programme_digest,
    canonical_programme_json,
    normalized_programme_email,
    normalized_programme_instant,
    normalized_programme_policy_code,
    normalized_programme_slug,
    normalized_programme_text,
)

PROGRAMME_IMPORT_SCHEMA: Literal["applications.programme_import"] = (
    "applications.programme_import"
)
PROGRAMME_IMPORT_VERSION: Literal[1] = 1
MAX_PROGRAMME_IMPORT_BYTES = 8 * 1024 * 1024
MAX_PROGRAMME_IMPORT_ITEMS = 1_000
MAX_PROGRAMME_IMPORT_DEPTH = 16
MAX_PROGRAMME_IMPORT_VALUES = 250_000
MAX_PROGRAMME_IMPORT_OBJECT_MEMBERS = 32
MAX_PROGRAMME_IMPORT_ARRAY_ITEMS = 1_000
MAX_PROGRAMME_IMPORT_STRING_LENGTH = 65_536

_MAX_SOURCE_KEY_LENGTH = 200
_MAX_ADDRESS_PART_LENGTH = 200
_MIN_PHONE_LENGTH = 3
_MAX_PHONE_LENGTH = 40
_MAX_INTEGER_TOKEN_DIGITS = 19
_MIN_SIGNED_32_BIT = -(2**31)
_MAX_SIGNED_32_BIT = (2**31) - 1
_MIN_SURROGATE = 0xD800
_MAX_SURROGATE = 0xDFFF
_SOURCE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$")
_DECIMAL_PATTERN = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
_COUNTRY_CODE_PATTERN = re.compile(r"^[A-Za-z]{2}$")
_UTF_BOMS = (
    b"\x00\x00\xfe\xff",
    b"\xff\xfe\x00\x00",
    b"\xef\xbb\xbf",
    b"\xfe\xff",
    b"\xff\xfe",
)

_ERROR_TYPE = "applications_programme_import_payload_type_invalid"
_ERROR_TOO_LARGE = "applications_programme_import_payload_too_large"
_ERROR_ENCODING = "applications_programme_import_encoding_invalid"
_ERROR_JSON = "applications_programme_import_json_invalid"
_ERROR_DUPLICATE_KEY = "applications_programme_import_duplicate_key"
_ERROR_COMPLEXITY = "applications_programme_import_complexity_limit"
_ERROR_SCHEMA = "applications_programme_import_schema_invalid"
_ERROR_SHAPE = "applications_programme_import_shape_invalid"
_ERROR_FIELD = "applications_programme_import_field_invalid"
_ERROR_SOURCE_DUPLICATE = "applications_programme_import_source_duplicate"
_ERROR_QUESTION_TYPE = "applications_programme_import_question_type_unsupported"

_ROOT_FIELDS = ("schema", "version", "items")
_CALL_ITEM_FIELDS = ("kind", "source_key", "definition", "configuration")
_PROPOSAL_ITEM_FIELDS = (
    "kind",
    "source_key",
    "call_source_key",
    "lead_email",
    "selection",
    "answers",
)
_DEFINITION_FIELDS = (
    "code",
    "name",
    "description",
    "purpose",
    "classification",
    "maximum_submissions_per_person",
    "opens_at",
    "closes_at",
    "applicant_edit_until",
    "audience_policy_code",
    "retention_policy_code",
    "sections",
)
_CONFIGURATION_FIELDS = (
    "maximum_collaborators",
    "content_policy_code",
    "contributor_consent_policy_code",
    "collaboration_retention_policy_code",
    "tracks",
    "formats",
    "contributor_fields",
)
_TRACK_FIELDS = ("code", "label", "description")
_FORMAT_FIELDS = (
    "code",
    "label",
    "description",
    "minimum_duration_minutes",
    "default_duration_minutes",
    "maximum_duration_minutes",
)
_CONTRIBUTOR_FIELD_FIELDS = (
    "field_code",
    "lead_requirement",
    "collaborator_requirement",
)
_SECTION_FIELDS = ("key", "title", "help_text", "questions")
_QUESTION_FIELDS = (
    "key",
    "field_type",
    "label",
    "help_text",
    "required",
    "purpose",
    "classification",
    "retention_policy_code",
    "condition",
    "constraints",
)
_CONDITION_FIELDS = ("question_key", "operator", "value")
_OPTION_FIELDS = ("code", "label")
_SELECTION_FIELDS = (
    "track_code",
    "format_code",
    "requested_duration_minutes",
)
_ANSWER_FIELDS = ("question_key", "field_type", "value")
_ADDRESS_REQUIRED_FIELDS = ("line_1", "locality", "postal_code", "country_code")
_ADDRESS_OPTIONAL_FIELDS = ("line_2", "region")
_TEXT_CONSTRAINT_FIELDS = ("minimum_length", "maximum_length")
_NUMBER_CONSTRAINT_FIELDS = ("minimum_value", "maximum_value")

_ADMITTED_QUESTION_TYPES = frozenset(
    {
        ProgrammeCallQuestionType.SHORT_TEXT.value,
        ProgrammeCallQuestionType.LONG_TEXT.value,
        ProgrammeCallQuestionType.INTEGER.value,
        ProgrammeCallQuestionType.DECIMAL.value,
        ProgrammeCallQuestionType.BOOLEAN.value,
        ProgrammeCallQuestionType.SINGLE_CHOICE.value,
        ProgrammeCallQuestionType.MULTIPLE_CHOICE.value,
        ProgrammeCallQuestionType.DATE.value,
        ProgrammeCallQuestionType.TIME.value,
        ProgrammeCallQuestionType.INSTANT.value,
        ProgrammeCallQuestionType.EMAIL.value,
        ProgrammeCallQuestionType.PHONE.value,
        ProgrammeCallQuestionType.URL.value,
        ProgrammeCallQuestionType.ADDRESS.value,
    },
)
_DEFERRED_QUESTION_TYPES = frozenset(
    {
        ProgrammeCallQuestionType.PERSON_REFERENCE.value,
        ProgrammeCallQuestionType.DOMAIN_REFERENCE.value,
        ProgrammeCallQuestionType.SAFE_FILE.value,
    },
)


class ProgrammeImportInputError(ValueError):
    """Expose one stable, parser-safe import diagnostic.

    Attributes
    ----------
    code : str
        Stable machine-readable error code.
    item_index : int | None
        Zero-based wire item index when the error is item-local.
    pointer : str
        Safe schema pointer containing only fixed field names and indexes.
    field : str | None
        Fixed schema field name when one can be disclosed safely.
    retryable : bool
        Always false for deterministic input failures.
    """

    def __init__(
        self,
        code: str,
        *,
        item_index: int | None = None,
        pointer: str = "",
        field: str | None = None,
    ) -> None:
        """Initialize a value-free import diagnostic.

        Parameters
        ----------
        code : str
            Stable machine-readable error code.
        item_index : int | None, default=None
            Zero-based item position when the failure is item-local.
        pointer : str, default=''
            Safe schema pointer with no submitted key or value.
        field : str | None, default=None
            Fixed schema field when disclosure is safe.
        """
        super().__init__(code)
        self.code = code
        self.item_index = item_index
        self.pointer = pointer
        self.field = field
        self.retryable = False


@dataclass(frozen=True, slots=True)
class ProgrammeImportAddressInput:
    """Hold one immutable normalized address-valued proposal answer.

    Attributes
    ----------
    line_1 : str
        Required normalized first address line.
    line_2 : str
        Optional normalized second address line, or an empty string.
    locality : str
        Required normalized city or locality.
    region : str
        Optional normalized region, state, or province, or an empty string.
    postal_code : str
        Required normalized postal code.
    country_code : str
        Required normalized two-letter country code.
    """

    line_1: str
    line_2: str
    locality: str
    region: str
    postal_code: str
    country_code: str

    def as_application_value(self) -> dict[str, str]:
        """Return the JSON-shaped value expected by proposal validation.

        Returns
        -------
        dict[str, str]
            A new address mapping with absent optional blank fields omitted.
        """
        value = {
            "line_1": self.line_1,
            "locality": self.locality,
            "postal_code": self.postal_code,
            "country_code": self.country_code,
        }
        if self.line_2:
            value["line_2"] = self.line_2
        if self.region:
            value["region"] = self.region
        return value


type ProgrammeImportAnswerValue = (
    str | int | bool | tuple[str, ...] | ProgrammeImportAddressInput
)


@dataclass(frozen=True, slots=True)
class ProgrammeImportCallConfigurationInput:
    """Hold normalized call configuration before trusted owner binding.

    Attributes
    ----------
    maximum_collaborators : int
        Maximum collaborators permitted on each proposal.
    content_policy_code : str
        Normalized policy code governing submitted proposal content.
    contributor_consent_policy_code : str
        Normalized policy code governing contributor consent.
    collaboration_retention_policy_code : str
        Normalized policy code governing collaboration-data retention.
    tracks : tuple[ProgrammeCallTrackInput, ...]
        Closed, normalized call tracks in source order.
    formats : tuple[ProgrammeCallFormatInput, ...]
        Closed, normalized call formats in source order.
    contributor_fields : tuple[ProgrammeCallContributorFieldInput, ...]
        Closed, normalized contributor-field requirements in source order.
    """

    maximum_collaborators: int
    content_policy_code: str
    contributor_consent_policy_code: str
    collaboration_retention_policy_code: str
    tracks: tuple[ProgrammeCallTrackInput, ...]
    formats: tuple[ProgrammeCallFormatInput, ...]
    contributor_fields: tuple[ProgrammeCallContributorFieldInput, ...]

    def for_owner_department(
        self,
        owner_department_id: UUID,
    ) -> ProgrammeCallConfigurationInput:
        """Bind trusted Department context to the public call configuration.

        Parameters
        ----------
        owner_department_id : UUID
            Trusted exact-edition Department identifier supplied by the service.

        Returns
        -------
        ProgrammeCallConfigurationInput
            The complete public command input with its owner bound.
        """
        return ProgrammeCallConfigurationInput(
            owner_department_id=owner_department_id,
            maximum_collaborators=self.maximum_collaborators,
            content_policy_code=self.content_policy_code,
            contributor_consent_policy_code=self.contributor_consent_policy_code,
            collaboration_retention_policy_code=(
                self.collaboration_retention_policy_code
            ),
            tracks=self.tracks,
            formats=self.formats,
            contributor_fields=self.contributor_fields,
        )


@dataclass(frozen=True, slots=True)
class ProgrammeImportProposalSelectionInput:
    """Select normalized call-owned codes before preview resolves identifiers.

    Attributes
    ----------
    track_code : str
        Normalized unresolved call track code.
    format_code : str
        Normalized unresolved call format code.
    requested_duration_minutes : int
        Requested session duration in whole minutes.
    """

    track_code: str
    format_code: str
    requested_duration_minutes: int


@dataclass(frozen=True, slots=True)
class ProgrammeImportProposalAnswerInput:
    """Hold one normalized, immutable imported proposal answer.

    Attributes
    ----------
    question_key : str
        Normalized unresolved call question key.
    field_type : ProgrammeCallQuestionType
        Declared question field type used to normalize the answer.
    value : ProgrammeImportAnswerValue
        Immutable normalized answer value.
    """

    question_key: str
    field_type: ProgrammeCallQuestionType
    value: ProgrammeImportAnswerValue

    def as_application_value(self) -> object:
        """Return the mutable JSON shape expected by proposal validation.

        Returns
        -------
        object
            A scalar or a fresh list/address mapping for domain validation.
        """
        if isinstance(self.value, ProgrammeImportAddressInput):
            return self.value.as_application_value()
        if isinstance(self.value, tuple):
            return list(self.value)
        return self.value


@dataclass(frozen=True, slots=True)
class ProgrammeImportCallItemInput:
    """Hold one closed normalized call item and its canonical evidence.

    Attributes
    ----------
    item_index : int
        Zero-based source position of the import item.
    source_key : str
        Normalized batch-local source key for dependency resolution.
    definition : ProgrammeCallDefinitionInput
        Closed normalized call definition.
    configuration : ProgrammeImportCallConfigurationInput
        Closed normalized call configuration without a trusted owner.
    canonical_payload : bytes
        Deterministic canonical JSON bytes for this item.
    source_digest : str
        SHA-256 digest of the canonical item payload.
    """

    item_index: int
    source_key: str
    definition: ProgrammeCallDefinitionInput
    configuration: ProgrammeImportCallConfigurationInput
    canonical_payload: bytes
    source_digest: str

    @property
    def kind(self) -> Literal["call"]:
        """Return the closed wire discriminator."""
        return "call"

    @property
    def definition_input(self) -> ProgrammeCallDefinitionInput:
        """Return the public call-definition input expected by commands."""
        return self.definition

    def configuration_for_owner_department(
        self,
        owner_department_id: UUID,
    ) -> ProgrammeCallConfigurationInput:
        """Build the public configuration with trusted owner context.

        Parameters
        ----------
        owner_department_id : UUID
            Trusted exact-edition Department identifier supplied by the service.

        Returns
        -------
        ProgrammeCallConfigurationInput
            The complete public command input with its owner bound.
        """
        return self.configuration.for_owner_department(owner_department_id)


@dataclass(frozen=True, slots=True)
class ProgrammeImportProposalItemInput:
    """Hold one closed normalized proposal item and its canonical evidence.

    Attributes
    ----------
    item_index : int
        Zero-based source position of the import item.
    source_key : str
        Normalized batch-local source key for this proposal.
    call_source_key : str
        Normalized source key of the proposal's call dependency.
    lead_email : str
        Normalized lead email retained only in private staging.
    selection : ProgrammeImportProposalSelectionInput
        Normalized unresolved track, format, and duration selection.
    answers : tuple[ProgrammeImportProposalAnswerInput, ...]
        Closed normalized proposal answers in source order.
    canonical_payload : bytes
        Deterministic canonical JSON bytes for this item.
    source_digest : str
        SHA-256 digest of the canonical item payload.
    """

    item_index: int
    source_key: str
    call_source_key: str
    lead_email: str
    selection: ProgrammeImportProposalSelectionInput
    answers: tuple[ProgrammeImportProposalAnswerInput, ...]
    canonical_payload: bytes
    source_digest: str

    @property
    def kind(self) -> Literal["proposal"]:
        """Return the closed wire discriminator."""
        return "proposal"

    @property
    def track_code(self) -> str:
        """Return the normalized unresolved track code."""
        return self.selection.track_code

    @property
    def format_code(self) -> str:
        """Return the normalized unresolved format code."""
        return self.selection.format_code

    @property
    def requested_duration_minutes(self) -> int:
        """Return the normalized requested duration."""
        return self.selection.requested_duration_minutes


type ProgrammeImportItemInput = (
    ProgrammeImportCallItemInput | ProgrammeImportProposalItemInput
)


@dataclass(frozen=True, slots=True)
class ParsedProgrammeImportDocument:
    """Hold one normalized import batch suitable for preview orchestration.

    Attributes
    ----------
    schema : Literal['applications.programme_import']
        Closed import document schema discriminator.
    version : Literal[1]
        Supported import document schema version.
    items : tuple[ProgrammeImportItemInput, ...]
        Immutable normalized call and proposal items in source order.
    canonical_payload : bytes
        Deterministic canonical JSON bytes for the complete document.
    source_digest : str
        SHA-256 digest of the canonical document payload.
    """

    schema: Literal["applications.programme_import"]
    version: Literal[1]
    items: tuple[ProgrammeImportItemInput, ...]
    canonical_payload: bytes
    source_digest: str


ProgrammeImportBatchInput = ParsedProgrammeImportDocument


class _DuplicateKeyError(Exception):
    """Mark an exact or NFC-colliding JSON object key."""


class _ComplexityError(Exception):
    """Mark a JSON resource-limit failure."""


class _NumberTokenError(Exception):
    """Mark a JSON number outside the integer-only wire grammar."""


class _UnicodeScalarError(Exception):
    """Mark a decoded string containing a surrogate code point."""


def _fail(
    code: str,
    *,
    item_index: int | None = None,
    pointer: str = "",
    field: str | None = None,
) -> Never:
    raise ProgrammeImportInputError(
        code,
        item_index=item_index,
        pointer=pointer,
        field=field,
    )


def _validate_unicode_scalar(value: str) -> None:
    if any(_MIN_SURROGATE <= ord(character) <= _MAX_SURROGATE for character in value):
        raise _UnicodeScalarError


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) > MAX_PROGRAMME_IMPORT_OBJECT_MEMBERS:
        raise _ComplexityError
    parsed: dict[str, object] = {}
    for key, value in pairs:
        _validate_unicode_scalar(key)
        if len(key) > MAX_PROGRAMME_IMPORT_STRING_LENGTH:
            raise _ComplexityError
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in parsed:
            raise _DuplicateKeyError
        parsed[normalized_key] = value
    return parsed


def _parse_integer_token(value: str) -> int:
    if value == "-0" or len(value.removeprefix("-")) > _MAX_INTEGER_TOKEN_DIGITS:
        raise _NumberTokenError
    return int(value)


def _reject_non_integer_number(_value: str) -> Never:
    raise _NumberTokenError


def _check_lexical_depth(document: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in document:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_PROGRAMME_IMPORT_DEPTH:
                raise _ComplexityError
        elif character in "]}":
            depth -= 1


def _check_value_complexity(value: object) -> None:
    values_seen = 0
    remaining = [value]
    while remaining:
        current = remaining.pop()
        values_seen += 1
        if values_seen > MAX_PROGRAMME_IMPORT_VALUES:
            raise _ComplexityError
        if isinstance(current, dict):
            if len(current) > MAX_PROGRAMME_IMPORT_OBJECT_MEMBERS:
                raise _ComplexityError
            remaining.extend(current.values())
        elif isinstance(current, list):
            if len(current) > MAX_PROGRAMME_IMPORT_ARRAY_ITEMS:
                raise _ComplexityError
            remaining.extend(current)
        elif isinstance(current, str):
            _validate_unicode_scalar(current)
            if len(current) > MAX_PROGRAMME_IMPORT_STRING_LENGTH:
                raise _ComplexityError


def _decode_document(raw: bytes) -> object:
    if type(raw) is not bytes:
        _fail(_ERROR_TYPE)
    if len(raw) > MAX_PROGRAMME_IMPORT_BYTES:
        _fail(_ERROR_TOO_LARGE)
    if any(raw.startswith(bom) for bom in _UTF_BOMS) or b"\x00" in raw:
        _fail(_ERROR_ENCODING)
    try:
        document = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        _fail(_ERROR_ENCODING)
    try:
        _check_lexical_depth(document)
        parsed = json.loads(
            document,
            object_pairs_hook=_object_pairs,
            parse_int=_parse_integer_token,
            parse_float=_reject_non_integer_number,
            parse_constant=_reject_non_integer_number,
        )
        _check_value_complexity(parsed)
    except _DuplicateKeyError:
        _fail(_ERROR_DUPLICATE_KEY)
    except _ComplexityError:
        _fail(_ERROR_COMPLEXITY)
    except _UnicodeScalarError:
        _fail(_ERROR_ENCODING)
    except (_NumberTokenError, json.JSONDecodeError, RecursionError):
        _fail(_ERROR_JSON)
    return parsed


def _object(
    value: object,
    *,
    pointer: str,
    item_index: int | None,
) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail(_ERROR_SHAPE, item_index=item_index, pointer=pointer)
    return value


def _exact_object(
    value: object,
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...] = (),
    pointer: str,
    item_index: int | None,
) -> dict[str, object]:
    parsed = _object(value, pointer=pointer, item_index=item_index)
    admitted = frozenset((*required, *optional))
    if any(key not in admitted for key in parsed):
        _fail(_ERROR_SHAPE, item_index=item_index, pointer=pointer)
    missing = next((field for field in required if field not in parsed), None)
    if missing is not None:
        _fail(
            _ERROR_SHAPE,
            item_index=item_index,
            pointer=pointer,
            field=missing,
        )
    return parsed


def _array(
    value: object,
    *,
    minimum: int,
    maximum: int,
    pointer: str,
    item_index: int | None,
) -> list[object]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        _fail(_ERROR_SHAPE, item_index=item_index, pointer=pointer)
    return value


def _literal_string(
    value: object,
    *,
    pointer: str,
    item_index: int | None,
) -> str:
    if not isinstance(value, str):
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)
    return value


def _text(
    value: object,
    *,
    field: str,
    maximum: int,
    pointer: str,
    item_index: int,
    required: bool = False,
    collapse: bool = False,
    multiline: bool = False,
) -> str:
    if not isinstance(value, str):
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    try:
        return normalized_programme_text(
            value,
            field=field,
            maximum=maximum,
            required=required,
            collapse=collapse,
            multiline=multiline,
        )
    except ValidationError:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )


def _slug(
    value: object,
    *,
    field: str,
    pointer: str,
    item_index: int,
) -> str:
    if not isinstance(value, str):
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    try:
        return normalized_programme_slug(value, field=field)
    except ValidationError:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )


def _policy(
    value: object,
    *,
    field: str,
    pointer: str,
    item_index: int,
) -> str:
    if not isinstance(value, str):
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    try:
        return normalized_programme_policy_code(value, field=field)
    except ValidationError:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )


def _optional_policy(
    value: object,
    *,
    field: str,
    pointer: str,
    item_index: int,
) -> str:
    if value is None:
        return ""
    return _policy(
        value,
        field=field,
        pointer=pointer,
        item_index=item_index,
    )


def _source_key(
    value: object,
    *,
    field: str,
    pointer: str,
    item_index: int,
) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_SOURCE_KEY_LENGTH
        or _SOURCE_KEY_PATTERN.fullmatch(value) is None
    ):
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    return value


def _integer(
    value: object,
    *,
    minimum: int,
    maximum: int,
    field: str,
    pointer: str,
    item_index: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    return value


def _optional_integer(
    value: object,
    *,
    minimum: int,
    maximum: int,
    field: str,
    pointer: str,
    item_index: int,
) -> int | None:
    if value is None:
        return None
    return _integer(
        value,
        minimum=minimum,
        maximum=maximum,
        field=field,
        pointer=pointer,
        item_index=item_index,
    )


def _boolean(
    value: object,
    *,
    field: str,
    pointer: str,
    item_index: int,
) -> bool:
    if type(value) is not bool:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    return value


def _instant(
    value: object,
    *,
    field: str,
    pointer: str,
    item_index: int,
) -> datetime:
    text = _literal_string(value, pointer=pointer, item_index=item_index)
    try:
        return normalized_programme_instant(text, field=field)
    except ValidationError:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )


def _decimal_bound(
    value: object,
    *,
    field: str,
    pointer: str,
    item_index: int,
) -> Decimal | None:
    if value is None:
        return None
    text = _literal_string(value, pointer=pointer, item_index=item_index)
    if _DECIMAL_PATTERN.fullmatch(text) is None:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    fraction = text.partition(".")[2]
    significant = text.removeprefix("-").replace(".", "").lstrip("0") or "0"
    if (
        len(fraction) > MAX_PROGRAMME_DECIMAL_PLACES
        or len(significant) > MAX_PROGRAMME_DECIMAL_DIGITS
    ):
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field=field,
        )
    return Decimal(0) if parsed.is_zero() else parsed.normalize()


def _parse_option(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeCallQuestionOptionInput:
    parsed = _exact_object(
        value,
        required=_OPTION_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    try:
        return ProgrammeCallQuestionOptionInput(
            code=_slug(
                parsed["code"],
                field="code",
                pointer=f"{pointer}/code",
                item_index=item_index,
            ),
            label=_text(
                parsed["label"],
                field="label",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
                pointer=f"{pointer}/label",
                item_index=item_index,
            ),
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_condition(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeCallQuestionConditionInput | None:
    if value is None:
        return None
    parsed = _exact_object(
        value,
        required=_CONDITION_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    condition_value = parsed["value"]
    if isinstance(condition_value, str):
        condition_value = _text(
            condition_value,
            field="value",
            maximum=MAX_PROGRAMME_LABEL_LENGTH,
            required=True,
            multiline=True,
            pointer=f"{pointer}/value",
            item_index=item_index,
        )
    elif type(condition_value) is int:
        condition_value = _integer(
            condition_value,
            minimum=_MIN_SIGNED_32_BIT,
            maximum=_MAX_SIGNED_32_BIT,
            field="value",
            pointer=f"{pointer}/value",
            item_index=item_index,
        )
    elif type(condition_value) is not bool:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=f"{pointer}/value",
            field="value",
        )
    try:
        return ProgrammeCallQuestionConditionInput(
            question_key=_slug(
                parsed["question_key"],
                field="question_key",
                pointer=f"{pointer}/question_key",
                item_index=item_index,
            ),
            operator=_literal_string(
                parsed["operator"],
                pointer=f"{pointer}/operator",
                item_index=item_index,
            ),
            value=condition_value,
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_question_constraints(
    field_type: ProgrammeCallQuestionType,
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> tuple[
    tuple[ProgrammeCallQuestionOptionInput, ...],
    int | None,
    int | None,
    Decimal | None,
    Decimal | None,
    int | None,
]:
    empty_options: tuple[ProgrammeCallQuestionOptionInput, ...] = ()
    text_types = {
        ProgrammeCallQuestionType.SHORT_TEXT,
        ProgrammeCallQuestionType.LONG_TEXT,
        ProgrammeCallQuestionType.EMAIL,
        ProgrammeCallQuestionType.PHONE,
        ProgrammeCallQuestionType.URL,
    }
    if field_type in text_types:
        parsed = _exact_object(
            value,
            required=_TEXT_CONSTRAINT_FIELDS,
            pointer=pointer,
            item_index=item_index,
        )
        return (
            empty_options,
            _optional_integer(
                parsed["minimum_length"],
                minimum=0,
                maximum=MAX_PROGRAMME_ANSWER_LENGTH,
                field="minimum_length",
                pointer=f"{pointer}/minimum_length",
                item_index=item_index,
            ),
            _optional_integer(
                parsed["maximum_length"],
                minimum=0,
                maximum=MAX_PROGRAMME_ANSWER_LENGTH,
                field="maximum_length",
                pointer=f"{pointer}/maximum_length",
                item_index=item_index,
            ),
            None,
            None,
            None,
        )
    if field_type is ProgrammeCallQuestionType.INTEGER:
        parsed = _exact_object(
            value,
            required=_NUMBER_CONSTRAINT_FIELDS,
            pointer=pointer,
            item_index=item_index,
        )
        minimum = _optional_integer(
            parsed["minimum_value"],
            minimum=_MIN_SIGNED_32_BIT,
            maximum=_MAX_SIGNED_32_BIT,
            field="minimum_value",
            pointer=f"{pointer}/minimum_value",
            item_index=item_index,
        )
        maximum = _optional_integer(
            parsed["maximum_value"],
            minimum=_MIN_SIGNED_32_BIT,
            maximum=_MAX_SIGNED_32_BIT,
            field="maximum_value",
            pointer=f"{pointer}/maximum_value",
            item_index=item_index,
        )
        return (
            empty_options,
            None,
            None,
            None if minimum is None else Decimal(minimum),
            None if maximum is None else Decimal(maximum),
            None,
        )
    if field_type is ProgrammeCallQuestionType.DECIMAL:
        parsed = _exact_object(
            value,
            required=_NUMBER_CONSTRAINT_FIELDS,
            pointer=pointer,
            item_index=item_index,
        )
        return (
            empty_options,
            None,
            None,
            _decimal_bound(
                parsed["minimum_value"],
                field="minimum_value",
                pointer=f"{pointer}/minimum_value",
                item_index=item_index,
            ),
            _decimal_bound(
                parsed["maximum_value"],
                field="maximum_value",
                pointer=f"{pointer}/maximum_value",
                item_index=item_index,
            ),
            None,
        )
    if field_type in {
        ProgrammeCallQuestionType.SINGLE_CHOICE,
        ProgrammeCallQuestionType.MULTIPLE_CHOICE,
    }:
        fields = (
            ("options",)
            if field_type is ProgrammeCallQuestionType.SINGLE_CHOICE
            else ("options", "maximum_choices")
        )
        parsed = _exact_object(
            value,
            required=fields,
            pointer=pointer,
            item_index=item_index,
        )
        raw_options = _array(
            parsed["options"],
            minimum=2,
            maximum=MAX_PROGRAMME_CALL_QUESTION_OPTIONS,
            pointer=f"{pointer}/options",
            item_index=item_index,
        )
        options = tuple(
            _parse_option(
                option,
                pointer=f"{pointer}/options/{index}",
                item_index=item_index,
            )
            for index, option in enumerate(raw_options)
        )
        maximum_choices = None
        if field_type is ProgrammeCallQuestionType.MULTIPLE_CHOICE:
            maximum_choices = _integer(
                parsed["maximum_choices"],
                minimum=1,
                maximum=len(options),
                field="maximum_choices",
                pointer=f"{pointer}/maximum_choices",
                item_index=item_index,
            )
        return options, None, None, None, None, maximum_choices
    _exact_object(
        value,
        required=(),
        pointer=pointer,
        item_index=item_index,
    )
    return empty_options, None, None, None, None, None


def _parse_question(
    value: object,
    *,
    pointer: str,
    item_index: int,
    position: int,
) -> ProgrammeCallQuestionInput:
    parsed = _exact_object(
        value,
        required=_QUESTION_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    field_type_value = _literal_string(
        parsed["field_type"],
        pointer=f"{pointer}/field_type",
        item_index=item_index,
    )
    if field_type_value in _DEFERRED_QUESTION_TYPES:
        _fail(
            _ERROR_QUESTION_TYPE,
            item_index=item_index,
            pointer=f"{pointer}/field_type",
            field="field_type",
        )
    if field_type_value not in _ADMITTED_QUESTION_TYPES:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=f"{pointer}/field_type",
            field="field_type",
        )
    field_type = ProgrammeCallQuestionType(field_type_value)
    (
        options,
        minimum_length,
        maximum_length,
        minimum_value,
        maximum_value,
        maximum_choices,
    ) = _parse_question_constraints(
        field_type,
        parsed["constraints"],
        pointer=f"{pointer}/constraints",
        item_index=item_index,
    )
    try:
        return ProgrammeCallQuestionInput(
            key=_slug(
                parsed["key"],
                field="key",
                pointer=f"{pointer}/key",
                item_index=item_index,
            ),
            field_type=field_type,
            label=_text(
                parsed["label"],
                field="label",
                maximum=200,
                required=True,
                collapse=True,
                pointer=f"{pointer}/label",
                item_index=item_index,
            ),
            help_text=_text(
                parsed["help_text"],
                field="help_text",
                maximum=2_000,
                multiline=True,
                pointer=f"{pointer}/help_text",
                item_index=item_index,
            ),
            position=position,
            required=_boolean(
                parsed["required"],
                field="required",
                pointer=f"{pointer}/required",
                item_index=item_index,
            ),
            options=options,
            minimum_length=minimum_length,
            maximum_length=maximum_length,
            minimum_value=minimum_value,
            maximum_value=maximum_value,
            maximum_choices=maximum_choices,
            reference_kind="",
            condition=_parse_condition(
                parsed["condition"],
                pointer=f"{pointer}/condition",
                item_index=item_index,
            ),
            purpose=_text(
                parsed["purpose"],
                field="purpose",
                maximum=500,
                required=True,
                collapse=True,
                pointer=f"{pointer}/purpose",
                item_index=item_index,
            ),
            classification=_literal_string(
                parsed["classification"],
                pointer=f"{pointer}/classification",
                item_index=item_index,
            ),
            retention_policy_code=_optional_policy(
                parsed["retention_policy_code"],
                field="retention_policy_code",
                pointer=f"{pointer}/retention_policy_code",
                item_index=item_index,
            ),
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_section(
    value: object,
    *,
    pointer: str,
    item_index: int,
    position: int,
) -> ProgrammeCallSectionInput:
    parsed = _exact_object(
        value,
        required=_SECTION_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    raw_questions = _array(
        parsed["questions"],
        minimum=1,
        maximum=MAX_PROGRAMME_CALL_QUESTIONS,
        pointer=f"{pointer}/questions",
        item_index=item_index,
    )
    questions = tuple(
        _parse_question(
            question,
            pointer=f"{pointer}/questions/{index}",
            item_index=item_index,
            position=index + 1,
        )
        for index, question in enumerate(raw_questions)
    )
    try:
        return ProgrammeCallSectionInput(
            key=_slug(
                parsed["key"],
                field="key",
                pointer=f"{pointer}/key",
                item_index=item_index,
            ),
            title=_text(
                parsed["title"],
                field="title",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
                pointer=f"{pointer}/title",
                item_index=item_index,
            ),
            help_text=_text(
                parsed["help_text"],
                field="help_text",
                maximum=2_000,
                multiline=True,
                pointer=f"{pointer}/help_text",
                item_index=item_index,
            ),
            position=position,
            questions=questions,
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_definition(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeCallDefinitionInput:
    parsed = _exact_object(
        value,
        required=_DEFINITION_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    raw_sections = _array(
        parsed["sections"],
        minimum=1,
        maximum=MAX_PROGRAMME_CALL_SECTIONS,
        pointer=f"{pointer}/sections",
        item_index=item_index,
    )
    sections = tuple(
        _parse_section(
            section,
            pointer=f"{pointer}/sections/{index}",
            item_index=item_index,
            position=index + 1,
        )
        for index, section in enumerate(raw_sections)
    )
    if (
        sum(len(section.questions) for section in sections)
        > MAX_PROGRAMME_CALL_QUESTIONS
    ):
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=f"{pointer}/sections",
            field="sections",
        )
    try:
        return ProgrammeCallDefinitionInput(
            code=_slug(
                parsed["code"],
                field="code",
                pointer=f"{pointer}/code",
                item_index=item_index,
            ),
            name=_text(
                parsed["name"],
                field="name",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
                pointer=f"{pointer}/name",
                item_index=item_index,
            ),
            description=_text(
                parsed["description"],
                field="description",
                maximum=MAX_PROGRAMME_DESCRIPTION_LENGTH,
                multiline=True,
                pointer=f"{pointer}/description",
                item_index=item_index,
            ),
            purpose=_text(
                parsed["purpose"],
                field="purpose",
                maximum=500,
                required=True,
                collapse=True,
                pointer=f"{pointer}/purpose",
                item_index=item_index,
            ),
            classification=_literal_string(
                parsed["classification"],
                pointer=f"{pointer}/classification",
                item_index=item_index,
            ),
            maximum_submissions_per_person=_integer(
                parsed["maximum_submissions_per_person"],
                minimum=1,
                maximum=100,
                field="maximum_submissions_per_person",
                pointer=f"{pointer}/maximum_submissions_per_person",
                item_index=item_index,
            ),
            opens_at=_instant(
                parsed["opens_at"],
                field="opens_at",
                pointer=f"{pointer}/opens_at",
                item_index=item_index,
            ),
            closes_at=_instant(
                parsed["closes_at"],
                field="closes_at",
                pointer=f"{pointer}/closes_at",
                item_index=item_index,
            ),
            applicant_edit_until=_instant(
                parsed["applicant_edit_until"],
                field="applicant_edit_until",
                pointer=f"{pointer}/applicant_edit_until",
                item_index=item_index,
            ),
            audience_policy_code=_optional_policy(
                parsed["audience_policy_code"],
                field="audience_policy_code",
                pointer=f"{pointer}/audience_policy_code",
                item_index=item_index,
            ),
            retention_policy_code=_optional_policy(
                parsed["retention_policy_code"],
                field="retention_policy_code",
                pointer=f"{pointer}/retention_policy_code",
                item_index=item_index,
            ),
            sections=sections,
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_track(
    value: object,
    *,
    pointer: str,
    item_index: int,
    position: int,
) -> ProgrammeCallTrackInput:
    parsed = _exact_object(
        value,
        required=_TRACK_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    try:
        return ProgrammeCallTrackInput(
            code=_slug(
                parsed["code"],
                field="code",
                pointer=f"{pointer}/code",
                item_index=item_index,
            ),
            label=_text(
                parsed["label"],
                field="label",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
                pointer=f"{pointer}/label",
                item_index=item_index,
            ),
            description=_text(
                parsed["description"],
                field="description",
                maximum=MAX_PROGRAMME_DESCRIPTION_LENGTH,
                multiline=True,
                pointer=f"{pointer}/description",
                item_index=item_index,
            ),
            position=position,
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_format(
    value: object,
    *,
    pointer: str,
    item_index: int,
    position: int,
) -> ProgrammeCallFormatInput:
    parsed = _exact_object(
        value,
        required=_FORMAT_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    try:
        return ProgrammeCallFormatInput(
            code=_slug(
                parsed["code"],
                field="code",
                pointer=f"{pointer}/code",
                item_index=item_index,
            ),
            label=_text(
                parsed["label"],
                field="label",
                maximum=MAX_PROGRAMME_LABEL_LENGTH,
                required=True,
                collapse=True,
                pointer=f"{pointer}/label",
                item_index=item_index,
            ),
            description=_text(
                parsed["description"],
                field="description",
                maximum=MAX_PROGRAMME_DESCRIPTION_LENGTH,
                multiline=True,
                pointer=f"{pointer}/description",
                item_index=item_index,
            ),
            position=position,
            minimum_duration_minutes=_integer(
                parsed["minimum_duration_minutes"],
                minimum=1,
                maximum=MAX_PROGRAMME_DURATION_MINUTES,
                field="minimum_duration_minutes",
                pointer=f"{pointer}/minimum_duration_minutes",
                item_index=item_index,
            ),
            default_duration_minutes=_integer(
                parsed["default_duration_minutes"],
                minimum=1,
                maximum=MAX_PROGRAMME_DURATION_MINUTES,
                field="default_duration_minutes",
                pointer=f"{pointer}/default_duration_minutes",
                item_index=item_index,
            ),
            maximum_duration_minutes=_integer(
                parsed["maximum_duration_minutes"],
                minimum=1,
                maximum=MAX_PROGRAMME_DURATION_MINUTES,
                field="maximum_duration_minutes",
                pointer=f"{pointer}/maximum_duration_minutes",
                item_index=item_index,
            ),
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_contributor_field(
    value: object,
    *,
    pointer: str,
    item_index: int,
    position: int,
) -> ProgrammeCallContributorFieldInput:
    parsed = _exact_object(
        value,
        required=_CONTRIBUTOR_FIELD_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    try:
        return ProgrammeCallContributorFieldInput(
            field_code=_literal_string(
                parsed["field_code"],
                pointer=f"{pointer}/field_code",
                item_index=item_index,
            ),
            lead_requirement=_literal_string(
                parsed["lead_requirement"],
                pointer=f"{pointer}/lead_requirement",
                item_index=item_index,
            ),
            collaborator_requirement=_literal_string(
                parsed["collaborator_requirement"],
                pointer=f"{pointer}/collaborator_requirement",
                item_index=item_index,
            ),
            position=position,
        )
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)


def _parse_configuration(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeImportCallConfigurationInput:
    parsed = _exact_object(
        value,
        required=_CONFIGURATION_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    raw_tracks = _array(
        parsed["tracks"],
        minimum=1,
        maximum=MAX_PROGRAMME_CALL_TRACKS,
        pointer=f"{pointer}/tracks",
        item_index=item_index,
    )
    raw_formats = _array(
        parsed["formats"],
        minimum=1,
        maximum=MAX_PROGRAMME_CALL_FORMATS,
        pointer=f"{pointer}/formats",
        item_index=item_index,
    )
    raw_contributor_fields = _array(
        parsed["contributor_fields"],
        minimum=1,
        maximum=MAX_PROGRAMME_CALL_CONTRIBUTOR_FIELDS,
        pointer=f"{pointer}/contributor_fields",
        item_index=item_index,
    )
    configuration = ProgrammeImportCallConfigurationInput(
        maximum_collaborators=_integer(
            parsed["maximum_collaborators"],
            minimum=0,
            maximum=MAX_PROGRAMME_PROPOSAL_COLLABORATORS,
            field="maximum_collaborators",
            pointer=f"{pointer}/maximum_collaborators",
            item_index=item_index,
        ),
        content_policy_code=_policy(
            parsed["content_policy_code"],
            field="content_policy_code",
            pointer=f"{pointer}/content_policy_code",
            item_index=item_index,
        ),
        contributor_consent_policy_code=_policy(
            parsed["contributor_consent_policy_code"],
            field="contributor_consent_policy_code",
            pointer=f"{pointer}/contributor_consent_policy_code",
            item_index=item_index,
        ),
        collaboration_retention_policy_code=_policy(
            parsed["collaboration_retention_policy_code"],
            field="collaboration_retention_policy_code",
            pointer=f"{pointer}/collaboration_retention_policy_code",
            item_index=item_index,
        ),
        tracks=tuple(
            _parse_track(
                track,
                pointer=f"{pointer}/tracks/{index}",
                item_index=item_index,
                position=index + 1,
            )
            for index, track in enumerate(raw_tracks)
        ),
        formats=tuple(
            _parse_format(
                item,
                pointer=f"{pointer}/formats/{index}",
                item_index=item_index,
                position=index + 1,
            )
            for index, item in enumerate(raw_formats)
        ),
        contributor_fields=tuple(
            _parse_contributor_field(
                item,
                pointer=f"{pointer}/contributor_fields/{index}",
                item_index=item_index,
                position=index + 1,
            )
            for index, item in enumerate(raw_contributor_fields)
        ),
    )
    try:
        configuration.for_owner_department(UUID(int=0))
    except ValidationError:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer)
    return configuration


def _decimal_payload(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value.is_zero():
        return "0"
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _question_constraints_payload(
    question: ProgrammeCallQuestionInput,
) -> dict[str, object]:
    field_type = ProgrammeCallQuestionType(question.field_type)
    if field_type in {
        ProgrammeCallQuestionType.SHORT_TEXT,
        ProgrammeCallQuestionType.LONG_TEXT,
        ProgrammeCallQuestionType.EMAIL,
        ProgrammeCallQuestionType.PHONE,
        ProgrammeCallQuestionType.URL,
    }:
        return {
            "minimum_length": question.minimum_length,
            "maximum_length": question.maximum_length,
        }
    if field_type is ProgrammeCallQuestionType.INTEGER:
        return {
            "minimum_value": (
                None if question.minimum_value is None else int(question.minimum_value)
            ),
            "maximum_value": (
                None if question.maximum_value is None else int(question.maximum_value)
            ),
        }
    if field_type is ProgrammeCallQuestionType.DECIMAL:
        return {
            "minimum_value": _decimal_payload(question.minimum_value),
            "maximum_value": _decimal_payload(question.maximum_value),
        }
    if field_type in {
        ProgrammeCallQuestionType.SINGLE_CHOICE,
        ProgrammeCallQuestionType.MULTIPLE_CHOICE,
    }:
        payload: dict[str, object] = {
            "options": [
                {"code": option.code, "label": option.label}
                for option in question.options
            ],
        }
        if field_type is ProgrammeCallQuestionType.MULTIPLE_CHOICE:
            payload["maximum_choices"] = question.maximum_choices
        return payload
    return {}


def _question_payload(question: ProgrammeCallQuestionInput) -> dict[str, object]:
    condition = question.condition
    return {
        "key": question.key,
        "field_type": ProgrammeCallQuestionType(question.field_type).value,
        "label": question.label,
        "help_text": question.help_text,
        "required": question.required,
        "purpose": question.purpose,
        "classification": ProgrammeCallClassification(question.classification).value,
        "retention_policy_code": question.retention_policy_code or None,
        "condition": (
            None
            if condition is None
            else {
                "question_key": condition.question_key,
                "operator": ProgrammeCallConditionOperator(condition.operator).value,
                "value": condition.value,
            }
        ),
        "constraints": _question_constraints_payload(question),
    }


def _definition_payload(
    definition: ProgrammeCallDefinitionInput,
) -> dict[str, object]:
    return {
        "code": definition.code,
        "name": definition.name,
        "description": definition.description,
        "purpose": definition.purpose,
        "classification": ProgrammeCallClassification(definition.classification).value,
        "maximum_submissions_per_person": definition.maximum_submissions_per_person,
        "opens_at": definition.opens_at,
        "closes_at": definition.closes_at,
        "applicant_edit_until": definition.applicant_edit_until,
        "audience_policy_code": definition.audience_policy_code or None,
        "retention_policy_code": definition.retention_policy_code or None,
        "sections": [
            {
                "key": section.key,
                "title": section.title,
                "help_text": section.help_text,
                "questions": [
                    _question_payload(question) for question in section.questions
                ],
            }
            for section in definition.sections
        ],
    }


def _configuration_payload(
    configuration: ProgrammeImportCallConfigurationInput,
) -> dict[str, object]:
    return {
        "maximum_collaborators": configuration.maximum_collaborators,
        "content_policy_code": configuration.content_policy_code,
        "contributor_consent_policy_code": (
            configuration.contributor_consent_policy_code
        ),
        "collaboration_retention_policy_code": (
            configuration.collaboration_retention_policy_code
        ),
        "tracks": [
            {
                "code": track.code,
                "label": track.label,
                "description": track.description,
            }
            for track in configuration.tracks
        ],
        "formats": [
            {
                "code": item.code,
                "label": item.label,
                "description": item.description,
                "minimum_duration_minutes": item.minimum_duration_minutes,
                "default_duration_minutes": item.default_duration_minutes,
                "maximum_duration_minutes": item.maximum_duration_minutes,
            }
            for item in configuration.formats
        ],
        "contributor_fields": [
            {
                "field_code": str(item.field_code),
                "lead_requirement": str(item.lead_requirement),
                "collaborator_requirement": str(item.collaborator_requirement),
            }
            for item in configuration.contributor_fields
        ],
    }


def _call_item_payload(
    *,
    source_key: str,
    definition: ProgrammeCallDefinitionInput,
    configuration: ProgrammeImportCallConfigurationInput,
) -> dict[str, object]:
    return {
        "kind": "call",
        "source_key": source_key,
        "definition": _definition_payload(definition),
        "configuration": _configuration_payload(configuration),
    }


def _parse_call_item(
    value: object,
    *,
    item_index: int,
) -> ProgrammeImportCallItemInput:
    pointer = f"/items/{item_index}"
    parsed = _exact_object(
        value,
        required=_CALL_ITEM_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    source_key = _source_key(
        parsed["source_key"],
        field="source_key",
        pointer=f"{pointer}/source_key",
        item_index=item_index,
    )
    definition = _parse_definition(
        parsed["definition"],
        pointer=f"{pointer}/definition",
        item_index=item_index,
    )
    configuration = _parse_configuration(
        parsed["configuration"],
        pointer=f"{pointer}/configuration",
        item_index=item_index,
    )
    payload = _call_item_payload(
        source_key=source_key,
        definition=definition,
        configuration=configuration,
    )
    return ProgrammeImportCallItemInput(
        item_index=item_index,
        source_key=source_key,
        definition=definition,
        configuration=configuration,
        canonical_payload=canonical_programme_json(payload),
        source_digest=canonical_programme_digest(payload),
    )


def _parse_selection(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeImportProposalSelectionInput:
    parsed = _exact_object(
        value,
        required=_SELECTION_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    return ProgrammeImportProposalSelectionInput(
        track_code=_slug(
            parsed["track_code"],
            field="track_code",
            pointer=f"{pointer}/track_code",
            item_index=item_index,
        ),
        format_code=_slug(
            parsed["format_code"],
            field="format_code",
            pointer=f"{pointer}/format_code",
            item_index=item_index,
        ),
        requested_duration_minutes=_integer(
            parsed["requested_duration_minutes"],
            minimum=1,
            maximum=MAX_PROGRAMME_DURATION_MINUTES,
            field="requested_duration_minutes",
            pointer=f"{pointer}/requested_duration_minutes",
            item_index=item_index,
        ),
    )


def _parse_address(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeImportAddressInput:
    parsed = _exact_object(
        value,
        required=_ADDRESS_REQUIRED_FIELDS,
        optional=_ADDRESS_OPTIONAL_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    country_code = _literal_string(
        parsed["country_code"],
        pointer=f"{pointer}/country_code",
        item_index=item_index,
    )
    if _COUNTRY_CODE_PATTERN.fullmatch(country_code) is None:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=f"{pointer}/country_code",
            field="country_code",
        )
    return ProgrammeImportAddressInput(
        line_1=_text(
            parsed["line_1"],
            field="line_1",
            maximum=_MAX_ADDRESS_PART_LENGTH,
            required=True,
            pointer=f"{pointer}/line_1",
            item_index=item_index,
        ),
        line_2=_text(
            parsed.get("line_2", ""),
            field="line_2",
            maximum=_MAX_ADDRESS_PART_LENGTH,
            pointer=f"{pointer}/line_2",
            item_index=item_index,
        ),
        locality=_text(
            parsed["locality"],
            field="locality",
            maximum=_MAX_ADDRESS_PART_LENGTH,
            required=True,
            pointer=f"{pointer}/locality",
            item_index=item_index,
        ),
        region=_text(
            parsed.get("region", ""),
            field="region",
            maximum=_MAX_ADDRESS_PART_LENGTH,
            pointer=f"{pointer}/region",
            item_index=item_index,
        ),
        postal_code=_text(
            parsed["postal_code"],
            field="postal_code",
            maximum=_MAX_ADDRESS_PART_LENGTH,
            required=True,
            pointer=f"{pointer}/postal_code",
            item_index=item_index,
        ),
        country_code=country_code.upper(),
    )


def _answer_payload_value(value: ProgrammeImportAnswerValue) -> object:
    if isinstance(value, ProgrammeImportAddressInput):
        return value.as_application_value()
    if isinstance(value, tuple):
        return list(value)
    return value


def _parse_answer_field_type(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeCallQuestionType:
    field_type = _literal_string(
        value,
        pointer=pointer,
        item_index=item_index,
    )
    if field_type in _DEFERRED_QUESTION_TYPES:
        _fail(
            _ERROR_QUESTION_TYPE,
            item_index=item_index,
            pointer=pointer,
            field="field_type",
        )
    if field_type not in _ADMITTED_QUESTION_TYPES:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=pointer,
            field="field_type",
        )
    return ProgrammeCallQuestionType(field_type)


def _parse_answer_value(  # noqa: PLR0912, PLR0915
    field_type: ProgrammeCallQuestionType,
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeImportAnswerValue:
    text_types = {
        ProgrammeCallQuestionType.SHORT_TEXT,
        ProgrammeCallQuestionType.LONG_TEXT,
        ProgrammeCallQuestionType.EMAIL,
        ProgrammeCallQuestionType.PHONE,
        ProgrammeCallQuestionType.URL,
    }
    if field_type in text_types:
        parsed_text = _text(
            value,
            field="value",
            maximum=MAX_PROGRAMME_ANSWER_LENGTH,
            multiline=field_type is ProgrammeCallQuestionType.LONG_TEXT,
            pointer=pointer,
            item_index=item_index,
        )
        if field_type is ProgrammeCallQuestionType.PHONE and not (
            _MIN_PHONE_LENGTH <= len(parsed_text) <= _MAX_PHONE_LENGTH
        ):
            _fail(
                _ERROR_FIELD,
                item_index=item_index,
                pointer=pointer,
                field="value",
            )
        try:
            if field_type is ProgrammeCallQuestionType.EMAIL:
                validate_email(parsed_text)
            elif field_type is ProgrammeCallQuestionType.URL:
                URLValidator(schemes=("https",))(parsed_text)
        except ValidationError:
            _fail(
                _ERROR_FIELD,
                item_index=item_index,
                pointer=pointer,
                field="value",
            )
        parsed: ProgrammeImportAnswerValue = parsed_text
    elif field_type is ProgrammeCallQuestionType.INTEGER:
        parsed = _integer(
            value,
            minimum=_MIN_SIGNED_32_BIT,
            maximum=_MAX_SIGNED_32_BIT,
            field="value",
            pointer=pointer,
            item_index=item_index,
        )
    elif field_type is ProgrammeCallQuestionType.DECIMAL:
        decimal_value = _decimal_bound(
            value,
            field="value",
            pointer=pointer,
            item_index=item_index,
        )
        if decimal_value is None:
            _fail(
                _ERROR_FIELD,
                item_index=item_index,
                pointer=pointer,
                field="value",
            )
        decimal_payload = _decimal_payload(decimal_value)
        if decimal_payload is None:
            _fail(
                _ERROR_FIELD,
                item_index=item_index,
                pointer=pointer,
                field="value",
            )
        parsed = decimal_payload
    elif field_type is ProgrammeCallQuestionType.BOOLEAN:
        parsed = _boolean(
            value,
            field="value",
            pointer=pointer,
            item_index=item_index,
        )
    elif field_type is ProgrammeCallQuestionType.SINGLE_CHOICE:
        parsed = _slug(
            value,
            field="value",
            pointer=pointer,
            item_index=item_index,
        )
    elif field_type is ProgrammeCallQuestionType.MULTIPLE_CHOICE:
        values = _array(
            value,
            minimum=0,
            maximum=MAX_PROGRAMME_CALL_QUESTION_OPTIONS,
            pointer=pointer,
            item_index=item_index,
        )
        normalized = tuple(
            _slug(
                item,
                field="value",
                pointer=f"{pointer}/{index}",
                item_index=item_index,
            )
            for index, item in enumerate(values)
        )
        if len(set(normalized)) != len(normalized):
            _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer, field="value")
        parsed = tuple(sorted(normalized))
    elif field_type is ProgrammeCallQuestionType.DATE:
        text = _literal_string(value, pointer=pointer, item_index=item_index)
        if _DATE_PATTERN.fullmatch(text) is None:
            _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer, field="value")
        try:
            parsed = date.fromisoformat(text).isoformat()
        except ValueError:
            _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer, field="value")
    elif field_type is ProgrammeCallQuestionType.TIME:
        text = _literal_string(value, pointer=pointer, item_index=item_index)
        if _TIME_PATTERN.fullmatch(text) is None:
            _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer, field="value")
        try:
            parsed = time.fromisoformat(text).isoformat()
        except ValueError:
            _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer, field="value")
    elif field_type is ProgrammeCallQuestionType.INSTANT:
        parsed = (
            _instant(
                value,
                field="value",
                pointer=pointer,
                item_index=item_index,
            )
            .isoformat()
            .replace("+00:00", "Z")
        )
    elif field_type is ProgrammeCallQuestionType.ADDRESS:
        parsed = _parse_address(value, pointer=pointer, item_index=item_index)
    else:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer, field="value")
    payload = _answer_payload_value(parsed)
    wrapper_size = len(canonical_programme_json({"value": payload})) - len(
        b'{"value":}',
    )
    if wrapper_size > MAX_PROGRAMME_ANSWER_LENGTH:
        _fail(_ERROR_FIELD, item_index=item_index, pointer=pointer, field="value")
    return parsed


def _parse_answer(
    value: object,
    *,
    pointer: str,
    item_index: int,
) -> ProgrammeImportProposalAnswerInput:
    parsed = _exact_object(
        value,
        required=_ANSWER_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    field_type = _parse_answer_field_type(
        parsed["field_type"],
        pointer=f"{pointer}/field_type",
        item_index=item_index,
    )
    return ProgrammeImportProposalAnswerInput(
        question_key=_slug(
            parsed["question_key"],
            field="question_key",
            pointer=f"{pointer}/question_key",
            item_index=item_index,
        ),
        value=_parse_answer_value(
            field_type,
            parsed["value"],
            pointer=f"{pointer}/value",
            item_index=item_index,
        ),
        field_type=field_type,
    )


def _proposal_item_payload(
    *,
    source_key: str,
    call_source_key: str,
    lead_email: str,
    selection: ProgrammeImportProposalSelectionInput,
    answers: tuple[ProgrammeImportProposalAnswerInput, ...],
) -> dict[str, object]:
    return {
        "kind": "proposal",
        "source_key": source_key,
        "call_source_key": call_source_key,
        "lead_email": lead_email,
        "selection": {
            "track_code": selection.track_code,
            "format_code": selection.format_code,
            "requested_duration_minutes": selection.requested_duration_minutes,
        },
        "answers": [
            {
                "question_key": answer.question_key,
                "field_type": answer.field_type.value,
                "value": _answer_payload_value(answer.value),
            }
            for answer in answers
        ],
    }


def _parse_proposal_item(
    value: object,
    *,
    item_index: int,
) -> ProgrammeImportProposalItemInput:
    pointer = f"/items/{item_index}"
    parsed = _exact_object(
        value,
        required=_PROPOSAL_ITEM_FIELDS,
        pointer=pointer,
        item_index=item_index,
    )
    source_key = _source_key(
        parsed["source_key"],
        field="source_key",
        pointer=f"{pointer}/source_key",
        item_index=item_index,
    )
    call_source_key = _source_key(
        parsed["call_source_key"],
        field="call_source_key",
        pointer=f"{pointer}/call_source_key",
        item_index=item_index,
    )
    lead_email_value = _literal_string(
        parsed["lead_email"],
        pointer=f"{pointer}/lead_email",
        item_index=item_index,
    )
    try:
        lead_email = normalized_programme_email(
            lead_email_value,
            field="lead_email",
        )
    except ValidationError:
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=f"{pointer}/lead_email",
            field="lead_email",
        )
    selection = _parse_selection(
        parsed["selection"],
        pointer=f"{pointer}/selection",
        item_index=item_index,
    )
    raw_answers = _array(
        parsed["answers"],
        minimum=0,
        maximum=MAX_PROGRAMME_CALL_QUESTIONS,
        pointer=f"{pointer}/answers",
        item_index=item_index,
    )
    answers = tuple(
        _parse_answer(
            answer,
            pointer=f"{pointer}/answers/{index}",
            item_index=item_index,
        )
        for index, answer in enumerate(raw_answers)
    )
    if len({answer.question_key for answer in answers}) != len(answers):
        _fail(
            _ERROR_FIELD,
            item_index=item_index,
            pointer=f"{pointer}/answers",
            field="answers",
        )
    answers = tuple(sorted(answers, key=lambda answer: answer.question_key))
    payload = _proposal_item_payload(
        source_key=source_key,
        call_source_key=call_source_key,
        lead_email=lead_email,
        selection=selection,
        answers=answers,
    )
    return ProgrammeImportProposalItemInput(
        item_index=item_index,
        source_key=source_key,
        call_source_key=call_source_key,
        lead_email=lead_email,
        selection=selection,
        answers=answers,
        canonical_payload=canonical_programme_json(payload),
        source_digest=canonical_programme_digest(payload),
    )


def _item_payload(item: ProgrammeImportItemInput) -> dict[str, object]:
    if isinstance(item, ProgrammeImportCallItemInput):
        return _call_item_payload(
            source_key=item.source_key,
            definition=item.definition,
            configuration=item.configuration,
        )
    return _proposal_item_payload(
        source_key=item.source_key,
        call_source_key=item.call_source_key,
        lead_email=item.lead_email,
        selection=item.selection,
        answers=item.answers,
    )


def parse_programme_import(raw: bytes) -> ParsedProgrammeImportDocument:
    """Parse one strict raw-byte Programme import document.

    Parameters
    ----------
    raw : bytes
        Untrusted raw request bytes. Text, streams, and pre-decoded mappings are
        intentionally rejected so encoding and duplicate-key checks cannot be
        bypassed.

    Returns
    -------
    ParsedProgrammeImportDocument
        Immutable normalized items with canonical payloads and digests.

    """
    document = _decode_document(raw)
    root = _exact_object(
        document,
        required=_ROOT_FIELDS,
        pointer="",
        item_index=None,
    )
    if root["schema"] != PROGRAMME_IMPORT_SCHEMA:
        _fail(_ERROR_SCHEMA, pointer="/schema", field="schema")
    if type(root["version"]) is not int or root["version"] != PROGRAMME_IMPORT_VERSION:
        _fail(_ERROR_SCHEMA, pointer="/version", field="version")
    raw_items = _array(
        root["items"],
        minimum=1,
        maximum=MAX_PROGRAMME_IMPORT_ITEMS,
        pointer="/items",
        item_index=None,
    )
    parsed_items: list[ProgrammeImportItemInput] = []
    source_identities: set[tuple[str, str]] = set()
    for item_index, raw_item in enumerate(raw_items):
        item_object = _object(
            raw_item,
            pointer=f"/items/{item_index}",
            item_index=item_index,
        )
        kind = item_object.get("kind")
        item: ProgrammeImportItemInput
        if kind == "call":
            item = _parse_call_item(item_object, item_index=item_index)
        elif kind == "proposal":
            item = _parse_proposal_item(item_object, item_index=item_index)
        else:
            _fail(
                _ERROR_FIELD,
                item_index=item_index,
                pointer=f"/items/{item_index}/kind",
                field="kind",
            )
        source_identity = (item.kind, item.source_key)
        if source_identity in source_identities:
            _fail(
                _ERROR_SOURCE_DUPLICATE,
                item_index=item_index,
                pointer=f"/items/{item_index}",
            )
        source_identities.add(source_identity)
        parsed_items.append(item)
    items = tuple(
        sorted(
            parsed_items,
            key=lambda item: (0 if item.kind == "call" else 1, item.source_key),
        ),
    )
    payload: dict[str, object] = {
        "schema": PROGRAMME_IMPORT_SCHEMA,
        "version": PROGRAMME_IMPORT_VERSION,
        "items": [_item_payload(item) for item in items],
    }
    return ParsedProgrammeImportDocument(
        schema=PROGRAMME_IMPORT_SCHEMA,
        version=PROGRAMME_IMPORT_VERSION,
        items=items,
        canonical_payload=canonical_programme_json(payload),
        source_digest=canonical_programme_digest(payload),
    )


def parse_programme_import_document(raw: bytes) -> ParsedProgrammeImportDocument:
    """Parse one strict document through the orchestration-facing API.

    Parameters
    ----------
    raw : bytes
        Untrusted raw UTF-8 document bytes.

    Returns
    -------
    ParsedProgrammeImportDocument
        Immutable normalized items and canonical evidence.
    """
    return parse_programme_import(raw)


def parse_programme_import_batch(raw: bytes) -> ParsedProgrammeImportDocument:
    """Return :func:`parse_programme_import` for explicit batch call sites.

    Parameters
    ----------
    raw : bytes
        Untrusted raw UTF-8 document bytes.

    Returns
    -------
    ParsedProgrammeImportDocument
        Immutable normalized items and canonical evidence.
    """
    return parse_programme_import(raw)


def parse_programme_import_item_payload(raw: bytes) -> ProgrammeImportItemInput:
    """Reload one exact canonical staged item through full validation.

    Parameters
    ----------
    raw : bytes
        Trusted-at-rest canonical item bytes. The parser still repeats all
        transport, complexity, closed-shape, and domain validation.

    Returns
    -------
    ProgrammeImportItemInput
        The immutable typed item with a synthetic wire index of zero.

    """
    document = _decode_document(raw)
    item_object = _object(document, pointer="", item_index=0)
    kind = item_object.get("kind")
    item: ProgrammeImportItemInput
    if kind == "call":
        item = _parse_call_item(item_object, item_index=0)
    elif kind == "proposal":
        item = _parse_proposal_item(item_object, item_index=0)
    else:
        _fail(_ERROR_FIELD, item_index=0, pointer="/kind", field="kind")
    if item.canonical_payload != raw:
        _fail(_ERROR_SCHEMA, item_index=0)
    return item


__all__ = [
    "MAX_PROGRAMME_IMPORT_ARRAY_ITEMS",
    "MAX_PROGRAMME_IMPORT_BYTES",
    "MAX_PROGRAMME_IMPORT_DEPTH",
    "MAX_PROGRAMME_IMPORT_ITEMS",
    "MAX_PROGRAMME_IMPORT_OBJECT_MEMBERS",
    "MAX_PROGRAMME_IMPORT_STRING_LENGTH",
    "MAX_PROGRAMME_IMPORT_VALUES",
    "PROGRAMME_IMPORT_SCHEMA",
    "PROGRAMME_IMPORT_VERSION",
    "ParsedProgrammeImportDocument",
    "ProgrammeImportAddressInput",
    "ProgrammeImportAnswerValue",
    "ProgrammeImportBatchInput",
    "ProgrammeImportCallConfigurationInput",
    "ProgrammeImportCallItemInput",
    "ProgrammeImportInputError",
    "ProgrammeImportItemInput",
    "ProgrammeImportProposalAnswerInput",
    "ProgrammeImportProposalItemInput",
    "ProgrammeImportProposalSelectionInput",
    "parse_programme_import",
    "parse_programme_import_batch",
    "parse_programme_import_document",
    "parse_programme_import_item_payload",
]
