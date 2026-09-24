"""Events-owned current configuration for the additional restricted archive purpose."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.catalog import POLICY_VERSION
from maru.authorization.policy import (
    PolicyDecision,
    decide_verified_principal_exact_edition,
)
from maru.programme.archive_authorization import authorize_programme_archive_scope
from maru.programme.authorization import (
    DEFAULT_PROGRAMME_AUTHORIZER,
    ProgrammeAuthorizationDenied,
)
from maru.programme.exit_archive_protocol import ProgrammeArchiveSection

from .models import EventEdition
from .write_references import lock_edition_ownership

if TYPE_CHECKING:
    from maru.programme.authorization import ProgrammeAuthorizer

_FIELDS: Final = frozenset(
    {
        "id",
        "organization_id",
        "series_id",
        "slug",
        "name",
        "lifecycle",
        "aggregate_version",
        "adoption_profile_code",
        "adoption_profile_version",
        "time_zone",
        "language_codes",
        "starts_on",
        "ends_on",
    }
)
_OPERATION: Final = "events.query.programme_exit"


def load_programme_exit_configuration(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    programme_authorizer: ProgrammeAuthorizer = DEFAULT_PROGRAMME_AUTHORIZER,
) -> ProgrammeArchiveSection:
    """Read one explicit Events section with independent source and export authority.

    Parameters
    ----------
    actor_id : UUID
        Actual authenticated requester, independently reloaded by both policies.
    organization_id : UUID
        Exact expected owner of both edition and series.
    edition_id : UUID
        Known edition, never an unbounded or cross-tenant discovery request.
    correlation_id : UUID
        Trusted trace joining minimized archive source-read evidence.
    programme_authorizer : ProgrammeAuthorizer, default=DEFAULT_PROGRAMME_AUTHORIZER
        Additional Programme purpose policy, with its existing sealed test guard.
        This cannot substitute or bypass the independent Events source policy.

    Returns
    -------
    ProgrammeArchiveSection
        Exact current configuration and its schema, or no disclosed section.

    Raises
    ------
    ValidationError
        If trusted attribution has not supplied non-nil UUIDs.
    PermissionDenied
        If the additional purpose, source fields or locked owner scope is absent.

    Notes
    -----
    Source and purpose checks run before reading and before returning. Canonical
    ownership locks retain one coherent Events version; audit failure propagates
    without returning bytes. A cross-owner composer must hold its complete person
    closure before invoking any audited section, including this one.
    """
    if any(
        type(value) is not UUID or value.int == 0
        for value in (actor_id, organization_id, edition_id, correlation_id)
    ):
        raise ValidationError(
            "Use exact archive scope and attribution.", code="programme_exit_scope"
        )

    def admit() -> PolicyDecision:
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
            capability_code="events.view_basic",
            requested_fields=_FIELDS,
        )
        if (
            not isinstance(decision, PolicyDecision)
            or not decision.allowed
            or not decision.fields >= _FIELDS
        ):
            raise PermissionDenied
        return decision

    def audit(*, allowed: bool) -> None:
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="events.view_basic",
                operation=_OPERATION,
                target_type="events.event_edition",
                target_id=edition_id if allowed else None,
                outcome="allow" if allowed else "deny",
                reason_code="programme_exit_source"
                if allowed
                else "programme_exit_unavailable",
                correlation_id=correlation_id,
                request_id=correlation_id,
                source_channel="programme-exit",
                obligations=("audit_sensitive_read",),
                safe_metadata={"policy_version": POLICY_VERSION},
                retention_class="programme-restricted",
            )
        )

    def collect() -> ProgrammeArchiveSection:
        with transaction.atomic():
            if not lock_edition_ownership(
                organization_id=organization_id, edition_id=edition_id
            ):
                raise PermissionDenied
            admit()
            row = (
                EventEdition.objects.filter(
                    id=edition_id,
                    organization_id=organization_id,
                    series__organization_id=organization_id,
                )
                .values(*sorted(_FIELDS))
                .first()
            )
            if row is None:
                raise PermissionDenied
            data = {
                "id": str(row["id"]),
                "organization_id": str(row["organization_id"]),
                "series_id": str(row["series_id"]),
                "slug": row["slug"],
                "name": row["name"],
                "lifecycle": row["lifecycle"],
                "aggregate_version": row["aggregate_version"],
                "adoption_profile_code": row["adoption_profile_code"],
                "adoption_profile_version": row["adoption_profile_version"],
                "time_zone": row["time_zone"],
                "language_codes": row["language_codes"],
                "starts_on": row["starts_on"].isoformat(),
                "ends_on": row["ends_on"].isoformat(),
            }
            properties: dict[str, object] = {
                key: {"type": "string"}
                for key in (
                    "slug",
                    "name",
                    "lifecycle",
                    "adoption_profile_code",
                    "time_zone",
                )
            }
            properties.update(
                {
                    key: {"type": "string", "format": "uuid"}
                    for key in ("id", "organization_id", "series_id")
                }
            )
            properties.update(
                {
                    key: {"type": "integer", "minimum": 1}
                    for key in ("aggregate_version", "adoption_profile_version")
                }
            )
            properties.update(
                {
                    key: {"type": "string", "format": "date"}
                    for key in ("starts_on", "ends_on")
                }
            )
            properties["language_codes"] = {
                "type": "array",
                "items": {"type": "string"},
            }
            schema = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "Programme edition configuration v1",
                "type": "object",
                "properties": properties,
                "required": sorted(_FIELDS),
                "additionalProperties": False,
            }
            section = ProgrammeArchiveSection(
                "events",
                "events.programme-exit@1",
                json.dumps(
                    data,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8"),
                json.dumps(
                    schema, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode("utf-8"),
            )
            admit()
            audit(allowed=True)
            return section

    try:
        admit()
        return collect()
    except (PermissionDenied, ProgrammeAuthorizationDenied):
        audit(allowed=False)
        raise PermissionDenied(
            "Programme archive configuration is unavailable."
        ) from None
