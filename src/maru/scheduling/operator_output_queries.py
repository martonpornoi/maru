"""Compose one complete purpose-scoped Programme run sheet, never a planner dump."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.utils import timezone

from maru.programme.operator_queries import (
    OperatorDeliveryInstructions,
    load_operator_delivery_instructions,
    load_operator_programme_copy,
)
from maru.programme.output_queries import ReleasedProgrammeCopy
from maru.venues.operator_queries import load_operator_wayfinding
from maru.venues.programme_output_queries import ReleasedRoomWayfinding
from maru.workforce.operator_queries import (
    OperatorStaffingSnapshot,
    load_operator_staffing,
)

from .authorization import SchedulingAuthorizationDeniedError
from .command_support import SchedulingUnavailableError
from .operator_release_references import (
    OperatorReleaseOccurrence,
    OperatorReleaseReference,
    load_operator_release_reference,
)
from .operator_scope import OperatorReadRequest, OperatorScopeKind, operator_read

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

OPERATOR_OPTIONAL_LAYERS = frozenset(
    {"technical", "accessibility", "media", "staffing"}
)


@dataclass(frozen=True, slots=True)
class OperatorRunSheetEntry:
    """Approved context plus independently authorized and versioned owner content.

    Attributes
    ----------
    placement
        Exact released in-purpose geometry, not a draft or work assignment.
    copy
        Exact selected reviewed Programme rendition, never latest-copy fallback.
    room
        Current room/venue wayfinding and its own versions.
    delivery
        Only requested current delivery instructions, or None when unrequested.
    """

    placement: OperatorReleaseOccurrence
    copy: ReleasedProgrammeCopy
    room: ReleasedRoomWayfinding
    delivery: OperatorDeliveryInstructions | None


@dataclass(frozen=True, slots=True)
class OperatorRunSheet:
    """Complete checked private operator projection, not an offline freshness lease.

    Attributes
    ----------
    organization_id
        Exact authorized organization owner.
    edition_id
        Exact authorized edition, never a cross-edition discovery request.
    kind
        Closed operator purpose: room, Department or edition.
    target_id
        Exact independently resolved persisted target.
    layers
        Explicitly requested optional layers; default is no private extra fields.
    checked_at
        Server observation after all owner and release rechecks.
    reference
        Checked state, source identity and in-purpose approved geometry only.
    entries
        Complete deterministic approved rows, empty in nonavailable release states.
    staffing
        Complete requested owner layer, or None when unrequested.
    """

    organization_id: UUID
    edition_id: UUID
    kind: OperatorScopeKind
    target_id: UUID
    layers: frozenset[str]
    checked_at: datetime
    reference: OperatorReleaseReference
    entries: tuple[OperatorRunSheetEntry, ...]
    staffing: OperatorStaffingSnapshot | None


@dataclass(frozen=True, slots=True)
class _OwnerLayers:
    copies: tuple[ReleasedProgrammeCopy, ...]
    rooms: tuple[ReleasedRoomWayfinding, ...]
    delivery: tuple[OperatorDeliveryInstructions, ...] | None
    staffing: OperatorStaffingSnapshot | None


def _owners(
    request: OperatorReadRequest, release_id: UUID | None, layers: frozenset[str]
) -> _OwnerLayers:
    delivery_fields = layers - {"staffing"}
    result = _OwnerLayers(
        load_operator_programme_copy(request, expected_release_id=release_id),
        load_operator_wayfinding(request, expected_release_id=release_id),
        load_operator_delivery_instructions(
            request, expected_release_id=release_id, fields=delivery_fields
        )
        if delivery_fields
        else None,
        load_operator_staffing(request, expected_release_id=release_id)
        if "staffing" in layers
        else None,
    )
    if (
        type(result.copies) is not tuple
        or type(result.rooms) is not tuple
        or (delivery_fields and type(result.delivery) is not tuple)
        or (
            "staffing" in layers
            and type(result.staffing) is not OperatorStaffingSnapshot
        )
    ):
        raise SchedulingUnavailableError
    return result


def _entries(
    reference: OperatorReleaseReference, owners: _OwnerLayers
) -> tuple[OperatorRunSheetEntry, ...]:
    if (
        any(type(row) is not ReleasedProgrammeCopy for row in owners.copies)
        or any(type(row) is not ReleasedRoomWayfinding for row in owners.rooms)
        or any(
            type(row) is not OperatorDeliveryInstructions
            for row in owners.delivery or ()
        )
        or (
            owners.staffing is not None
            and type(owners.staffing) is not OperatorStaffingSnapshot
        )
    ):
        raise SchedulingUnavailableError
    copies = {row.rendition_id: row for row in owners.copies}
    rooms = {row.space_id: row for row in owners.rooms}
    delivery = {row.item_id: row for row in owners.delivery or ()}
    if (
        len(copies) != len(owners.copies)
        or len(rooms) != len(owners.rooms)
        or copies.keys() != {row.public_rendition_id for row in reference.occurrences}
        or rooms.keys() != {row.space_id for row in reference.occurrences}
        or (
            owners.delivery is not None
            and (
                len(delivery) != len(owners.delivery)
                or delivery.keys() != {row.item_id for row in reference.occurrences}
            )
        )
        or (
            owners.staffing is not None
            and owners.staffing.adopted != reference.staffing_adopted
        )
    ):
        raise SchedulingUnavailableError
    return tuple(
        OperatorRunSheetEntry(
            row,
            copies[row.public_rendition_id],
            rooms[row.space_id],
            delivery.get(row.item_id),
        )
        for row in reference.occurrences
    )


def load_operator_run_sheet(
    request: OperatorReadRequest, *, layers: frozenset[str] = frozenset()
) -> OperatorRunSheet:
    """Materialize exactly the requested complete operator run sheet through owners.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact persisted purpose and authenticated attribution, not a filter grant.
    layers : frozenset[str], default=frozenset()
        Closed optional technical/accessibility/media/staffing fields. Each
        requested owner must independently authorize even an empty approved scope.

    Returns
    -------
    OperatorRunSheet
        Complete freshly checked purpose-specific output with explicit layer state.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If any requested purpose or layer is unknown, unadmitted or denied.
    SchedulingUnavailableError
        If owner evidence is incomplete or changes before the complete read finishes.

    Notes
    -----
    No automatic optional-layer selection, partial-success fallback, anonymous
    payload augmentation, registration/attendance query or work mutation occurs.
    Owners re-resolve the release themselves. Final owner materialization checks
    their own current versions and authority after composition, so a late changed
    instruction or wayfinding name cannot slip through a release-only recheck.
    """
    with operator_read(
        request,
        capability="scheduling.view_operator_output",
        fields=frozenset({"released_geometry"}),
    ):
        if type(layers) is not frozenset or not layers <= OPERATOR_OPTIONAL_LAYERS:
            raise SchedulingAuthorizationDeniedError
        reference = load_operator_release_reference(request)
        owners = _owners(request, reference.release_id, layers)
        entries = _entries(reference, owners)
        if (
            _owners(request, reference.release_id, layers) != owners
            or load_operator_release_reference(request) != reference
        ):
            raise SchedulingUnavailableError
        return OperatorRunSheet(
            request.organization_id,
            request.edition_id,
            request.kind,
            request.target_id,
            layers,
            timezone.now(),
            reference,
            entries,
            owners.staffing,
        )
