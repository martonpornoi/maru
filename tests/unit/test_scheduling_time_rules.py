"""Database-free edge cases for explicit Scheduling time and host presence."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.scheduling.time_rules import (
    SchedulingEnvelope,
    SchedulingHostPresence,
    SchedulingWindow,
    normalize_host_presences,
    normalize_scheduling_envelope,
    normalize_scheduling_instant,
    normalize_scheduling_window,
    permitted_turnover_window,
    placement_fits_service_day,
    require_scheduling_precision,
    room_envelopes_conflict,
    scheduling_windows_overlap,
)

_BASE = datetime(2026, 10, 24, 22, tzinfo=UTC)


def instant(minutes: int) -> datetime:
    return _BASE + timedelta(minutes=minutes)


def envelope(*minutes: int) -> SchedulingEnvelope:
    return SchedulingEnvelope(*(instant(value) for value in minutes))


def test_offset_instant_is_normalized_without_rounding():
    offset = timezone(timedelta(hours=2))
    assert (
        normalize_scheduling_instant(
            datetime(2026, 10, 25, 0, tzinfo=offset), field="start"
        )
        == _BASE
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "2026-10-25T00:00Z",
        _BASE.replace(tzinfo=None),
        instant(1).replace(second=1),
        instant(1).replace(microsecond=1),
        datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_invalid_or_unrepresentable_instant_fails_closed(value):
    with pytest.raises(ValidationError):
        normalize_scheduling_instant(value, field="start")


def test_explicit_offsets_disambiguate_repeated_wall_clock_minutes():
    first = datetime.fromisoformat("2026-10-25T02:30:00+02:00")
    second = datetime.fromisoformat("2026-10-25T02:30:00+01:00")
    assert (
        normalize_scheduling_instant(second, field="start")
        - normalize_scheduling_instant(first, field="start")
    ) == timedelta(hours=1)


@pytest.mark.parametrize("value", [0, -1, 7, 61, True, False, 5.0, "5", None])
def test_precision_is_strict_and_divides_one_hour(value):
    with pytest.raises(ValidationError):
        require_scheduling_precision(value)


@pytest.mark.parametrize("value", [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60])
def test_supported_precision(value):
    assert require_scheduling_precision(value) == value


@pytest.mark.parametrize(
    "minutes", [(10, 0, 20, 30), (0, 10, 10, 20), (0, 20, 10, 30), (0, 10, 30, 20)]
)
def test_invalid_work_order_is_not_a_draft_warning(minutes):
    with pytest.raises(ValidationError):
        normalize_scheduling_envelope(envelope(*minutes))


def test_zero_preparation_and_teardown_are_allowed():
    value = envelope(0, 0, 30, 30)
    assert normalize_scheduling_envelope(value) == value
    window = SchedulingWindow(instant(0), instant(30))
    assert normalize_scheduling_window(window) == window
    assert placement_fits_service_day(value, window=window, precision_minutes=15)


@pytest.mark.parametrize("value", [None, (), "not an envelope"])
def test_untyped_envelope_is_rejected(value):
    with pytest.raises(ValidationError):
        normalize_scheduling_envelope(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        (),
        SchedulingWindow(instant(1), instant(1)),
        SchedulingWindow(instant(2), instant(1)),
    ],
)
def test_invalid_window_is_rejected(value):
    with pytest.raises(ValidationError):
        normalize_scheduling_window(value)


def test_overnight_window_and_grid_use_exact_day_anchor():
    window = SchedulingWindow(instant(2), instant(1502))
    assert placement_fits_service_day(
        envelope(1192, 1202, 1252, 1262), window=window, precision_minutes=5
    )
    assert not placement_fits_service_day(
        envelope(1190, 1200, 1250, 1260), window=window, precision_minutes=5
    )
    assert not placement_fits_service_day(
        envelope(-3, 2, 12, 17), window=window, precision_minutes=5
    )
    assert not placement_fits_service_day(
        envelope(1492, 1497, 1502, 1507), window=window, precision_minutes=5
    )


@pytest.mark.parametrize(
    ("right", "conflicts"),
    [
        ((40, 60, 90, 100), False),
        ((20, 60, 90, 100), True),
        ((30, 49, 90, 100), True),
        ((-10, 10, 20, 25), True),
        ((25, 35, 60, 70), True),
        ((50, 50, 70, 70), False),
        ((10, 15, 25, 30), True),
        ((80, 90, 100, 110), False),
    ],
)
def test_two_clique_conflicts_are_symmetric(right, conflicts):
    left = envelope(0, 10, 30, 50)
    candidate = envelope(*right)
    assert room_envelopes_conflict(left, candidate) is conflicts
    assert room_envelopes_conflict(candidate, left) is conflicts


def test_only_conflict_free_teardown_preparation_is_turnover():
    left, right = envelope(0, 10, 30, 50), envelope(40, 60, 90, 100)
    expected = SchedulingWindow(instant(40), instant(50))
    assert permitted_turnover_window(left, right) == expected
    assert permitted_turnover_window(right, left) == expected
    assert permitted_turnover_window(left, envelope(20, 60, 90, 100)) is None
    assert permitted_turnover_window(left, envelope(50, 50, 70, 70)) is None
    assert permitted_turnover_window(left, envelope(80, 90, 100, 110)) is None


def test_half_open_adjacency_is_not_person_overlap():
    left = SchedulingWindow(instant(0), instant(10))
    assert not scheduling_windows_overlap(
        left, SchedulingWindow(instant(10), instant(20))
    )
    assert scheduling_windows_overlap(left, SchedulingWindow(instant(9), instant(20)))


def test_host_presence_is_explicit_and_not_the_entire_room_envelope():
    first, second = UUID(int=1), UUID(int=2)
    values = (
        SchedulingHostPresence(second, instant(12), instant(20)),
        SchedulingHostPresence(first, instant(10), instant(30)),
    )
    actual = normalize_host_presences(values, envelope=envelope(0, 10, 30, 50))
    assert tuple(value.host_id for value in actual) == (first, second)
    assert actual[0].starts_at == instant(10)
    assert actual[0].ends_at == instant(30)
    assert normalize_host_presences((), envelope=envelope(0, 10, 30, 50)) == ()


@pytest.mark.parametrize("bounds", [(-1, 10), (10, 51), (20, 20), (30, 20)])
def test_invalid_host_presence_is_rejected(bounds):
    with pytest.raises(ValidationError):
        normalize_host_presences(
            (SchedulingHostPresence(uuid4(), instant(bounds[0]), instant(bounds[1])),),
            envelope=envelope(0, 10, 30, 50),
        )


def test_duplicate_untyped_and_unbounded_host_selection_is_rejected():
    value = SchedulingHostPresence(uuid4(), instant(10), instant(30))
    for values in [
        (value, value),
        (None,),
        (SchedulingHostPresence("bad", instant(10), instant(30)),),
        (value,) * 101,
        [value],
    ]:
        with pytest.raises(ValidationError):
            normalize_host_presences(values, envelope=envelope(0, 10, 30, 50))
