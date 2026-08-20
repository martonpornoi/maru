"""Exact typed authorization resolver for edition-selected venue spaces."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_resource_target,
)

from .bindings import edition_space_binding_id
from .models import EditionSpaceSelection

if TYPE_CHECKING:
    from uuid import UUID


def resolve_edition_space_target(
    *,
    organization_id: UUID,
    edition_id: UUID,
    space_selection_id: UUID,
) -> ResolvedAuthorizationTarget | None:
    """Resolve edition space target.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    space_selection_id : UUID
        The identifier of the space selection.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved edition space target.
    """
    row = (
        EditionSpaceSelection.objects.filter(
            id=space_selection_id,
            organization_id=organization_id,
            edition_id=edition_id,
            lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
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
        resource_binding_id=edition_space_binding_id(space_selection_id),
    )
