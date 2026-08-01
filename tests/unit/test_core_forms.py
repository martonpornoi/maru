"""Domain-neutral form defaults."""

from maru.core.forms import HttpsURLField, StrictInputForm


def test_https_url_field_uses_secure_default_scheme() -> None:
    field = HttpsURLField(required=False)

    assert field.clean("example.invalid") == "https://example.invalid"
    assert field.clean("http://example.invalid") == "http://example.invalid"


def test_strict_input_form_bounds_unknown_field_error_detail() -> None:
    form = StrictInputForm(
        data={f"unexpected_{number}": "value" for number in range(6)}
    )

    assert not form.is_valid()
    assert "unexpected_0" in form.non_field_errors()[0]
    assert "and 1 more" in form.non_field_errors()[0]
