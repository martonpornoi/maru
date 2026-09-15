"""Pure, bounded presentation of already authorized exact-seal review answers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from .models import MAX_ANSWER_BYTES, MAX_QUESTION_OPTIONS
from .programme_review_rules import ProgrammeReviewUnavailableError

_CHOICES = frozenset({"single_choice", "multiple_choice"})
_REFERENCES = frozenset({"safe_file", "person_reference", "domain_reference"})
_TEXT = frozenset({"short_text", "long_text", "email", "phone", "url"})
_ADDRESS = {
    "line_1": "Address line 1",
    "line_2": "Address line 2",
    "locality": "City or locality",
    "region": "Region",
    "postal_code": "Postal code",
    "country_code": "Country code",
}
_REQUIRED_ADDRESS = frozenset({"line_1", "locality", "postal_code", "country_code"})
_MAX_OPTION_CODE = 80
_MAX_OPTION_LABEL = 160
_MIN_OPTIONS = 2
_MAX_ADDRESS_COMPONENT = 200
_COUNTRY_CODE_LENGTH = 2
_KINDS = (
    _CHOICES
    | _REFERENCES
    | _TEXT
    | {
        "address",
        "boolean",
        "integer",
        "decimal",
        "date",
        "time",
        "instant",
    }
)
_PROTECTED = (
    "Protected file/reference: dedicated safe viewer remains tracked in "
    "#108; no download or person lookup is offered here."
)


def _text(value: object, maximum: int = MAX_ANSWER_BYTES) -> str:
    if not isinstance(value, str):
        raise ProgrammeReviewUnavailableError
    try:
        if len(value.encode("utf-8")) > maximum:
            raise ProgrammeReviewUnavailableError
    except UnicodeError as error:
        raise ProgrammeReviewUnavailableError from error
    return value


def _codes(kind: str, value: object) -> list[str]:
    values = [value] if kind == "single_choice" else value
    if (
        not isinstance(values, list)
        or len(values) > MAX_QUESTION_OPTIONS
        or any(
            not isinstance(code, str) or not code or len(code) > _MAX_OPTION_CODE
            for code in values
        )
        or len(set(values)) != len(values)
    ):
        raise ProgrammeReviewUnavailableError
    return values


def programme_choice_display_options(
    kind: str, value: object, options: object
) -> list[dict[str, str]]:
    """Select only original question labels for a permitted choice answer.

    Parameters
    ----------
    kind : str
        Closed single_choice or multiple_choice answer kind.
    value : object
        Exact retained non-null canonical choice value.
    options : object
        Original immutable question's complete bounded code/label metadata.

    Returns
    -------
    list[dict[str, str]]
        Selected code/label pairs only, in retained answer order.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If the kind, metadata or exact selected codes are incoherent.

    Notes
    -----
    Pure formatting carries no authority. The owner must prove exact-seal,
    stage, field, classification and audit admission before disclosure.
    """
    if (
        kind not in _CHOICES
        or not isinstance(options, list)
        or not _MIN_OPTIONS <= len(options) <= MAX_QUESTION_OPTIONS
    ):
        raise ProgrammeReviewUnavailableError
    labels: dict[str, str] = {}
    for option in options:
        if not isinstance(option, dict) or set(option) != {"code", "label"}:
            raise ProgrammeReviewUnavailableError
        code = _text(option["code"], 4 * _MAX_OPTION_CODE)
        label = _text(option["label"], 4 * _MAX_OPTION_LABEL)
        if (
            not code
            or len(code) > _MAX_OPTION_CODE
            or not label.strip()
            or len(label) > _MAX_OPTION_LABEL
            or code in labels
        ):
            raise ProgrammeReviewUnavailableError
        labels[code] = label
    codes = _codes(kind, value)
    if any(code not in labels for code in codes):
        raise ProgrammeReviewUnavailableError
    return [{"code": code, "label": labels[code]} for code in codes]


def _choice_text(kind: str, value: object, selected: object) -> str:
    codes = _codes(kind, value)
    if not isinstance(selected, list) or len(selected) != len(codes):
        raise ProgrammeReviewUnavailableError
    labels = []
    for code, option in zip(codes, selected, strict=True):
        if (
            not isinstance(option, dict)
            or set(option) != {"code", "label"}
            or option["code"] != code
        ):
            raise ProgrammeReviewUnavailableError
        label = _text(option["label"], 4 * _MAX_OPTION_LABEL)
        if not label.strip() or len(label) > _MAX_OPTION_LABEL:
            raise ProgrammeReviewUnavailableError
        labels.append(label)
    if kind == "single_choice":
        return labels[0]
    return (
        "\n".join(f"• {label}" for label in labels)
        if labels
        else "No options selected in this exact revision."
    )


def _address_text(value: object) -> str:
    if (
        not isinstance(value, dict)
        or not value.keys() >= _REQUIRED_ADDRESS
        or not value.keys() <= _ADDRESS.keys()
    ):
        raise ProgrammeReviewUnavailableError
    components: dict[str, str] = {}
    for code, component in value.items():
        text = _text(component, 4 * _MAX_ADDRESS_COMPONENT)
        if len(text) > _MAX_ADDRESS_COMPONENT or (
            code in _REQUIRED_ADDRESS and not text.strip()
        ):
            raise ProgrammeReviewUnavailableError
        components[code] = text
    if (
        len(components["country_code"]) != _COUNTRY_CODE_LENGTH
        or not components["country_code"].isalpha()
    ):
        raise ProgrammeReviewUnavailableError
    return "\n".join(
        f"{label}: {components[code]}"
        for code, label in _ADDRESS.items()
        if components.get(code)
    )


def _temporal_text(kind: str, text: str) -> str:
    try:
        if kind == "date":
            return date.fromisoformat(text).isoformat()
        if kind == "time":
            return time.fromisoformat(text).isoformat()
        if kind == "instant":
            instant = datetime.fromisoformat(text)
            if instant.utcoffset() is not None:
                return instant.isoformat(sep=" ")
    except ValueError as error:
        raise ProgrammeReviewUnavailableError from error
    raise ProgrammeReviewUnavailableError


def _scalar_text(kind: str, value: object) -> str:
    if kind in _TEXT:
        return _text(value)
    if kind == "boolean" and type(value) is bool:
        return "Yes" if value else "No"
    if kind == "integer" and type(value) is int and -(2**31) <= value < 2**31:
        return str(value)
    text = _text(value)
    if kind in {"date", "time", "instant"}:
        return _temporal_text(kind, text)
    try:
        if kind == "decimal" and Decimal(text).is_finite():
            return text
    except InvalidOperation as error:
        raise ProgrammeReviewUnavailableError from error
    raise ProgrammeReviewUnavailableError


def programme_review_answer_text(row: Mapping[str, object]) -> str:
    """Render one authorized exact-seal value as plain text, never safe HTML.

    Parameters
    ----------
    row : Mapping[str, object]
        Owner-projected type/value and selected_options for non-null choices.

    Returns
    -------
    str
        Bounded readable text, explicit absence or a protected-reference notice.

    Raises
    ------
    ProgrammeReviewUnavailableError
        If a type or its retained shape/selected metadata is unsupported.

    Notes
    -----
    No I/O, identity resolution, download, timezone inference or mutation occurs.
    Consumers must escape the result and independently reauthorize disclosure.
    """
    if not isinstance(row, Mapping):
        raise ProgrammeReviewUnavailableError
    kind = row.get("type")
    if not isinstance(kind, str) or kind not in _KINDS or "value" not in row:
        raise ProgrammeReviewUnavailableError
    value = row["value"]
    if value is None:
        return "No answer in this exact revision."
    if kind in _REFERENCES:
        return _PROTECTED
    if kind in _CHOICES:
        return _choice_text(kind, value, row.get("selected_options"))
    if kind == "address":
        return _address_text(value)
    return _scalar_text(kind, value)
