"""Minimized stop-purpose accounting, never a personnel or approval directory."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from maru.audit.services import AuditRecord, append_audit
from maru.authorization.models import (
    CapabilityGrant,
    ProgrammeRoleRequest,
    RoleAssignment,
)
from maru.authorization.programme_stop_authorization import (
    require_programme_stop_controller,
)
from maru.authorization.services import AuthorizationDenied

if TYPE_CHECKING:
    from collections.abc import Sequence

MAX_STOP_AUTHORITY_RECORDS: Final = 2_000
_SOURCE_FIELDS: Final = (
    "id",
    "edition_id",
    "department_id",
    "resource_binding_id",
    "principal_id",
    "effective_from",
    "expires_at",
    "revoked_at",
    "revoked_by_id",
)
_REQUEST_FIELDS: Final = (
    "id",
    "edition_id",
    "department_id",
    "resource_binding_id",
    "scope_level",
    "recipe_code",
    "recipe_version",
    "recipe_digest",
    "requested_at",
    "approval_deadline",
    "not_before",
    "expires_at",
    "decision__id",
    "decision__action",
    "decision__role_assignment_id",
)


class ProgrammeStopAuthorityUnavailableError(RuntimeError):
    """Withhold incomplete accounting without disclosing partial private scope."""

    def __init__(self) -> None:
        super().__init__("programme_stop_authority_unavailable")


@dataclass(frozen=True, slots=True)
class ProgrammeStopAuthorityReference:
    """Identify exact retained authority without a person, label or rationale.

    Attributes
    ----------
    kind, id
        Exact capability-grant or role-assignment identity, not effective access.
    scope_level, department_id, resource_binding_id
        Actual retained target; Organization references are explicitly shared.
    disposition
        Historical/shared retention, already inactive or separately revoked.
        Nothing here claims that stop revoked, extended or activated a grant.
    source_fingerprint
        Closed original source identity and validity/revocation values, hashed
        without releasing recipients, controllers, reasons or private role intent.
    """

    kind: str
    id: UUID
    scope_level: str
    department_id: UUID | None
    resource_binding_id: UUID | None
    disposition: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class ProgrammeStopAuthorityImpact:
    """Account for this adoption's authority without granting any consequence.

    Attributes
    ----------
    assignments
        Complete bounded exact scoped outputs, including this adoption's guided
        shared Venue assignments, never unrelated Organization-wide grants.
    pending_requests, expired_requests, decided_requests
        Minimized complete counts of original unapproved/decided intent.
    source_fingerprint
        Stable comparison of this exact scope, outputs and request metadata.
    """

    assignments: tuple[ProgrammeStopAuthorityReference, ...]
    pending_requests: int
    expired_requests: int
    decided_requests: int
    source_fingerprint: str


def _json_scalar(value: object) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime) and timezone.is_aware(value):
        return value.isoformat()
    raise ProgrammeStopAuthorityUnavailableError


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
            default=_json_scalar,
        ).encode("ascii")
    ).hexdigest()


def _reference(
    kind: str, row: dict[str, Any], now: datetime
) -> ProgrammeStopAuthorityReference:
    if row["revoked_at"] is not None:
        disposition = "separately_revoked"
    elif row["effective_from"] > now or (
        row["expires_at"] is not None and row["expires_at"] <= now
    ):
        disposition = "already_inactive"
    else:
        disposition = (
            "retained_shared" if row["edition_id"] is None else "retained_historical"
        )
    scope = (
        "resource"
        if row["resource_binding_id"] is not None
        else "department"
        if row["department_id"] is not None
        else "edition"
        if row["edition_id"] is not None
        else "organization"
    )
    return ProgrammeStopAuthorityReference(
        kind,
        row["id"],
        scope,
        row["department_id"],
        row["resource_binding_id"],
        disposition,
        _digest({"kind": kind, "source": row}),
    )


def _project(
    *,
    organization_id: UUID,
    edition_id: UUID,
    grants: Sequence[dict[str, Any]],
    roles: Sequence[dict[str, Any]],
    requests: Sequence[dict[str, Any]],
    now: datetime,
) -> ProgrammeStopAuthorityImpact:
    if any(
        len(rows) > MAX_STOP_AUTHORITY_RECORDS for rows in (grants, roles, requests)
    ):
        raise ProgrammeStopAuthorityUnavailableError
    references = tuple(
        _reference(kind, row, now)
        for kind, rows in (("capability_grant", grants), ("role_assignment", roles))
        for row in rows
    )
    decided = sum(row["decision__id"] is not None for row in requests)
    expired = sum(
        row["decision__id"] is None and row["approval_deadline"] <= now
        for row in requests
    )
    pending = len(requests) - decided - expired
    return ProgrammeStopAuthorityImpact(
        references,
        pending,
        expired,
        decided,
        _digest(
            {
                "contract": "authorization.programme-stop-impact@1",
                "organization_id": organization_id,
                "edition_id": edition_id,
                "assignments": [asdict(row) for row in references],
                "requests": list(requests),
                "counts": [pending, expired, decided],
            }
        ),
    )


def load_programme_stop_authority(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
) -> ProgrammeStopAuthorityImpact:
    """Read complete minimized assignment accounting under actual stop authority.

    Parameters
    ----------
    actor_id : UUID
        Actual ordinary controller with independent current Events transition rights.
    organization_id, edition_id : UUID
        Exact known adoption scope; neither is inferred from an assignment.
    correlation_id : UUID
        Server-issued non-nil disclosure audit trace.

    Returns
    -------
    ProgrammeStopAuthorityImpact
        Bounded output identities/dispositions and unapproved-intent counts, without
        person labels, private reasons, proposals or an effective-access assertion.

    Raises
    ------
    ValidationError
        If the correlation identifier is malformed.
    ProgrammeStopAuthorityUnavailableError
        If the complete bounded inventory cannot be returned.
    AuthorizationDenied
        If current controller or Events purpose authority is missing.

    Notes
    -----
    Each successful or denied authorized-shape read is audited before returning.
    Stop composition must retain its outer canonical ownership/person transaction,
    rebuild this projection and compare the original preview before mutating.
    Organization roots and unrelated/shared grants are not enumerated or changed.
    Retained historical authority never overrides terminal owner guards. An expired
    approval is still original unapproved intent, not a manufactured rejection.
    """
    if type(correlation_id) is not UUID or not correlation_id.int:
        raise ValidationError("Use an exact audit trace.", code="programme_stop_trace")
    scope = {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "edition_id": edition_id,
    }

    def audit(*, allowed: bool) -> None:
        append_audit(
            AuditRecord(
                principal_kind="account",
                principal_id=actor_id,
                principal_context_id=None,
                organization_id=organization_id,
                event_edition_id=edition_id,
                capability_code="events.transition",
                operation="authorization.query.programme_stop",
                target_type="events.event_edition",
                target_id=edition_id if allowed else None,
                outcome="allow" if allowed else "deny",
                reason_code="programme_stop_impact"
                if allowed
                else "programme_stop_unavailable",
                correlation_id=correlation_id,
                source_channel="programme-stop",
                obligations=("audit_sensitive_read",),
                retention_class="security-extended",
            )
        )

    try:
        with transaction.atomic():
            require_programme_stop_controller(**scope)
            requests = tuple(
                ProgrammeRoleRequest.objects.filter(
                    organization_id=organization_id,
                    programme_edition_id=edition_id,
                )
                .order_by("id")
                .values(*_REQUEST_FIELDS)[: MAX_STOP_AUTHORITY_RECORDS + 1]
            )
            if len(requests) > MAX_STOP_AUTHORITY_RECORDS:
                raise ProgrammeStopAuthorityUnavailableError
            shared = {
                row["decision__role_assignment_id"]
                for row in requests
                if row["scope_level"] == "organization"
                and row["decision__action"] == "approve"
                and row["decision__role_assignment_id"] is not None
            }
            grants = tuple(
                CapabilityGrant.objects.filter(
                    organization_id=organization_id,
                    edition_id=edition_id,
                )
                .order_by("id")
                .values(*_SOURCE_FIELDS, "capability_code", "delegated_from_id")[
                    : MAX_STOP_AUTHORITY_RECORDS + 1
                ]
            )
            roles = tuple(
                RoleAssignment.objects.filter(
                    Q(edition_id=edition_id)
                    | Q(edition_id__isnull=True, id__in=shared),
                    organization_id=organization_id,
                )
                .order_by("id")
                .values(*_SOURCE_FIELDS, "role_bundle_id")[
                    : MAX_STOP_AUTHORITY_RECORDS + 1
                ]
            )
            if not shared <= {row["id"] for row in roles if row["edition_id"] is None}:
                raise ProgrammeStopAuthorityUnavailableError
            result = _project(
                organization_id=organization_id,
                edition_id=edition_id,
                grants=grants,
                roles=roles,
                requests=requests,
                now=timezone.now(),
            )
            require_programme_stop_controller(**scope)
            audit(allowed=True)
            return result
    except AuthorizationDenied:
        audit(allowed=False)
        raise
