"""Supervise hard-bounded child workers with fair tenant rotation."""

import logging
import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import close_old_connections

from maru.effects.supervisor import (
    ChildOutcome,
    FairTenantScheduler,
    eligible_tenant_ids,
    run_effect_child,
)

logger = logging.getLogger(__name__)
MAX_LEASE_SECONDS = 900


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Run the supervised, tenant-fair effect worker."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument("--pool", default="default")
        parser.add_argument("--lease-seconds", type=int, default=60)
        parser.add_argument("--execution-timeout-seconds", type=int, default=30)
        parser.add_argument("--hard-timeout-seconds", type=int, default=40)
        parser.add_argument("--idle-seconds", type=float, default=1.0)
        parser.add_argument("--max-cycles", type=int)
        parser.add_argument("--stop-when-idle", action="store_true")

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
        del args
        lease_seconds: int = options["lease_seconds"]
        execution_timeout_seconds: int = options["execution_timeout_seconds"]
        hard_timeout_seconds: int = options["hard_timeout_seconds"]
        idle_seconds: float = options["idle_seconds"]
        max_cycles: int | None = options["max_cycles"]
        workload_pool: str = options["pool"]
        if lease_seconds < 1 or lease_seconds > MAX_LEASE_SECONDS:
            raise CommandError("Lease must be between 1 and 900 seconds.")
        if execution_timeout_seconds < 1 or execution_timeout_seconds > lease_seconds:
            raise CommandError(
                "Execution timeout must be positive and no longer than the lease."
            )
        if hard_timeout_seconds <= execution_timeout_seconds:
            raise CommandError(
                "Hard timeout must exceed the handler execution timeout."
            )
        if idle_seconds < 0:
            raise CommandError("Idle interval cannot be negative.")
        if max_cycles is not None and max_cycles < 0:
            raise CommandError("Maximum cycles cannot be negative.")

        scheduler = FairTenantScheduler()
        cycles = 0
        while max_cycles is None or cycles < max_cycles:
            close_old_connections()
            organization_id = scheduler.select(
                eligible_tenant_ids(workload_pool=workload_pool)
            )
            if organization_id is None:
                if options["stop_when_idle"]:
                    break
                time.sleep(idle_seconds)
                cycles += 1
                continue

            result = run_effect_child(
                organization_id=organization_id,
                workload_pool=workload_pool,
                lease_seconds=lease_seconds,
                execution_timeout_seconds=execution_timeout_seconds,
                hard_timeout_seconds=hard_timeout_seconds,
            )
            level = (
                logging.INFO
                if result.outcome is ChildOutcome.COMPLETED
                else logging.ERROR
            )
            logger.log(
                level,
                "effect worker child completed",
                extra={
                    "service": "effects-worker",
                    "organization_id": str(organization_id),
                    "workload_pool": workload_pool,
                    "result": result.outcome,
                    "safe_error_code": (
                        "handler_hard_timeout"
                        if result.outcome is ChildOutcome.TIMED_OUT
                        else (
                            "worker_child_failed"
                            if result.outcome is ChildOutcome.FAILED
                            else ""
                        )
                    ),
                },
            )
            cycles += 1
