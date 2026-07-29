"""Fair tenant scheduling and hard-timeout child-process supervision."""

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db.models import F, Q
from django.utils import timezone

from maru.effects.models import OutboxMessage


class ChildOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class ChildResult:
    outcome: ChildOutcome
    return_code: int | None = None


class FairTenantScheduler:
    """Select one eligible tenant after the tenant served most recently."""

    def __init__(self) -> None:
        self._last_served: UUID | None = None

    def select(self, candidates: tuple[UUID, ...]) -> UUID | None:
        ordered = tuple(sorted(set(candidates), key=str))
        if not ordered:
            return None
        if self._last_served not in ordered:
            selected = ordered[0]
        else:
            current_index = ordered.index(self._last_served)
            selected = ordered[(current_index + 1) % len(ordered)]
        self._last_served = selected
        return selected


def eligible_tenant_ids(
    *,
    workload_pool: str,
    now: datetime | None = None,
) -> tuple[UUID, ...]:
    observed_at = now or timezone.now()
    ready = Q(
        status=OutboxMessage.Status.PENDING,
        available_at__lte=observed_at,
        attempt_count__lt=F("max_attempts"),
    )
    expired = Q(
        status=OutboxMessage.Status.PROCESSING,
        lease_expires_at__lte=observed_at,
    )
    return tuple(
        OutboxMessage.objects.filter(
            ready | expired,
            workload_pool=workload_pool,
        )
        .order_by("organization_id")
        .values_list("organization_id", flat=True)
        .distinct()
    )


def run_effect_child(
    *,
    organization_id: UUID,
    workload_pool: str,
    lease_seconds: int,
    execution_timeout_seconds: int,
    hard_timeout_seconds: int,
) -> ChildResult:
    manage_path = Path(settings.BASE_DIR) / "src" / "manage.py"
    command = [
        sys.executable,
        str(manage_path),
        "effects_run_once",
        "--organization",
        str(organization_id),
        "--pool",
        workload_pool,
        "--lease-seconds",
        str(lease_seconds),
        "--execution-timeout-seconds",
        str(execution_timeout_seconds),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 - fixed interpreter and command
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=hard_timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ChildResult(ChildOutcome.TIMED_OUT)
    if completed.returncode != 0:
        return ChildResult(ChildOutcome.FAILED, completed.returncode)
    return ChildResult(ChildOutcome.COMPLETED, completed.returncode)
