"""Immutable authorization anchors for edition-selected physical spaces."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.authorization.models import ScopedResourceBinding
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)

from .models import EditionSpaceSelection

_BINDING_PREFIX = "https://maru.invalid/authorization/venue.edition-space/"


def edition_space_binding_id(space_selection_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"{_BINDING_PREFIX}{space_selection_id}")


@transaction.atomic
def ensure_edition_space_binding(
    *,
    space_selection: EditionSpaceSelection,
) -> ScopedResourceBinding:
    if space_selection._state.adding or space_selection.pk is None:
        raise ValidationError(
            "Save the edition space before creating its resource binding.",
            code="venue_space_unavailable",
        )
    lock_retired_department_authority_boundaries()
    locked = (
        EditionSpaceSelection.objects.select_for_update()
        .select_related("responsible_department")
        .filter(pk=space_selection.pk)
        .first()
    )
    if locked is None or locked.responsible_department.retired_at is not None:
        raise ValidationError(
            "The edition space is unavailable for exact authority.",
            code="venue_space_unavailable",
        )
    expected_id = edition_space_binding_id(locked.id)
    kind = ScopedResourceBinding.ResourceKind.VENUE_EDITION_SPACE
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
                "The existing venue binding does not match its exact scope.",
                code="venue_binding_scope_mismatch",
            )
        return binding
    if (
        ScopedResourceBinding.objects.select_for_update()
        .filter(pk=expected_id)
        .exists()
    ):
        raise ValidationError(
            "The venue binding identifier is already occupied.",
            code="venue_binding_scope_mismatch",
        )
    return ScopedResourceBinding.objects.create(
        id=expected_id,
        organization_id=locked.organization_id,
        edition_id=locked.edition_id,
        department_id=locked.responsible_department_id,
        resource_kind=kind,
        resource_id=locked.id,
    )
