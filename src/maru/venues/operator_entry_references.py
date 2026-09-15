"""Opaque current operator candidates and purpose-authorized minimal room labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.core.exceptions import ValidationError

from .models import EditionSpaceSelection
from .scheduling_queries import MAX_SCHEDULING_SPACE_SELECTIONS

if TYPE_CHECKING:
    from django.db.models import QuerySet


@dataclass(frozen=True, slots=True)
class OperatorRoomCandidate:
    """Keep opaque current source identity without room or Department names.

    Attributes
    ----------
    space_id, version
        Current active selected room identity and owner revision.
    venue_id, venue_version
        Exact active parent selection and its revision.
    department_id
        Current exact responsibility, not a grant or reporting-tree inference.
    """

    space_id: UUID
    version: int
    venue_id: UUID
    venue_version: int
    department_id: UUID


@dataclass(frozen=True, slots=True)
class OperatorRoomSetReference:
    """Keep the full current room set behind an opaque owner boundary.

    Attributes
    ----------
    organization_id, edition_id
        Exact expected owner scope for every candidate.
    rooms
        Complete deterministic opaque current candidate tuple.
    """

    organization_id: UUID
    edition_id: UUID
    rooms: tuple[OperatorRoomCandidate, ...]


@dataclass(frozen=True, slots=True)
class OperatorRoomChoiceReference:
    """Name one exact room after the consumer admits its operator purpose.

    Attributes
    ----------
    source
        Exact current candidate used for source comparison, not authorization.
    label, venue_label
        Minimal local room and parent venue wayfinding labels only.
    """

    source: OperatorRoomCandidate
    label: str
    venue_label: str


def _current(
    organization_id: UUID, edition_id: UUID
) -> QuerySet[EditionSpaceSelection]:
    return EditionSpaceSelection.objects.filter(
        organization_id=organization_id,
        edition_id=edition_id,
        lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
        venue_selection__lifecycle="active",
        responsible_department__retired_at__isnull=True,
    )


def _coherent(
    query: QuerySet[EditionSpaceSelection], organization_id: UUID, edition_id: UUID
) -> QuerySet[EditionSpaceSelection]:
    return query.filter(
        venue_selection__organization_id=organization_id,
        venue_selection__edition_id=edition_id,
        responsible_department__organization_id=organization_id,
        responsible_department__edition_id=edition_id,
    )


_SOURCE_FIELDS = (
    "id",
    "aggregate_version",
    "venue_selection_id",
    "venue_selection__aggregate_version",
    "responsible_department_id",
)


def resolve_operator_room_set_reference(
    *, organization_id: UUID, edition_id: UUID
) -> OperatorRoomSetReference | None:
    """Resolve complete current room identifiers without selecting a single name.

    Parameters
    ----------
    organization_id : UUID
        Exact expected tenant owner, independently admitted by the consumer.
    edition_id : UUID
        Exact edition, never a cross-edition discovery filter.

    Returns
    -------
    OperatorRoomSetReference | None
        Bounded opaque candidates, or None for invalid, incoherent or oversized scope.

    Notes
    -----
    This owner reference is not a user-facing query or permission token. Consumers
    must authorize every prospective exact resource before looking up names,
    compare current sources before disclosure and fulfill their own read audit.
    Database failures propagate; they never become an apparently empty directory.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (organization_id, edition_id)
    ):
        return None
    try:
        query = _current(organization_id, edition_id)
        rows = tuple(
            _coherent(query, organization_id, edition_id)
            .order_by("id")
            .values_list(*_SOURCE_FIELDS)[: MAX_SCHEDULING_SPACE_SELECTIONS + 1]
        )
        if len(rows) > MAX_SCHEDULING_SPACE_SELECTIONS or query.count() != len(rows):
            return None
    except (TypeError, ValueError, ValidationError):
        return None
    return OperatorRoomSetReference(
        organization_id, edition_id, tuple(OperatorRoomCandidate(*row) for row in rows)
    )


def resolve_operator_room_choice_reference(
    *, organization_id: UUID, edition_id: UUID, space_id: UUID
) -> OperatorRoomChoiceReference | None:
    """Read one minimal room label after independent exact-purpose admission.

    Parameters
    ----------
    organization_id : UUID
        Exact expected organization owner.
    edition_id : UUID
        Exact current edition owner.
    space_id : UUID
        Exact selected room already independently admitted by the consumer.

    Returns
    -------
    OperatorRoomChoiceReference | None
        Current source and minimal labels, or None for invalid or unavailable scope.

    Notes
    -----
    The caller rechecks operator policy, source and required audit before disclosing
    the labels. No layout, configuration, contacts, personnel or instructions are
    selected; this reference grants no authority and performs no discovery.
    """
    if any(
        type(value) is not UUID or not value.int
        for value in (organization_id, edition_id, space_id)
    ):
        return None
    try:
        row = (
            _coherent(
                _current(organization_id, edition_id), organization_id, edition_id
            )
            .filter(id=space_id)
            .values_list(*_SOURCE_FIELDS, "local_name", "venue_selection__local_name")
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        return None
    if row is None:
        return None
    return OperatorRoomChoiceReference(OperatorRoomCandidate(*row[:5]), row[5], row[6])
