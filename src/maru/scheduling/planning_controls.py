"""Compose one native editing form from independently authorized page projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .catalogs import SchedulingOperation
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .planning_forms import (
    PlanningCommandForm,
    PlanningPlacementForm,
    PlanningServiceDayForm,
)
from .planning_record_forms import PLANNING_RECORD_OPERATIONS, PlanningRecordForm
from .planning_selection import resolve_planning_selection

if TYPE_CHECKING:
    from uuid import UUID

    from django.http import QueryDict

    from .planning_board import PlanningBoardEntry, SchedulingPlanningBoard
    from .planning_hosts import PlanningHostRequirements
    from .planning_queries import PlanningHistoricalManifest, SchedulingPlanningSnapshot
    from .planning_reservations import SchedulingReservationReview
    from .planning_review import SchedulingPlanningReview
    from .planning_selection import PlanningSelection


_TITLES = {
    "placement": "Place or move this occurrence",
    "create_day": "Create a service day",
    "revise_day": "Revise this service day",
    SchedulingOperation.DAY_RETIRE: "Retire this service day",
    SchedulingOperation.OCCURRENCE_CREATE: "Create one occurrence",
    SchedulingOperation.OCCURRENCE_REVISE: "Revise occurrence grouping",
    SchedulingOperation.OCCURRENCE_RETIRE: "Retire this occurrence",
    SchedulingOperation.CANDIDATE_CREATE: "Create a private draft",
    SchedulingOperation.CANDIDATE_COPY: "Copy an exact draft revision",
    SchedulingOperation.CANDIDATE_RESTORE: "Restore an exact draft revision",
    SchedulingOperation.CANDIDATE_ARCHIVE: "Archive this private draft",
    SchedulingOperation.PLACEMENT_REMOVE: "Unplace this occurrence",
    SchedulingOperation.EVALUATION_RECORD: "Record current conflict checks",
    SchedulingOperation.WARNING_ACKNOWLEDGE: "Acknowledge this exact warning",
    SchedulingOperation.RESERVATION_REPLACE: "Request or replace the physical hold",
    SchedulingOperation.RESERVATION_CANCEL: "Cancel the existing physical hold",
}


@dataclass(frozen=True, slots=True)
class PlanningControl:
    """One ordinary form or a safe explanation of its missing prerequisites.

    Attributes
    ----------
    title
        Human task name, not an operation slug or permission claim.
    form
        Explicit native input, or none until required context is selected.
    submit_actions
        Closed action buttons; the template omits the duplicate hidden action.
    guidance
        Context, consequences or safe next action adjacent to the control.
    """

    title: str
    form: PlanningCommandForm | None
    submit_actions: tuple[tuple[str, str], ...]
    guidance: str

    @property
    def button_choices(self) -> tuple[dict[str, str], ...]:
        """Return the generic native template's explicit value/label contract.

        Returns
        -------
        tuple[dict[str, str], ...]
            Closed buttons in order, keeping placement Preview first.
        """
        return tuple(
            {"value": value, "label": label} for value, label in self.submit_actions
        )


def _missing(title: str, guidance: str) -> PlanningControl:
    return PlanningControl(title, None, (), guidance)


def _groups(board: SchedulingPlanningBoard) -> tuple[tuple[UUID, str], ...]:
    groups: dict[UUID, str] = {}
    for entry in board.entries:
        if entry.occurrence and entry.occurrence.group_key:
            groups.setdefault(
                entry.occurrence.group_key, f"Group: {entry.item.internal_title}"
            )
    return tuple(groups.items())


def _placement_control(
    snapshot: SchedulingPlanningSnapshot,
    board: SchedulingPlanningBoard,
    selection: PlanningSelection,
    entry: PlanningBoardEntry | None,
    hosts: PlanningHostRequirements | None,
    data: QueryDict | None,
) -> PlanningControl:
    title = _TITLES["placement"]
    candidate = board.candidate
    if candidate is None or entry is None or entry.occurrence is None:
        return _missing(title, "Select a private draft and an exact occurrence first.")
    day = (
        next((day for day in snapshot.days if day.id == selection.day_id), None)
        if selection.day_id
        else entry.day
    )
    if day is None:
        return _missing(
            title, "Choose a service day in the workspace before opening this form."
        )
    if hosts is None:
        raise SchedulingUnavailableError
    if hosts.candidate_version != candidate.version:
        raise SchedulingVersionConflictError
    if (
        hosts.occurrence_id != entry.occurrence.id
        or hosts.item_id != entry.item.item.id
        or hosts.placement_id != (entry.placement.id if entry.placement else None)
    ):
        raise SchedulingUnavailableError
    if data is None and (
        candidate.lifecycle != "draft"
        or entry.occurrence.lifecycle != "active"
        or entry.item.item.lifecycle != "active"
        or day.lifecycle != "active"
    ):
        return _missing(
            title,
            "Select an active occurrence, active service day "
            "and editable private draft.",
        )
    initial: dict[str, Any] = {}
    if data is None:
        initial = {
            "retry_key": uuid4(),
            "candidate_id": candidate.id,
            "expected_version": candidate.version,
            "occurrence_id": entry.occurrence.id,
            "occurrence_version": entry.occurrence.version,
            "day_id": day.id,
            "day_version": day.version,
            "space_selection_id": selection.space_id
            or (entry.space.id if entry.space else None),
        }
        if entry.placement:
            initial.update(
                capacity_mode=entry.placement.capacity_mode,
                expected_attendance=entry.placement.expected_attendance,
            )
            for name in (
                "setup_starts_at",
                "effective_starts_at",
                "effective_ends_at",
                "teardown_ends_at",
            ):
                initial[name] = getattr(entry.placement.envelope, name)
        for presence in hosts.presences:
            prefix = f"host_{presence.host_id.hex}"
            initial.update(
                {
                    f"{prefix}_required": "required",
                    f"{prefix}_starts_at": presence.starts_at,
                    f"{prefix}_ends_at": presence.ends_at,
                }
            )
    form = PlanningPlacementForm(
        data,
        initial=initial,
        auto_id="planning-edit-%s",
        zone_name=snapshot.zone_name,
        occurrences=((entry.occurrence.id, entry.item.internal_title),),
        days=((day.id, day.label),),
        spaces=tuple(
            (space.id, f"{space.venue_label} — {space.label}") for space in board.spaces
        ),
        hosts=tuple(
            (host.relationship.host_id, host.display_label)
            for host in hosts.roster.entries
        ),
    )
    return PlanningControl(
        title,
        form,
        (
            ("preview_placement", "Preview changes"),
            ("save_placement", "Save private draft"),
        ),
        "Preparation, delivery and teardown use the edition time zone. "
        "To change day or occurrence, select that target in the workspace first. "
        "A preview is not a save or a room hold.",
    )


def _record_initial(
    operation: SchedulingOperation,
    snapshot: SchedulingPlanningSnapshot,
    board: SchedulingPlanningBoard,
    selection: PlanningSelection,
    entry: PlanningBoardEntry | None,
    history: PlanningHistoricalManifest | None,
    reservation: SchedulingReservationReview | None,
    review: SchedulingPlanningReview | None,
) -> dict[str, Any] | None:
    initial: dict[str, Any] = {"retry_key": uuid4()}
    occurrence = entry.occurrence if entry else None
    day = next((day for day in snapshot.days if day.id == selection.day_id), None)
    match operation:
        case (
            SchedulingOperation.CANDIDATE_CREATE | SchedulingOperation.OCCURRENCE_CREATE
        ):
            initial["expected_version"] = snapshot.control_version
            if operation == SchedulingOperation.OCCURRENCE_CREATE:
                initial["item_id"] = selection.item_id
        case SchedulingOperation.DAY_RETIRE:
            if day is None or day.lifecycle != "active":
                return None
            initial.update(day_id=day.id, expected_version=day.version)
        case (
            SchedulingOperation.OCCURRENCE_REVISE
            | SchedulingOperation.OCCURRENCE_RETIRE
        ):
            if occurrence is None or occurrence.lifecycle != "active":
                return None
            initial.update(
                occurrence_id=occurrence.id, expected_version=occurrence.version
            )
            if operation == SchedulingOperation.OCCURRENCE_REVISE:
                initial.update(
                    item_id=occurrence.item_id,
                    group_key=occurrence.group_key,
                    group_sequence=occurrence.group_sequence,
                )
        case (
            SchedulingOperation.CANDIDATE_COPY
            | SchedulingOperation.CANDIDATE_RESTORE
            | SchedulingOperation.CANDIDATE_ARCHIVE
            | SchedulingOperation.PLACEMENT_REMOVE
            | SchedulingOperation.EVALUATION_RECORD
        ):
            return _candidate_initial(operation, snapshot, board, entry, history)
        case SchedulingOperation.WARNING_ACKNOWLEDGE:
            return _warning_initial(board, selection, review)
        case (
            SchedulingOperation.RESERVATION_REPLACE
            | SchedulingOperation.RESERVATION_CANCEL
        ):
            return _reservation_initial(operation, board, entry, reservation)
        case _:
            raise SchedulingUnavailableError
    return initial


def _candidate_initial(
    operation: SchedulingOperation,
    snapshot: SchedulingPlanningSnapshot,
    board: SchedulingPlanningBoard,
    entry: PlanningBoardEntry | None,
    history: PlanningHistoricalManifest | None,
) -> dict[str, Any] | None:
    initial: dict[str, Any] = {"retry_key": uuid4()}
    candidate = board.candidate
    occurrence = entry.occurrence if entry else None
    match operation:
        case SchedulingOperation.CANDIDATE_COPY:
            if history:
                initial["source_revision_id"] = history.entry.revision_id
            elif candidate:
                initial["source_revision_id"] = candidate.revision_id
            else:
                return None
            initial["expected_version"] = snapshot.control_version
        case SchedulingOperation.CANDIDATE_RESTORE:
            if candidate is None or candidate.lifecycle != "draft" or history is None:
                return None
            if history.candidate_id != candidate.id:
                raise SchedulingUnavailableError
            initial.update(
                candidate_id=candidate.id,
                expected_version=candidate.version,
                source_revision_id=history.entry.revision_id,
            )
        case (
            SchedulingOperation.CANDIDATE_ARCHIVE
            | SchedulingOperation.PLACEMENT_REMOVE
            | SchedulingOperation.EVALUATION_RECORD
        ):
            if candidate is None or candidate.lifecycle != "draft":
                return None
            initial.update(
                candidate_id=candidate.id, expected_version=candidate.version
            )
            if operation == SchedulingOperation.PLACEMENT_REMOVE:
                if entry is None or entry.placement is None or occurrence is None:
                    return None
                initial["occurrence_id"] = occurrence.id
        case _:
            raise SchedulingUnavailableError
    return initial


def _warning_initial(
    board: SchedulingPlanningBoard,
    selection: PlanningSelection,
    review: SchedulingPlanningReview | None,
) -> dict[str, Any] | None:
    candidate = board.candidate
    if (
        candidate is None
        or review is None
        or review.current.candidate_id != candidate.id
        or review.current.candidate_version != candidate.version
    ):
        return None
    finding = next(
        (
            finding
            for finding in review.saved_findings
            if finding.id == selection.conflict_id
        ),
        None,
    )
    if finding is None or not finding.eligible_for_acknowledgement:
        return None
    return {"retry_key": uuid4(), "conflict_id": finding.id}


def _reservation_initial(
    operation: SchedulingOperation,
    board: SchedulingPlanningBoard,
    entry: PlanningBoardEntry | None,
    reservation: SchedulingReservationReview | None,
) -> dict[str, Any] | None:
    if entry is None or entry.occurrence is None or reservation is None:
        return None
    if reservation.occurrence_id != entry.occurrence.id:
        raise SchedulingUnavailableError
    candidate, active = board.candidate, reservation.active
    initial: dict[str, Any] = {
        "retry_key": uuid4(),
        "previous_booking_id": active.booking_id if active else None,
        "expected_booking_version": active.booking_version if active else 0,
    }
    if operation == SchedulingOperation.RESERVATION_CANCEL:
        if active is None:
            return None
        # A hold may belong to an older/different draft. Keep its retained source.
        initial.update(
            candidate_id=active.candidate_id,
            candidate_version=active.candidate_version,
            placement_id=active.placement_id,
        )
    else:
        if (
            candidate is None
            or candidate.lifecycle != "draft"
            or entry.placement is None
        ):
            return None
        initial.update(
            candidate_id=candidate.id,
            candidate_version=candidate.version,
            placement_id=entry.placement.id,
        )
    return initial


def build_planning_control(
    snapshot: SchedulingPlanningSnapshot,
    board: SchedulingPlanningBoard,
    selection: PlanningSelection,
    *,
    data: QueryDict | None = None,
    hosts: PlanningHostRequirements | None = None,
    history: PlanningHistoricalManifest | None = None,
    reservation: SchedulingReservationReview | None = None,
    review: SchedulingPlanningReview | None = None,
) -> PlanningControl:
    """Build one explicit form without granting permission, querying or writing.

    Callers authorize base scope before binding input, load each required owner
    projection independently, and authorize the selected operation. All forms
    still submit through the existing owner command adapters. Fresh forms use
    observed object/control versions. Bound forms use no fresh initial values:
    old versions and retry keys survive stale, validation and uncertain results.
    A read-only transition hides new forms but cannot silently rewrite a retry.
    Placement composition propagates a version conflict if the independently
    read host requirements no longer match the observed candidate version.

    Parameters
    ----------
    snapshot : SchedulingPlanningSnapshot
        Current complete authorized Scheduling projection, including control.
    board : SchedulingPlanningBoard
        Complete independently labelled board, never the filtered card subset.
    selection : PlanningSelection
        Explicit scoped context and one closed editor mode.
    data : QueryDict | None, default=None
        Exact command namespace, retaining unknown and repeated fields if bound.
    hosts : PlanningHostRequirements | None, default=None
        Independently authorized exact-current roster/requirements for placement.
    history : PlanningHistoricalManifest | None, default=None
        Independently authorized exact historical source for copy/restore.
    reservation : SchedulingReservationReview | None, default=None
        Independently rechecked current physical hold for the selected occurrence.
    review : SchedulingPlanningReview | None, default=None
        Fresh independently authorized conflict review for warning selection.

    Returns
    -------
    PlanningControl
        One native control or explicit missing-context/read-only guidance.

    Raises
    ------
    SchedulingUnavailableError
        If an unknown mode or inconsistent owner projection was supplied.
    """
    selection, entry = resolve_planning_selection(board, selection)
    title = _TITLES.get(selection.mode)
    if title is None:
        raise SchedulingUnavailableError
    if data is None and not snapshot.accepts_writes:
        return _missing(
            title,
            "This edition is read-only. Existing history and physical holds remain.",
        )
    if selection.mode == "placement":
        return _placement_control(snapshot, board, selection, entry, hosts, data)
    if (
        selection.mode
        in {SchedulingOperation.CANDIDATE_COPY, SchedulingOperation.CANDIDATE_RESTORE}
        and selection.history_id
        and (history is None or history.entry.revision_id != selection.history_id)
    ):
        raise SchedulingUnavailableError
    if selection.mode in {"create_day", "revise_day"}:
        initial: dict[str, Any] = {}
        if data is None:
            initial = {
                "retry_key": uuid4(),
                "expected_version": snapshot.control_version,
            }
            if selection.mode == "revise_day":
                day = next(
                    (day for day in snapshot.days if day.id == selection.day_id), None
                )
                if day is None or day.lifecycle != "active":
                    return _missing(title, "Select an active service day first.")
                initial.update(
                    day_id=day.id,
                    expected_version=day.version,
                    label=day.label,
                    starts_at=day.window.starts_at,
                    ends_at=day.window.ends_at,
                    precision_minutes=day.precision_minutes,
                )
        form = PlanningServiceDayForm(
            data,
            initial=initial,
            auto_id="planning-edit-%s",
            zone_name=snapshot.zone_name,
        )
        return PlanningControl(
            title,
            form,
            ((selection.mode, title),),
            "Use explicit start and end dates; a service day may cross midnight.",
        )
    operation = SchedulingOperation(selection.mode)
    if operation not in PLANNING_RECORD_OPERATIONS:
        raise SchedulingUnavailableError
    record_initial = (
        {}
        if data is not None
        else _record_initial(
            operation, snapshot, board, selection, entry, history, reservation, review
        )
    )
    if record_initial is None:
        return _missing(
            title,
            "Select the exact eligible record or review evidence first. "
            "No change has been made.",
        )
    items = {entry.item.item.id: entry.item.internal_title for entry in board.entries}
    record_form = PlanningRecordForm(
        data,
        operation=operation,
        initial=record_initial,
        auto_id="planning-edit-%s",
        choices={"item_id": tuple(items.items()), "group_key": _groups(board)},
    )
    return PlanningControl(
        title,
        record_form,
        ((operation.value, title),),
        "This is an explicit versioned change. "
        "Review its target and consequences before submitting.",
    )
