"""Retry durable verification and recovery email delivery."""

from typing import cast

from django.core.management.base import BaseCommand, CommandParser

from maru.identity.services import deliver_pending_identity_challenges

MAX_DELIVERY_BATCH = 10_000


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Retry pending, unexpired identity verification and recovery messages."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args: object, **options: object) -> None:
        """Execute the management command.

        Parameters
        ----------
        *args : object
            Positional arguments forwarded to the framework implementation.
        **options : object
            Management-command options supplied by Django.
        """
        del args
        limit = cast("int", options["limit"])
        if limit < 1 or limit > MAX_DELIVERY_BATCH:
            self.stderr.write("Limit must be between 1 and 10000.")
            return
        attempted, pending = deliver_pending_identity_challenges(limit=limit)
        self.stdout.write(
            self.style.SUCCESS(
                f"Identity delivery attempted {attempted}; {pending} remain pending."
            )
        )
