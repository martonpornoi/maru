"""Inspect bounded, tenant-scoped effect replay rationale."""

import json
from typing import Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.authorization.services import AuthorizationDenied
from maru.effects.commands import inspect_effect_replay_history
from maru.identity.models import Account


class Command(BaseCommand):
    """Execute the tenant-bounded replay-history query."""

    help = "Inspect retained rationale for one tenant-owned outbox message."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add tenant, message, and bounded result arguments.

        Parameters
        ----------
        parser : CommandParser
            Parser receiving the command's explicit scope and limit options.
        """
        parser.add_argument("--organization", required=True, type=UUID)
        parser.add_argument("--message", required=True, type=UUID)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args: Any, **options: Any) -> None:
        """Write deterministic JSON without event payload disclosure.

        Parameters
        ----------
        *args : Any
            Positional framework arguments.
        **options : Any
            Validated management-command options.

        Raises
        ------
        CommandError
            If the requested history bound is invalid.
        """
        del args
        organization_id = options["organization"]
        message_id = options["message"]
        try:
            actor = Account.objects.get(email__iexact=options["actor"].strip())
        except Account.DoesNotExist as error:
            raise CommandError("The replay-history actor is unavailable.") from error
        correlation_id = uuid4()
        try:
            receipts = inspect_effect_replay_history(
                actor=actor,
                organization_id=organization_id,
                message_id=message_id,
                limit=options["limit"],
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
                    "message_id": str(message_id),
                    "organization_id": str(organization_id),
                    "replays": [
                        {
                            "actor_id": str(receipt.actor_id),
                            "additional_attempts": receipt.additional_attempts,
                            "correlation_id": str(receipt.correlation_id),
                            "created_at": receipt.created_at.isoformat(),
                            "new_max_attempts": receipt.new_max_attempts,
                            "previous_max_attempts": receipt.previous_max_attempts,
                            "reason": receipt.reason,
                            "replay_count": receipt.replay_count,
                        }
                        for receipt in receipts
                    ],
                },
                sort_keys=True,
            )
        )
