"""Native editor submissions delegated to the existing versioned owner commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    VIEW_PLANNING,
    authorize_scheduling_scope,
)
from .day_commands import create_scheduling_service_day, revise_scheduling_service_day
from .inputs import SchedulingCommandRequest
from .placement_commands import set_scheduling_placement
from .planning_preview import preview_scheduling_candidate
from .planning_queries import PLANNING_FIELDS

if TYPE_CHECKING:
    from .authorization import SchedulingAuthorizer
    from .command_support import SchedulingCommandResult
    from .planning_forms import (
        PlanningCommandForm,
        PlanningPlacementForm,
        PlanningServiceDayForm,
    )
    from .planning_preview import SchedulingPlanningPreview
    from .planning_queries import SchedulingReadRequest


def _authorize(
    request: SchedulingReadRequest, authorizer: SchedulingAuthorizer
) -> None:
    authorize_scheduling_scope(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        capability_code=VIEW_PLANNING,
        requested_fields=PLANNING_FIELDS,
        authorizer=authorizer,
    )


def _command_request(
    request: SchedulingReadRequest, form: PlanningCommandForm
) -> SchedulingCommandRequest:
    return SchedulingCommandRequest(
        request.actor_id,
        request.organization_id,
        request.edition_id,
        form.cleaned_data["retry_key"],
        request.correlation_id,
        form.cleaned_data["reason"],
        "scheduling-planning",
    )


def submit_planning_placement(
    request: SchedulingReadRequest,
    form: PlanningPlacementForm,
    *,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingPlanningPreview | SchedulingCommandResult | None:
    """Preview or save explicit intent without a separate pointer/keyboard writer.

    Invalid input stays in the same bound form. Preview creates no command
    request or acknowledgement. Save reuses the submitted retry key, reason and
    exact version; domain denial, stale state or unavailable sources propagate
    for the view's safe error presentation, without resetting the entered form.

    Parameters
    ----------
    request : SchedulingReadRequest
        Server-resolved authenticated actor, exact edition and correlation.
    form : PlanningPlacementForm
        Bound strict input built with independently authorized owner choices.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary policy, or the existing sealed isolated-test substitute.

    Returns
    -------
    SchedulingPlanningPreview | SchedulingCommandResult | None
        Explicit preview, saved/replayed command result, or invalid form with errors.
    """
    _authorize(request, authorizer)
    if not form.is_valid() or form.placement_intent is None:
        return None
    fields = form.cleaned_data
    if fields["action"] == "preview_placement":
        return preview_scheduling_candidate(
            request,
            candidate_id=fields["candidate_id"],
            expected_version=fields["expected_version"],
            placement=form.placement_intent,
            authorizer=authorizer,
        )
    return set_scheduling_placement(
        _command_request(request, form),
        candidate_id=fields["candidate_id"],
        expected_version=fields["expected_version"],
        placement=form.placement_intent,
        authorizer=authorizer,
    )


def submit_planning_service_day(
    request: SchedulingReadRequest,
    form: PlanningServiceDayForm,
    *,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> SchedulingCommandResult | None:
    """Create or revise one explicit service day through its existing owner command.

    Parameters
    ----------
    request : SchedulingReadRequest
        Server-resolved authenticated actor, edition and correlation.
    form : PlanningServiceDayForm
        Bound strict day input using the trusted Events time zone.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary policy, or the existing sealed isolated-test substitute.

    Returns
    -------
    SchedulingCommandResult | None
        Exact saved/replayed owner result, or invalid form with retained input.
    """
    _authorize(request, authorizer)
    if not form.is_valid() or form.day_intent is None:
        return None
    command = _command_request(request, form)
    if form.cleaned_data["action"] == "create_day":
        return create_scheduling_service_day(
            command,
            day=form.day_intent,
            expected_control_version=form.cleaned_data["expected_version"],
            authorizer=authorizer,
        )
    return revise_scheduling_service_day(
        command,
        day_id=form.cleaned_data["day_id"],
        day=form.day_intent,
        expected_version=form.cleaned_data["expected_version"],
        authorizer=authorizer,
    )
