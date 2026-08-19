"""Exact typed authorization resolver for Logistics manifests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maru.authorization.policy import (
    ResolvedAuthorizationTarget,
    resolve_resource_target,
)

from .bindings import logistics_manifest_binding_id
from .models import LogisticsManifest

if TYPE_CHECKING:
    from uuid import UUID


def resolve_logistics_manifest_target(
    *, organization_id: UUID, edition_id: UUID, manifest_id: UUID
) -> ResolvedAuthorizationTarget | None:
    """Resolve logistics manifest target.

    Parameters
    ----------
    organization_id : UUID
        The identifier of the organization that owns the operation.
    edition_id : UUID
        The identifier of the event edition that scopes the operation.
    manifest_id : UUID
        The identifier of the manifest.

    Returns
    -------
    ResolvedAuthorizationTarget | None
        The resolved logistics manifest target.
    """
    row = (
        LogisticsManifest.objects.filter(
            id=manifest_id,
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
        resource_binding_id=logistics_manifest_binding_id(manifest_id),
    )
