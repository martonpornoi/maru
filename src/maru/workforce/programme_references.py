"""Identifier-only Workforce references for governed Programme staffing writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.events.queries import resolve_edition_series_identity
from maru.workforce.edition_write_scope import lock_workforce_edition_write_scope
from maru.workforce.models import Position

if TYPE_CHECKING:
    from maru.workforce.edition_write_scope import LockedWorkforceEditionWriteScope


@dataclass(frozen=True, slots=True)
class StaffingPositionReference:
    """Return opaque scope and current Position lifecycle, never personnel data.

    Attributes
    ----------
    position_id
        Exact retained Position identifier.
    department_id
        Exact owning Department identifier.
    accepts_staffing
        Whether the Position and Department accept new operational demand.
    """

    position_id: UUID
    department_id: UUID
    accepts_staffing: bool


def lock_programme_staffing_scope(
    *, organization_id: UUID, edition_id: UUID
) -> LockedWorkforceEditionWriteScope:
    """Acquire the canonical scope before any Programme or Scheduling row lock.

    This reference seam grants no authority. The caller authorizes its exact
    purpose before calling and reauthorizes under the returned transaction scope.

    Parameters
    ----------
    organization_id : UUID
        Expected owner, independently checked by Workforce.
    edition_id : UUID
        Exact edition, not a discovery filter.

    Returns
    -------
    LockedWorkforceEditionWriteScope
        Identifier-only scope valid inside the caller's existing transaction.

    Raises
    ------
    ValidationError
        If the exact scope is unavailable or malformed.
    """
    if not isinstance(organization_id, UUID) or not isinstance(edition_id, UUID):
        raise ValidationError(
            "Staffing scope unavailable.", code="staffing_scope_unavailable"
        )
    series_id = resolve_edition_series_identity(
        organization_id=organization_id, edition_id=edition_id
    )
    if series_id is None:
        raise ValidationError(
            "Staffing scope unavailable.", code="staffing_scope_unavailable"
        )
    return lock_workforce_edition_write_scope(
        organization_id=organization_id, series_id=series_id, edition_id=edition_id
    )


def resolve_staffing_position_reference(
    *, organization_id: UUID, edition_id: UUID, position_id: UUID
) -> StaffingPositionReference | None:
    """Resolve one retained Position after the caller locks the edition scope.

    This conveys no labels or authority and does not lock a narrower row out of
    order. The shared edition scope serializes governed Position/Department
    changes. Consumers must authorize their own command before using this seam.

    Parameters
    ----------
    organization_id : UUID
        Expected owner of both Position and Department.
    edition_id : UUID
        Exact edition of both owner records.
    position_id : UUID
        Opaque Position already selected by the caller.

    Returns
    -------
    StaffingPositionReference | None
        Minimal retained reference, or the same absence for all invalid scope.
    """
    if any(
        not isinstance(value, UUID)
        for value in (organization_id, edition_id, position_id)
    ):
        return None
    row = (
        Position.objects.filter(
            id=position_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department__organization_id=organization_id,
            department__edition_id=edition_id,
        )
        .values("id", "department_id", "status", "department__retired_at")
        .first()
    )
    if row is None:
        return None
    return StaffingPositionReference(
        row["id"],
        row["department_id"],
        row["status"] != Position.Status.CLOSED
        and row["department__retired_at"] is None,
    )
