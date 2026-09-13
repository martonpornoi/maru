"""Venue-owned current operator membership and minimized room wayfinding."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_scope import (
    OperatorReadRequest,
    OperatorScopeKind,
    operator_read,
)

from .models import EditionSpaceSelection
from .programme_output_queries import ReleasedRoomWayfinding
from .scheduling_queries import MAX_SCHEDULING_SPACE_SELECTIONS

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class OperatorRoomLink:
    """Opaque current responsibility; never room names or wider discovery rights.

    Attributes
    ----------
    space_id
        Exact active selected room identity.
    version
        Current room version, including its responsibility relationship.
    """

    space_id: UUID
    version: int


def load_operator_room_links(
    request: OperatorReadRequest,
) -> tuple[OperatorRoomLink, ...]:
    """Resolve complete current room membership under independent Venue authority.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact operator purpose, independently resolved and authorized here.

    Returns
    -------
    tuple[OperatorRoomLink, ...]
        Stable bounded active room membership; no descendants or shared members.

    Raises
    ------
    SchedulingUnavailableError
        If membership exceeds its completeness bound or the selected room moves.

    Notes
    -----
    Operator admission propagates a uniform SchedulingAuthorizationDeniedError.
    This content-free seam does not call Scheduling release queries, avoiding a
    recursive owner projection. Programme item ownership is never inferred.
    """
    with operator_read(
        request,
        capability="venues.view_operator_wayfinding",
        fields=frozenset({"scope_links"}),
    ):
        filters = {}
        if request.kind is OperatorScopeKind.ROOM:
            filters["id"] = request.target_id
        elif request.kind is OperatorScopeKind.DEPARTMENT:
            filters["responsible_department_id"] = request.target_id
        rows = tuple(
            EditionSpaceSelection.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                venue_selection__organization_id=request.organization_id,
                venue_selection__edition_id=request.edition_id,
                responsible_department__organization_id=request.organization_id,
                responsible_department__edition_id=request.edition_id,
                responsible_department__retired_at__isnull=True,
                lifecycle=EditionSpaceSelection.Lifecycle.ACTIVE,
                **filters,
            )
            .order_by("id")
            .values_list("id", "aggregate_version")[
                : MAX_SCHEDULING_SPACE_SELECTIONS + 1
            ]
        )
        if len(rows) > MAX_SCHEDULING_SPACE_SELECTIONS or (
            request.kind is OperatorScopeKind.ROOM and len(rows) != 1
        ):
            raise SchedulingUnavailableError
        return tuple(OperatorRoomLink(*row) for row in rows)


def load_operator_wayfinding(
    request: OperatorReadRequest, *, expected_release_id: UUID | None
) -> tuple[ReleasedRoomWayfinding, ...]:
    """Select only current labels for independently resolved in-purpose occurrences.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact operator target with trusted attribution, not an accepted manifest.
    expected_release_id : UUID | None
        Optimistic current release identity, not authority to read its content.

    Returns
    -------
    tuple[ReleasedRoomWayfinding, ...]
        Complete minimal current owner labels, with their own versions.

    Raises
    ------
    SchedulingUnavailableError
        If release identity, room ownership, completeness or source checks fail.

    Notes
    -----
    Independent Venue authority is required even for an empty approved scope.
    Release/admission exceptions propagate without identifying the denied layer.
    No layouts, contact details, physical membership or restrictions are selected.
    """
    from maru.scheduling.operator_release_references import (  # noqa: PLC0415
        load_operator_release_reference,
    )

    with operator_read(
        request,
        capability="venues.view_operator_wayfinding",
        fields=frozenset({"wayfinding"}),
    ):
        reference = load_operator_release_reference(request)
        if reference.release_id != expected_release_id:
            raise SchedulingUnavailableError
        selected = {row.space_id for row in reference.occurrences}
        rows = tuple(
            EditionSpaceSelection.objects.filter(
                organization_id=request.organization_id,
                edition_id=request.edition_id,
                venue_selection__organization_id=request.organization_id,
                venue_selection__edition_id=request.edition_id,
                id__in=selected,
            )
            .order_by("id")
            .values_list(
                "id",
                "aggregate_version",
                "venue_selection__aggregate_version",
                "local_name",
                "venue_selection__local_name",
            )[: len(selected) + 1]
        )
        if (
            len(rows) != len(selected)
            or load_operator_release_reference(request) != reference
        ):
            raise SchedulingUnavailableError
        return tuple(ReleasedRoomWayfinding(*row) for row in rows)
