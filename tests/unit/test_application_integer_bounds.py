"""Configured integer bounds agree at forms, owner input and new seal checks."""

from decimal import Decimal
from math import ceil, floor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_commands as commands
from maru.applications.forms import _answer_field
from tests.unit.test_application_answer_values import _normalize, _question


@pytest.mark.parametrize(
    ("minimum", "maximum", "allowed", "rejected"),
    [
        (Decimal(10), Decimal(15), (10, 15), (9, 16)),
        (Decimal(-2), Decimal(0), (-2, 0), (-3, 1)),
        (Decimal("1.5"), Decimal("4.5"), (2, 4), (1, 5)),
        (Decimal("-4.5"), Decimal("-1.5"), (-4, -2), (-5, -1)),
        (None, None, (-(2**31), 2**31 - 1), (-(2**31) - 1, 2**31)),
        (Decimal(-(2**40)), Decimal(2**40), (0,), (2**31,)),
    ],
)
def test_integer_form_and_owner_enforce_identical_numeric_bounds(
    minimum, maximum, allowed, rejected
):
    bounds = {"minimum_value": minimum, "maximum_value": maximum}
    field = _answer_field(_question("integer", **bounds))
    assert (
        field.widget.attrs["min"] == max(-(2**31), ceil(minimum))
        if minimum is not None
        else field.widget.attrs["min"] == -(2**31)
    )
    assert (
        field.widget.attrs["max"] == min(2**31 - 1, floor(maximum))
        if maximum is not None
        else field.widget.attrs["max"] == 2**31 - 1
    )
    for value in allowed:
        assert field.clean(str(value)) == value
        assert _normalize("integer", value, **bounds) == value
    for value in rejected:
        with pytest.raises(ValidationError):
            field.clean(str(value))
        with pytest.raises(ValidationError) as error:
            _normalize("integer", value, **bounds)
        assert error.value.code == "invalid_application_integer"


@pytest.mark.parametrize("value", [True, False, "1", 1.0])
def test_owner_still_refuses_noninteger_types(value):
    with pytest.raises(ValidationError):
        _normalize("integer", value, minimum_value=Decimal(0), maximum_value=Decimal(2))


@pytest.mark.parametrize("required", [False, True])
@pytest.mark.parametrize("value", [9, 16, True, "10"])
def test_invalid_retained_integer_blocks_new_seal_without_rewriting_history(
    monkeypatch, required, value
):
    question = _question(
        "integer",
        key="capacity",
        required=required,
        minimum_value=Decimal(10),
        maximum_value=Decimal(15),
    )
    answer = SimpleNamespace(value=value, save=Mock())
    monkeypatch.setattr(
        commands, "_latest_answer_map", lambda **_: {"capacity": answer}
    )
    proposal = SimpleNamespace(
        submission=object(),
        call=SimpleNamespace(
            definition=SimpleNamespace(
                questions=SimpleNamespace(order_by=lambda *_: (question,))
            )
        ),
    )
    with pytest.raises(commands.ApplicationsProgrammeCompletenessError):
        commands._applicable_questions(proposal=proposal, through_version=8)
    answer.save.assert_not_called()
    assert answer.value == value


@pytest.mark.parametrize("value", [None, 10, 15])
def test_blank_optional_or_valid_retained_answer_remains_sealable(monkeypatch, value):
    question = _question(
        "integer",
        key="capacity",
        required=False,
        minimum_value=Decimal(10),
        maximum_value=Decimal(15),
    )
    answer = SimpleNamespace(value=value)
    monkeypatch.setattr(
        commands, "_latest_answer_map", lambda **_: {"capacity": answer}
    )
    proposal = SimpleNamespace(
        submission=object(),
        call=SimpleNamespace(
            definition=SimpleNamespace(
                questions=SimpleNamespace(order_by=lambda *_: (question,))
            )
        ),
    )
    assert commands._applicable_questions(proposal=proposal, through_version=8) == (
        (question, answer),
    )
