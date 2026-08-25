"""Pure Shift interval, safety-number, and browser-form contract coverage."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError

from maru.workforce.shift_forms import ShiftDemandForm, ShiftWithdrawForm
from maru.workforce.shift_inputs import (
    normalize_shift_interval,
    validate_shift_numbers,
)
from maru.workforce.shift_serializers import (
    ShiftDemandWriteSerializer,
    ShiftLockCommandSerializer,
    ShiftWithdrawCommandSerializer,
)


def test_shift_interval_is_canonical_and_bounded_by_edition_dates() -> None:
    starts_at, ends_at = normalize_shift_interval(
        starts_at=datetime.fromisoformat("2030-08-01T09:00:00+02:00"),
        ends_at=datetime.fromisoformat("2030-08-01T13:00:00+02:00"),
        starts_on=date(2030, 8, 1),
        ends_on=date(2030, 8, 4),
        zone=ZoneInfo("Europe/Budapest"),
    )

    assert starts_at.isoformat() == "2030-08-01T07:00:00+00:00"
    assert ends_at.isoformat() == "2030-08-01T11:00:00+00:00"


def test_shift_interval_and_break_reject_unsafe_input() -> None:
    with pytest.raises(ValidationError, match="within the edition"):
        normalize_shift_interval(
            starts_at=datetime.fromisoformat("2030-07-31T23:00:00+02:00"),
            ends_at=datetime.fromisoformat("2030-08-01T01:00:00+02:00"),
            starts_on=date(2030, 8, 1),
            ends_on=date(2030, 8, 4),
            zone=ZoneInfo("Europe/Budapest"),
        )

    with pytest.raises(ValidationError) as raised:
        validate_shift_numbers(
            required_headcount=1,
            break_minutes=60,
            minimum_rest_minutes=30,
            starts_at=datetime.fromisoformat("2030-08-01T09:00:00+02:00"),
            ends_at=datetime.fromisoformat("2030-08-01T10:00:00+02:00"),
        )
    assert raised.value.error_dict["break_minutes"][0].code == ("shift_break_too_long")


def test_shift_form_rejects_dst_fold_and_unknown_input() -> None:
    form = ShiftDemandForm(
        {
            "position_id": "11111111-1111-4111-8111-111111111111",
            "title": "Night desk",
            "location_label": "Operations desk",
            "starts_at": "2030-10-27T02:30",
            "ends_at": "2030-10-27T04:00",
            "required_headcount": "1",
            "break_minutes": "0",
            "minimum_rest_minutes": "60",
            "briefing": "Keep the desk staffed.",
            "supervision_note": "",
            "reason": "Cover the overnight operating period.",
            "expected_version": "0",
            "retry_key": "22222222-2222-4222-8222-222222222222",
            "unsupported": "must be rejected",
        },
        position_choices=(
            (
                "11111111-1111-4111-8111-111111111111",
                "Operations — Night steward",
            ),
        ),
        starts_on=date(2030, 8, 1),
        ends_on=date(2030, 10, 31),
        time_zone="Europe/Budapest",
        expected_version=0,
    )

    assert not form.is_valid()
    assert form.errors["starts_at"]
    assert form.non_field_errors()


def _api_demand_payload() -> dict[str, object]:
    return {
        "position_id": "aaaaaaaa-1111-4111-8111-111111111111",
        "title": "Morning desk",
        "location_label": "Operations desk",
        "briefing": "Receive handover and answer radio calls.",
        "supervision_note": "Check in with the Operations lead.",
        "starts_at": "2030-08-01T09:00:00+02:00",
        "ends_at": "2030-08-01T13:00:00+02:00",
        "required_headcount": 1,
        "break_minutes": 30,
        "minimum_rest_minutes": 60,
        "reason": "Publish a complete work expectation.",
    }


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("position_id", "AAAAAAAA-1111-4111-8111-111111111111"),
        ("title", 7),
        ("starts_at", "2030-08-01T09:00:00"),
        ("required_headcount", "1"),
        ("break_minutes", False),
    ],
)
def test_shift_api_demand_input_rejects_coercion_and_ambiguous_values(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _api_demand_payload()
    payload[field_name] = invalid_value
    serializer = ShiftDemandWriteSerializer(data=payload)

    assert not serializer.is_valid()
    assert field_name in serializer.errors


def test_shift_action_api_requires_exact_booleans_and_affirmative_withdrawal() -> None:
    lock = ShiftLockCommandSerializer(
        data={
            "expected_version": 1,
            "reason": "Keep planning open when coverage is underfilled.",
            "allow_understaffed": "false",
        }
    )
    withdraw = ShiftWithdrawCommandSerializer(
        data={"expected_version": 1, "confirm": False}
    )

    assert not lock.is_valid()
    assert "allow_understaffed" in lock.errors
    assert not withdraw.is_valid()
    assert "confirm" in withdraw.errors


def test_withdraw_form_never_collects_a_personal_explanation() -> None:
    form = ShiftWithdrawForm(
        {
            "expected_version": "1",
            "retry_key": "22222222-2222-4222-8222-222222222222",
            "confirm": "on",
            "reason": "This private explanation must not be accepted.",
        },
        expected_version=1,
    )

    assert not form.is_valid()
    assert "reason" not in form.fields
    assert form.non_field_errors()
