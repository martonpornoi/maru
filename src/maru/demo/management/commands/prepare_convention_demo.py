"""Prepare only the disposable, local convention preview owned by its launcher."""

import json
import os
import traceback
from datetime import date
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.demo.convention_fixture import bootstrap_demo_accounts, seed_convention_demo


class Command(BaseCommand):
    """Provide bounded setup phases without accepting an arbitrary target or actor."""

    help = "Internal local-preview setup; start it through scripts/try_maru.py."

    def add_arguments(self, parser: CommandParser) -> None:
        """Select the account bootstrap or runtime content phase.

        Parameters
        ----------
        parser : CommandParser
            Django's command-line parser.
        """
        parser.add_argument("phase", choices=("accounts", "content"))

    def handle(self, *_args: Any, **options: Any) -> None:
        """Execute one phase and emit only non-secret initial state.

        Parameters
        ----------
        *_args : Any
            Unused positional arguments.
        **options : Any
            Parsed phase selection.

        Raises
        ------
        CommandError
            If preparation fails; credentials and private exception text are withheld.
        """
        try:
            if options["phase"] == "accounts":
                bootstrap_demo_accounts(json.loads(os.environ["MARU_DEMO_PASSWORDS"]))
                result = {"accounts_prepared": True}
            else:
                result = seed_convention_demo(
                    date.fromisoformat(os.environ["MARU_DEMO_ANCHOR"])
                )
        except Exception as error:  # noqa: BLE001 -- credentials must not reach command output
            frame = traceback.extract_tb(error.__traceback__)[-1]
            location = f"{Path(frame.filename).name}:{frame.lineno}"
            raise CommandError(
                f"Convention demo preparation failed "
                f"({type(error).__name__}; {location}). "
                "No ready preview was exposed. Keep the evidence and start a "
                "fresh preview."
            ) from None
        self.stdout.write(json.dumps(result, sort_keys=True))
