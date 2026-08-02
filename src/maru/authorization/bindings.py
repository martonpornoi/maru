"""Explicit application services for immutable typed resource bindings."""

from __future__ import annotations

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
    """Return the stable binding identifier used by the scope-v2 migration."""

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
