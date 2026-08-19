"""Stable canonical evidence for registration configuration content."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from maru.registration.setup_content import configuration_content_digest


def _digest(*, opens_at: datetime, closes_at: datetime) -> str:
    return configuration_content_digest(
        name="Synthetic attendee registration",
        schema_version=1,
        opens_at=opens_at,
        closes_at=closes_at,
        capacity=500,
        currency="EUR",
        minimum_age=18,
        default_payment_window_minutes=1_440,
        waitlist_enabled=True,
        automatic_waitlist_promotion=True,
        sections=(),
        questions=(),
        products=(),
        minor_policy=None,
    )


def test_digest_normalizes_equivalent_aware_datetimes_to_utc() -> None:
    budapest = ZoneInfo("Europe/Budapest")
    local_open = datetime(2030, 2, 1, 9, 0, tzinfo=budapest)
    local_close = datetime(2030, 7, 31, 23, 59, tzinfo=budapest)

    assert _digest(opens_at=local_open, closes_at=local_close) == _digest(
        opens_at=local_open.astimezone(UTC),
        closes_at=local_close.astimezone(UTC),
    )
