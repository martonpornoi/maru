"""Closed typed answer normalization for the shared form vocabulary."""
# ruff: noqa: PLR0912, PLR0915, PLR2004

from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator, validate_email

from maru.applications.models import (
    MAX_ANSWER_BYTES,
    ApplicationFileReceipt,
    ApplicationQuestion,
    ApplicationQuestionType,
)
from maru.identity.models import Account


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError(
            "Use one canonical UUID.", code="invalid_application_reference"
        )
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ValidationError(
            "Use one canonical UUID.", code="invalid_application_reference"
        ) from error
    if str(parsed) != value:
        raise ValidationError(
            "Use one canonical UUID.", code="invalid_application_reference"
        )
    return value


def _bounded_string(question: ApplicationQuestion, value: object) -> str:
    if not isinstance(value, str):
        raise ValidationError("Enter text.", code="invalid_application_answer_type")
    minimum = question.minimum_length or 0
    default_maximum = (
        240 if question.field_type == ApplicationQuestionType.SHORT_TEXT else 16_384
    )
    maximum = question.maximum_length or default_maximum
    if not minimum <= len(value) <= maximum:
        raise ValidationError(
            "The answer length is outside the configured bounds.",
            code="invalid_application_answer_length",
        )
    return value


def _address(value: object) -> dict[str, str]:
    required = {"line_1", "locality", "postal_code", "country_code"}
    optional = {"line_2", "region"}
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or not set(value) <= required | optional
    ):
        raise ValidationError(
            "Use the closed address shape.", code="invalid_application_address"
        )
    if any(
        not isinstance(item, str) or not item.strip() or len(item) > 200
        for key, item in value.items()
        if key in required
    ):
        raise ValidationError(
            "Required address values must be bounded text.",
            code="invalid_application_address",
        )
    if any(
        not isinstance(item, str) or len(item) > 200
        for key, item in value.items()
        if key in optional
    ):
        raise ValidationError(
            "Optional address values must be bounded text.",
            code="invalid_application_address",
        )
    country = value["country_code"]
    if len(country) != 2 or not country.isalpha():
        raise ValidationError(
            "Use a two-letter country code.", code="invalid_application_address"
        )
    return {key: item.strip() for key, item in value.items()}


def normalize_answer_value(
    *,
    question: ApplicationQuestion,
    account: Account,
    value: object,
) -> object:
    if value is None:
        return None
    field_type = question.field_type
    if field_type in {
        ApplicationQuestionType.SHORT_TEXT,
        ApplicationQuestionType.LONG_TEXT,
    }:
        normalized: object = _bounded_string(question, value)
    elif field_type == ApplicationQuestionType.INTEGER:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not -(2**31) <= value < 2**31
        ):
            raise ValidationError(
                "Enter a bounded whole number.", code="invalid_application_integer"
            )
        normalized = value
    elif field_type == ApplicationQuestionType.DECIMAL:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValidationError(
                "Enter a decimal number.", code="invalid_application_decimal"
            )
        try:
            number = Decimal(str(value))
        except InvalidOperation as error:
            raise ValidationError(
                "Enter a decimal number.", code="invalid_application_decimal"
            ) from error
        if (
            not number.is_finite()
            or (question.minimum_value is not None and number < question.minimum_value)
            or (question.maximum_value is not None and number > question.maximum_value)
        ):
            raise ValidationError(
                "The decimal is outside the configured bounds.",
                code="invalid_application_decimal",
            )
        normalized = format(number, "f")
    elif field_type == ApplicationQuestionType.BOOLEAN:
        if not isinstance(value, bool):
            raise ValidationError(
                "Enter true or false.", code="invalid_application_boolean"
            )
        normalized = value
    elif field_type == ApplicationQuestionType.SINGLE_CHOICE:
        codes = {option["code"] for option in question.options}
        if not isinstance(value, str) or value not in codes:
            raise ValidationError(
                "Choose one configured option.", code="invalid_application_choice"
            )
        normalized = value
    elif field_type == ApplicationQuestionType.MULTIPLE_CHOICE:
        codes = {option["code"] for option in question.options}
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) for item in value)
            or len(value) != len(set(value))
            or not set(value) <= codes
            or len(value) > (question.maximum_choices or 0)
        ):
            raise ValidationError(
                "Choose a bounded set of configured options.",
                code="invalid_application_choices",
            )
        normalized = value
    elif field_type == ApplicationQuestionType.DATE:
        if not isinstance(value, str):
            raise ValidationError("Use an ISO date.", code="invalid_application_date")
        try:
            normalized = date.fromisoformat(value).isoformat()
        except ValueError as error:
            raise ValidationError(
                "Use an ISO date.", code="invalid_application_date"
            ) from error
    elif field_type == ApplicationQuestionType.TIME:
        if not isinstance(value, str):
            raise ValidationError("Use an ISO time.", code="invalid_application_time")
        try:
            normalized = time.fromisoformat(value).isoformat()
        except ValueError as error:
            raise ValidationError(
                "Use an ISO time.", code="invalid_application_time"
            ) from error
    elif field_type == ApplicationQuestionType.INSTANT:
        if not isinstance(value, str):
            raise ValidationError(
                "Use an ISO date-time with an offset.",
                code="invalid_application_instant",
            )
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValidationError(
                "Use an ISO date-time with an offset.",
                code="invalid_application_instant",
            ) from error
        if parsed.tzinfo is None:
            raise ValidationError(
                "The date-time must include an offset.",
                code="invalid_application_instant",
            )
        normalized = parsed.isoformat()
    elif field_type == ApplicationQuestionType.EMAIL:
        normalized = _bounded_string(question, value)
        validate_email(normalized)
    elif field_type == ApplicationQuestionType.PHONE:
        normalized = _bounded_string(question, value)
        if not 3 <= len(normalized) <= 40:
            raise ValidationError(
                "Enter a bounded phone number.", code="invalid_application_phone"
            )
    elif field_type == ApplicationQuestionType.URL:
        normalized = _bounded_string(question, value)
        URLValidator(schemes=("https",))(normalized)
    elif field_type == ApplicationQuestionType.ADDRESS:
        normalized = _address(value)
    elif field_type in {
        ApplicationQuestionType.PERSON_REFERENCE,
        ApplicationQuestionType.DOMAIN_REFERENCE,
    }:
        normalized = _canonical_uuid(value)
    elif field_type == ApplicationQuestionType.SAFE_FILE:
        receipt_id = _canonical_uuid(value)
        receipt = ApplicationFileReceipt.objects.filter(
            id=receipt_id,
            organization_id=question.definition.organization_id,
            edition_id=question.definition.edition_id,
            account_id=account.id,
            status=ApplicationFileReceipt.Status.CLEAN,
        ).first()
        if receipt is None:
            raise ValidationError(
                "The safety-checked file receipt is unavailable.",
                code="application_file_unavailable",
            )
        normalized = receipt_id
    else:
        raise ValidationError(
            "Question type is not registered.", code="unknown_application_question_type"
        )
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if len(encoded) > MAX_ANSWER_BYTES:
        raise ValidationError(
            "The answer is too large.", code="application_answer_too_large"
        )
    return normalized


def condition_matches(condition: dict[str, object], answers: dict[str, object]) -> bool:
    if not condition:
        return True
    current = answers.get(str(condition["question_key"]))
    expected = condition["value"]
    operator = condition["operator"]
    if operator == "equals":
        return current == expected
    if operator == "not_equals":
        return current != expected
    if operator == "contains":
        return isinstance(current, list) and expected in current
    return False
