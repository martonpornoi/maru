"""Emit tenant-bounded outbox health for monitoring and runbooks."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Count, QuerySet
from django.utils import timezone

from maru.effects.models import OutboxMessage


def _age_seconds(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


class Command(BaseCommand):
    help = "Report safe outbox status for exactly one organization."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--organization",
            type=UUID,
            required=True,
            help="Organization UUID to inspect.",
        )
        parser.add_argument(
            "--pool",
            help="Optional exact workload pool.",
        )
        parser.add_argument(
            "--fail-on-quarantine",
            action="store_true",
            help="Exit non-zero when the selected scope has quarantined work.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        _ = args
        organization_id: UUID = options["organization"]
        pool: str | None = options["pool"]
        messages: QuerySet[OutboxMessage] = OutboxMessage.objects.filter(
            organization_id=organization_id
        )
        if pool:
            messages = messages.filter(workload_pool=pool)

        counts = {
            row["status"]: row["count"]
            for row in messages.values("status")
            .annotate(count=Count("id"))
            .order_by("status")
        }
        now = timezone.now()
        oldest_ready = (
            messages.filter(
                status=OutboxMessage.Status.PENDING,
                available_at__lte=now,
            )
            .order_by("available_at")
            .values_list("available_at", flat=True)
            .first()
        )
        oldest_expired = (
            messages.filter(
                status=OutboxMessage.Status.PROCESSING,
                lease_expires_at__lte=now,
            )
            .order_by("lease_expires_at")
            .values_list("lease_expires_at", flat=True)
            .first()
        )
        result = {
            "organization_id": str(organization_id),
            "workload_pool": pool,
            "counts": counts,
            "oldest_ready_age_seconds": _age_seconds(oldest_ready, now=now),
            "oldest_expired_lease_age_seconds": _age_seconds(
                oldest_expired,
                now=now,
            ),
        }
        self.stdout.write(json.dumps(result, sort_keys=True))
        if options["fail_on_quarantine"] and counts.get(
            OutboxMessage.Status.QUARANTINED,
            0,
        ):
            raise CommandError("Selected outbox scope contains quarantined work.")
