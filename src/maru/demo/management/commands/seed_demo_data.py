"""Create the bounded, synthetic local demonstration dataset."""

import json
import os
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.test.utils import override_settings

from maru.demo.constants import DEMO_ACCOUNT_PASSWORD
from maru.demo.fixture import DemoDataConflictError, seed_demo_data


class Command(BaseCommand):
    """Execute the Django management command."""

    help = (
        "Create an idempotent two-convention synthetic dataset. "
        "Available only with local or test settings."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add arguments.

        Parameters
        ----------
        parser : CommandParser
            The parser that converts untrusted input into canonical domain data.
        """
        parser.add_argument(
            "--password",
            default=DEMO_ACCOUNT_PASSWORD,
            help=(
                "Password assigned to newly created synthetic accounts. "
                "Defaults to the documented local demo password."
            ),
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Replace passwords on every account owned by the demo fixture.",
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
        _ = args
        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        if settings_module not in {"maru.settings.local", "maru.settings.test"}:
            raise CommandError(
                "Synthetic data can be seeded only with Maru local or test settings."
            )

        password = str(options["password"])
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError(
                "The supplied demo password does not satisfy password validation: "
                + " ".join(error.messages)
            ) from error

        try:
            # Archived demo editions install their synthetic closure evidence
            # later in the same atomic fixture. The command is local/test-only,
            # so allow that bounded construction order without weakening normal
            # lifecycle transitions.
            with override_settings(ENFORCE_EDITION_CLOSURE_GATES=False):
                summary = seed_demo_data(
                    password=password,
                    reset_passwords=options["reset_passwords"],
                )
        except DemoDataConflictError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
