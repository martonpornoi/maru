"""Create the bounded, synthetic local demonstration dataset."""

import json
import os
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.demo.constants import DEMO_ACCOUNT_PASSWORD
from maru.demo.fixture import DemoDataConflictError, seed_demo_data


class Command(BaseCommand):
    help = (
        "Create an idempotent two-convention synthetic dataset. "
        "Available only with local or test settings."
    )

    def add_arguments(self, parser: CommandParser) -> None:
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
            summary = seed_demo_data(
                password=password,
                reset_passwords=options["reset_passwords"],
            )
        except DemoDataConflictError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
