"""Exact typed authorization resolver for charity selections."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_resource_target,
)

from .bindings import charity_selection_binding_id
from .models import CharitySelection

if TYPE_CHECKING:
    from uuid import UUID


def resolve_charity_selection_target(
    *,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
) -> ResolvedAuthorizationTarget | None:
    """Resolve a selection only through its persisted complete tenant chain.

    Parameters
    ----------
    organization_id : UUID
        The organization identifier that owns the requested resource.
    edition_id : UUID
        The event edition identifier that scopes the operation.
    selection_id : UUID
        The selection identifier within the requested scope.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved ResolvedAuthorizationTarget | None for the requested scope.
    """
    row = (
        CharitySelection.objects.filter(
            id=selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department__retired_at__isnull=True,
        )
        .order_by()
        .values("responsible_department_id")
        .first()
    )
    if row is None:
        return None
    return resolve_resource_target(
        organization_id=organization_id,
        edition_id=edition_id,
        department_id=row["responsible_department_id"],
        resource_binding_id=charity_selection_binding_id(selection_id),
    )
