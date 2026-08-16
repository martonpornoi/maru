"""Report Logistics production readiness without exposing domain data."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.logistics.readiness import build_logistics_readiness_report


class Command(BaseCommand):
    help = (
        "Inspect the installed Logistics database integrity and least-privilege "
        "contract. The report contains only named gate states."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Print blocked production gates without returning an error.",
        )

    def handle(self, *args: object, **options: object) -> None:
        del args
        report = build_logistics_readiness_report()
        self.stdout.write(json.dumps(report, sort_keys=True, separators=(",", ":")))
        if report["status"] != "ready" and not options["no_fail"]:
            raise CommandError(
                "Logistics production readiness is blocked; inspect the "
                "identifier-free report."
            )
