"""Expire account invitations without requiring delivery decryption keys."""

from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection

from maru.identity.invitation_commands import expire_platform_account_invitations

MAX_EXPIRY_BATCH = 1_000


class Command(BaseCommand):
    """Execute the Django management command."""

    help = (
        "Expire elapsed platform-account invitations and destroy their encrypted "
        "delivery payloads. This scheduler command does not need private keys."
    )

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

        Raises
        ------
        CommandError
            If the command cannot complete safely with the supplied state.
        """
        del args
        limit = options["limit"]
        if type(limit) is not int or not 1 <= limit <= MAX_EXPIRY_BATCH:
            raise CommandError("Expiry limit must be between 1 and 1000.")
        expired = expire_platform_account_invitations(
            correlation_id=uuid4(),
            limit=limit,
            source_channel="identity_expiry_scheduler",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH evidence AS MATERIALIZED (
                    SELECT clock_timestamp() AS recorded_at
                ), backlog AS MATERIALIZED (
                    SELECT count(*) AS remaining_count
                      FROM identity_platformaccountinvitation AS invitation
                      CROSS JOIN evidence
                     WHERE invitation.status = 'pending'
                       AND invitation.expires_at <= evidence.recorded_at
                )
                INSERT INTO identity_platforminvitationschedulerrun (
                    id, created_at, updated_at, kind, generation, ran_at,
                    processed_count, remaining_count,
                    private_key_coverage_complete, policy_digest,
                    inspected_count, blocked_count, held_count,
                    retention_cursor_transition_at,
                    retention_cursor_invitation_id
                )
                SELECT %s, evidence.recorded_at, evidence.recorded_at,
                    'expiry', 'expiry-v1', evidence.recorded_at,
                    %s, backlog.remaining_count, false, '', 0, 0, 0, NULL, NULL
                  FROM evidence CROSS JOIN backlog
                """,
                [uuid4(), expired],
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Platform invitation expiry processed: {expired} expired."
            )
        )
