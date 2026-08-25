"""Pure Availability interval, local-time, and formset contract coverage."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError

from maru.workforce.availability_inputs import (
    AvailabilityWindowInput,
    availability_window_set_digest,
    normalize_availability_windows,
)
from maru.workforce.forms import AvailabilityWindowFormSet


def _window(
    start: str,
    end: str,
    *,
    preference: str = "available",
) -> AvailabilityWindowInput:
    return AvailabilityWindowInput(
        starts_at=datetime.fromisoformat(start),
        ends_at=datetime.fromisoformat(end),
        preference=preference,
    )


def test_windows_are_sorted_normalized_and_may_touch_without_overlap() -> None:
    normalized = normalize_availability_windows(
        (
            _window(
                "2030-08-01T12:00:00+02:00",
                "2030-08-01T14:00:00+02:00",
                preference="preferred",
            ),
            _window(
                "2030-08-01T10:00:00+02:00",
                "2030-08-01T12:00:00+02:00",
            ),
        ),
        starts_on=date(2030, 8, 1),
        ends_on=date(2030, 8, 4),
        time_zone="Europe/Budapest",
    )

    assert [item.starts_at.tzinfo for item in normalized] == [UTC, UTC]
    assert normalized[0].starts_at == datetime(2030, 8, 1, 8, tzinfo=UTC)
    assert normalized[1].preference == "preferred"
    assert len(availability_window_set_digest(normalized)) == 64
    assert availability_window_set_digest(normalized) != (
        availability_window_set_digest(normalized[:1])
    )


@pytest.mark.parametrize(
    ("windows", "code"),
    [
        (
            (
                _window(
                    "2030-08-01T10:00:00+02:00",
                    "2030-08-01T12:01:00+02:00",
                ),
                _window(
                    "2030-08-01T12:00:00+02:00",
                    "2030-08-01T13:00:00+02:00",
                ),
            ),
            "availability_windows_overlap",
        ),
        (
            (_window("2030-07-31T23:59:00+02:00", "2030-08-01T01:00:00+02:00"),),
            "availability_window_outside_edition",
        ),
        (
            (_window("2030-08-01T10:00:00", "2030-08-01T11:00:00"),),
            "availability_timezone_required",
        ),
        (
            (
                _window(
                    "2030-08-01T10:00:00+02:00",
                    "2030-08-01T11:00:00+02:00",
                    preference="required",
                ),
            ),
            "availability_preference_invalid",
        ),
    ],
)
def test_window_contract_rejects_unsafe_sets(
    windows: tuple[AvailabilityWindowInput, ...],
    code: str,
) -> None:
    with pytest.raises(ValidationError) as raised:
        normalize_availability_windows(
            windows,
            starts_on=date(2030, 8, 1),
            ends_on=date(2030, 8, 4),
            time_zone="Europe/Budapest",
        )

    assert raised.value.error_dict["windows"][0].code == code


@pytest.mark.parametrize(
    "local_value",
    [
        "2030-03-31T02:30",  # nonexistent spring-forward minute
        "2030-10-27T02:30",  # ambiguous fall-back minute
    ],
)
def test_browser_formset_rejects_dst_gap_and_fold(local_value: str) -> None:
    formset = AvailabilityWindowFormSet(
        {
            "windows-TOTAL_FORMS": "1",
            "windows-INITIAL_FORMS": "0",
            "windows-MIN_NUM_FORMS": "0",
            "windows-MAX_NUM_FORMS": "64",
            "windows-0-starts_at": local_value,
            "windows-0-ends_at": "2030-10-27T04:00",
            "windows-0-preference": "available",
        },
        prefix="windows",
        starts_on=date(2030, 3, 1),
        ends_on=date(2030, 10, 31),
        time_zone="Europe/Budapest",
    )

    assert not formset.is_valid()
    assert formset.forms[0].errors["starts_at"]


def test_empty_formset_is_an_explicit_valid_complete_set() -> None:
    formset = AvailabilityWindowFormSet(
        {
            "windows-TOTAL_FORMS": "1",
            "windows-INITIAL_FORMS": "0",
            "windows-MIN_NUM_FORMS": "0",
            "windows-MAX_NUM_FORMS": "64",
            "windows-0-starts_at": "",
            "windows-0-ends_at": "",
            "windows-0-preference": "available",
        },
        prefix="windows",
        starts_on=date(2030, 8, 1),
        ends_on=date(2030, 8, 4),
        time_zone=str(ZoneInfo("Europe/Budapest")),
    )

    assert formset.is_valid()
    assert formset.windows == ()
