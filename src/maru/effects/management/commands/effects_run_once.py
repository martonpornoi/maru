"""Claim and execute at most one effect for one tenant and workload pool."""

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser

from maru.effects.handlers import built_in_handler_registry
from maru.effects.services import claim_next_effect
from maru.effects.worker import run_claimed_effect


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Run at most one tenant-bounded effect."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument("--organization", required=True, type=UUID)
        parser.add_argument("--pool", default="default")
        parser.add_argument("--lease-seconds", type=int, default=60)
        parser.add_argument("--execution-timeout-seconds", type=int, default=30)

    def handle(self, *args: Any, **options: Any) -> None:
        """Execute the management command.

        Parameters
        ----------
        *args : Any
            Positional arguments forwarded to the framework implementation.
        **options : Any
            Management-command options supplied by Django.
        """
        del args
        organization_id: UUID = options["organization"]
        workload_pool: str = options["pool"]
        claim = claim_next_effect(
            organization_id=organization_id,
            workload_pool=workload_pool,
            lease_duration=timedelta(seconds=options["lease_seconds"]),
        )
        if claim is None:
            result = {"result": "idle"}
        else:
            run_result = run_claimed_effect(
                claim,
                handlers=built_in_handler_registry(),
                execution_timeout=timedelta(
                    seconds=options["execution_timeout_seconds"]
                ),
            )
            result = {
                "result": run_result.outcome,
                "error_code": run_result.error_code,
            }
        self.stdout.write(json.dumps(result, sort_keys=True))
