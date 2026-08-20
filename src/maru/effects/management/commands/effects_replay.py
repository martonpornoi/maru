"""Replay one quarantined effect through the authorized application command."""

import json
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.authorization.services import AuthorizationDenied
from maru.effects.commands import replay_effect
from maru.identity.models import Account


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Replay one tenant-owned quarantined effect with reason and audit."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument("--organization", required=True, type=UUID)
        parser.add_argument("--message", required=True, type=UUID)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--additional-attempts", type=int, default=3)

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
        try:
            actor = Account.objects.get(email__iexact=options["actor"].strip())
        except Account.DoesNotExist as error:
            raise CommandError("The replay actor is unavailable.") from error

        correlation_id = uuid4()
        try:
            message = replay_effect(
                actor=actor,
                organization_id=options["organization"],
                message_id=options["message"],
                additional_attempts=options["additional_attempts"],
                reason=options["reason"],
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="management-command",
            )
        except (AuthorizationDenied, ValidationError) as error:
            raise CommandError(str(error)) from error

        self.stdout.write(
            json.dumps(
                {
                    "correlation_id": str(correlation_id),
                    "message_id": str(message.id),
                    "organization_id": str(message.organization_id),
                    "replay_count": message.replay_count,
                    "status": message.status,
                },
                sort_keys=True,
            )
        )
