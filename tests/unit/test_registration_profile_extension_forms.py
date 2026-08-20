"""Strict browser input coverage for profile-extension value edits."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from django.http import QueryDict

from maru.registration.models import QuestionFieldType
from maru.registration.profile_extension_forms import ProfileExtensionValueForm
from maru.registration.profile_extension_values import (
    ProfileExtensionValueFieldProjection,
)


def _field(
    *,
    field_type: str = QuestionFieldType.SHORT_TEXT,
    options: tuple[str, ...] = (),
    required: bool = False,
    value: object | None = None,
) -> ProfileExtensionValueFieldProjection:
    return ProfileExtensionValueFieldProjection(
        field_id=uuid4(),
        field_key="synthetic-detail",
        field_version=1,
        label="Synthetic detail",
        help_text="Provide one synthetic current detail.",
        field_type=field_type,
        options=options,
        purpose="Exercise the strict profile-value browser contract.",
        classification="C2",
        audience_policy="self",
        audience_department_id=None,
        required=required,
        writer_policy="attendee",
        can_write=True,
        current_value=value,
        current_sequence=2,
        updated_at=None,
    )


def _data(*, value: object, **extra: object) -> QueryDict:
    retry_key = uuid4()
    query = QueryDict(mutable=True)
    if isinstance(value, list):
        query.setlist("value", [str(item) for item in value])
    else:
        query["value"] = str(value)
    query["expected_sequence"] = "2"
    query["retry_key"] = str(retry_key)
    for key, item in extra.items():
        query[key] = str(item)
    return query


@pytest.mark.parametrize("alias", [" 2", "+2", "02", "2 ", "-0"])
def test_command_sequence_accepts_only_canonical_base10(alias: str) -> None:
    form = ProfileExtensionValueForm(
        _data(value="detail", expected_sequence=alias),
        profile_field=_field(),
    )

    assert not form.is_valid()
    assert "expected_sequence" in form.errors


def test_closed_form_rejects_unknown_and_duplicate_single_values() -> None:
    unknown = ProfileExtensionValueForm(
        _data(value="detail", actor_id=uuid4()),
        profile_field=_field(),
    )
    duplicate = _data(value="detail")
    duplicate.setlist("expected_sequence", ["2", "2"])
    duplicate_form = ProfileExtensionValueForm(
        duplicate,
        profile_field=_field(),
    )

    assert not unknown.is_valid()
    assert "unsupported input fields" in str(unknown.non_field_errors()).casefold()
    assert not duplicate_form.is_valid()
    assert "at most once" in str(duplicate_form.non_field_errors()).casefold()


@pytest.mark.parametrize(
    ("field_type", "raw", "expected"),
    [
        (QuestionFieldType.BOOLEAN, "true", True),
        (QuestionFieldType.BOOLEAN, "false", False),
        (QuestionFieldType.INTEGER, "-2147483648", -(2**31)),
        (QuestionFieldType.INTEGER, "2147483647", (2**31) - 1),
        (QuestionFieldType.SINGLE_CHOICE, "alpha", "alpha"),
    ],
)
def test_typed_value_controls_return_domain_values(
    field_type: str,
    raw: str,
    expected: object,
) -> None:
    options = ("alpha", "beta") if field_type == QuestionFieldType.SINGLE_CHOICE else ()
    form = ProfileExtensionValueForm(
        _data(value=raw),
        profile_field=_field(field_type=field_type, options=options),
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["value"] == expected
    assert type(form.cleaned_data["retry_key"]) is UUID


@pytest.mark.parametrize(
    "field_type",
    [
        QuestionFieldType.BOOLEAN,
        QuestionFieldType.INTEGER,
        QuestionFieldType.SINGLE_CHOICE,
    ],
)
def test_optional_closed_types_use_none_as_the_clear_value(field_type: str) -> None:
    form = ProfileExtensionValueForm(
        _data(value=""),
        profile_field=_field(
            field_type=field_type,
            options=("alpha", "beta"),
        ),
    )

    assert form.is_valid(), form.errors
    assert form.cleaned_data["value"] is None


@pytest.mark.parametrize(
    "alias",
    [
        "-0",
        "+1",
        "01",
        "-01",
        "1.0",
        "1111111111x",
        "\N{ARABIC-INDIC DIGIT ONE}",
    ],
)
def test_signed_integer_rejects_noncanonical_input_without_regex(alias: str) -> None:
    form = ProfileExtensionValueForm(
        _data(value=alias),
        profile_field=_field(field_type=QuestionFieldType.INTEGER),
    )

    assert not form.is_valid()
    assert form.errors.as_data()["value"][0].code == "invalid"


def test_multiple_choices_reject_duplicate_values() -> None:
    multiple = ProfileExtensionValueForm(
        _data(value=["alpha", "alpha"]),
        profile_field=_field(
            field_type=QuestionFieldType.MULTIPLE_CHOICE,
            options=("alpha", "beta"),
        ),
    )

    assert not multiple.is_valid()
    assert "value" in multiple.errors
