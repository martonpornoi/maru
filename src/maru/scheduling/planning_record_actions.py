"""Explicit native record submissions through Scheduling's existing commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER
from .candidate_commands import (
    archive_scheduling_candidate,
    copy_scheduling_candidate,
    create_scheduling_candidate,
    remove_scheduling_placement,
    restore_scheduling_candidate,
)
from .catalogs import SchedulingOperation
from .day_commands import retire_scheduling_service_day
from .evaluation_commands import (
    acknowledge_scheduling_warning,
    evaluate_scheduling_candidate,
)
from .occurrence_commands import (
    create_scheduling_occurrence,
    retire_scheduling_occurrence,
    revise_scheduling_occurrence,
)
from .planning_actions import _authorize, _command_request
from .reservation_commands import change_scheduling_reservation

if TYPE_CHECKING:
    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult
    from .inputs import SchedulingCommandRequest
    from .planning_queries import SchedulingReadRequest
    from .planning_record_forms import PlanningRecordForm


def submit_planning_record(
    request: SchedulingReadRequest,
    form: PlanningRecordForm,
    *,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult | None:
    """Submit one exact explicit intent, preserving retry keys and owner checks.

    Base read authority is checked before cleaning private submitted input.
    Every mutation still performs its independent command authorization and
    transaction. Invalid forms retain their input; domain failures propagate
    without refreshing optimistic versions or creating a second pending intent.

    Parameters
    ----------
    request : SchedulingReadRequest
        Server-resolved authenticated actor, exact edition and correlation.
    form : PlanningRecordForm
        One bound closed record operation with already-authorized owner choices.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary policy, or the existing sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult | None
        Exact saved/replayed owner result, or invalid form with retained input.

    Raises
    ------
    ValueError
        If server-side form configuration does not match a validated record intent.
    """
    _authorize(request, authorizer)
    if not form.is_valid():
        return None
    command = _command_request(request, form)
    fields = form.cleaned_data
    match form.operation:
        case (
            SchedulingOperation.CANDIDATE_CREATE
            | SchedulingOperation.CANDIDATE_COPY
            | SchedulingOperation.CANDIDATE_RESTORE
            | SchedulingOperation.CANDIDATE_ARCHIVE
            | SchedulingOperation.PLACEMENT_REMOVE
        ):
            result = _submit_candidate(command, form, authorizer)
        case (
            SchedulingOperation.OCCURRENCE_CREATE
            | SchedulingOperation.OCCURRENCE_REVISE
            | SchedulingOperation.OCCURRENCE_RETIRE
        ):
            result = _submit_occurrence(command, form, authorizer)
        case SchedulingOperation.DAY_RETIRE:
            result = retire_scheduling_service_day(
                command,
                day_id=fields["day_id"],
                expected_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case SchedulingOperation.EVALUATION_RECORD:
            result = evaluate_scheduling_candidate(
                command,
                candidate_id=fields["candidate_id"],
                expected_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case SchedulingOperation.WARNING_ACKNOWLEDGE:
            result = acknowledge_scheduling_warning(
                command,
                conflict_id=fields["conflict_id"],
                authorizer=authorizer,
            )
        case (
            SchedulingOperation.RESERVATION_REPLACE
            | SchedulingOperation.RESERVATION_CANCEL
        ):
            if form.reservation_intent is None:
                raise ValueError("A validated reservation intent is required.")
            result = change_scheduling_reservation(
                command,
                reservation=form.reservation_intent,
                operation=form.operation,
                authorizer=authorizer,
            )
        case _:
            raise ValueError("Select a supported planning record operation.")
    return result


def _submit_candidate(
    command: SchedulingCommandRequest,
    form: PlanningRecordForm,
    authorizer: SchedulingAuthorizer,
) -> SchedulingCommandResult:
    fields = form.cleaned_data
    match form.operation:
        case SchedulingOperation.CANDIDATE_CREATE:
            return create_scheduling_candidate(
                command,
                label=fields["label"],
                expected_control_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case SchedulingOperation.CANDIDATE_COPY:
            return copy_scheduling_candidate(
                command,
                label=fields["label"],
                source_revision_id=fields["source_revision_id"],
                expected_control_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case SchedulingOperation.CANDIDATE_RESTORE:
            return restore_scheduling_candidate(
                command,
                candidate_id=fields["candidate_id"],
                source_revision_id=fields["source_revision_id"],
                expected_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case SchedulingOperation.CANDIDATE_ARCHIVE:
            return archive_scheduling_candidate(
                command,
                candidate_id=fields["candidate_id"],
                expected_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case SchedulingOperation.PLACEMENT_REMOVE:
            return remove_scheduling_placement(
                command,
                candidate_id=fields["candidate_id"],
                occurrence_id=fields["occurrence_id"],
                expected_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case _:
            raise ValueError("Select a candidate operation.")


def _submit_occurrence(
    command: SchedulingCommandRequest,
    form: PlanningRecordForm,
    authorizer: SchedulingAuthorizer,
) -> SchedulingCommandResult:
    fields = form.cleaned_data
    if form.operation == SchedulingOperation.OCCURRENCE_RETIRE:
        return retire_scheduling_occurrence(
            command,
            occurrence_id=fields["occurrence_id"],
            expected_version=fields["expected_version"],
            authorizer=authorizer,
        )
    if form.occurrence_intent is None:
        raise ValueError("A validated occurrence intent is required.")
    match form.operation:
        case SchedulingOperation.OCCURRENCE_CREATE:
            return create_scheduling_occurrence(
                command,
                occurrence=form.occurrence_intent,
                expected_control_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case SchedulingOperation.OCCURRENCE_REVISE:
            return revise_scheduling_occurrence(
                command,
                occurrence_id=fields["occurrence_id"],
                occurrence=form.occurrence_intent,
                expected_version=fields["expected_version"],
                authorizer=authorizer,
            )
        case _:
            raise ValueError("Select an occurrence operation.")
