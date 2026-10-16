from datetime import UTC, date, datetime, timedelta

import pytest

from maru.demo.convention_plan import (
    ACCOUNT_KEYS,
    DEMO_ZONE,
    account_identity,
    current_anchor,
    edition_plan,
)


@pytest.mark.parametrize(
    "anchor",
    [
        date(2026, 12, 31),
        date(2027, 1, 1),
        date(2028, 2, 29),
        date(2026, 3, 29),
        date(2026, 10, 25),
    ],
)
def test_two_timelines_are_current_and_future_across_calendar_boundaries(anchor):
    current, future = edition_plan(anchor)
    assert current.starts_on < anchor < current.ends_on
    assert future.starts_on > anchor
    assert future.ends_on - future.starts_on == timedelta(days=3)
    assert current.review_on > current.ends_on
    assert future.review_on > future.ends_on
    assert current.key != future.key


def test_anchor_is_event_local_not_host_local_and_stays_fixed():
    instant = datetime(2026, 12, 31, 23, 30, tzinfo=UTC)
    anchor = current_anchor(instant)
    assert DEMO_ZONE == "Europe/Budapest"
    assert anchor == date(2027, 1, 1)
    old = edition_plan(anchor)
    new = edition_plan(current_anchor(instant + timedelta(days=2)))
    assert old[0].starts_on == date(2026, 12, 31)
    assert new[0].starts_on == old[0].starts_on + timedelta(days=2)


@pytest.mark.parametrize("bad", [date.min, date.max, datetime.now(UTC), "2026-10-15"])
def test_bad_or_overflowing_anchor_is_rejected(bad):
    with pytest.raises(ValueError, match="calendar"):
        edition_plan(bad)


def test_naive_clock_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        current_anchor(datetime(2026, 1, 1, tzinfo=None))  # noqa: DTZ001 -- explicit invalid-input test


def test_identity_namespace_is_closed_unique_and_fictional():
    accounts = tuple(account_identity(key) for key in ACCOUNT_KEYS)
    assert len({identity for identity, _email in accounts}) == 9
    assert len({email for _identity, email in accounts}) == 9
    assert all(email.endswith("@maru.invalid") for _identity, email in accounts)
    with pytest.raises(ValueError, match="Unknown"):
        account_identity("real-person@example.org")
