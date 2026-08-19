"""Exact typed authorization resolver for charity selections."""

from __future__ import annotations

from uuid import UUID

from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_resource_target,
)

from .bindings import charity_selection_binding_id
from .models import CharitySelection


def resolve_charity_selection_target(
    *,
    organization_id: UUID,
    edition_id: UUID,
    selection_id: UUID,
) -> ResolvedAuthorizationTarget | None:
    """Resolve a selection only through its persisted complete tenant chain."""

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
