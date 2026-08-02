"""Canonical lock ordering for edition-scoped workforce writers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn
from uuid import UUID

from django.core.exceptions import ValidationError

from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.events.models import EventEdition
from maru.organizations.models import ConventionSeries, Organization
from maru.workforce.models import Department
from maru.workforce.writer_boundary import lock_edition_structure_mutex


@dataclass(frozen=True, slots=True)
class LockedWorkforceEditionWriteScope:
    """Identifier-only proof of one locked organization/series/edition chain."""

    organization_id: UUID
    series_id: UUID
    edition_id: UUID


def _raise_scope_unavailable() -> NoReturn:
    raise ValidationError(
        "The workforce edition write scope is unavailable.",
        code="workforce_edition_scope_unavailable",
    )


def lock_workforce_edition_write_scope(
    *,
    organization_id: UUID,
    series_id: UUID,
    edition_id: UUID,
) -> LockedWorkforceEditionWriteScope:
    """Lock one exact edition scope in the canonical cross-module order.

    Callers may perform identifier-only reads to discover the candidate scope,
    but must call this function before taking any Position or
    PositionAssignment row lock or performing any corresponding write.  The
    returned proof contains no labels and is valid only for the surrounding
    transaction.
    """

    lock_retired_department_authority_boundaries()

    locked_organization_id = (
        Organization.objects.select_for_update()
        .filter(id=organization_id)
        .order_by()
        .values_list("id", flat=True)
        .first()
    )
    if locked_organization_id is None:
        _raise_scope_unavailable()

    series_row = (
        ConventionSeries.objects.select_for_update()
        .filter(id=series_id)
        .order_by()
        .values_list("id", "organization_id")
        .first()
    )
    if series_row is None or series_row[1] != locked_organization_id:
        _raise_scope_unavailable()

    edition_row = (
        EventEdition.objects.select_for_update()
        .filter(id=edition_id)
        .order_by()
        .values_list("id", "organization_id", "series_id")
        .first()
    )
    if (
        edition_row is None
        or edition_row[1] != locked_organization_id
        or edition_row[2] != series_row[0]
    ):
        _raise_scope_unavailable()

    lock_edition_structure_mutex(
        organization_id=locked_organization_id,
        edition_id=edition_row[0],
    )
    return LockedWorkforceEditionWriteScope(
        organization_id=locked_organization_id,
        series_id=series_row[0],
        edition_id=edition_row[0],
    )


def lock_active_department_write_target(
    *,
    scope: LockedWorkforceEditionWriteScope,
    department_id: UUID,
) -> None:
    """Lock and recheck a current Department before a narrower workforce row."""

    department_row = (
        Department.objects.select_for_update()
        .filter(id=department_id)
        .order_by()
        .values_list("organization_id", "edition_id", "retired_at")
        .first()
    )
    if (
        department_row is None
        or department_row[0] != scope.organization_id
        or department_row[1] != scope.edition_id
    ):
        raise ValidationError(
            "The workforce Department target is unavailable.",
            code="workforce_department_unavailable",
        )
    if department_row[2] is not None:
        raise ValidationError(
            "A retired Department cannot receive new workforce records.",
            code="workforce_department_retired",
        )
