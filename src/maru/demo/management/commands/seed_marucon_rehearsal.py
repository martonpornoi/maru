"""Create the bounded, admin-first local Marucon educational rehearsal."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.demo.marucon_rehearsal import (
    MARUCON_SHARED_PASSWORD,
    MaruconRehearsalConflictError,
    seed_marucon_rehearsal,
)
from maru.demo.public_roster import (
    AWOOSTRIA_ROSTER_URL,
    fetch_awoostria_roster,
    load_public_roster_file,
)


class Command(BaseCommand):
    help = (
        "Create the local-only Marucon admin-first educational rehearsal from "
        "an explicitly acknowledged public or local HTML roster."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--roster-file",
            type=Path,
            help=(
                "Read a saved or synthetic roster HTML file instead of making a "
                "network request."
            ),
        )
        parser.add_argument(
            "--roster-url",
            default=AWOOSTRIA_ROSTER_URL,
            help="Public Awoostria volunteer page used by the local rehearsal.",
        )
        parser.add_argument(
            "--accept-public-roster",
            action="store_true",
            help=(
                "Acknowledge that public usernames, departments, descriptions, "
                "and role labels will be copied into the local database. Images "
                "and contact data are never imported."
            ),
        )
        parser.add_argument(
            "--password",
            default=MARUCON_SHARED_PASSWORD,
            help="Shared password assigned to newly created rehearsal accounts.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        _ = args
        settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
        if settings_module not in {"maru.settings.local", "maru.settings.test"}:
            raise CommandError(
                "The Marucon rehearsal can be seeded only with local or test settings."
            )

        password = str(options["password"])
        try:
            validate_password(password)
        except ValidationError as error:
            raise CommandError(
                "The supplied rehearsal password does not satisfy password "
                "validation: " + " ".join(error.messages)
            ) from error

        roster_file = options.get("roster_file")
        try:
            if roster_file is not None:
                roster = load_public_roster_file(roster_file)
                roster_source = str(roster_file)
            else:
                if not options["accept_public_roster"]:
                    raise CommandError(
                        "Pass --accept-public-roster to acknowledge the bounded "
                        "public data import, or use --roster-file."
                    )
                roster = fetch_awoostria_roster(str(options["roster_url"]))
                roster_source = str(options["roster_url"])
            summary = seed_marucon_rehearsal(
                roster=roster,
                password=password,
            )
        except (OSError, UnicodeError, ValueError) as error:
            raise CommandError(
                f"Could not load the rehearsal roster: {error}"
            ) from error
        except MaruconRehearsalConflictError as error:
            raise CommandError(str(error)) from error

        result = summary.as_dict()
        result.update(
            {
                "local_only": True,
                "roster_source": roster_source,
                "shared_password": password,
            }
        )
        self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
