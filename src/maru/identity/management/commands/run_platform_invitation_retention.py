"""Run one bounded, audited invitation-retention scheduler batch."""

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from maru.identity.invitation_retention import (
    MAX_RETENTION_BATCH,
    InvitationRetentionConfigurationError,
    InvitationRetentionUnavailableError,
    run_platform_invitation_retention,
)


class Command(BaseCommand):
    """Execute the Django management command."""

    help = (
        "Anonymize one bounded batch of due abandoned invitation identities "
        "under the exact activated deployment policy."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument(
            "--limit",
            type=int,
            default=MAX_RETENTION_BATCH,
            help=f"Maximum due invitations to inspect (1-{MAX_RETENTION_BATCH}).",
        )

    def handle(self, *args: object, **options: object) -> None:
        """Execute the management command.

        Parameters
        ----------
        *args : object
            Positional arguments forwarded to the framework implementation.
        **options : object
            Management-command options supplied by Django.

        Raises
        ------
        CommandError
            If the command cannot complete safely with the supplied state.
        """
        del args
        limit = options.get("limit")
        if not isinstance(limit, int):
            raise CommandError("The retention batch limit must be an integer.")
        try:
            result = run_platform_invitation_retention(
                limit=limit,
                source_channel="scheduler",
            )
        except (
            DatabaseError,
            InvitationRetentionConfigurationError,
            InvitationRetentionUnavailableError,
            ValidationError,
            ValueError,
        ) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                "Invitation retention batch completed: "
                f"disposed={result.disposed_count} "
                f"held={result.held_count} "
                f"blocked={result.blocked_count} "
                f"remaining={result.remaining_count}."
            )
        )
