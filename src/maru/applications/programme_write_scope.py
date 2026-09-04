"""Canonical cross-module lock order for Programme ownership writers.

The boundary is deliberately lifecycle-neutral.  Command-specific authorization
decides whether a current or retired Department may be acted on after the shared
edition mutex has serialized the decision with Workforce retirement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization
from maru.workforce.models import Department
from maru.workforce.writer_boundary import lock_edition_structure_mutex

if TYPE_CHECKING:
    from collections.abc import Collection
    from uuid import UUID


class ApplicationsProgrammeWriteScopeUnavailableError(RuntimeError):
    """Hide which organization, edition, Department, or actor was unavailable."""


@dataclass(frozen=True, slots=True)
class LockedProgrammeEditionWriteScope:
    """Identifier-only proof of the canonical Programme writer lock chain.

    Attributes
    ----------
    organization_id
        Exact locked organization identifier.
    series_id
        Exact locked convention-series identifier.
    edition_id
        Exact locked edition identifier.
    department_ids
        Sorted exact Department identifiers locked for the command.
    actor_id
        Exact locked actor identifier.
    """

    organization_id: UUID
    series_id: UUID
    edition_id: UUID
    department_ids: tuple[UUID, ...]
    actor_id: UUID


def lock_programme_edition_write_scope(
    *,
    organization_id: UUID,
    edition_id: UUID,
    department_ids: Collection[UUID],
    actor_id: UUID,
) -> LockedProgrammeEditionWriteScope:
    """Lock an exact Programme scope in the shared retirement-safe order.

    A caller may perform identifier-only discovery before this boundary, but it
    must invoke the boundary before locking any mutable Applications aggregate.
    The order is the shared structure/provenance/retirement barriers,
    Organization, ConventionSeries, EventEdition, the exact-edition mutex,
    Departments by UUID, and finally the actor.  A successful retained-receipt
    replay should return before calling this function.

    Parameters
    ----------
    organization_id : UUID
        Organization expected to own the edition and all Departments.
    edition_id : UUID
        Exact edition whose Programme state will change.
    department_ids : Collection[UUID]
        Complete source/destination Department set needed by the command.
    actor_id : UUID
        Exact command actor to lock after the Department set.

    Returns
    -------
    LockedProgrammeEditionWriteScope
        Identifier-only proof of the locked chain.

    Raises
    ------
    ApplicationsProgrammeWriteScopeUnavailableError
        If any exact scope component is missing or incoherent.
    """
    candidate_series_id = (
        EventEdition.objects.filter(
            id=edition_id,
            organization_id=organization_id,
            series__organization_id=organization_id,
        )
        .order_by()
        .values_list("series_id", flat=True)
        .first()
    )
    if candidate_series_id is None:
        raise ApplicationsProgrammeWriteScopeUnavailableError

    normalized_department_ids = tuple(sorted(set(department_ids)))
    lock_retired_department_authority_boundaries()

    locked_organization_id = (
        Organization.objects.select_for_update()
        .filter(id=organization_id)
        .order_by()
        .values_list("id", flat=True)
        .first()
    )
    if locked_organization_id is None:
        raise ApplicationsProgrammeWriteScopeUnavailableError

    locked_series_id = (
        ConventionSeries.objects.select_for_update()
        .filter(id=candidate_series_id, organization_id=locked_organization_id)
        .order_by()
        .values_list("id", flat=True)
        .first()
    )
    if locked_series_id is None:
        raise ApplicationsProgrammeWriteScopeUnavailableError

    locked_edition_id = (
        EventEdition.objects.select_for_update()
        .filter(
            id=edition_id,
            organization_id=locked_organization_id,
            series_id=locked_series_id,
        )
        .order_by()
        .values_list("id", flat=True)
        .first()
    )
    if locked_edition_id is None:
        raise ApplicationsProgrammeWriteScopeUnavailableError

    lock_edition_structure_mutex(
        organization_id=locked_organization_id,
        edition_id=locked_edition_id,
    )

    locked_department_rows = tuple(
        Department.objects.select_for_update()
        .filter(id__in=normalized_department_ids)
        .order_by("id")
        .values_list("id", "organization_id", "edition_id")
    )
    if tuple(
        row[0] for row in locked_department_rows
    ) != normalized_department_ids or any(
        row[1] != locked_organization_id or row[2] != locked_edition_id
        for row in locked_department_rows
    ):
        raise ApplicationsProgrammeWriteScopeUnavailableError

    locked_actor_id = (
        Account.objects.select_for_update()
        .filter(id=actor_id)
        .order_by()
        .values_list("id", flat=True)
        .first()
    )
    if locked_actor_id is None:
        raise ApplicationsProgrammeWriteScopeUnavailableError

    return LockedProgrammeEditionWriteScope(
        organization_id=locked_organization_id,
        series_id=locked_series_id,
        edition_id=locked_edition_id,
        department_ids=normalized_department_ids,
        actor_id=locked_actor_id,
    )


__all__ = [
    "ApplicationsProgrammeWriteScopeUnavailableError",
    "LockedProgrammeEditionWriteScope",
    "lock_programme_edition_write_scope",
]
