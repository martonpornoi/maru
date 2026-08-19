"""Explicit application services for immutable typed resource bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.exceptions import ValidationError
from django.db import transaction

from maru.authorization.models import ScopedResourceBinding
from maru.authorization.retired_targets import (
    lock_retired_department_authority_boundaries,
)
from maru.workforce.models import Position

_WORKFORCE_POSITION_BINDING_NAME_PREFIX = (
    "https://maru.invalid/authorization/workforce.position/"
)


def workforce_position_binding_id(position_id: UUID) -> UUID:
    """Return the stable binding identifier used by the scope-v2 migration.

    Parameters
    ----------
    position_id : UUID
        The position identifier within the requested scope.

    Returns
    -------
    UUID
        The resolved UUID for workforce position binding id.
    """
    return uuid5(
        NAMESPACE_URL,
        f"{_WORKFORCE_POSITION_BINDING_NAME_PREFIX}{position_id}",
    )


def _raise_binding_mismatch() -> None:
    raise ValidationError(
        "The existing workforce position binding does not match its exact scope.",
        code="resource_binding_scope_mismatch",
    )


@transaction.atomic
def ensure_workforce_position_binding(
    *,
    position: Position,
) -> ScopedResourceBinding:
    """Create or return the position's exact immutable authorization anchor.

    The persisted Position is the source of truth. Locking and re-reading it
    prevents a stale or caller-mutated model instance from choosing authority
    scope, and serializes concurrent creators with the database binding guard.

    Parameters
    ----------
    position : Position
        The workforce position within the exact edition structure.

    Returns
    -------
    ScopedResourceBinding
        The resolved ScopedResourceBinding for ensure workforce position binding.

    Raises
    ------
    ValidationError
        If the submitted state or input violates a domain invariant.
    """
    if position._state.adding or position.pk is None:
        raise ValidationError(
            "Save the workforce position before creating its resource binding.",
            code="workforce_position_unavailable",
        )

    lock_retired_department_authority_boundaries()

    try:
        locked_position = (
            Position.objects.select_for_update()
            .select_related("organization", "edition", "department")
            .get(pk=position.pk)
        )
    except Position.DoesNotExist as exc:
        raise ValidationError(
            "The workforce position is no longer available.",
            code="workforce_position_unavailable",
        ) from exc

    if locked_position.department.retired_at is not None:
        raise ValidationError(
            "A retired Department cannot receive a workforce position binding.",
            code="workforce_department_retired",
        )

    resource_kind = ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION
    expected_id = workforce_position_binding_id(locked_position.pk)
    binding = (
        ScopedResourceBinding.objects.select_for_update()
        .filter(
            resource_kind=resource_kind,
            resource_id=locked_position.pk,
        )
        .first()
    )
    if binding is not None:
        if (
            binding.organization_id != locked_position.organization_id
            or binding.edition_id != locked_position.edition_id
            or binding.department_id != locked_position.department_id
        ):
            _raise_binding_mismatch()
        return binding

    # A deterministic UUID lets activation backfill and live writers converge.
    # Treat an occupied UUID as corruption instead of selecting a new identity.
    if (
        ScopedResourceBinding.objects.select_for_update()
        .filter(pk=expected_id)
        .exists()
    ):
        _raise_binding_mismatch()

    return ScopedResourceBinding.objects.create(
        id=expected_id,
        organization=locked_position.organization,
        edition=locked_position.edition,
        department=locked_position.department,
        resource_kind=resource_kind,
        resource_id=locked_position.pk,
    )


def resource_binding_target_exists(
    binding: ScopedResourceBinding | Mapping[str, Any],
    *,
    for_update: bool = False,
) -> bool:
    """Validate one typed binding against its domain owner's exact scope.

    Parameters
    ----------
    binding : ScopedResourceBinding | Mapping[str, Any]
        The binding mapping to validate or transform.
    for_update : bool, default=False
        The for update evaluated while resource binding target exists.

    Returns
    -------
    bool
        `True` when Validate one typed binding against its domain owner's exact
        scope; otherwise `False`.
    """
    if isinstance(binding, Mapping):
        resource_kind = binding["resource_kind"]
        resource_id = binding["resource_id"]
        organization_id = binding["organization_id"]
        edition_id = binding["edition_id"]
        department_id = binding["department_id"]
    else:
        resource_kind = binding.resource_kind
        resource_id = binding.resource_id
        organization_id = binding.organization_id
        edition_id = binding.edition_id
        department_id = binding.department_id
    if resource_kind == ScopedResourceBinding.ResourceKind.WORKFORCE_POSITION:
        positions = Position.objects.all()
        if for_update:
            positions = positions.select_for_update()
        return positions.filter(
            pk=resource_id,
            organization_id=organization_id,
            edition_id=edition_id,
            department_id=department_id,
        ).exists()
    if resource_kind == ScopedResourceBinding.ResourceKind.CHARITY_SELECTION:
        from maru.charities.models import CharitySelection  # noqa: PLC0415

        selections = CharitySelection.objects.all()
        if for_update:
            selections = selections.select_for_update()
        return selections.filter(
            pk=resource_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=department_id,
        ).exists()
    if resource_kind == ScopedResourceBinding.ResourceKind.VENUE_EDITION_SPACE:
        from maru.venues.models import EditionSpaceSelection  # noqa: PLC0415

        venue_spaces = EditionSpaceSelection.objects.all()
        if for_update:
            venue_spaces = venue_spaces.select_for_update()
        return venue_spaces.filter(
            pk=resource_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=department_id,
        ).exists()
    if resource_kind == ScopedResourceBinding.ResourceKind.LOGISTICS_MANIFEST:
        from maru.logistics.models import LogisticsManifest  # noqa: PLC0415

        manifests = LogisticsManifest.objects.all()
        if for_update:
            manifests = manifests.select_for_update()
        return manifests.filter(
            pk=resource_id,
            organization_id=organization_id,
            edition_id=edition_id,
            responsible_department_id=department_id,
        ).exists()
    return False
