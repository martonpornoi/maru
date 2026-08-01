"""Report ADR 0044 authority-lineage blockers without subject disclosure."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.authorization.provenance_readiness import (
    build_authority_provenance_readiness_report,
)


class Command(BaseCommand):
    help = (
        "Inspect exact authority provenance and emit privacy-minimized count-only JSON."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Return success with blockers present; JSON status is unchanged.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        report = build_authority_provenance_readiness_report()
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] == "blocked" and not options["no_fail"]:
            raise CommandError(
                "Authority provenance blockers detected; inspect the count-only "
                "JSON report."
            )
