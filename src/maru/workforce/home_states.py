"""Pure continuation choices over bounded, independently admitted owner facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

WorkPhase = Literal["planning", "closing", "retained"]


@dataclass(frozen=True, slots=True)
class OperatingHomeItem:
    """One closed owner decision without people, counts or private input.

    Attributes
    ----------
    code, priority
        Stable copy/route discriminator and deterministic ascending priority.
    object_id
        Exact authorized owner record, or no target for an area-wide review.
    due_at
        Authorized Shift/Assignment decision boundary, never personal Availability.
    checked_at, time_zone
        Final disclosure time and the edition's named display zone.
    """

    code: str
    priority: int
    object_id: UUID | None = None
    due_at: datetime | None = None
    checked_at: datetime | None = None
    time_zone: str = "UTC"


@dataclass(frozen=True, slots=True)
class AssignmentHomeFact:
    """Internal Assignment metadata needed to distinguish independent work.

    Attributes
    ----------
    id, status, proposed_by_id
        Owner identity/state and opaque proposer identity used only internally.
    effective_from, expires_at
        Existing authority interval; no inferred or extended term.
    """

    id: UUID
    status: str
    proposed_by_id: UUID
    effective_from: datetime
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class ShiftHomeFact:
    """Internal demand-level consequences from existing Shift read rules.

    Attributes
    ----------
    id, status, starts_at, ends_at
        Exact demand identity, lifecycle and existing work interval.
    underfilled, has_claims, has_independent_claim, changed_evidence
        Bounded derived consequences; no count or person leaves the owner.
    """

    id: UUID
    status: str
    starts_at: datetime
    ends_at: datetime
    underfilled: bool = False
    has_claims: bool = False
    has_independent_claim: bool = False
    changed_evidence: bool = False


def _proposal_item(
    proposed: tuple[AssignmentHomeFact, ...], actor_id: UUID, *, can_issue: bool
) -> OperatingHomeItem:
    independent = next(
        (row for row in proposed if row.proposed_by_id != actor_id), None
    )
    if independent is not None and can_issue:
        return OperatingHomeItem("assignment_review", 25, independent.id)
    if independent is not None:
        return OperatingHomeItem("assignment_wait_authority", 25)
    return OperatingHomeItem("assignment_wait_review", 25)


def assignment_home_item(
    facts: tuple[AssignmentHomeFact, ...],
    *,
    phase: WorkPhase,
    now: datetime,
    actor_id: UUID,
    can_issue: bool,
    can_end: bool,
) -> OperatingHomeItem:
    """Choose a review continuation without promising approval readiness.

    Parameters
    ----------
    facts : tuple[AssignmentHomeFact, ...]
        Complete bounded and validated admitted Assignment metadata.
    phase : WorkPhase
        Fresh owner lifecycle phase.
    now : datetime
        Aware instant at which interval consequences are evaluated.
    actor_id : UUID
        Current principal, used only to preserve independent decisions.
    can_issue : bool
        Separate current authority-management admission.
    can_end : bool
        Separate current authority-revocation admission.

    Returns
    -------
    OperatingHomeItem
        One scoped next review, waiting explanation or retained-history item.
    """
    if phase == "retained":
        return OperatingHomeItem("assignment_history", 95)
    expired = next(
        (
            row
            for row in facts
            if row.status == "active"
            and row.expires_at is not None
            and row.expires_at <= now
        ),
        None,
    )
    if expired is not None:
        return OperatingHomeItem(
            "assignment_end" if can_end else "assignment_wait_end",
            12,
            expired.id,
            expired.expires_at,
        )
    proposed = tuple(row for row in facts if row.status == "proposed")
    if proposed:
        return _proposal_item(proposed, actor_id, can_issue=can_issue)
    if phase == "closing":
        return OperatingHomeItem("assignment_closing", 70)
    code = "assignment_history"
    if not facts:
        code = "assignment_plan"
    elif any(row.status == "active" for row in facts):
        code = "assignment_active"
    return OperatingHomeItem(
        code, {"assignment_plan": 75, "assignment_active": 85}.get(code, 95)
    )


def availability_home_item(
    states: tuple[str, ...], *, phase: WorkPhase
) -> OperatingHomeItem | None:
    """Keep shared consequences separate from private drafts and exact periods.

    Parameters
    ----------
    states : tuple[str, ...]
        One validated organizer-visible consequence per related person.
    phase : WorkPhase
        Fresh owner lifecycle phase.

    Returns
    -------
    OperatingHomeItem | None
        One consequence, or no item when no open Assignment person exists.
    """
    if not states:
        return None
    if phase == "retained":
        return OperatingHomeItem("availability_retained", 96)
    if "withdrawn" in states:
        return OperatingHomeItem("availability_withdrawn", 32)
    if "not_shared" in states:
        return OperatingHomeItem("availability_wait", 42)
    if "unavailable" in states:
        return OperatingHomeItem("availability_empty", 46)
    return OperatingHomeItem("availability_shared", 90)


def _open_shift_item(
    row: ShiftHomeFact, phase: WorkPhase, *, can_manage: bool
) -> OperatingHomeItem:
    if row.has_claims:
        code = "shift_wait_manager"
        if can_manage:
            code = "shift_claims" if row.has_independent_claim else "shift_wait_claims"
        return OperatingHomeItem(
            code,
            20,
            row.id,
            row.starts_at,
        )
    if phase == "closing":
        return OperatingHomeItem("shift_closing", 35, row.id, row.ends_at)
    if row.underfilled:
        return OperatingHomeItem("shift_coverage", 30, row.id, row.starts_at)
    return OperatingHomeItem(
        "shift_lock" if can_manage else "shift_wait_lock",
        40,
        row.id,
        row.starts_at,
    )


def _unlocked_shift_item(
    row: ShiftHomeFact, phase: WorkPhase, now: datetime, *, can_manage: bool
) -> OperatingHomeItem:
    if row.ends_at <= now:
        return OperatingHomeItem("shift_ended", 8, row.id, row.ends_at)
    if row.changed_evidence:
        return OperatingHomeItem("shift_changed", 10, row.id, row.starts_at)
    if row.status == "open":
        return _open_shift_item(row, phase, can_manage=can_manage)
    if phase == "closing":
        return OperatingHomeItem("shift_closing", 35, row.id, row.ends_at)
    return OperatingHomeItem(
        "shift_draft" if can_manage else "shift_wait_draft",
        55,
        row.id,
        row.starts_at,
    )


def _shift_item(
    row: ShiftHomeFact, phase: WorkPhase, now: datetime, *, can_manage: bool
) -> OperatingHomeItem | None:
    if row.status in {"completed", "cancelled"}:
        return None
    if row.status != "locked":
        return _unlocked_shift_item(row, phase, now, can_manage=can_manage)
    if row.ends_at <= now:
        return OperatingHomeItem(
            "shift_complete" if can_manage else "shift_wait_complete",
            5,
            row.id,
            row.ends_at,
        )
    if row.changed_evidence:
        return OperatingHomeItem("shift_changed", 10, row.id, row.starts_at)
    if phase == "closing":
        return OperatingHomeItem("shift_closing", 35, row.id, row.ends_at)
    upcoming = now < row.starts_at
    return OperatingHomeItem(
        "shift_scheduled" if upcoming else "shift_running",
        65,
        row.id,
        row.starts_at if upcoming else row.ends_at,
    )


def shift_home_item(
    facts: tuple[ShiftHomeFact, ...],
    *,
    phase: WorkPhase,
    now: datetime,
    can_manage: bool,
) -> OperatingHomeItem:
    """Choose existing Shift review work without approving risk or attendance.

    Parameters
    ----------
    facts : tuple[ShiftHomeFact, ...]
        Complete bounded demand consequences using existing suitability rules.
    phase : WorkPhase
        Fresh owner lifecycle phase.
    now : datetime
        Aware decision instant, independent of the host or browser time zone.
    can_manage : bool
        Current separate Shift management authority.

    Returns
    -------
    OperatingHomeItem
        Highest-priority current demand review or an informational area state.
    """
    if phase == "retained":
        return OperatingHomeItem("shift_history", 95)
    candidates = tuple(
        item
        for row in facts
        if (item := _shift_item(row, phase, now, can_manage=can_manage)) is not None
    )
    if candidates:
        return min(
            candidates,
            key=lambda item: (item.priority, item.due_at or now, str(item.object_id)),
        )
    return OperatingHomeItem(
        "shift_plan" if not facts and phase == "planning" else "shift_history", 95
    )
