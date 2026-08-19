"""Closed typed-value coverage for Applications answers and conditions."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.applications import answer_values
from maru.applications.answer_values import condition_matches, normalize_answer_value
from maru.applications.models import (
    ApplicationDefinition,
    ApplicationFileReceipt,
    ApplicationQuestion,
    ApplicationQuestionType,
)
from maru.identity.models import Account


def _question(field_type: str, **overrides: object) -> ApplicationQuestion:
    definition = ApplicationDefinition(
        organization_id=uuid4(),
        edition_id=uuid4(),
    )
    values: dict[str, object] = {
        "definition": definition,
        "field_type": field_type,
        "options": [],
    }
    values.update(overrides)
    return ApplicationQuestion(**values)


def _normalize(
    field_type: str,
    value: object,
    **question_values: object,
) -> object:
    return normalize_answer_value(
        question=_question(field_type, **question_values),
        account=Account(id=uuid4()),
        value=value,
    )


def _assert_invalid(
    field_type: str,
    value: object,
    expected_code: str,
    **question_values: object,
) -> None:
    with pytest.raises(ValidationError) as caught:
        _normalize(field_type, value, **question_values)
    assert caught.value.code == expected_code


@pytest.mark.parametrize(
    ("field_type", "value", "expected", "question_values"),
    [
        (ApplicationQuestionType.SHORT_TEXT, "short", "short", {}),
        (
            ApplicationQuestionType.LONG_TEXT,
            "a longer answer",
            "a longer answer",
            {"minimum_length": 2, "maximum_length": 30},
        ),
        (ApplicationQuestionType.INTEGER, -(2**31), -(2**31), {}),
        (ApplicationQuestionType.INTEGER, 2**31 - 1, 2**31 - 1, {}),
        (
            ApplicationQuestionType.DECIMAL,
            "12.3400",
            "12.3400",
            {"minimum_value": Decimal("10"), "maximum_value": Decimal("15")},
        ),
        (ApplicationQuestionType.DECIMAL, 12, "12", {}),
        (ApplicationQuestionType.DECIMAL, 1.25, "1.25", {}),
        (ApplicationQuestionType.BOOLEAN, True, True, {}),
        (
            ApplicationQuestionType.SINGLE_CHOICE,
            "yes",
            "yes",
            {"options": [{"code": "yes"}, {"code": "no"}]},
        ),
        (
            ApplicationQuestionType.MULTIPLE_CHOICE,
            ["one", "two"],
            ["one", "two"],
            {
                "options": [{"code": "one"}, {"code": "two"}],
                "maximum_choices": 2,
            },
        ),
        (ApplicationQuestionType.DATE, "2031-08-10", "2031-08-10", {}),
        (ApplicationQuestionType.TIME, "09:30:00", "09:30:00", {}),
        (
            ApplicationQuestionType.INSTANT,
            "2031-08-10T09:30:00+02:00",
            "2031-08-10T09:30:00+02:00",
            {},
        ),
        (
            ApplicationQuestionType.EMAIL,
            "helper@example.invalid",
            "helper@example.invalid",
            {},
        ),
        (ApplicationQuestionType.PHONE, "+3612345678", "+3612345678", {}),
        (
            ApplicationQuestionType.URL,
            "https://example.invalid/application",
            "https://example.invalid/application",
            {},
        ),
        (
            ApplicationQuestionType.ADDRESS,
            {
                "line_1": " 1 Synthetic Street ",
                "line_2": "",
                "locality": " Budapest ",
                "region": "Pest",
                "postal_code": " 1000 ",
                "country_code": "HU",
            },
            {
                "line_1": "1 Synthetic Street",
                "line_2": "",
                "locality": "Budapest",
                "region": "Pest",
                "postal_code": "1000",
                "country_code": "HU",
            },
            {},
        ),
        (
            ApplicationQuestionType.PERSON_REFERENCE,
            "00000000-0000-0000-0000-000000000000",
            "00000000-0000-0000-0000-000000000000",
            {},
        ),
        (
            ApplicationQuestionType.DOMAIN_REFERENCE,
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "ffffffff-ffff-ffff-ffff-ffffffffffff",
            {},
        ),
    ],
)
def test_normalize_answer_value_accepts_each_closed_value_shape(
    field_type: str,
    value: object,
    expected: object,
    question_values: dict[str, object],
) -> None:
    assert _normalize(field_type, value, **question_values) == expected


def test_normalize_answer_value_preserves_explicit_null() -> None:
    assert _normalize(ApplicationQuestionType.SHORT_TEXT, None) is None


@pytest.mark.parametrize(
    ("field_type", "value", "expected_code", "question_values"),
    [
        (
            ApplicationQuestionType.SHORT_TEXT,
            5,
            "invalid_application_answer_type",
            {},
        ),
        (
            ApplicationQuestionType.SHORT_TEXT,
            "x",
            "invalid_application_answer_length",
            {"minimum_length": 2},
        ),
        (
            ApplicationQuestionType.LONG_TEXT,
            "too long",
            "invalid_application_answer_length",
            {"maximum_length": 3},
        ),
        (ApplicationQuestionType.INTEGER, True, "invalid_application_integer", {}),
        (ApplicationQuestionType.INTEGER, "1", "invalid_application_integer", {}),
        (
            ApplicationQuestionType.INTEGER,
            2**31,
            "invalid_application_integer",
            {},
        ),
        (ApplicationQuestionType.DECIMAL, True, "invalid_application_decimal", {}),
        (
            ApplicationQuestionType.DECIMAL,
            object(),
            "invalid_application_decimal",
            {},
        ),
        (
            ApplicationQuestionType.DECIMAL,
            "not-a-number",
            "invalid_application_decimal",
            {},
        ),
        (
            ApplicationQuestionType.DECIMAL,
            "NaN",
            "invalid_application_decimal",
            {},
        ),
        (
            ApplicationQuestionType.DECIMAL,
            "0.5",
            "invalid_application_decimal",
            {"minimum_value": Decimal("1")},
        ),
        (
            ApplicationQuestionType.DECIMAL,
            "2",
            "invalid_application_decimal",
            {"maximum_value": Decimal("1")},
        ),
        (ApplicationQuestionType.BOOLEAN, 1, "invalid_application_boolean", {}),
        (
            ApplicationQuestionType.SINGLE_CHOICE,
            1,
            "invalid_application_choice",
            {"options": [{"code": "yes"}]},
        ),
        (
            ApplicationQuestionType.SINGLE_CHOICE,
            "missing",
            "invalid_application_choice",
            {"options": [{"code": "yes"}]},
        ),
        (
            ApplicationQuestionType.MULTIPLE_CHOICE,
            "one",
            "invalid_application_choices",
            {"options": [{"code": "one"}], "maximum_choices": 1},
        ),
        (
            ApplicationQuestionType.MULTIPLE_CHOICE,
            [1],
            "invalid_application_choices",
            {"options": [{"code": "one"}], "maximum_choices": 1},
        ),
        (
            ApplicationQuestionType.MULTIPLE_CHOICE,
            ["one", "one"],
            "invalid_application_choices",
            {"options": [{"code": "one"}], "maximum_choices": 2},
        ),
        (
            ApplicationQuestionType.MULTIPLE_CHOICE,
            ["missing"],
            "invalid_application_choices",
            {"options": [{"code": "one"}], "maximum_choices": 1},
        ),
        (
            ApplicationQuestionType.MULTIPLE_CHOICE,
            ["one", "two"],
            "invalid_application_choices",
            {
                "options": [{"code": "one"}, {"code": "two"}],
                "maximum_choices": 1,
            },
        ),
        (ApplicationQuestionType.DATE, 1, "invalid_application_date", {}),
        (ApplicationQuestionType.DATE, "31-01-2030", "invalid_application_date", {}),
        (ApplicationQuestionType.TIME, 1, "invalid_application_time", {}),
        (ApplicationQuestionType.TIME, "25:00", "invalid_application_time", {}),
        (ApplicationQuestionType.INSTANT, 1, "invalid_application_instant", {}),
        (
            ApplicationQuestionType.INSTANT,
            "not-an-instant",
            "invalid_application_instant",
            {},
        ),
        (
            ApplicationQuestionType.INSTANT,
            "2031-08-10T09:30:00",
            "invalid_application_instant",
            {},
        ),
        (
            ApplicationQuestionType.PHONE,
            "12",
            "invalid_application_phone",
            {},
        ),
        (
            ApplicationQuestionType.PHONE,
            "1" * 41,
            "invalid_application_phone",
            {},
        ),
        (
            ApplicationQuestionType.ADDRESS,
            "not-an-object",
            "invalid_application_address",
            {},
        ),
        (
            ApplicationQuestionType.ADDRESS,
            {"line_1": "Street"},
            "invalid_application_address",
            {},
        ),
        (
            ApplicationQuestionType.ADDRESS,
            {
                "line_1": "Street",
                "locality": "City",
                "postal_code": "1000",
                "country_code": "HU",
                "unknown": "closed",
            },
            "invalid_application_address",
            {},
        ),
        (
            ApplicationQuestionType.ADDRESS,
            {
                "line_1": " ",
                "locality": "City",
                "postal_code": "1000",
                "country_code": "HU",
            },
            "invalid_application_address",
            {},
        ),
        (
            ApplicationQuestionType.ADDRESS,
            {
                "line_1": "Street",
                "line_2": 5,
                "locality": "City",
                "postal_code": "1000",
                "country_code": "HU",
            },
            "invalid_application_address",
            {},
        ),
        (
            ApplicationQuestionType.ADDRESS,
            {
                "line_1": "Street",
                "locality": "City",
                "postal_code": "1000",
                "country_code": "HUN",
            },
            "invalid_application_address",
            {},
        ),
        (
            ApplicationQuestionType.PERSON_REFERENCE,
            1,
            "invalid_application_reference",
            {},
        ),
        (
            ApplicationQuestionType.PERSON_REFERENCE,
            "not-a-uuid",
            "invalid_application_reference",
            {},
        ),
        (
            ApplicationQuestionType.PERSON_REFERENCE,
            "A7CBF0A8-B0B1-4991-A650-6DD8E12E8810",
            "invalid_application_reference",
            {},
        ),
        ("future_type", "value", "unknown_application_question_type", {}),
    ],
)
def test_normalize_answer_value_rejects_malformed_values(
    field_type: str,
    value: object,
    expected_code: str,
    question_values: dict[str, object],
) -> None:
    _assert_invalid(field_type, value, expected_code, **question_values)


def test_normalize_answer_value_rejects_invalid_email_and_non_https_url() -> None:
    _assert_invalid(ApplicationQuestionType.EMAIL, "not-an-email", "invalid")
    _assert_invalid(
        ApplicationQuestionType.URL,
        "http://example.invalid",
        "invalid",
    )


def test_normalize_answer_value_accepts_only_owned_clean_file_receipt() -> None:
    receipt_id = uuid4()
    question = _question(ApplicationQuestionType.SAFE_FILE)
    account = Account(id=uuid4())
    query = ApplicationFileReceipt.objects

    with patch.object(query, "filter") as filter_rows:
        filter_rows.return_value.first.return_value = ApplicationFileReceipt(
            id=receipt_id
        )
        assert normalize_answer_value(
            question=question,
            account=account,
            value=str(receipt_id),
        ) == str(receipt_id)

    filter_rows.assert_called_once_with(
        id=str(receipt_id),
        organization_id=question.definition.organization_id,
        edition_id=question.definition.edition_id,
        account_id=account.id,
        status=ApplicationFileReceipt.Status.CLEAN,
    )

    with patch.object(query, "filter") as filter_rows:
        filter_rows.return_value.first.return_value = None
        _assert_file_unavailable(question, account, str(receipt_id))


def _assert_file_unavailable(
    question: ApplicationQuestion,
    account: Account,
    receipt_id: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        normalize_answer_value(question=question, account=account, value=receipt_id)
    assert caught.value.code == "application_file_unavailable"


def test_normalize_answer_value_enforces_encoded_byte_ceiling() -> None:
    with patch.object(answer_values, "MAX_ANSWER_BYTES", 4):
        _assert_invalid(
            ApplicationQuestionType.SHORT_TEXT,
            "éé",
            "application_answer_too_large",
        )


@pytest.mark.parametrize(
    ("condition", "answers", "expected"),
    [
        ({}, {}, True),
        (
            {"question_key": "kind", "operator": "equals", "value": "panel"},
            {"kind": "panel"},
            True,
        ),
        (
            {"question_key": "kind", "operator": "not_equals", "value": "panel"},
            {"kind": "dance"},
            True,
        ),
        (
            {"question_key": "tags", "operator": "contains", "value": "music"},
            {"tags": ["music", "dance"]},
            True,
        ),
        (
            {"question_key": "tags", "operator": "contains", "value": "music"},
            {"tags": "music"},
            False,
        ),
        (
            {"question_key": "kind", "operator": "future", "value": "panel"},
            {"kind": "panel"},
            False,
        ),
    ],
)
def test_condition_matches_closed_operators(
    condition: dict[str, object],
    answers: dict[str, object],
    expected: bool,
) -> None:
    assert condition_matches(condition, answers) is expected


def test_reference_result_is_a_uuid_compatible_canonical_string() -> None:
    value = str(uuid4())
    normalized = _normalize(ApplicationQuestionType.DOMAIN_REFERENCE, value)
    assert UUID(str(normalized)) == UUID(value)
