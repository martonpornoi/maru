"""Strict browser-input and edition-local time contracts for Applications."""

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.http import QueryDict

from maru.applications.forms import (
    ApplicantAnswerForm,
    DefinitionConfigureForm,
    DefinitionLifecycleForm,
    EditionLocalDateTimeField,
    QuestionAddForm,
    StarterCopyForm,
)
from maru.applications.models import ApplicationQuestion
from maru.core.forms import StrictBase10IntegerField


@pytest.mark.parametrize("alias", ["+1", "01", " 1", "1 ", "1.0"])
def test_expected_versions_reject_noncanonical_integer_aliases(alias: str) -> None:
    form = DefinitionLifecycleForm(
        {
            "retry_key": str(uuid4()),
            "expected_version": alias,
            "reason": "Synthetic strict input regression.",
        }
    )

    assert form.is_valid() is False
    assert form.errors.as_data()["expected_version"][0].code == "invalid"


def test_command_forms_reuse_strict_integer_contract_for_all_control_numbers() -> None:
    for field in (
        DefinitionConfigureForm.base_fields["expected_version"],
        DefinitionConfigureForm.base_fields["maximum_submissions"],
        DefinitionConfigureForm.base_fields["minimum_age"],
        QuestionAddForm.base_fields["expected_version"],
        QuestionAddForm.base_fields["minimum_length"],
        QuestionAddForm.base_fields["maximum_length"],
        QuestionAddForm.base_fields["maximum_choices"],
    ):
        assert isinstance(field, StrictBase10IntegerField)


def test_command_form_rejects_duplicate_and_unknown_transport_values() -> None:
    data = QueryDict(mutable=True)
    data.update(
        {
            "retry_key": str(uuid4()),
            "expected_version": "1",
            "reason": "Synthetic strict input regression.",
            "unexpected": "preview principal",
        }
    )
    data.appendlist("expected_version", "1")
    form = DefinitionLifecycleForm(data)

    assert form.is_valid() is False
    codes = {item.code for item in form.non_field_errors().as_data()}
    assert codes == {"invalid_input_cardinality"}

    unknown_form = DefinitionLifecycleForm(
        {
            "retry_key": str(uuid4()),
            "expected_version": "1",
            "reason": "Synthetic strict input regression.",
            "unexpected": "preview principal",
        }
    )
    assert unknown_form.is_valid() is False
    assert unknown_form.non_field_errors().as_data()[0].code == "unknown_input_field"


@pytest.mark.parametrize(
    ("local_value", "expected_code"),
    [
        ("2026-03-29T02:30", "nonexistent"),
        ("2026-10-25T02:30", "ambiguous"),
    ],
)
def test_edition_local_windows_reject_dst_gaps_and_folds(
    local_value: str,
    expected_code: str,
) -> None:
    form = StarterCopyForm(
        {
            "retry_key": str(uuid4()),
            "opens_at": local_value,
            "closes_at": "2026-10-26T12:00",
            "applicant_edit_until": "2026-10-26T11:00",
        },
        edition_time_zone="Europe/Budapest",
    )

    assert form.is_valid() is False
    assert form.errors.as_data()["opens_at"][0].code == expected_code


