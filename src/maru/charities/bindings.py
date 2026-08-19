"""Immutable authorization anchors for edition charity selections."""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.authorization.models import ScopedResourceBinding
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)

from .models import CharitySelection

_BINDING_NAME_PREFIX = "https://maru.invalid/authorization/charity.selection/"


def charity_selection_binding_id(selection_id: UUID) -> UUID:
    """Return charity selection binding id.

    Parameters
    ----------
    selection_id : UUID
        The identifier of the selection.

    Returns
    -------
    UUID
        The UUID established after charity selection binding id completes.
    """
    return uuid5(NAMESPACE_URL, f"{_BINDING_NAME_PREFIX}{selection_id}")


@transaction.atomic
def ensure_charity_selection_binding(
    *,
    selection: CharitySelection,
) -> ScopedResourceBinding:
    """Create or return the exact immutable selection authorization anchor.

    Parameters
    ----------
    selection : CharitySelection
        The selection evaluated while ensure charity selection binding.

    Returns
    -------
    ScopedResourceBinding
        The resolved ScopedResourceBinding for ensure charity selection binding.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if selection._state.adding or selection.pk is None:  # noqa: SLF001
        raise ValidationError(
            "Save the charity selection before creating its resource binding.",
            code="charity_selection_unavailable",
        )
    lock_retired_department_authority_boundaries()
    locked = (
        CharitySelection.objects.select_for_update()
        .select_related("responsible_department")
        .filter(pk=selection.pk)
        .first()
    )
    if locked is None or locked.responsible_department.retired_at is not None:
        raise ValidationError(
            "The charity selection is unavailable for exact authority.",
            code="charity_selection_unavailable",
        )
    expected_id = charity_selection_binding_id(locked.id)
    kind = ScopedResourceBinding.ResourceKind.CHARITY_SELECTION
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
                "The existing charity binding does not match its exact scope.",
                code="charity_binding_scope_mismatch",
            )
        return binding
    if (
        ScopedResourceBinding.objects.select_for_update()
        .filter(pk=expected_id)
        .exists()
    ):
        raise ValidationError(
            "The charity binding identifier is already occupied.",
            code="charity_binding_scope_mismatch",
        )
    return ScopedResourceBinding.objects.create(
        id=expected_id,
        organization_id=locked.organization_id,
        edition_id=locked.edition_id,
        department_id=locked.responsible_department_id,
        resource_kind=kind,
        resource_id=locked.id,
    )
