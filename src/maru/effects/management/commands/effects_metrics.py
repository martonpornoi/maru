"""Render tenant-bounded outbox metrics in Prometheus text format."""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser

from maru.effects.operations import outbox_health_snapshot, render_prometheus


class Command(BaseCommand):
    help = "Render safe outbox metrics for one tenant and workload pool."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--organization", required=True, type=UUID)
        parser.add_argument("--pool", default="default")

    def handle(self, *args: Any, **options: Any) -> None:
        del args
        snapshot = outbox_health_snapshot(
            organization_id=options["organization"],
            workload_pool=options["pool"],
        )
        self.stdout.write(render_prometheus(snapshot), ending="")
