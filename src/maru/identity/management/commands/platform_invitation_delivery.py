"""Deliver durable platform-account invitations."""

from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection

from maru.identity.invitation_crypto import InvitationCryptoError
from maru.identity.invitation_delivery import (
    MAX_DELIVERY_BATCH,
    deliver_pending_platform_identity_invitations,
    platform_identity_delivery_backlog_snapshot,
)
from maru.identity.invitation_key_config import (
    active_invitation_encryption_key,
    worker_invitation_private_keyring,
)
from maru.identity.models import (
    PlatformIdentityDelivery,
)


class Command(BaseCommand):
    """Execute the Django management command."""

    help = (
        "Deliver durable single-use platform-account invitation messages. Run "
        "this command only in an identity worker with the private-key ring "
        "configured. Schedule expire_platform_account_invitations separately."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument("--delivery-limit", type=int, default=100)

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
        delivery_limit = options["delivery_limit"]
        if (
            type(delivery_limit) is not int
            or not 1 <= delivery_limit <= MAX_DELIVERY_BATCH
        ):
            raise CommandError("Delivery limit must be between 1 and 1000.")
        try:
            private_keyring = worker_invitation_private_keyring()
            active_key = active_invitation_encryption_key()
        except InvitationCryptoError:
            raise CommandError(
                "Invitation worker key configuration is unavailable."
            ) from None
        if not private_keyring.matches(active_key):
            raise CommandError(
                "Invitation worker key configuration does not match the active key."
            )
        if (
            PlatformIdentityDelivery.objects.filter(
                payload_destroyed_at__isnull=True,
            )
            .exclude(encryption_key_id__in=private_keyring.key_ids)
            .exists()
        ):
            raise CommandError(
                "Invitation worker key coverage is incomplete for live deliveries."
            )

        attempted, pending = deliver_pending_platform_identity_invitations(
            limit=delivery_limit,
            private_keyring=private_keyring,
        )
        backlog = platform_identity_delivery_backlog_snapshot()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH evidence AS MATERIALIZED (
                    SELECT clock_timestamp() AS recorded_at
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
                    'delivery', 'delivery-v1', evidence.recorded_at,
                    %s, %s, true, '', 0, 0, 0, NULL, NULL
                  FROM evidence
                """,
                [uuid4(), attempted, backlog.eligible_count],
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Platform invitation delivery processed: "
                f"{attempted} delivery attempts completed, "
                f"{pending} selected deliveries remain pending."
            )
        )
