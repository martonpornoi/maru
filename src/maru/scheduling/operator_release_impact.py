"""Independently scoped operator release transitions without a recipient directory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maru.venues.operator_queries import load_operator_room_links
from maru.workforce.operator_links import (
    load_operator_department_work_links,
    operator_staffing_adopted,
)

from .catalogs import MAX_OCCURRENCES
from .command_support import SchedulingUnavailableError
from .models import SchedulingRelease
from .operator_release_references import _geometry
from .operator_scope import OperatorReadRequest, OperatorScopeKind, operator_read
from .release_impact import ReleaseSelectionChangeKind
from .release_queries import ProgrammeReleaseState, _manifest

if TYPE_CHECKING:
    from uuid import UUID

    from maru.venues.operator_queries import OperatorRoomLink
    from maru.workforce.operator_links import OperatorWorkLink

    from .operator_release_references import OperatorReleaseOccurrence


@dataclass(frozen=True, slots=True)
class OperatorOccurrenceChange:
    """Membership and geometry changes within one currently authorized purpose.

    Attributes
    ----------
    occurrence_id
        Stable occurrence present in at least one independently filtered side.
    kind
        Addition/removal/change within this scope, not global event cancellation.
    before
        Prior in-scope geometry; None also covers movement into the scope.
    after
        Current in-scope geometry; None also covers movement out of the scope.
    changed_fields
        Closed reference/day/room/phase names, only when both sides are in scope.
        An omitted side never reveals its destination or other source fields.
    """

    occurrence_id: UUID
    kind: ReleaseSelectionChangeKind
    before: OperatorReleaseOccurrence | None
    after: OperatorReleaseOccurrence | None
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OperatorReleaseImpact:
    """Checked purpose-specific transition with current owner membership versions.

    Attributes
    ----------
    kind
        Exact admitted room, Department or edition purpose.
    target_id
        Exact persisted authorized purpose target.
    state
        Current active release state, not a cached last-good value.
    pointer_version
        Current publication/withdrawal sequence checked around both sides.
    release_id
        Current active release identity where present.
    previous_release_id
        Current publication's retained predecessor, never caller-selected history.
    previous_state
        Checked predecessor state, absent on first publication, otherwise None
        when current governing state prevents predecessor lookup.
    room_links
        Complete current authorized room membership with independent owner versions.
    staffing_adopted
        Explicit optional staffing adoption, not an inference from empty work.
    work_links
        Current/retained Department lineage only when applicable and independently
        authorized; opaque references, not personnel or accepted work intervals.
    changes
        Complete in-scope union or None on governing suppression. Empty means
        an available complete comparison has no occurrences in this purpose.
    """

    kind: OperatorScopeKind
    target_id: UUID
    state: ProgrammeReleaseState
    pointer_version: int
    release_id: UUID | None
    previous_release_id: UUID | None
    previous_state: ProgrammeReleaseState | None
    room_links: tuple[OperatorRoomLink, ...]
    staffing_adopted: bool
    work_links: tuple[OperatorWorkLink, ...]
    changes: tuple[OperatorOccurrenceChange, ...] | None


def _fields(
    before: OperatorReleaseOccurrence, after: OperatorReleaseOccurrence
) -> tuple[str, ...]:
    return tuple(
        field
        for field in (
            "placement_id",
            "public_rendition_id",
            "space_id",
            "day_id",
            "day_starts_at",
            "day_ends_at",
        )
        if getattr(before, field) != getattr(after, field)
    ) + tuple(
        field
        for field in (
            "setup_starts_at",
            "effective_starts_at",
            "effective_ends_at",
            "teardown_ends_at",
        )
        if getattr(before.envelope, field) != getattr(after.envelope, field)
    )


def _compare(
    before: tuple[OperatorReleaseOccurrence, ...],
    after: tuple[OperatorReleaseOccurrence, ...],
) -> tuple[OperatorOccurrenceChange, ...]:
    prior = {row.occurrence_id: row for row in before}
    current = {row.occurrence_id: row for row in after}
    if (
        len(before) != len(prior)
        or len(after) != len(current)
        or max(len(prior), len(current)) > MAX_OCCURRENCES
    ):
        raise SchedulingUnavailableError
    result = []
    for occurrence in sorted(prior.keys() | current.keys()):
        old, new = prior.get(occurrence), current.get(occurrence)
        if old is not None and new is not None and old.item_id != new.item_id:
            raise SchedulingUnavailableError
        fields = _fields(old, new) if old is not None and new is not None else ()
        kind = (
            ReleaseSelectionChangeKind.ADDED
            if old is None
            else ReleaseSelectionChangeKind.REMOVED
            if new is None
            else ReleaseSelectionChangeKind.CHANGED
            if fields
            else ReleaseSelectionChangeKind.UNCHANGED
        )
        result.append(OperatorOccurrenceChange(occurrence, kind, old, new, fields))
    return tuple(result)


def load_operator_release_impact(request: OperatorReadRequest) -> OperatorReleaseImpact:
    """Compare each side inside fresh independent room/Department/edition authority.

    Parameters
    ----------
    request : OperatorReadRequest
        Exact persisted purpose with trusted actor and trace, never permission
        to read a different scope, arbitrary history or another recipient.

    Returns
    -------
    OperatorReleaseImpact
        Complete minimized geometry transition and current owner membership proof.

    Raises
    ------
    SchedulingUnavailableError
        If owner or native evidence is incomplete, oversized, inconsistent or moving.

    Notes
    -----
    Independent scope/field denial propagates SchedulingAuthorizationDeniedError.
    Both sides use current purpose membership, not old grants or inferred item
    ownership. A move across the boundary exposes only the admitted side. Copy
    references grant no text authority. Canonical parents, final owner/source
    rechecks and mandatory owner audits precede disclosure. No personnel, private
    copy, accepted intervals, contact, delivery or acknowledgement is returned;
    retained work is never altered by this read.
    """
    with operator_read(
        request,
        capability="scheduling.view_operator_output",
        fields=frozenset({"released_geometry"}),
    ):
        rooms = load_operator_room_links(request)
        staffing = operator_staffing_adopted(request)
        links = (
            load_operator_department_work_links(request)
            if staffing and request.kind is OperatorScopeKind.DEPARTMENT
            else ()
        )
        ownership = {
            "organization_id": request.organization_id,
            "edition_id": request.edition_id,
        }
        current = _manifest(**ownership, release_id=None)
        previous = None
        previous_id = None
        changes = None
        if current.state is ProgrammeReleaseState.AVAILABLE:
            if current.release_id is None or not current.is_active:
                raise SchedulingUnavailableError
            release = (
                SchedulingRelease.objects.filter(
                    **ownership,
                    id=current.release_id,
                )
                .only("id", "previous_release_id", "pointer_version")
                .first()
            )
            if release is None or release.pointer_version != current.pointer_version:
                raise SchedulingUnavailableError
            previous_id = release.previous_release_id
            previous = (
                _manifest(**ownership, release_id=previous_id)
                if previous_id is not None
                else None
            )
            if (
                previous is not None
                and previous.pointer_version != current.pointer_version
            ):
                raise SchedulingUnavailableError
            if previous is None or previous.state is ProgrammeReleaseState.AVAILABLE:
                room_ids = {room.space_id for room in rooms}
                work_ids = {link.occurrence_id for link in links}
                before = (
                    _geometry(request, previous, room_ids, work_ids)
                    if previous is not None
                    else ()
                )
                after = _geometry(request, current, room_ids, work_ids)
                changes = _compare(before, after)
        if (
            load_operator_room_links(request) != rooms
            or operator_staffing_adopted(request) != staffing
            or (
                staffing
                and request.kind is OperatorScopeKind.DEPARTMENT
                and load_operator_department_work_links(request) != links
            )
            or (
                previous is not None
                and _manifest(**ownership, release_id=previous_id) != previous
            )
            or _manifest(**ownership, release_id=None) != current
        ):
            raise SchedulingUnavailableError
        return OperatorReleaseImpact(
            request.kind,
            request.target_id,
            current.state,
            current.pointer_version,
            current.release_id,
            previous_id,
            previous.state
            if previous
            else (
                ProgrammeReleaseState.ABSENT
                if current.state is ProgrammeReleaseState.AVAILABLE
                else None
            ),
            rooms,
            staffing,
            links,
            changes,
        )
