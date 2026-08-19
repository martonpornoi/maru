"""Strict browser-input and edition-local time contracts for Applications."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.http import QueryDict

from maru.applications.forms import (
    DefinitionConfigureForm,
    DefinitionLifecycleForm,
    EditionLocalDateTimeField,
    QuestionAddForm,
    StarterCopyForm,
)
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
