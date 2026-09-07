"""Canonical mutex shared by ordinary and Programme-linked physical writers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.identity.queries import lock_account_references_for_evidence

from .models import EditionSpaceMember, EditionSpaceSelection, VenueSpace

if TYPE_CHECKING:
    from uuid import UUID

_MAX_SELECTIONS = 256
_MAX_PHYSICAL_MEMBERS = 4_096


def _lock_physical_scope(
    *,
    actor_id: UUID,
    organization_id: UUID,
    edition_id: UUID,
    selection_ids: tuple[UUID, ...],
) -> None:
    # Edition -> principal -> complete shared physical member union -> selections.
    # The union is essential for swaps: never acquire the old and new rooms in
    # separate passes. Physical members serialize the same rooms across editions.
    if (
        resolve_scheduling_edition_reference(
            organization_id=organization_id, edition_id=edition_id, lock=True
        )
        is None
        or lock_account_references_for_evidence(account_ids=(actor_id,)) is None
    ):
        raise ValidationError("Physical scope is unavailable.")
    ids = tuple(sorted(set(selection_ids)))
    members = tuple(
        EditionSpaceMember.objects.filter(
            organization_id=organization_id,
            edition_id=edition_id,
            space_selection_id__in=ids,
        )
        .order_by("source_space_id")
        .values_list("source_space_id", flat=True)
        .distinct()[: _MAX_PHYSICAL_MEMBERS + 1]
    )
    if (
        not ids
        or len(ids) > _MAX_SELECTIONS
        or not members
        or len(members) > _MAX_PHYSICAL_MEMBERS
    ):
        raise ValidationError("Physical scope is unavailable.")
    physical = tuple(
        VenueSpace.objects.select_for_update(of=("self",))
        .filter(organization_id=organization_id, id__in=members)
        .order_by("id")
        .values_list("id", flat=True)
    )
    selections = tuple(
        EditionSpaceSelection.objects.select_for_update(of=("self",))
        .filter(organization_id=organization_id, edition_id=edition_id, id__in=ids)
        .order_by("id")
        .values_list("id", flat=True)
    )
    if physical != members or selections != ids:
        raise ValidationError("Physical scope is unavailable.")
