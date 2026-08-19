"""Immutable authorization anchors for exact Logistics manifests."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.authorization.models import ScopedResourceBinding
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)

from .models import LogisticsManifest

_BINDING_PREFIX = "https://maru.invalid/authorization/logistics.manifest/"


def logistics_manifest_binding_id(manifest_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"{_BINDING_PREFIX}{manifest_id}")


@transaction.atomic
def ensure_logistics_manifest_binding(
    *, manifest: LogisticsManifest
) -> ScopedResourceBinding:
    if manifest._state.adding or manifest.pk is None:
        raise ValidationError(
            "Save the Logistics manifest before creating its resource binding.",
            code="logistics_manifest_unavailable",
        )
    lock_retired_department_authority_boundaries()
    locked = (
        LogisticsManifest.objects.select_for_update()
        .select_related("responsible_department")
        .filter(pk=manifest.pk)
        .first()
    )
    if locked is None or locked.responsible_department.retired_at is not None:
        raise ValidationError(
            "The Logistics manifest is unavailable for exact authority.",
            code="logistics_manifest_unavailable",
        )
    expected_id = logistics_manifest_binding_id(locked.id)
    kind = ScopedResourceBinding.ResourceKind.LOGISTICS_MANIFEST
    binding = (
        ScopedResourceBinding.objects.select_for_update()
        .filter(resource_kind=kind, resource_id=locked.id)
        .first()
    )
    if binding is not None:
        if (
            binding.id != expected_id
            or binding.organization_id != locked.organization_id
            or binding.edition_id != locked.edition_id
            or binding.department_id != locked.responsible_department_id
        ):
            raise ValidationError(
                "The existing Logistics binding does not match its exact scope.",
                code="logistics_manifest_binding_scope_mismatch",
            )
        return binding
    if (
        ScopedResourceBinding.objects.select_for_update()
        .filter(pk=expected_id)
        .exists()
    ):
        raise ValidationError(
            "The Logistics binding identifier is already occupied.",
            code="logistics_manifest_binding_scope_mismatch",
        )
    return ScopedResourceBinding.objects.create(
        id=expected_id,
        organization_id=locked.organization_id,
        edition_id=locked.edition_id,
        department_id=locked.responsible_department_id,
        resource_kind=kind,
        resource_id=locked.id,
    )
