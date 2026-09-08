"""Unrouted authenticated HTTP composition for the dormant timetable editor."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.template.response import TemplateResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.queries import ProgrammeQueryError
from maru.venues.scheduling_queries import (
    VenueSchedulingSourceDeniedError,
    VenueSchedulingSourceUnavailableError,
)
from maru.venues.services import (
    VenueAuthorizationDeniedError,
    VenueAvailabilityConflictError,
    VenueBookingOverlapError,
    VenueCapacityConflictError,
    VenueCommandError,
    VenueRetryConflictError,
    VenueStateConflictError,
    VenueVersionConflictError,
)
from maru.venues.timetable_queries import (
    VenueTimetableQueryDeniedError,
    VenueTimetableQueryUnavailableError,
)

from .authorization import (
    DEFAULT_SCHEDULING_AUTHORIZER,
    SchedulingAuthorizationDeniedError,
)
from .catalogs import SchedulingOperation as Op
from .command_support import (
    SchedulingCommandError,
    SchedulingCommandResult,
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingVersionConflictError,
)
from .planning_actions import submit_planning_placement, submit_planning_service_day
from .planning_forms import PlanningPlacementForm, PlanningServiceDayForm
from .planning_presentation import describe_planning_findings
from .planning_preview import SchedulingPlanningPreview
from .planning_queries import SchedulingReadRequest, load_scheduling_planning
from .planning_record_actions import submit_planning_record
from .planning_record_forms import PLANNING_RECORD_OPERATIONS, PlanningRecordForm
from .planning_selection import (
    PlanningQueryForm,
    PlanningSelection,
    split_planning_post,
)
from .planning_workspace import compose_planning_workspace

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse, QueryDict

    from .authorization import SchedulingAuthorizer
    from .planning_forms import PlanningCommandForm
    from .planning_queries import SchedulingPlanningSnapshot


_ACTION_MODES = {
    "preview_placement": "placement",
    "save_placement": "placement",
    "create_day": "create_day",
    "revise_day": "revise_day",
    **{operation.value: operation.value for operation in PLANNING_RECORD_OPERATIONS},
}
_DENIALS = (
    SchedulingAuthorizationDeniedError,
    ProgrammeAuthorizationDeniedError,
    VenueTimetableQueryDeniedError,
    VenueAuthorizationDeniedError,
    VenueSchedulingSourceDeniedError,
)
_UNAVAILABLE = (
    SchedulingCommandError,
    ProgrammeQueryError,
    VenueTimetableQueryUnavailableError,
    DatabaseError,
    VenueCommandError,
    VenueSchedulingSourceUnavailableError,
)


class _InvalidPlanningRequestError(ValueError):
    pass


def _selection(request: HttpRequest) -> tuple[PlanningSelection, QueryDict | None]:
    if request.GET or request.FILES:
        raise _InvalidPlanningRequestError
    if request.method == "GET":
        return PlanningSelection(), None
    selection_form, command = split_planning_post(request.POST)
    selection = selection_form.selection()
    actions = command.getlist("action")
    if selection is None or len(actions) != 1:
        raise _InvalidPlanningRequestError
    action = actions[0]
    if action in {"select", "clear_filters"}:
        query = PlanningQueryForm(command)
        if not query.is_valid():
            raise _InvalidPlanningRequestError
        if action == "clear_filters":
            selection = replace(
                selection, day_id=None, space_id=None, text="", state="all"
            )
        return selection, None
    if action not in _ACTION_MODES or selection.mode != _ACTION_MODES[action]:
        raise _InvalidPlanningRequestError
    return selection, command


def _submit(
    scope: SchedulingReadRequest,
    form: PlanningCommandForm,
    authorizer: SchedulingAuthorizer,
) -> SchedulingCommandResult | SchedulingPlanningPreview | None:
    if isinstance(form, PlanningPlacementForm):
        return submit_planning_placement(scope, form, authorizer=authorizer)
    if isinstance(form, PlanningServiceDayForm):
        return submit_planning_service_day(scope, form, authorizer=authorizer)
    if isinstance(form, PlanningRecordForm):
        return submit_planning_record(scope, form, authorizer=authorizer)
    raise _InvalidPlanningRequestError


def _after_command(
    selection: PlanningSelection, result: SchedulingCommandResult, action: str
) -> PlanningSelection:
    result_selection = replace(selection, mode="overview", conflict_id=None)
    if action in {Op.CANDIDATE_CREATE, Op.CANDIDATE_COPY}:
        result_selection = replace(
            result_selection,
            candidate_id=result.object_id,
            history_id=None,
            compare_id=None,
            before_version=None,
        )
    elif action in {"create_day", "revise_day"}:
        result_selection = replace(result_selection, day_id=result.object_id)
    elif action in {Op.OCCURRENCE_CREATE, Op.OCCURRENCE_REVISE, Op.OCCURRENCE_RETIRE}:
        result_selection = replace(
            result_selection, occurrence_id=result.object_id, item_id=None
        )
    elif action in {Op.EVALUATION_RECORD, Op.WARNING_ACKNOWLEDGE}:
        result_selection = replace(result_selection, mode="review")
    elif action in {Op.RESERVATION_REPLACE, Op.RESERVATION_CANCEL}:
        result_selection = replace(result_selection, mode="reservation")
    return result_selection


def _command_failure(error: Exception) -> tuple[int, str]:
    if isinstance(error, SchedulingVersionConflictError | VenueVersionConflictError):
        return (
            409,
            "The observed version changed. Your entered values and old version "
            "are retained. Refresh deliberately and review a new intent; "
            "nothing was automatically rebased.",
        )
    if isinstance(error, SchedulingIdempotencyConflictError | VenueRetryConflictError):
        return (
            409,
            "This retry key already describes different input. "
            "Check the retained result before deliberately starting a new intent.",
        )
    if isinstance(error, SchedulingLifecycleConflictError | VenueStateConflictError):
        return (
            409,
            "The current edition or record no longer accepts this change. "
            "Your pending input has not been rewritten.",
        )
    if isinstance(error, SchedulingLimitError):
        return (
            409,
            "This action reached a complete-inventory or history limit. "
            "No partial command was accepted.",
        )
    if isinstance(error, ValidationError):
        return (
            400,
            "The owner could not accept this input. "
            "Review the explicit fields and current source records.",
        )
    return _source_failure(error)


def _source_failure(error: Exception) -> tuple[int, str]:
    if isinstance(
        error,
        VenueAvailabilityConflictError
        | VenueCapacityConflictError
        | VenueBookingOverlapError,
    ):
        return 409, (
            "The physical hold was not accepted. Review current room availability, "
            "capacity and overlapping holds before explicitly changing the request."
        )
    return (
        503,
        "Completion could not be confirmed. Keep this exact pending input and "
        "retry key; do not assume the change failed or submit a different intent "
        "with this key.",
    )


def _workspace_response(
    request: HttpRequest,
    scope: SchedulingReadRequest,
    initial: SchedulingPlanningSnapshot,
    edition_label: str,
    authorizer: SchedulingAuthorizer,
) -> HttpResponse:
    selection, data = _selection(request)
    snapshot = (
        load_scheduling_planning(
            scope, candidate_id=selection.candidate_id, authorizer=authorizer
        )
        if selection.candidate_id
        else initial
    )
    context = compose_planning_workspace(
        scope, snapshot, selection, data=data, authorizer=authorizer
    )
    status = 200
    if data is not None:
        control = context["control"]
        if control is None or control.form is None:
            raise _InvalidPlanningRequestError
        try:
            result = _submit(scope, control.form, authorizer)
        except _DENIALS:
            # Venue authorization failures also inherit its command-error base.
            # They must withhold the page, not become a retained private form.
            raise
        except (*_UNAVAILABLE, ValidationError) as error:
            status, context["action_error"] = _command_failure(error)
        else:
            context, status = _command_response(
                scope, context, result, str(data["action"]), authorizer
            )
    context["edition_label"] = edition_label
    return TemplateResponse(
        request, "scheduling/planning_board.html", context, status=status
    )


def _command_response(
    scope: SchedulingReadRequest,
    context: dict[str, Any],
    result: SchedulingCommandResult | SchedulingPlanningPreview | None,
    action: str,
    authorizer: SchedulingAuthorizer,
) -> tuple[dict[str, Any], int]:
    if result is None:
        return context, 400
    if isinstance(result, SchedulingPlanningPreview):
        context.update(
            preview=result,
            preview_rows=describe_planning_findings(result.findings),
            status_message="Preview only. "
            "No draft, evaluation or physical hold was saved.",
        )
        return context, 200
    selection = _after_command(context["selection"], result, action)
    snapshot = load_scheduling_planning(
        scope, candidate_id=selection.candidate_id, authorizer=authorizer
    )
    refreshed = compose_planning_workspace(
        scope, snapshot, selection, authorizer=authorizer
    )
    refreshed["status_message"] = (
        "Previously completed command confirmed; no duplicate change."
        if result.replayed
        else "Command completed. Current owner records have been reloaded. "
        "No Programme timetable was published."
    )
    return refreshed, 200


def _failure(request: HttpRequest, status: int, message: str) -> HttpResponse:
    return TemplateResponse(
        request,
        "scheduling/planning_failure.html",
        {"failure_message": message},
        status=status,
    )


@transaction.non_atomic_requests
@never_cache
@sensitive_post_parameters()
@csrf_protect
@require_http_methods(["GET", "POST"])
def scheduling_planning_view(
    request: HttpRequest,
    *,
    organization_id: UUID,
    edition_id: UUID,
    edition_label: str,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> HttpResponse:
    """Serve a dormant component using authenticated and server-resolved scope only.

    This adapter is intentionally absent from production URL configuration.
    Future activation must resolve the canonical route through the accepted
    profile/runtime boundary. Supplying a scope or label never grants authority.
    No personal input is read from URLs or persisted in browser/server sessions.
    Bound commands keep exact retry values; refresh never silently rebases them.

    Parameters
    ----------
    request : HttpRequest
        Authenticated request with normal CSRF protection and private POST masking.
    organization_id : UUID
        Exact server-resolved tenant, never read from POST data.
    edition_id : UUID
        Exact server-resolved edition, independently checked by each owner.
    edition_label : str
        Trusted parent-context label, withheld if base or owner authority fails.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary Scheduling policy or its existing doubly sealed test substitute.

    Returns
    -------
    HttpResponse
        No-store native workspace, retained authorized form failure, or a generic
        non-disclosing denial/unavailable response with no prior private context.
    """
    actor_id = getattr(request.user, "pk", None)
    if not request.user.is_authenticated or not isinstance(actor_id, UUID):
        return _failure(
            request, 403, "This planning workspace is unavailable to this account."
        )
    scope = SchedulingReadRequest(actor_id, organization_id, edition_id, uuid4())
    try:
        # Authorize and audit before parsing private selection or command input.
        initial = load_scheduling_planning(scope, authorizer=authorizer)
        return _workspace_response(request, scope, initial, edition_label, authorizer)
    except _DENIALS:
        return _failure(
            request,
            403,
            "Current permission for this workspace or selected owner layer is "
            "unavailable. If you submitted a change, check its history when "
            "access is restored.",
        )
    except _InvalidPlanningRequestError:
        return _failure(
            request,
            400,
            "The request selection is invalid. Use the native controls; "
            "filters do not belong in URLs. No command was dispatched "
            "for this invalid request.",
        )
    except _UNAVAILABLE:
        return _failure(
            request,
            503,
            "The complete workspace could not be loaded. Do not assume a "
            "submitted change failed; check its retained result or retry the "
            "exact same pending intent when available.",
        )
