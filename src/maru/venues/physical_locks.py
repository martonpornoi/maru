"""Canonical mutex shared by ordinary and Programme-linked physical writers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.events.write_references import lock_edition_ownership
from maru.identity.queries import lock_account_references_for_evidence

from .models import EditionSpaceMember, EditionSpaceSelection, VenueProperty, VenueSpace

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
    # Canonical parents -> principal -> properties -> complete members -> selections.
    # The union is essential for swaps: never acquire the old and new rooms in
    # separate passes. Physical members serialize the same rooms across editions.
    if (
        not lock_edition_ownership(
            organization_id=organization_id, edition_id=edition_id
        )
        or resolve_scheduling_edition_reference(
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
    property_ids = tuple(
        VenueSpace.objects.filter(organization_id=organization_id, id__in=members)
        .order_by("property_id")
        .values_list("property_id", flat=True)
        .distinct()
    )
    properties = tuple(
        VenueProperty.objects.select_for_update(of=("self",))
        .filter(organization_id=organization_id, id__in=property_ids)
        .order_by("id")
        .values_list("id", flat=True)
    )
    if not properties or properties != property_ids:
        raise ValidationError("Physical scope is unavailable.")
    physical_rows = tuple(
        VenueSpace.objects.select_for_update(of=("self",))
        .filter(organization_id=organization_id, id__in=members)
        .order_by("id")
        .values_list("id", "property_id")
    )
    selections = tuple(
        EditionSpaceSelection.objects.select_for_update(of=("self",))
        .filter(organization_id=organization_id, edition_id=edition_id, id__in=ids)
        .order_by("id")
        .values_list("id", flat=True)
    )
    current_members = tuple(
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
        tuple(row[0] for row in physical_rows) != members
        or tuple(sorted({row[1] for row in physical_rows})) != property_ids
        or current_members != members
        or selections != ids
    ):
        raise ValidationError("Physical scope is unavailable.")
