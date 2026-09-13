"""Exact released-selection differences, never serving or recipient authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from .release_artifacts import ReleaseArtifactSelection, _selections

if TYPE_CHECKING:
    from uuid import UUID


class ReleaseSelectionChangeKind(StrEnum):
    """Closed membership consequences of two exact canonical selections."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True, slots=True)
class ReleaseSelectionChange:
    """One stable occurrence and its exact before/after references.

    Attributes
    ----------
    occurrence_id
        Stable Scheduling occurrence, never matched by a mutable display label.
    kind
        Added, removed, changed or unchanged membership.
    before
        Earlier exact placement/copy selection, absent for an addition.
    after
        Later exact placement/copy selection, absent for a removal.
    changed_fields
        Placement and/or reviewed-copy reference changes for retained occurrences.
        A placement reference change alone does not prove a time or room move.
    """

    occurrence_id: UUID
    kind: ReleaseSelectionChangeKind
    before: ReleaseArtifactSelection | None
    after: ReleaseArtifactSelection | None
    changed_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReleaseSelectionImpact:
    """Complete bounded comparison, including unchanged occurrences.

    Attributes
    ----------
    changes
        Deterministic stable-occurrence ordering, independent of input ordering.
    added_count
        Number of occurrences present only in the later selection.
    changed_count
        Number retained with different exact placement or reviewed-copy references.
    removed_count
        Number of occurrences present only in the earlier selection.
    """

    changes: tuple[ReleaseSelectionChange, ...]
    added_count: int
    changed_count: int
    removed_count: int


def compare_release_selections(  # noqa: DOC502 - Canonical selection validation propagates.
    *,
    before: tuple[ReleaseArtifactSelection, ...],
    after: tuple[ReleaseArtifactSelection, ...],
) -> ReleaseSelectionImpact:
    """Compare complete exact selections without reading or mutating any owner.

    Parameters
    ----------
    before : tuple[ReleaseArtifactSelection, ...]
        Complete earlier selection; an empty tuple represents no earlier members.
    after : tuple[ReleaseArtifactSelection, ...]
        Complete later selection; an empty tuple represents no later members.

    Returns
    -------
    ReleaseSelectionImpact
        Closed reference differences and counts with no person or private content.

    Raises
    ------
    ReleaseArtifactInvalidError
        If either nonempty selection fails canonical type, identity, uniqueness
        or complete-manifest bounds. Lists and other non-tuple inputs also fail.

    Notes
    -----
    This pure function establishes no tenant, release authenticity, freshness,
    disclosure, delivery or acknowledgement. The owning command/query must
    authenticate both selections and their shared scope. Unavailable or withheld
    evidence must never be supplied as an empty selection to imply removals.
    Publication uses these same counts; later governed readers must separately
    resolve time/room differences and authorized affected purposes. No Shift is
    cancelled, moved, confirmed or acknowledged by a selection difference.
    """
    for rows in (before, after):
        if type(rows) is not tuple or rows:
            _selections(rows)
    old = {row.occurrence_id: row for row in before}
    new = {row.occurrence_id: row for row in after}
    changes = []
    for occurrence in sorted(old.keys() | new.keys(), key=str):
        previous, following = old.get(occurrence), new.get(occurrence)
        fields: tuple[str, ...] = ()
        if previous is None:
            kind = ReleaseSelectionChangeKind.ADDED
        elif following is None:
            kind = ReleaseSelectionChangeKind.REMOVED
        elif previous == following:
            kind = ReleaseSelectionChangeKind.UNCHANGED
        else:
            kind = ReleaseSelectionChangeKind.CHANGED
            fields = tuple(
                name
                for name in ("placement_id", "public_rendition_id")
                if getattr(previous, name) != getattr(following, name)
            )
        changes.append(
            ReleaseSelectionChange(occurrence, kind, previous, following, fields)
        )
    return ReleaseSelectionImpact(
        tuple(changes),
        sum(row.kind is ReleaseSelectionChangeKind.ADDED for row in changes),
        sum(row.kind is ReleaseSelectionChangeKind.CHANGED for row in changes),
        sum(row.kind is ReleaseSelectionChangeKind.REMOVED for row in changes),
    )
