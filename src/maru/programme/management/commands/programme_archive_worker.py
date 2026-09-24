"""Run bounded, supervised Programme archive work without provisioning a service."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.programme.archive_worker import supervise_archive_queue_once

MAX_CYCLES = 4


class Command(BaseCommand):
    """Execute an explicitly bounded archive worker pass."""

    help = "Process Programme archives with a single supervised child and hard timeout."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the bounded pass count.

        Parameters
        ----------
        parser : CommandParser
            Django's management argument parser.
        """
        parser.add_argument("--max-cycles", type=int, default=1)

    def handle(self, *args: Any, **options: Any) -> None:
        """Run silent children and print only safe closed results.

        Parameters
        ----------
        *args : Any
            Unused positional framework arguments.
        **options : Any
            Parsed finite cycle count and Django standard options.

        Raises
        ------
        CommandError
            If the count is invalid or a child failed/timed out.
        """
        del args
        cycles = options["max_cycles"]
        if type(cycles) is not int or not 1 <= cycles <= MAX_CYCLES:
            raise CommandError("Archive cycles must be between 1 and 4.")
        for _ in range(cycles):
            result = supervise_archive_queue_once()
            if result in {"failed", "timed_out"}:
                raise CommandError(f"Programme archive worker: {result}.")
            self.stdout.write(f"Programme archive worker: {result}.")
            if result in {"idle", "busy"}:
                break
