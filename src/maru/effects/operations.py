"""Safe tenant-bounded outbox health snapshots and metrics rendering."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db.models import Count, Sum
from django.utils import timezone

from maru.effects.models import EffectAttempt, OutboxMessage


@dataclass(frozen=True, slots=True)
class OutboxHealthSnapshot:
    """Describe outbox health snapshot.

    Attributes
    ----------
    organization_id
        The organization identifier that owns the requested resource.
    workload_pool
        The workload pool retained in this immutable projection.
    counts
        The counts retained in this immutable projection.
    attempt_counts
        The attempt counts retained in this immutable projection.
    replay_count
        The bounded number of replay records.
    oldest_ready_age_seconds
        The oldest ready age seconds retained in this immutable projection.
    oldest_expired_lease_age_seconds
        The oldest expired lease age seconds retained in this immutable projection.
    """

    organization_id: UUID
    workload_pool: str
    counts: tuple[tuple[str, int], ...]
    attempt_counts: tuple[tuple[str, int], ...]
    replay_count: int
    oldest_ready_age_seconds: int | None
    oldest_expired_lease_age_seconds: int | None


def _age_seconds(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def outbox_health_snapshot(
    *,
    organization_id: UUID,
    workload_pool: str,
    now: datetime | None = None,
) -> OutboxHealthSnapshot:
    """Return outbox health snapshot.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    workload_pool : str
        The named worker pool that owns the work.
    now : datetime | None, default=None
        The effective time for the operation.

    Returns
    -------
    OutboxHealthSnapshot
        The OutboxHealthSnapshot established after outbox health snapshot completes.
    """
    observed_at = now or timezone.now()
    messages = OutboxMessage.objects.filter(
        organization_id=organization_id,
        workload_pool=workload_pool,
    )
    observed_counts = {
        row["status"]: row["count"]
        for row in messages.values("status")
        .annotate(count=Count("id"))
        .order_by("status")
    }
    counts = tuple(
        (status, observed_counts.get(status, 0))
        for status in OutboxMessage.Status.values
    )
    attempts = EffectAttempt.objects.filter(
        outbox_message__organization_id=organization_id,
        outbox_message__workload_pool=workload_pool,
    )
    observed_attempt_counts = {
        row["outcome"]: row["count"]
        for row in attempts.values("outcome")
        .annotate(count=Count("id"))
        .order_by("outcome")
    }
    attempt_counts = tuple(
        (outcome, observed_attempt_counts.get(outcome, 0))
        for outcome in EffectAttempt.Outcome.values
    )
    replay_count = messages.aggregate(total=Sum("replay_count"))["total"] or 0
    oldest_ready = (
        messages.filter(
            status=OutboxMessage.Status.PENDING,
            available_at__lte=observed_at,
        )
        .order_by("available_at")
        .values_list("available_at", flat=True)
        .first()
    )
    oldest_expired = (
        messages.filter(
            status=OutboxMessage.Status.PROCESSING,
            lease_expires_at__lte=observed_at,
        )
        .order_by("lease_expires_at")
        .values_list("lease_expires_at", flat=True)
        .first()
    )
    return OutboxHealthSnapshot(
        organization_id=organization_id,
        workload_pool=workload_pool,
        counts=counts,
        attempt_counts=attempt_counts,
        replay_count=replay_count,
        oldest_ready_age_seconds=_age_seconds(oldest_ready, now=observed_at),
        oldest_expired_lease_age_seconds=_age_seconds(
            oldest_expired,
            now=observed_at,
        ),
    )


def _metric_value(value: int | None) -> str:
    return "NaN" if value is None else str(value)


def render_prometheus(snapshot: OutboxHealthSnapshot) -> str:
    """Render prometheus.

    Parameters
    ----------
    snapshot : OutboxHealthSnapshot
        The snapshot evaluated while render prometheus.

    Returns
    -------
    str
        The rendered prometheus text.
    """
    labels = (
        f'organization_id="{snapshot.organization_id}",'
        f'workload_pool="{snapshot.workload_pool}"'
    )
    lines = [
        "# HELP maru_outbox_messages Current outbox messages by delivery state.",
        "# TYPE maru_outbox_messages gauge",
    ]
    lines.extend(
        f'maru_outbox_messages{{{labels},status="{status}"}} {count}'
        for status, count in snapshot.counts
    )
    lines.extend(
        (
            "# HELP maru_outbox_attempts_total Durable effect attempts by outcome.",
            "# TYPE maru_outbox_attempts_total counter",
        )
    )
    lines.extend(
        f'maru_outbox_attempts_total{{{labels},outcome="{outcome}"}} {count}'
        for outcome, count in snapshot.attempt_counts
    )
    lines.extend(
        (
            "# HELP maru_outbox_oldest_ready_age_seconds Age of oldest ready work.",
            "# TYPE maru_outbox_oldest_ready_age_seconds gauge",
            (
                f"maru_outbox_oldest_ready_age_seconds{{{labels}}} "
                f"{_metric_value(snapshot.oldest_ready_age_seconds)}"
            ),
            (
                "# HELP maru_outbox_oldest_expired_lease_age_seconds "
                "Age of oldest expired processing lease."
            ),
            "# TYPE maru_outbox_oldest_expired_lease_age_seconds gauge",
            (
                f"maru_outbox_oldest_expired_lease_age_seconds{{{labels}}} "
                f"{_metric_value(snapshot.oldest_expired_lease_age_seconds)}"
            ),
            "# HELP maru_outbox_replays_total Operator replay count.",
            "# TYPE maru_outbox_replays_total counter",
            f"maru_outbox_replays_total{{{labels}}} {snapshot.replay_count}",
        )
    )
    return "\n".join(lines) + "\n"
