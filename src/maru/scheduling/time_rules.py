"""Pure Scheduling time contracts, independent from persistence and authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from django.core.exceptions import ValidationError

MINUTES_PER_HOUR: Final = 60
MAX_HOSTS_PER_OCCURRENCE: Final = 100


@dataclass(frozen=True, slots=True)
class SchedulingWindow:
    """One positive, half-open interval of absolute time.

    Attributes
    ----------
    starts_at
        Inclusive, offset-aware start, normalized to UTC by the boundary.
    ends_at
        Exclusive, offset-aware end, normalized to UTC by the boundary.
    """

    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class SchedulingEnvelope:
    """Ordered preparation, effective delivery and teardown boundaries.

    Attributes
    ----------
    setup_starts_at
        First room-occupying preparation instant.
    effective_starts_at
        Beginning of positive effective delivery.
    effective_ends_at
        End of effective delivery.
    teardown_ends_at
        Final room-occupying teardown instant.
    """

    setup_starts_at: datetime
    effective_starts_at: datetime
    effective_ends_at: datetime
    teardown_ends_at: datetime


@dataclass(frozen=True, slots=True)
class SchedulingHostPresence:
    """Explicit required presence, not a host's consent or availability record.

    Attributes
    ----------
    host_id
        Exact Programme item/host relationship to resolve through its owner.
    starts_at
        Inclusive required presence instant within the room work envelope.
    ends_at
        Exclusive required presence instant within the room work envelope.
    """

    host_id: UUID
    starts_at: datetime
    ends_at: datetime


def normalize_scheduling_instant(value: datetime, *, field: str) -> datetime:
    """Require a representable whole-minute instant and normalize it to UTC.

    Parameters
    ----------
    value : datetime
        Offset-aware input; a local wall-clock minute is insufficient.
    field : str
        Closed caller-owned field name for actionable validation.

    Returns
    -------
    datetime
        The exact UTC instant, without rounding or loss of precision.

    Raises
    ------
    ValidationError
        If the input is naive, malformed, sub-minute or unrepresentable.
    """
    message = {field: "Use an offset-aware, whole-minute instant."}
    if not isinstance(value, datetime):
        raise ValidationError(message, code="scheduling_instant_invalid")
    try:
        normalized = value.astimezone(UTC) if value.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError(
            message,
            code="scheduling_instant_invalid",
        ) from exc
    if normalized is None or normalized.second or normalized.microsecond:
        raise ValidationError(message, code="scheduling_instant_invalid")
    return normalized


def normalize_scheduling_window(value: SchedulingWindow) -> SchedulingWindow:
    """Validate a positive interval without interpreting missing time as free.

    Parameters
    ----------
    value : SchedulingWindow
        Typed interval supplied by a boundary or owner projection.

    Returns
    -------
    SchedulingWindow
        Positive half-open UTC interval.

    Raises
    ------
    ValidationError
        If the shape, either instant or interval ordering is invalid.
    """
    if not isinstance(value, SchedulingWindow):
        raise ValidationError("Use a typed Scheduling interval.")
    start = normalize_scheduling_instant(value.starts_at, field="starts_at")
    end = normalize_scheduling_instant(value.ends_at, field="ends_at")
    if start >= end:
        raise ValidationError("The interval end must follow its start.")
    return SchedulingWindow(start, end)


def normalize_scheduling_envelope(value: SchedulingEnvelope) -> SchedulingEnvelope:
    """Require the SCH-009 work envelope without inventing host attendance.

    Parameters
    ----------
    value : SchedulingEnvelope
        Proposed room occupancy; setup and teardown may have zero duration.

    Returns
    -------
    SchedulingEnvelope
        Ordered UTC boundaries with positive effective duration.

    Raises
    ------
    ValidationError
        If the typed shape, any instant or ordering is invalid.
    """
    if not isinstance(value, SchedulingEnvelope):
        raise ValidationError("Use a typed Scheduling work envelope.")
    setup, start, end, teardown = (
        normalize_scheduling_instant(getattr(value, name), field=name)
        for name in (
            "setup_starts_at",
            "effective_starts_at",
            "effective_ends_at",
            "teardown_ends_at",
        )
    )
    if not setup <= start < end <= teardown:
        raise ValidationError("Order preparation, delivery and teardown boundaries.")
    return SchedulingEnvelope(setup, start, end, teardown)


def require_scheduling_precision(value: int) -> int:
    """Require a whole-minute grid that divides one hour exactly.

    Parameters
    ----------
    value : int
        Proposed service-day grid step, from one through sixty minutes.

    Returns
    -------
    int
        Validated minute precision, without coercing booleans or strings.

    Raises
    ------
    ValidationError
        If the value is not a positive integer divisor of sixty.
    """
    if (
        type(value) is not int
        or not 1 <= value <= MINUTES_PER_HOUR
        or MINUTES_PER_HOUR % value
    ):
        raise ValidationError("Grid minutes must be a positive divisor of 60.")
    return value


def normalize_host_presences(
    values: tuple[SchedulingHostPresence, ...], *, envelope: SchedulingEnvelope
) -> tuple[SchedulingHostPresence, ...]:
    """Bound and order explicit host requirements without resolving private people.

    Parameters
    ----------
    values : tuple[SchedulingHostPresence, ...]
        Complete explicit selection, at most one hundred distinct relationships.
    envelope : SchedulingEnvelope
        Work envelope that must contain each required presence interval.

    Returns
    -------
    tuple[SchedulingHostPresence, ...]
        UUID-ordered, normalized presence requirements. Empty remains empty;
        the Programme owner must separately prove hosting is not applicable.

    Raises
    ------
    ValidationError
        If input is unbounded, malformed, duplicated or outside the work envelope.
    """
    envelope = normalize_scheduling_envelope(envelope)
    if not isinstance(values, tuple) or len(values) > MAX_HOSTS_PER_OCCURRENCE:
        raise ValidationError("Select at most 100 explicit host relationships.")
    result: list[SchedulingHostPresence] = []
    identifiers: set[UUID] = set()
    for value in values:
        if (
            not isinstance(value, SchedulingHostPresence)
            or not isinstance(value.host_id, UUID)
            or value.host_id in identifiers
        ):
            raise ValidationError("Select each typed host relationship once.")
        window = normalize_scheduling_window(
            SchedulingWindow(value.starts_at, value.ends_at)
        )
        if (
            window.starts_at < envelope.setup_starts_at
            or window.ends_at > envelope.teardown_ends_at
        ):
            raise ValidationError("Host presence must fit the work envelope.")
        identifiers.add(value.host_id)
        result.append(
            SchedulingHostPresence(value.host_id, window.starts_at, window.ends_at)
        )
    return tuple(sorted(result, key=lambda value: str(value.host_id)))


def placement_fits_service_day(
    envelope: SchedulingEnvelope, *, window: SchedulingWindow, precision_minutes: int
) -> bool:
    """Check all room phases against the day window and its anchored UTC grid.

    Parameters
    ----------
    envelope : SchedulingEnvelope
        Complete room occupancy to check.
    window : SchedulingWindow
        Current service-day window, possibly crossing local midnight.
    precision_minutes : int
        Validated day-grid precision; the anchor is the window start.

    Returns
    -------
    bool
        Whether every boundary fits the window and exact grid.
    """
    envelope = normalize_scheduling_envelope(envelope)
    window = normalize_scheduling_window(window)
    step = require_scheduling_precision(precision_minutes) * 60
    return (
        envelope.setup_starts_at >= window.starts_at
        and envelope.teardown_ends_at <= window.ends_at
        and all(
            (instant - window.starts_at).total_seconds() % step == 0
            for instant in (
                envelope.setup_starts_at,
                envelope.effective_starts_at,
                envelope.effective_ends_at,
                envelope.teardown_ends_at,
            )
        )
    )


def scheduling_windows_overlap(left: SchedulingWindow, right: SchedulingWindow) -> bool:
    """Compare normalized half-open intervals; exact adjacency is not overlap.

    Parameters
    ----------
    left : SchedulingWindow
        First normalized positive interval.
    right : SchedulingWindow
        Second normalized positive interval.

    Returns
    -------
    bool
        Whether the intervals share a positive amount of time.
    """
    return left.starts_at < right.ends_at and right.starts_at < left.ends_at


def room_envelopes_conflict(
    left: SchedulingEnvelope, right: SchedulingEnvelope
) -> bool:
    """Apply the Venue-owned SCH-009 two-clique rule to normalized proposals.

    Parameters
    ----------
    left : SchedulingEnvelope
        First normalized complete room work envelope.
    right : SchedulingEnvelope
        Second normalized complete room work envelope sharing a physical member.

    Returns
    -------
    bool
        Whether either setup-through-effective or effective-through-teardown
        interval overlaps its corresponding interval in the other envelope.
    """
    return scheduling_windows_overlap(
        SchedulingWindow(left.setup_starts_at, left.effective_ends_at),
        SchedulingWindow(right.setup_starts_at, right.effective_ends_at),
    ) or scheduling_windows_overlap(
        SchedulingWindow(left.effective_starts_at, left.teardown_ends_at),
        SchedulingWindow(right.effective_starts_at, right.teardown_ends_at),
    )


def permitted_turnover_window(
    left: SchedulingEnvelope, right: SchedulingEnvelope
) -> SchedulingWindow | None:
    """Identify only a conflict-free teardown/preparation overlap.

    Parameters
    ----------
    left : SchedulingEnvelope
        First normalized complete envelope, in either temporal order.
    right : SchedulingEnvelope
        Second normalized complete envelope, in either temporal order.

    Returns
    -------
    SchedulingWindow | None
        Positive turnover overlap, or none for adjacency, separation or any
        independent two-clique occupancy conflict.
    """
    if room_envelopes_conflict(left, right):
        return None
    earlier, later = sorted((left, right), key=lambda value: value.effective_starts_at)
    start = max(earlier.effective_ends_at, later.setup_starts_at)
    end = min(earlier.teardown_ends_at, later.effective_starts_at)
    return SchedulingWindow(start, end) if start < end else None
