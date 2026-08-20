"""Domain-neutral form defaults."""

import pytest
from django import forms
from django.http import QueryDict

from maru.core.forms import HttpsURLField, StrictBase10IntegerField, StrictInputForm


class _CardinalityForm(StrictInputForm):
    single = forms.CharField(required=False)
    multiple = forms.MultipleChoiceField(
        required=False,
        choices=(("one", "One"), ("two", "Two")),
    )


def test_https_url_field_uses_secure_default_scheme() -> None:
    field = HttpsURLField(required=False)

    assert field.clean("example.invalid") == "https://example.invalid"
    assert field.clean("http://example.invalid") == "http://example.invalid"


@pytest.mark.parametrize(
    "value",
    ["+1", "01", "1.0", "1x", "1" * 18 + "x", "\N{ARABIC-INDIC DIGIT ONE}"],
)
def test_strict_base10_integer_rejects_noncanonical_input_without_regex(
    value: str,
) -> None:
    field = StrictBase10IntegerField()

    with pytest.raises(forms.ValidationError) as caught:
        field.clean(value)

    assert caught.value.code == "invalid"


def test_strict_base10_integer_accepts_canonical_ascii_digits() -> None:
    field = StrictBase10IntegerField()

    assert field.clean("0") == 0
    assert field.clean("123456789") == 123456789


def test_strict_input_form_bounds_unknown_field_error_detail() -> None:
    form = StrictInputForm(
        data={f"unexpected_{number}": "value" for number in range(6)}
    )

    assert not form.is_valid()
    assert "unexpected_0" in form.non_field_errors()[0]
    assert "and 1 more" in form.non_field_errors()[0]


def test_strict_input_form_rejects_duplicate_single_value_fields() -> None:
    data = QueryDict(mutable=True)
    data.setlist("single", ["first", "second"])
    data.setlist("multiple", ["one", "two"])

    form = _CardinalityForm(data)

    assert not form.is_valid()
    assert "single-value field at most once" in form.non_field_errors()[0]


def test_strict_input_form_preserves_multi_value_fields_and_explicit_blank() -> None:
    data = QueryDict(mutable=True)
    data.setlist("single", [""])
    data.setlist("multiple", ["one", "two"])

    form = _CardinalityForm(data)

    assert form.is_valid(), form.errors
    assert form.cleaned_data["single"] == ""
    assert form.cleaned_data["multiple"] == ["one", "two"]
