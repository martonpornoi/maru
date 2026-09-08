"""Complete board composition from independently authorized owner projections."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .command_support import SchedulingUnavailableError

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from maru.programme.queries import ProgrammeTimetableItemProjection
    from maru.venues.timetable_queries import VenueTimetableSpace

    from .planning_queries import (
        PlanningCandidate,
        PlanningDay,
        PlanningOccurrence,
        PlanningPlacement,
        SchedulingPlanningSnapshot,
    )


class PlanningInventoryState(StrEnum):
    """Visible inventory states, not item acceptance or release decisions."""

    NO_OCCURRENCE = "no_occurrence"
    NO_CANDIDATE = "no_candidate"
    UNPLACED = "unplaced"
    PLACED = "placed"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True)
class PlanningBoardEntry:
    """One explicit occurrence, or an item which has no occurrence yet.

    Attributes
    ----------
    key
        Stable page identity, independent of current title or placement revision.
    item
        Already-authorized Programme title and current item facts, no other layer.
    state
        Explicit inventory consequence in the selected private draft.
    occurrence
        Exact occurrence, or none for an item before occurrence creation.
    placement
        Selected candidate geometry, or none when not placed there.
    day
        Current day context, even when the placement references older metadata.
    space
        Separately authorized current room labels; never availability proof.
    metadata_changed
        Selected day/occurrence revision differs from current owner metadata.
    """

    key: str
    item: ProgrammeTimetableItemProjection
    state: PlanningInventoryState
    occurrence: PlanningOccurrence | None
    placement: PlanningPlacement | None
    day: PlanningDay | None
    space: VenueTimetableSpace | None
    metadata_changed: bool


@dataclass(frozen=True, slots=True)
class PlanningBoardLane:
    """One labelled day/room lane with an ordered complete placement list.

    Attributes
    ----------
    day
        Current stable service-day context and explicit zone-independent window.
    space
        Authorized room labels, not a physical reservation.
    entries
        Every selected placement in this lane, including retired/stale records.
    """

    day: PlanningDay
    space: VenueTimetableSpace
    entries: tuple[PlanningBoardEntry, ...]


@dataclass(frozen=True, slots=True)
class SchedulingPlanningBoard:
    """One private draft's complete labelled inventory and ordered board.

    Attributes
    ----------
    candidate
        Selected candidate summary, or none before deliberate selection.
    zone_name
        Events-owned IANA time zone, never the browser's inferred zone.
    entries
        Complete inventory, including items before occurrence creation.
    lanes
        Nonempty day/room lanes; empty destinations remain available in native forms.
    days
        Complete current/retired day choices, including days with no placements.
    spaces
        Complete independently authorized room choices, including unused rooms.
    """

    candidate: PlanningCandidate | None
    zone_name: str
    entries: tuple[PlanningBoardEntry, ...]
    lanes: tuple[PlanningBoardLane, ...]
    days: tuple[PlanningDay, ...]
    spaces: tuple[VenueTimetableSpace, ...]


def _entry(
    item: ProgrammeTimetableItemProjection,
    occurrence: PlanningOccurrence | None,
    placement: PlanningPlacement | None,
    day: PlanningDay | None,
    space: VenueTimetableSpace | None,
    *,
    selected: bool,
) -> PlanningBoardEntry:
    if item.item.lifecycle == "retired" or (
        occurrence and occurrence.lifecycle == "retired"
    ):
        state = PlanningInventoryState.RETIRED
    elif occurrence is None:
        state = PlanningInventoryState.NO_OCCURRENCE
    elif not selected:
        state = PlanningInventoryState.NO_CANDIDATE
    elif placement is None:
        state = PlanningInventoryState.UNPLACED
    else:
        state = PlanningInventoryState.PLACED
    return PlanningBoardEntry(
        f"occurrence-{occurrence.id.hex}" if occurrence else f"item-{item.item.id.hex}",
        item,
        state,
        occurrence,
        placement,
        day,
        space,
        bool(
            placement
            and occurrence
            and day
            and (
                placement.day_revision_id != day.revision_id
                or placement.occurrence_revision_id != occurrence.revision_id
            )
        ),
    )


def build_scheduling_planning_board(
    snapshot: SchedulingPlanningSnapshot,
    *,
    items: tuple[ProgrammeTimetableItemProjection, ...],
    spaces: tuple[VenueTimetableSpace, ...],
) -> SchedulingPlanningBoard:
    """Compose complete owner reads without inventing labels or hiding retained work.

    This pure function grants no authority and performs no reads or writes.
    Callers must obtain each input through its independently audited owner query.
    Missing/duplicate references withhold the whole composition rather than
    presenting a partial inventory as an empty or complete programme.

    Parameters
    ----------
    snapshot : SchedulingPlanningSnapshot
        Complete scoped day, occurrence and selected candidate projection.
    items : tuple[ProgrammeTimetableItemProjection, ...]
        Complete independently authorized Programme working-title inventory.
    spaces : tuple[VenueTimetableSpace, ...]
        Complete independently authorized Venue-room label inventory.

    Returns
    -------
    SchedulingPlanningBoard
        Stable complete inventory and day/room lanes ordered by exact instants.

    Raises
    ------
    SchedulingUnavailableError
        If projections contain duplicate, missing or inconsistent selected references.
    """
    item_map = {item.item.id: item for item in items}
    space_map = {space.id: space for space in spaces}
    day_map = {day.id: day for day in snapshot.days}
    candidate_map = {candidate.id: candidate for candidate in snapshot.candidates}
    occurrences = {occurrence.id: occurrence for occurrence in snapshot.occurrences}
    placements = {
        placement.occurrence_id: placement for placement in snapshot.placements
    }
    for index, values in (
        (item_map, items),
        (space_map, spaces),
        (day_map, snapshot.days),
        (candidate_map, snapshot.candidates),
        (occurrences, snapshot.occurrences),
        (placements, snapshot.placements),
    ):
        if len(index) != len(values):
            raise SchedulingUnavailableError
    candidate = (
        candidate_map.get(snapshot.selected_candidate_id)
        if snapshot.selected_candidate_id
        else None
    )
    if (
        (snapshot.selected_candidate_id and candidate is None)
        or (not candidate and placements)
        or (candidate and candidate.placement_count != len(placements))
    ):
        raise SchedulingUnavailableError
    if set(placements) - set(occurrences):
        raise SchedulingUnavailableError
    entries = []
    used_items: set[UUID] = set()
    for occurrence in snapshot.occurrences:
        item = item_map.get(occurrence.item_id)
        placement = placements.get(occurrence.id)
        day = day_map.get(placement.day_id) if placement else None
        space = space_map.get(placement.space_id) if placement else None
        if item is None or (placement and (day is None or space is None)):
            raise SchedulingUnavailableError
        entries.append(
            _entry(
                item, occurrence, placement, day, space, selected=candidate is not None
            )
        )
        used_items.add(occurrence.item_id)
    entries.extend(
        _entry(item, None, None, None, None, selected=candidate is not None)
        for item in items
        if item.item.id not in used_items
    )
    ordered = tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.item.internal_title.casefold(),
                entry.occurrence.group_sequence or 0 if entry.occurrence else 0,
                entry.key,
            ),
        )
    )
    lane_map: dict[tuple[UUID, UUID], list[PlanningBoardEntry]] = {}
    for entry in ordered:
        if entry.placement and entry.day and entry.space:
            lane_map.setdefault((entry.day.id, entry.space.id), []).append(entry)
    lanes = tuple(
        PlanningBoardLane(
            day,
            space,
            tuple(
                sorted(
                    lane_map[(day.id, space.id)],
                    key=_placement_order,
                )
            ),
        )
        for day in sorted(snapshot.days, key=lambda day: (day.window.starts_at, day.id))
        for space in sorted(
            spaces, key=lambda space: (space.venue_label, space.label, space.id)
        )
        if (day.id, space.id) in lane_map
    )
    return SchedulingPlanningBoard(
        candidate, snapshot.zone_name, ordered, lanes, snapshot.days, spaces
    )


def _placement_order(entry: PlanningBoardEntry) -> tuple[datetime, str]:
    if entry.placement is None:
        raise SchedulingUnavailableError
    return entry.placement.envelope.effective_starts_at, entry.key
