"""Emit tenant-bounded outbox health for monitoring and runbooks."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Count, QuerySet
from django.utils import timezone

from maru.effects.models import OutboxMessage
from maru.effects.services import (
    MAX_EFFECT_ERROR_CODE_LENGTH,
    SAFE_EFFECT_CODE_PATTERN,
)

MAX_STATUS_ERROR_CODES = 64


def _age_seconds(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - value).total_seconds()))


def safe_status_error_code(raw_code: object) -> str:
    """Return a value-safe code for tenant-bounded status output.

    Parameters
    ----------
    raw_code : object
        A persisted error-code candidate from the selected outbox scope.

    Returns
    -------
    str
        The validated code or a stable redaction marker.
    """
    if (
        isinstance(raw_code, str)
        and len(raw_code) <= MAX_EFFECT_ERROR_CODE_LENGTH
        and SAFE_EFFECT_CODE_PATTERN.fullmatch(raw_code)
    ):
        return raw_code
    return "invalid_effect_error_code"


def _quarantine_error_counts(
    messages: QuerySet[OutboxMessage],
) -> tuple[dict[str, int], bool]:
    rows = list(
        messages.filter(status=OutboxMessage.Status.QUARANTINED)
        .values("last_error_code")
        .annotate(count=Count("id"))
        .order_by("last_error_code")[: MAX_STATUS_ERROR_CODES + 1]
    )
    counts: dict[str, int] = {}
    for row in rows[:MAX_STATUS_ERROR_CODES]:
        code = safe_status_error_code(row["last_error_code"])
        counts[code] = counts.get(code, 0) + row["count"]
    return counts, len(rows) > MAX_STATUS_ERROR_CODES


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Report safe outbox status for exactly one organization."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
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
        """Execute the management command.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **options : Any
            Management-command options supplied by Django.

        Raises
        ------
        CommandError
            If the command cannot complete safely with the supplied state.
        """
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
        quarantine_error_codes, quarantine_error_codes_truncated = (
            _quarantine_error_counts(messages)
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
            "quarantine_error_codes": quarantine_error_codes,
            "quarantine_error_codes_truncated": quarantine_error_codes_truncated,
        }
        self.stdout.write(json.dumps(result, sort_keys=True))
        if options["fail_on_quarantine"] and counts.get(
            OutboxMessage.Status.QUARANTINED,
            0,
        ):
            raise CommandError("Selected outbox scope contains quarantined work.")
