"""Fail closed for the retired public-roster Marucon rehearsal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

RETIRED_COMMAND_MESSAGE = (
    "seed_marucon_rehearsal is retired and cannot import public roster data or "
    "create convention authority. Use `python src/manage.py seed_demo_data` for "
    "the synthetic rehearsal, then use Page 8, Representation & access, for the "
    "explicit Executive Board handoff."
)

_RETIRED_ROSTER_URL = "https://awoostria.at/about-us/our-volunteers"


class Command(BaseCommand):
    """Execute the Django management command."""

    help = "Retired: use seed_demo_data and Page 8 instead."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument(
            "--roster-file",
            type=Path,
            help="Retired compatibility option; no file is read.",
        )
        parser.add_argument(
            "--roster-url",
            default=_RETIRED_ROSTER_URL,
            help="Retired compatibility option; no network request is made.",
        )
        parser.add_argument(
            "--accept-public-roster",
            action="store_true",
            help="Retired compatibility option; public roster import is disabled.",
        )
        parser.add_argument(
            "--password",
            help="Retired compatibility option; no password is validated or stored.",
        )

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
        del args, options
        raise CommandError(RETIRED_COMMAND_MESSAGE)
