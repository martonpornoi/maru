"""Report Page 10 invitation readiness without exposing identity data."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.identity.invitation_readiness import (
    build_platform_invitation_readiness_report,
)


class Command(BaseCommand):
    help = (
        "Inspect Page 10's additive database contract and the still-separate "
        "production cutover gates. The report contains no account data."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--no-fail",
            action="store_true",
            help="Print blocked production gates without returning an error.",
        )

    def handle(self, *args: object, **options: object) -> None:
        del args
        report = build_platform_invitation_readiness_report()
        self.stdout.write(json.dumps(report, sort_keys=True, separators=(",", ":")))
        if report["production_status"] != "ready" and not options["no_fail"]:
            raise CommandError(
                "Platform invitation production readiness is blocked; inspect "
                "the value-minimized report."
            )
