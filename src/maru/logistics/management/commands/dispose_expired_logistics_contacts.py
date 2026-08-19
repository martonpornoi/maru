"""Dispose one explicit, bounded batch of expired Logistics contact values."""

from argparse import ArgumentTypeError
from typing import cast
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from maru.logistics.retention import (
    MAX_RETENTION_DISPOSALS,
    dispose_expired_restricted_addresses,
)


def _canonical_uuid(value: str) -> UUID:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ArgumentTypeError(
            "Enter a canonical lower-case hyphenated UUID."
        ) from error
    if str(parsed) != value:
        raise ArgumentTypeError("Enter a canonical lower-case hyphenated UUID.")
    return parsed


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Redact one bounded batch of expired purpose-bound Logistics contacts."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument("--organization-id", required=True, type=_canonical_uuid)
        scope = parser.add_mutually_exclusive_group(required=True)
        scope.add_argument("--edition-id", type=_canonical_uuid)
        scope.add_argument(
            "--global-scope",
            action="store_true",
            help="Dispose organization-global records only.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help=f"Maximum records to inspect (1-{MAX_RETENTION_DISPOSALS}).",
        )
        parser.add_argument(
            "--correlation-id",
            type=_canonical_uuid,
            help="Optional stable correlation UUID for this scheduler invocation.",
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
        organization_id = options.get("organization_id")
        edition_id = options.get("edition_id")
        limit = options.get("limit")
        correlation_id = cast("UUID", options.get("correlation_id") or uuid4())
        if not isinstance(organization_id, UUID):
            raise CommandError("An organization UUID is required.")
        if edition_id is not None and not isinstance(edition_id, UUID):
            raise CommandError("Use a canonical edition UUID.")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise CommandError("The retention batch limit must be an integer.")
        try:
            disposed_ids = dispose_expired_restricted_addresses(
                organization_id=organization_id,
                edition_id=edition_id,
                correlation_id=correlation_id,
                limit=limit,
            )
        except (DatabaseError, ValidationError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Logistics contact retention completed: disposed={len(disposed_ids)}."
            )
        )
