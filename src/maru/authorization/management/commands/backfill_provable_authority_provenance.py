"""Backfill only authority provenance that ADR 0044 permits proving."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.authorization.provenance_backfill import (
    WritersStoppedAcknowledgementRequiredError,
    reconcile_provable_authority_provenance,
)


class Command(BaseCommand):
    """Execute the Django management command."""

    help = (
        "Dry-run the provable-only authority-provenance reconciliation, or append "
        "it atomically during an acknowledged stopped-writer window."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Append the exact provable ledger rows instead of planning only.",
        )
        parser.add_argument(
            "--acknowledge-writers-stopped",
            action="store_true",
            help=(
                "Confirm that every authority and representation writer is stopped "
                "for this maintenance transaction. Required with --apply."
            ),
        )
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Return success with blockers present; JSON status is unchanged.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        """Execute the management command.

        Parameters
        ----------
        *_args : Any
            Positional arguments forwarded to the framework implementation.
        **options : Any
            Management-command options supplied by Django.

        Raises
        ------
        CommandError
            If the command cannot complete safely with the supplied state.
        """
        try:
            report = reconcile_provable_authority_provenance(
                apply=bool(options["apply"]),
                acknowledge_writers_stopped=bool(
                    options["acknowledge_writers_stopped"]
                ),
            )
        except WritersStoppedAcknowledgementRequiredError:
            raise CommandError(
                "Refusing mutation without --acknowledge-writers-stopped."
            ) from None
        except Exception:  # noqa: BLE001 - sanitize every private failure context
            # Never echo an exception whose database context may contain an
            # identity, authority target, capability, or tenant identifier.
            raise CommandError(
                "Authority provenance reconciliation failed; the transaction was "
                "rolled back."
            ) from None

        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] == "blocked" and not options["no_fail"]:
            raise CommandError(
                "Authority provenance reconciliation is blocked; inspect the "
                "count-only JSON report."
            )
