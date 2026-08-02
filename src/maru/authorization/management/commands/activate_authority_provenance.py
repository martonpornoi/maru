"""Irreversibly activate ADR 0044 exact authority-lineage enforcement."""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError

from maru.authorization.activation import (
    AuthorityProvenanceActivationBlockedError,
    AuthorityProvenanceActivationEnvironmentError,
    AuthorityProvenanceActivationError,
    AuthorityProvenanceActivationTransactionError,
    AuthorityProvenanceActivationVerificationError,
    ProcessesStoppedAcknowledgementRequiredError,
    activate_authority_provenance,
)
from maru.identity.models import Account

logger = logging.getLogger(__name__)


def _failure_code(error: Exception) -> str:
    """Map private failures to a bounded operator-safe diagnostic category."""

    if isinstance(error, Account.DoesNotExist):
        code = "actor_unavailable"
    elif isinstance(error, ProcessesStoppedAcknowledgementRequiredError):
        code = "process_acknowledgement_required"
    elif isinstance(error, AuthorityProvenanceActivationBlockedError):
        code = "readiness_blocked"
    elif isinstance(error, AuthorityProvenanceActivationVerificationError):
        code = "postcondition_invalid"
    elif isinstance(error, AuthorityProvenanceActivationEnvironmentError):
        code = "environment_invalid"
    elif isinstance(error, AuthorityProvenanceActivationTransactionError):
        code = "transaction_boundary_invalid"
    elif isinstance(error, AuthorityProvenanceActivationError):
        code = "activation_request_invalid"
    elif isinstance(error, DatabaseError):
        cause = error.__cause__
        sqlstate = getattr(cause, "sqlstate", None)
        if sqlstate == "55P03":
            code = "writer_drain_timeout"
        elif sqlstate == "40001":
            code = "concurrent_writer_conflict"
        else:
            code = "database_unavailable"
    else:
        code = "internal_error"
    return code


class Command(BaseCommand):
    help = (
        "Activate exact authority lineage once, during an acknowledged "
        "stopped-process maintenance window."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--actor",
            required=True,
            help="Email address of the active platform administrator performing it.",
        )
        parser.add_argument(
            "--reason",
            required=True,
            help="Operational reason retained in the restricted audit boundary.",
        )
        parser.add_argument(
            "--acknowledge-processes-stopped",
            action="store_true",
            help=(
                "Confirm that every old reader and every web, worker, scheduler, "
                "integration, and operator writer is stopped."
            ),
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        correlation_id = uuid4()
        try:
            actor = Account.objects.get(email__iexact=str(options["actor"]).strip())
            result = activate_authority_provenance(
                actor=actor,
                reason=str(options["reason"]),
                correlation_id=correlation_id,
                acknowledge_processes_stopped=bool(
                    options["acknowledge_processes_stopped"]
                ),
                source_channel="management_command",
            )
        except Exception as error:  # noqa: BLE001 - sanitize every failure
            failure_code = _failure_code(error)
            logger.error(  # noqa: TRY400 - tracebacks may expose private values
                "authority_provenance_activation_failed "
                "code=%s correlation_id=%s exception_type=%s",
                failure_code,
                correlation_id,
                type(error).__name__,
            )
            raise CommandError(
                "Authority provenance activation failed "
                f"(code={failure_code}; correlation_id={correlation_id}); "
                "no subject or authority details are disclosed."
            ) from None

        self.stdout.write(
            json.dumps(
                {
                    "status": "activated" if result.activated else "already_active",
                    "contract_version": result.contract_version,
                    "policy_version": result.policy_version,
                    "correlation_id": str(result.correlation_id),
                    "blocker_total": result.blocker_total,
                    "production_status": result.production_status,
                },
                indent=2,
                sort_keys=True,
            )
        )
