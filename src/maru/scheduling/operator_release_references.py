"""Checked approved geometry reduced to a freshly authorized operator purpose."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.events.scheduling_queries import resolve_scheduling_edition_reference
from maru.venues.operator_queries import load_operator_room_links
from maru.workforce.operator_links import (
    load_operator_department_work_links,
    operator_staffing_adopted,
)

from .catalogs import MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError
from .models import SchedulingPlacementRevision, SchedulingRelease
from .operator_scope import OperatorReadRequest, OperatorScopeKind, operator_read
from .release_queries import ProgrammeReleaseManifest, ProgrammeReleaseState, _manifest
from .time_rules import SchedulingEnvelope

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class OperatorReleaseOccurrence:
    """Exact approved phases and opaque owner references, excluding private copy.

    Attributes
    ----------
    occurrence_id
        Stable released occurrence within the exact purpose.
    placement_id
        Selected immutable placement identity.
    item_id
        Opaque Programme source; no private-content authority is implied.
    public_rendition_id
        Exact selected reviewed copy; latest-copy substitution is forbidden.
    space_id
        Exact room; its current names require independent Venue authority.
    day_id
        Stable selected service-day identity without a private planning label.
    day_starts_at
        Selected immutable service-day start.
    day_ends_at
        Selected immutable service-day end.
    envelope
        Approved preparation, effective delivery and teardown context.
    """

    occurrence_id: UUID
    placement_id: UUID
    item_id: UUID
    public_rendition_id: UUID
    space_id: UUID
    day_id: UUID
    day_starts_at: datetime
    day_ends_at: datetime
    envelope: SchedulingEnvelope


@dataclass(frozen=True, slots=True)
class OperatorReleaseReference:
    """Only in-purpose approved references, never the complete private manifest.

    Attributes
    ----------
    state
        Fresh complete canonical/native release state.
    pointer_version
        Exact active pointer version, not an approval of current owner text.
    release_id
        Exact active release identity where one has been selected.
    published_at
        Immutable release creation instant where applicable.
    zone_name
        Current Events-owned IANA zone.
    staffing_adopted
        Whether the independent Programme staffing adapter is currently adopted.
    occurrences
        Complete deterministic in-purpose selection; empty while nonavailable.
    """

    state: ProgrammeReleaseState
    pointer_version: int
    release_id: UUID | None
    published_at: datetime | None
    zone_name: str
    staffing_adopted: bool
    occurrences: tuple[OperatorReleaseOccurrence, ...]


def _geometry(
    request: OperatorReadRequest,
    manifest: ProgrammeReleaseManifest,
    rooms: set[UUID],
    work: set[UUID],
) -> tuple[OperatorReleaseOccurrence, ...]:
    if manifest.state is not ProgrammeReleaseState.AVAILABLE:
        return ()
    selected = {row.placement_id: row for row in manifest.selections}
    rows = tuple(
        SchedulingPlacementRevision.objects.filter(
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            id__in=selected,
            occurrence_revision__organization_id=request.organization_id,
            occurrence_revision__edition_id=request.edition_id,
            occurrence_revision__occurrence__organization_id=request.organization_id,
            occurrence_revision__occurrence__edition_id=request.edition_id,
            day_revision__organization_id=request.organization_id,
            day_revision__edition_id=request.edition_id,
        )
        .order_by("effective_starts_at", "occurrence_revision__occurrence_id")
        .values_list(
            "id",
            "occurrence_revision__occurrence_id",
            "occurrence_revision__occurrence__programme_item_id",
            "space_selection_id",
            "day_revision__day_id",
            "day_revision__starts_at",
            "day_revision__ends_at",
            "setup_starts_at",
            "effective_starts_at",
            "effective_ends_at",
            "teardown_ends_at",
        )[: MAX_OCCURRENCES + 1]
    )
    if not 1 <= len(rows) == len(selected) <= MAX_OCCURRENCES:
        raise SchedulingUnavailableError
    result = []
    for (
        placement,
        occurrence,
        item,
        space,
        day,
        day_start,
        day_end,
        setup,
        start,
        end,
        teardown,
    ) in rows:
        selection = selected[placement]
        if (
            selection.occurrence_id != occurrence
            or not day_start <= setup <= start < end <= teardown <= day_end
        ):
            raise SchedulingUnavailableError
        if (
            request.kind is OperatorScopeKind.EDITION
            or space in rooms
            or occurrence in work
        ):
            result.append(
                OperatorReleaseOccurrence(
                    occurrence,
                    placement,
                    item,
                    selection.public_rendition_id,
                    space,
                    day,
                    day_start,
                    day_end,
                    SchedulingEnvelope(setup, start, end, teardown),
                )
            )
    return tuple(result)


def load_operator_release_reference(
    request: OperatorReadRequest,
) -> OperatorReleaseReference:
    """Recheck canonical release and independent current purpose membership.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact persisted target, never caller-selected release/manifest authority.

    Returns
    -------
    OperatorReleaseReference
        Only authorized approved geometry, with explicit nonavailable states.

    Raises
    ------
    SchedulingUnavailableError
        For incomplete, oversized or changing owner/release evidence.

    Notes
    -----
    Independent scope/field denial propagates SchedulingAuthorizationDeniedError.
    Department work membership requires Workforce scope_links even without a
    detailed staffing request. An unadopted staffing adapter means rooms only.
    The full manifest is verified internally, never returned with an operator
    projection. No public, planning, host or candidate query is used as authority.
    """
    with operator_read(
        request,
        capability="scheduling.view_operator_output",
        fields=frozenset({"released_geometry"}),
    ):
        ownership = {
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
        }
        edition = resolve_scheduling_edition_reference(
            organization_id=request.organization_id, edition_id=request.edition_id
        )
        if edition is None:
            raise SchedulingUnavailableError
        rooms = load_operator_room_links(request)
        staffing = operator_staffing_adopted(request)
        links = (
            load_operator_department_work_links(request)
            if staffing and request.kind is OperatorScopeKind.DEPARTMENT
            else ()
        )
        manifest = _manifest(**ownership, release_id=None)
        occurrences = _geometry(
            request,
            manifest,
            {room.space_id for room in rooms},
            {link.occurrence_id for link in links},
        )
        published_at = None
        if manifest.release_id is not None:
            published_at = (
                SchedulingRelease.objects.filter(**ownership, id=manifest.release_id)
                .values_list("occurred_at", flat=True)
                .first()
            )
            if published_at is None:
                raise SchedulingUnavailableError
        if (
            load_operator_room_links(request) != rooms
            or operator_staffing_adopted(request) != staffing
            or (
                staffing
                and request.kind is OperatorScopeKind.DEPARTMENT
                and load_operator_department_work_links(request) != links
            )
            or resolve_scheduling_edition_reference(
                organization_id=request.organization_id, edition_id=request.edition_id
            )
            != edition
            or _manifest(**ownership, release_id=None) != manifest
        ):
            raise SchedulingUnavailableError
        return OperatorReleaseReference(
            manifest.state,
            manifest.pointer_version,
            manifest.release_id,
            published_at,
            edition.zone_name,
            staffing,
            occurrences,
        )
