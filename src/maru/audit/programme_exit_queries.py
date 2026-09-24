"""Minimized generation receipts, never a general security-history export."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import transaction

from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import DEFAULT_PROGRAMME_AUTHORIZER
from maru.programme.exit_archive_protocol import ProgrammeArchiveSection
from maru.workforce.programme_references import lock_programme_staffing_scope

from .models import AuditEvent
from .services import AuditRecord, append_audit

if TYPE_CHECKING:
    from maru.programme.authorization import ProgrammeAuthorizer

MAX_EXIT_RECEIPTS: Final = 50_000
MAX_EXIT_JSON_BYTES: Final = 16_777_216
FIELDS: Final = ("id", "occurred_at", "capability_code", "operation", "outcome")
GENERATION_OPERATIONS: Final = frozenset(
    {
        "applications.programme.query.exit_owner",
        "authorization.programme_exit.read",
        "events.query.programme_exit",
        "programme.query.exit_owner",
        "scheduling.query.exit_owner",
        "venues.query.timetable_spaces",
        "workforce.programme_binding.exit_owner",
    }
)
EXCLUSIONS: Final = (
    "other-principals",
    "other-correlations",
    "source-security-history",
    "target-identities",
    "reason-and-metadata",
    "integrity-batches",
)


class ProgrammeExitAuditUnavailableError(RuntimeError):
    """Withhold absent, malformed or overbudget receipts without private details."""

    def __init__(self) -> None:
        super().__init__("programme_exit_audit_unavailable")


def _record(row: dict[str, object]) -> dict[str, object]:
    identifier, occurred = row["id"], row["occurred_at"]
    if (
        type(identifier) is not UUID
        or not identifier.int
        or type(occurred) is not datetime
        or occurred.utcoffset() is None
        or row["outcome"] != "allow"
        or any(type(row[key]) is not str for key in FIELDS[2:])
    ):
        raise ProgrammeExitAuditUnavailableError
    return {
        "id": str(identifier),
        "occurred_at": occurred.astimezone(UTC).isoformat(),
        "capability_code": row["capability_code"],
        "operation": row["operation"],
        "outcome": "allow",
    }


def _object(properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _section(rows: tuple[dict[str, object], ...]) -> ProgrammeArchiveSection:
    if not rows or len(rows) > MAX_EXIT_RECEIPTS:
        raise ProgrammeExitAuditUnavailableError
    records = [_record(row) for row in rows]
    if len({row["id"] for row in records}) != len(records):
        raise ProgrammeExitAuditUnavailableError
    if {row["operation"] for row in records} != GENERATION_OPERATIONS:
        raise ProgrammeExitAuditUnavailableError
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_object(
            {
                "scope": {"const": "generation-read-receipts@1"},
                "purpose_exclusions": {"const": list(EXCLUSIONS)},
                "receipts": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_EXIT_RECEIPTS,
                    "items": _object(
                        {
                            "id": {"type": "string", "format": "uuid"},
                            "occurred_at": {"type": "string", "format": "date-time"},
                            "capability_code": {"type": "string"},
                            "operation": {"type": "string"},
                            "outcome": {"const": "allow"},
                        }
                    ),
                },
            }
        ),
    }
    try:
        data = json.dumps(
            {
                "scope": "generation-read-receipts@1",
                "purpose_exclusions": EXCLUSIONS,
                "receipts": records,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        schema_bytes = json.dumps(
            schema, sort_keys=True, separators=(",", ":")
        ).encode()
    except (ValueError, TypeError, UnicodeError):
        raise ProgrammeExitAuditUnavailableError from None
    if max(len(data), len(schema_bytes)) > MAX_EXIT_JSON_BYTES:
        raise ProgrammeExitAuditUnavailableError
    return ProgrammeArchiveSection(
        "audit", "audit.programme-exit@1", data, schema_bytes
    )


def load_programme_exit_audit(  # noqa: DOC503 -- nested admission raises PermissionDenied.
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeArchiveSection:
    """Collect this generation's own successful receipts under real security policy.

    Parameters
    ----------
    actor_id : UUID
        Actual requester, also the only principal whose receipts can be included.
    organization_id : UUID
        Exact expected tenant.
    edition_id : UUID
        Exact source edition, checked independently before private reads.
    correlation_id : UUID
        Fresh server-selected generation trace, never a browser-selected filter.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional bulk purpose, never a replacement for security-read policy.

    Returns
    -------
    ProgrammeArchiveSection
        Minimized selected generation receipts, not the complete security log.

    Raises
    ------
    ProgrammeExitAuditUnavailableError
        If attribution, bounded source projection or serialization is unavailable.
    PermissionDenied
        If independent source security-read fields are not currently allowed.

    Notes
    -----
    Call after all owner reads, under the composer's full canonical lock closure.
    The final audit append is retained separately, avoiding recursive self-inclusion.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (
            actor_id,
            organization_id,
            edition_id,
            correlation_id,
        )
    ):
        raise ProgrammeExitAuditUnavailableError

    def admit() -> None:
        authorize_programme_archive_scope(
            actor_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            requested_fields=frozenset({"source_lineage"}),
            authorizer=programme_authorizer,
        )
        decision = decide_verified_principal_exact_edition(
            principal_id=actor_id,
            organization_id=organization_id,
            edition_id=edition_id,
            capability_code="audit.view_security",
            requested_fields=frozenset(FIELDS),
        )
        if (
            not isinstance(decision, PolicyDecision)
            or not decision.allowed
            or not (frozenset(FIELDS) <= decision.fields)
        ):
            raise PermissionDenied("Programme exit audit unavailable.")

    admit()
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=organization_id, edition_id=edition_id
        )
        admit()
        rows = tuple(
            AuditEvent.objects.filter(
                organization_id=organization_id,
                event_edition_id=edition_id,
                principal_kind="account",
                principal_id=actor_id,
                correlation_id=correlation_id,
                outcome="allow",
                operation__in=GENERATION_OPERATIONS,
            )
            .order_by("occurred_at", "id")
            .values(*FIELDS)[: MAX_EXIT_RECEIPTS + 1]
        )
        result = _section(rows)
        admit()
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="audit.view_security",
                operation="audit.programme_exit.read",
                target_type="audit.event_set",
                target_id=edition_id,
                outcome="allow",
                reason_code="programme_exit_source",
                correlation_id=correlation_id,
                source_channel="programme-exit",
                obligations=("audit_sensitive_read",),
                safe_metadata={
                    "policy_version": POLICY_VERSION,
                    "access_purpose": "compliance_review",
                },
                retention_class="security-extended",
            )
        )
        return result
