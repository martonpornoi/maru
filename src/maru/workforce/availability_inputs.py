"""Pure validation and privacy-preserving digests for person availability."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

MAX_AVAILABILITY_WINDOWS = 64
AVAILABILITY_PREFERENCES = frozenset({"available", "preferred"})


@dataclass(frozen=True, slots=True)
class AvailabilityWindowInput:
    """Describe one exact workable interval supplied by its person owner.

    Attributes
    ----------
    starts_at
        Inclusive aware start instant.
    ends_at
        Exclusive aware end instant.
    preference
        ``available`` or the soft ``preferred`` planning signal.
    """

    starts_at: datetime
    ends_at: datetime
    preference: str


def normalize_availability_windows(
    windows: Sequence[AvailabilityWindowInput],
    *,
    starts_on: date,
    ends_on: date,
    time_zone: str,
) -> tuple[AvailabilityWindowInput, ...]:
    """Return one ordered, bounded, non-overlapping edition window set.

    Parameters
    ----------
    windows : Sequence[AvailabilityWindowInput]
        Complete candidate availability set.
    starts_on : date
        First local calendar day in the edition horizon.
    ends_on : date
        Last local calendar day in the edition horizon.
    time_zone : str
        Persisted IANA zone used to interpret the edition calendar horizon.

    Returns
    -------
    tuple[AvailabilityWindowInput, ...]
        Canonically ordered aware intervals.

    Raises
    ------
    ValidationError
        If count, awareness, ordering, preference, horizon, or overlap is
        invalid.
    """
    if len(windows) > MAX_AVAILABILITY_WINDOWS:
        raise ValidationError(
            {
                "windows": ValidationError(
                    f"Provide no more than {MAX_AVAILABILITY_WINDOWS} periods.",
                    code="availability_window_limit_exceeded",
                )
            }
        )
    zone = ZoneInfo(time_zone)
    horizon_start = datetime.combine(starts_on, time.min, tzinfo=zone)
    horizon_end = datetime.combine(ends_on + timedelta(days=1), time.min, tzinfo=zone)
    normalized: list[AvailabilityWindowInput] = []
    for window in windows:
        if (
            not isinstance(window.starts_at, datetime)
            or not isinstance(window.ends_at, datetime)
            or not timezone.is_aware(window.starts_at)
            or not timezone.is_aware(window.ends_at)
        ):
            raise ValidationError(
                {
                    "windows": ValidationError(
                        "Every period needs date-times with a timezone.",
                        code="availability_timezone_required",
                    )
                }
            )
        if window.starts_at >= window.ends_at:
            raise ValidationError(
                {
                    "windows": ValidationError(
                        "Every period must end after it starts.",
                        code="availability_window_order_invalid",
                    )
                }
            )
        if window.preference not in AVAILABILITY_PREFERENCES:
            raise ValidationError(
                {
                    "windows": ValidationError(
                        "Choose Available or Preferred for every period.",
                        code="availability_preference_invalid",
                    )
                }
            )
        if window.starts_at < horizon_start or window.ends_at > horizon_end:
            raise ValidationError(
                {
                    "windows": ValidationError(
                        "Every period must stay within the edition's calendar dates.",
                        code="availability_window_outside_edition",
                    )
                }
            )
        normalized.append(
            AvailabilityWindowInput(
                starts_at=window.starts_at.astimezone(UTC),
                ends_at=window.ends_at.astimezone(UTC),
                preference=window.preference,
            )
        )
    normalized.sort(key=lambda item: (item.starts_at, item.ends_at, item.preference))
    for previous, current in pairwise(normalized):
        if current.starts_at < previous.ends_at:
            raise ValidationError(
                {
                    "windows": ValidationError(
                        "Availability periods may not overlap.",
                        code="availability_windows_overlap",
                    )
                }
            )
    return tuple(normalized)


def _canonical_payload(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def keyed_availability_digest(payload: Mapping[str, object]) -> str:
    """Return a server-keyed digest without retaining exact time input.

    Parameters
    ----------
    payload : Mapping[str, object]
        Canonical JSON-compatible command or window-set material.

    Returns
    -------
    str
        Lowercase SHA-256 HMAC suitable for retry and evidence comparison.
    """
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        _canonical_payload(payload),
        hashlib.sha256,
    ).hexdigest()


def availability_window_set_digest(
    windows: Sequence[AvailabilityWindowInput],
) -> str:
    """Return minimized keyed evidence for one complete current window set.

    Parameters
    ----------
    windows : Sequence[AvailabilityWindowInput]
        Already normalized current windows.

    Returns
    -------
    str
        Keyed digest that is not itself an exact-time projection.
    """
    return keyed_availability_digest(
        {
            "windows": [
                {
                    "starts_at": window.starts_at.isoformat(),
                    "ends_at": window.ends_at.isoformat(),
                    "preference": window.preference,
                }
                for window in windows
            ]
        }
    )
