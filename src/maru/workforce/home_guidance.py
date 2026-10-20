"""Minimized, authorized Workforce setup guidance for the administration home."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from maru.authorization.enforcement import (
    FieldProjectionDeniedError,
    require_complete_projection,
)
from maru.authorization.policy import PolicyDecision, decide, resolve_edition_target
from maru.events.queries import (
    edition_adoption_profile_reference,
    resolve_private_planning_edition_reference,
)
from maru.organizations.queries import organization_accepts_planning_changes
from maru.workforce.models import Department, EditionStructureControl, Position
from maru.workforce.queries import (
    MAX_STRUCTURE_DEPARTMENTS,
    MAX_STRUCTURE_POSITIONS,
    WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
)
from maru.workforce.structure_audit import append_structure_read_audit
from maru.workforce.structure_snapshot import (
    StructureSnapshotRead,
    load_version_fenced_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from uuid import UUID

    from maru.identity.models import Account

SetupStep = Literal[
    "departments",
    "positions",
    "opportunities",
    "published",
    "review",
    "read_only",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class WorkforceSetupGuidance:
    """Describe one current, bounded setup continuation without private labels.

    Attributes
    ----------
    step
        The owner-derived continuation; published covers opportunities only.
    checked_at
        The final authorization time, not a promise of future freshness.
    can_manage
        Whether the current principal may use the existing management pages.
    position_id
        An exact-edition draft Position for the next review, when applicable.
    """

    step: SetupStep
    checked_at: datetime
    can_manage: bool = False
    position_id: UUID | None = None


def _authorize(
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> PolicyDecision:
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    decision = decide(
        principal=actor,
        capability_code="workforce.view_structure",
        resource=target,
        requested_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
        at=timezone.now(),
    )
    if not decision.allowed:
        raise PermissionDenied
    try:
        require_complete_projection(
            required_fields=WORKFORCE_STRUCTURE_REQUIRED_FIELDS,
            permitted_fields=decision.fields,
        )
    except FieldProjectionDeniedError as error:
        raise PermissionDenied from error
    return decision


def _adopted(organization_id: UUID, edition_id: UUID) -> bool:
    profile = edition_adoption_profile_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    return bool(profile and profile.code == "workforce_only" and profile.version == 1)


def _planning_allowed(organization_id: UUID, edition_id: UUID) -> bool:
    edition = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    return bool(
        edition
        and edition.accepts_private_planning_writes
        and organization_accepts_planning_changes(organization_id=organization_id)
    )


def _snapshot(
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
) -> StructureSnapshotRead[WorkforceSetupGuidance]:
    _authorize(actor, organization_id, edition_id)
    control = (
        EditionStructureControl.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        .values_list("aggregate_version", flat=True)
        .first()
    )
    version = int(control) if control is not None else 0
    result = WorkforceSetupGuidance("unavailable", timezone.now())
    if not _planning_allowed(organization_id, edition_id):
        result = replace(result, step="read_only")
    else:
        departments = list(
            Department.objects.filter(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            .order_by("id")
            .values_list("id", "retired_at")[: MAX_STRUCTURE_DEPARTMENTS + 1]
        )
        if len(departments) <= MAX_STRUCTURE_DEPARTMENTS:
            active_ids = {
                identity for identity, retired_at in departments if retired_at is None
            }
            if not active_ids and (control is not None or not departments):
                result = replace(result, step="departments")
            elif active_ids and version > 0:
                rows = list(
                    Position.objects.filter(
                        organization_id=organization_id,
                        edition_id=edition_id,
                    )
                    .order_by("id")
                    .values_list(
                        "id",
                        "status",
                        "opportunity__status",
                        "department_id",
                    )[: MAX_STRUCTURE_POSITIONS + 1]
                )
                if len(rows) <= MAX_STRUCTURE_POSITIONS:
                    current_rows = [
                        (identity, status, publication)
                        for identity, status, publication, department_id in rows
                        if department_id in active_ids
                    ]
                    result = _position_step(result, current_rows)
    return StructureSnapshotRead(
        value=result,
        organization_id=organization_id,
        edition_id=edition_id,
        aggregate_version=version,
    )


def _position_step(
    result: WorkforceSetupGuidance,
    rows: Sequence[tuple[UUID, str, str | None]],
) -> WorkforceSetupGuidance:
    if not rows:
        return replace(result, step="positions")
    if any(
        status not in {"planned", "open", "filled", "closed"}
        or publication not in {"draft", "published", "closed", "withdrawn"}
        for _identity, status, publication in rows
    ):
        return result
    current = [row for row in rows if row[1] != "closed"]
    draft = next((row for row in current if row[2] == "draft"), None)
    if draft:
        return replace(result, step="opportunities", position_id=draft[0])
    if current and all(row[2] == "published" for row in current):
        return replace(result, step="published")
    return replace(result, step="review")


def load_workforce_setup_guidance(
    *,
    actor: Account,
    organization_id: UUID,
    edition_id: UUID,
    correlation_id: UUID,
    http_method: str,
) -> WorkforceSetupGuidance | None:
    """Read one scope-limited continuation, then reauthorize and audit disclosure.

    Parameters
    ----------
    actor : Account
        Current authenticated principal; selection does not grant authority.
    organization_id : UUID
        Exact owner of the selected event edition.
    edition_id : UUID
        Exact selected edition, never an inferred personal relationship.
    correlation_id : UUID
        Existing request correlation used by minimized structure-read evidence.
    http_method : str
        Current GET or HEAD administration-home method.

    Returns
    -------
    WorkforceSetupGuidance | None
        Fresh bounded guidance, or no contribution for an unadopted profile.

    Notes
    -----
    PermissionDenied propagates when complete structure-read authority is absent.
    Snapshot movement and mandatory-audit failures also prevent disclosure.
    """
    if not actor.is_active or not _adopted(organization_id, edition_id):
        return None
    result = load_version_fenced_snapshot(
        load=lambda: _snapshot(actor, organization_id, edition_id),
    )
    decision = _authorize(actor, organization_id, edition_id)
    if not _adopted(organization_id, edition_id):
        return None
    checked_at = timezone.now()
    target = resolve_edition_target(
        organization_id=organization_id,
        edition_id=edition_id,
    )
    can_manage = decide(
        principal=actor,
        capability_code="workforce.manage_structure",
        resource=target,
        at=checked_at,
    ).allowed
    if not _planning_allowed(organization_id, edition_id):
        result = replace(result, step="read_only", position_id=None)
    append_structure_read_audit(
        actor=actor,
        organization_id=organization_id,
        edition_id=edition_id,
        decision=decision,
        correlation_id=correlation_id,
        route_name="admin:index",
        http_method=http_method,
        source_channel="web",
        occurred_at=checked_at,
    )
    return replace(result, checked_at=checked_at, can_manage=can_manage)