def test_edition_local_window_uses_explicit_persisted_zone() -> None:
    form = StarterCopyForm(
        {
            "retry_key": str(uuid4()),
            "opens_at": "2026-03-28T12:00",
            "closes_at": "2026-03-28T14:00",
            "applicant_edit_until": "2026-03-28T13:00",
        },
        edition_time_zone="Europe/Budapest",
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["opens_at"].utcoffset() == timedelta(hours=1)
    assert isinstance(form.fields["opens_at"], EditionLocalDateTimeField)


def test_application_templates_are_same_shell_and_free_of_mojibake() -> None:
    template_root = (
        Path(__file__).parents[2]
        / "src"
        / "maru"
        / "applications"
        / "templates"
        / "applications"
    )

    for template_path in template_root.glob("*.html"):
        source = template_path.read_text(encoding="utf-8")
        assert '{% extends "admin/base_site.html" %}' in source
        assert "\ufffd" not in source
        assert "\u00c2" not in source
        assert "\u00e2" not in source


def test_personal_application_templates_own_one_heading_inside_the_base_main() -> None:
    template_root = (
        Path(__file__).parents[2]
        / "src"
        / "maru"
        / "applications"
        / "templates"
        / "applications"
    )

    for template_name in (
        "my_application_index.html",
        "my_applications.html",
        "my_application_detail.html",
    ):
        source = (template_root / template_name).read_text(encoding="utf-8")
        assert "{% block content_title %}{% endblock %}" in source
        assert source.count("<h1") == 1
        assert "<main" not in source


def _question_form(**changes: object) -> QuestionAddForm:
    section_id = uuid4()
    definition = Mock()
    definition.sections.order_by.return_value = (
        SimpleNamespace(id=section_id, title="Proposal"),
    )
    data = {
        "retry_key": str(uuid4()),
        "expected_version": "1",
        "section_id": str(section_id),
        "key": "format",
        "field_type": "single_choice",
        "label": "Session format",
        "purpose": "Choose a session format.",
        "classification": "C1",
        "reason": "Collect scheduling needs.",
        "options_text": "talk|Talk\npanel|Panel",
    }
    data.update(changes)
    return QuestionAddForm(data, definition=definition)


def test_question_form_normalizes_options_and_complete_conditions() -> None:
    form = _question_form(
        options_text=" talk | Talk \n\n panel | Panel ",
        condition_question_key="session",
        condition_operator="equals",
        condition_value='"talk"',
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["options_text"] == [
        {"code": "talk", "label": "Talk"},
        {"code": "panel", "label": "Panel"},
    ]
    assert form.condition == {
        "question_key": "session",
        "operator": "equals",
        "value": "talk",
    }


@pytest.mark.parametrize(
    "options",
    [
        "talk",
        "Upper|Talk",
        "talk|",
        "talk|" + "x" * 201,
        "talk|Talk\ntalk|Duplicate",
        "\n".join(f"option-{i}|Option {i}" for i in range(101)),
    ],
)
def test_question_form_rejects_malformed_or_unbounded_options(options: str) -> None:
    form = _question_form(options_text=options)
    assert not form.is_valid()
    assert set(form.errors) == {"options_text"}


@pytest.mark.parametrize(
    "condition",
    [
        {"condition_question_key": "session"},
        {"condition_operator": "equals"},
        {"condition_value": '"talk"'},
        {"condition_question_key": "session", "condition_operator": "equals"},
        {"condition_question_key": "session", "condition_value": '"talk"'},
        {"condition_operator": "equals", "condition_value": '"talk"'},
    ],
)
def test_question_form_rejects_partial_conditions(condition: dict[str, str]) -> None:
    form = _question_form(**condition)
    assert not form.is_valid()
    assert set(form.errors) == {"condition_question_key"}


@pytest.mark.parametrize("value", ["false", "0"])
def test_question_form_preserves_falsy_condition_values(value: str) -> None:
    form = _question_form(
        condition_question_key="session",
        condition_operator="equals",
        condition_value=value,
    )
    assert form.is_valid(), form.errors
    expected = False if value == "false" else 0
    assert form.condition["value"] == expected
    assert type(form.condition["value"]) is type(expected)


def test_question_form_accepts_no_condition_and_checks_section_membership() -> None:
    form = _question_form(options_text="")
    assert form.is_valid(), form.errors
    assert form.condition == {}
    assert form.cleaned_data["options_text"] == []
    unavailable = _question_form(section_id=str(uuid4()))
    assert not unavailable.is_valid()
    assert set(unavailable.errors) == {"section_id"}


def _answer_form(
    field_type: str, value: object, **question_fields: object
) -> ApplicantAnswerForm:
    question = ApplicationQuestion(
        id=uuid4(),
        field_type=field_type,
        label="Synthetic answer",
        required=True,
        options=[
            {"code": "talk", "label": "Talk"},
            {"code": "panel", "label": "Panel"},
        ],
        **question_fields,
    )
    return ApplicantAnswerForm(
        {
            "retry_key": str(uuid4()),
            "expected_version": "1",
            "question_id": str(question.id),
            "value": value,
        },
        question=question,
    )


@pytest.mark.parametrize(
    ("field_type", "raw", "expected"),
    [
        ("long_text", " Synthetic abstract ", "Synthetic abstract"),
        ("integer", "12", 12),
        ("decimal", "12.3400", "12.3400"),
        ("boolean", "true", True),
        ("boolean", "false", False),
        ("single_choice", "talk", "talk"),
        ("multiple_choice", ["talk", "panel"], ["talk", "panel"]),
        ("date", "2027-01-01", "2027-01-01"),
        ("time", "12:30", "12:30:00"),
        ("instant", "2027-01-01T12:30:00+00:00", "2027-01-01T12:30:00+00:00"),
        ("email", "speaker@example.invalid", "speaker@example.invalid"),
        ("url", "https://example.invalid/", "https://example.invalid/"),
        ("phone", "+36 12345678", "+36 12345678"),
        ("address", '{"city":"Budapest"}', {"city": "Budapest"}),
    ],
)
def test_applicant_answer_form_preserves_each_supported_value_type(
    field_type: str, raw: object, expected: object
) -> None:
    form = _answer_form(field_type, raw)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["value"] == expected
    assert type(form.cleaned_data["value"]) is type(expected)


@pytest.mark.parametrize(
    "field_type", ["person_reference", "domain_reference", "safe_file"]
)
def test_applicant_reference_form_requires_canonical_uuid(field_type: str) -> None:
    identifier = str(uuid4())
    form = _answer_form(field_type, identifier)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["value"] == identifier
    invalid = _answer_form(field_type, identifier.upper())
    assert not invalid.is_valid()
    assert set(invalid.errors) == {"value"}


@pytest.mark.parametrize(
    ("field_type", "raw", "constraints"),
    [
        ("long_text", "long", {"maximum_length": 3}),
        ("short_text", "ab", {"minimum_length": 3}),
        ("decimal", "1.00001", {}),
        ("decimal", "3", {"maximum_value": 2}),
        ("decimal", "1", {"minimum_value": 2}),
        ("integer", "1.5", {}),
        ("boolean", "yes", {}),
        ("single_choice", "unlisted", {}),
        ("multiple_choice", ["talk", "unlisted"], {}),
        ("date", "2027-02-30", {}),
        ("time", "25:00", {}),
        ("instant", "not-an-instant", {}),
        ("email", "invalid", {}),
        ("url", "not a url", {}),
        ("address", "{", {}),
    ],
)
def test_applicant_answer_form_reports_invalid_values_on_the_answer_field(
    field_type: str, raw: object, constraints: dict[str, object]
) -> None:
    form = _answer_form(field_type, raw, **constraints)
    assert not form.is_valid()
    assert set(form.errors) == {"value"}


def test_applicant_answer_form_rejects_a_different_question_id() -> None:
    form = _answer_form("short_text", "Synthetic title")
    form.data["question_id"] = str(uuid4())
    assert not form.is_valid()
    assert set(form.errors) == {"question_id"}
