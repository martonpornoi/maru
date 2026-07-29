"""Seal pending audit events and verify the complete digest chain."""

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from maru.audit.models import AuditEvent, AuditIntegrityBatch
from maru.audit.services import seal_pending_audit_events, verify_audit_integrity


class Command(BaseCommand):
    help = "Optionally seal pending audit events, then verify all integrity batches."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--seal",
            action="store_true",
            help="Seal one bounded batch of pending events before verification.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=1_000,
            help="Maximum events in a newly sealed batch (1-10000).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        _ = args
        sealed = None
        if options["seal"]:
            sealed = seal_pending_audit_events(limit=options["limit"])

        valid = verify_audit_integrity()
        result = {
            "valid": valid,
            "sealed_batch": str(sealed.id) if sealed else None,
            "batch_count": AuditIntegrityBatch.objects.count(),
            "pending_event_count": AuditEvent.objects.filter(
                integrity_batch__isnull=True
            ).count(),
        }
        self.stdout.write(json.dumps(result, sort_keys=True))
        if not valid:
            raise CommandError("Audit integrity verification failed.")
