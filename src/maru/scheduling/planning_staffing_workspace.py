"""One purpose-selected native staffing panel inside the existing timetable shell."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from django import forms
from django.db import transaction

from maru.programme.authorization import (
    PROGRAMME_MANAGE_STAFFING,
    ProgrammeAuthorizationDeniedError,
    authorize_programme_scope,
)
from maru.programme.staffing_inputs import ProgrammeStaffingSource
from maru.programme.staffing_queries import (
    ProgrammeStaffingReadRequest,
    load_programme_staffing_history,
    load_programme_staffing_requirements,
)
from maru.workforce.programme_binding_queries import (
    load_programme_binding_history,
    load_programme_bindings,
)
from maru.workforce.programme_references import lock_programme_staffing_scope
from maru.workforce.programme_staffing_choices import (
    list_programme_linkable_demands,
    list_programme_staffing_positions,
)
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    authorize_programme_staffing_adapter,
    load_programme_staffing_demand,
)

from .authorization import DEFAULT_SCHEDULING_AUTHORIZER
from .command_support import SchedulingUnavailableError, SchedulingVersionConflictError
from .planning_controls import PlanningControl
from .planning_queries import load_scheduling_planning
from .planning_staffing_forms import (
    BINDING_MODES,
    REQUIREMENT_ACTIONS,
    STAFFING_MODE_LABELS,
    PlanningStaffingBindingForm,
    PlanningStaffingRequirementForm,
)
from .staffing_queries import load_planning_staffing

if TYPE_CHECKING:
    from django.http import QueryDict

    from maru.programme.staffing_queries import (
        ProgrammeStaffingHistoryPage,
        ProgrammeStaffingOverview,
        ProgrammeStaffingRequirementView,
    )
    from maru.workforce.programme_binding_queries import (
        ProgrammeBindingHistoryPage,
        ProgrammeBindingView,
    )
    from maru.workforce.programme_staffing_choices import StaffingPositionChoice

    from .authorization import SchedulingAuthorizer
    from .planning_queries import SchedulingPlanningSnapshot, SchedulingReadRequest
    from .planning_selection import PlanningSelection


def _request(
    scope: SchedulingReadRequest, selection: PlanningSelection
) -> ProgrammeStaffingReadRequest:
    if selection.item_id is None:
        raise SchedulingUnavailableError
    return ProgrammeStaffingReadRequest(
        scope.actor_id,
        scope.organization_id,
        scope.edition_id,
        selection.item_id,
        scope.correlation_id,
        "scheduling-staffing",
    )


def _history(
    request: ProgrammeStaffingReadRequest, selection: PlanningSelection
) -> dict[str, Any]:
    if selection.staffing_through_version is None:
        return {
            "staffing_guidance": "Open history beside an authorized requirement "
            "or binding to choose its fixed version ceiling."
        }
    history: ProgrammeStaffingHistoryPage | ProgrammeBindingHistoryPage
    if selection.mode == "staffing_requirement_history":
        if selection.requirement_id is None:
            raise SchedulingUnavailableError
        history = load_programme_staffing_history(
            request,
            requirement_id=selection.requirement_id,
            through_version=selection.staffing_through_version,
            after_version=selection.staffing_after_version or 0,
        )
    else:
        if selection.binding_id is None:
            raise SchedulingUnavailableError
        history = load_programme_binding_history(
            request,
            binding_id=selection.binding_id,
            through_version=selection.staffing_through_version,
            after_version=selection.staffing_after_version or 0,
        )
    return {
        "staffing_history": history,
        "staffing_history_kind": "requirement"
        if selection.mode == "staffing_requirement_history"
        else "binding",
        "staffing_history_next_state": replace(
            selection, staffing_after_version=history.next_after_version
        ).hidden_values(),
    }


def _can_manage(request: ProgrammeStaffingReadRequest) -> bool:
    try:
        authorize_programme_scope(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            capability_code=PROGRAMME_MANAGE_STAFFING,
        )
    except ProgrammeAuthorizationDeniedError:
        return False
    return True


def _row_actions(
    selection: PlanningSelection,
    requirement: ProgrammeStaffingRequirementView,
    binding: ProgrammeBindingView | None,
    *,
    can_manage: bool,
    work_available: bool,
) -> tuple[dict[str, Any], ...]:
    target = replace(
        selection,
        occurrence_id=requirement.occurrence_id,
        requirement_id=requirement.requirement_id,
        binding_id=None,
        demand_id=None,
        staffing_through_version=None,
        staffing_after_version=None,
    )
    actions: list[dict[str, Any]] = [
        {
            "label": "Requirement history",
            "state": replace(
                target,
                mode="staffing_requirement_history",
                staffing_through_version=requirement.version,
            ).hidden_values(),
        }
    ]
    if binding:
        actions.append(
            {
                "label": "Work binding history",
                "state": replace(
                    target,
                    mode="staffing_binding_history",
                    binding_id=binding.binding_id,
                    staffing_through_version=binding.version,
                ).hidden_values(),
            }
        )
    if requirement.lifecycle == "active":
        modes = ["staffing_revise", "staffing_retire"] if can_manage else []
        if work_available and selection.candidate_id:
            modes.extend(
                ["staffing_reconcile_work", "staffing_successor_work"]
                if binding
                else ["staffing_create_work", "staffing_link_work"]
            )
        actions.extend(
            {
                "label": STAFFING_MODE_LABELS[mode],
                "state": replace(target, mode=mode).hidden_values(),
            }
            for mode in modes
        )
    return tuple(actions)


def _requirement_control(
    request: ProgrammeStaffingReadRequest,
    snapshot: SchedulingPlanningSnapshot,
    selection: PlanningSelection,
    overview: ProgrammeStaffingOverview,
    requirement: ProgrammeStaffingRequirementView | None,
    data: QueryDict | None,
) -> PlanningControl:
    title = STAFFING_MODE_LABELS[selection.mode]
    occurrence = next(
        (row for row in snapshot.occurrences if row.id == selection.occurrence_id), None
    )
    if occurrence is None or (
        selection.mode != "staffing_create" and requirement is None
    ):
        return PlanningControl(
            title,
            None,
            (),
            "Choose the exact occurrence and, for revision or retirement, "
            "the requirement beside its card.",
        )
    if selection.mode == "staffing_create" and requirement is not None:
        return PlanningControl(
            title,
            None,
            (),
            "Use Create requirement to begin a distinct need, "
            "or revise the selected one.",
        )
    if not _can_manage(request) or not snapshot.accepts_writes:
        if data is not None:
            raise ProgrammeAuthorizationDeniedError
        return PlanningControl(
            title,
            None,
            (),
            "Current read authority does not permit changing this requirement.",
        )
    if data is None and (
        overview.item_lifecycle != "active"
        or occurrence.lifecycle != "active"
        or (requirement and requirement.lifecycle != "active")
    ):
        return PlanningControl(
            title,
            None,
            (),
            "This retained item, occurrence or requirement is not editable. "
            "Its history remains available independently.",
        )
    positions: tuple[StaffingPositionChoice, ...] = ()
    if selection.mode != "staffing_retire":
        positions = list_programme_staffing_positions(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            correlation_id=request.correlation_id,
        )
    initial = {
        "action": selection.mode,
        "retry_key": uuid4(),
        "requirement_id": requirement.requirement_id if requirement else None,
        "expected_requirement_version": requirement.version if requirement else 0,
        "expected_item_version": overview.item_version,
        "expected_occurrence_version": occurrence.version,
        "expected_edition_version": snapshot.edition_version,
        **(
            asdict(requirement.expectation)
            if requirement
            else {"break_minutes": 0, "minimum_rest_minutes": 0}
        ),
    }
    form = PlanningStaffingRequirementForm(
        data,
        operation=selection.mode,
        zone_name=snapshot.zone_name,
        position_choices=tuple(
            (row.id, f"{row.department_label} · {row.title}") for row in positions
        ),
        initial=initial,
    )
    return PlanningControl(
        title,
        form,
        ((selection.mode, title),),
        "Explicit work terms are separate from audience-facing timing. "
        "Retirement retains history and does not cancel Workforce work.",
    )


def _binding_control(
    request: ProgrammeStaffingReadRequest,
    snapshot: SchedulingPlanningSnapshot,
    selection: PlanningSelection,
    requirement: ProgrammeStaffingRequirementView | None,
    binding: ProgrammeBindingView | None,
    data: QueryDict | None,
) -> tuple[PlanningControl, dict[str, Any]]:
    title = STAFFING_MODE_LABELS[selection.mode]
    extras: dict[str, Any] = {}
    if (
        requirement is None
        or selection.occurrence_id is None
        or selection.candidate_id is None
    ):
        return PlanningControl(
            title,
            None,
            (),
            "Select the exact requirement, occurrence and private alternative first.",
        ), extras
    common = {
        "actor_id": request.actor_id,
        "organization_id": request.organization_id,
        "edition_id": request.edition_id,
    }
    try:
        authorize_programme_staffing_adapter(**common, purpose="write")
        can_write = _can_manage(request) and snapshot.accepts_writes
    except ProgrammeStaffingDeniedError:
        can_write = False
    extras["staffing_can_apply"] = can_write
    if not snapshot.accepts_writes:
        if data is not None:
            raise ProgrammeStaffingDeniedError
        return PlanningControl(
            title,
            None,
            (),
            "This edition no longer accepts a new private work request. "
            "Current reads do not grant mutation authority.",
        ), extras
    operation = BINDING_MODES[selection.mode]
    if data is None and (operation in {"create", "link"}) != (binding is None):
        return PlanningControl(
            title,
            None,
            (),
            "Existing work lineage needs explicit reconciliation or successor "
            "recovery; it cannot be overwritten by another first link.",
        ), extras
    candidate = next(
        (row for row in snapshot.candidates if row.id == selection.candidate_id), None
    )
    occurrence = next(
        (row for row in snapshot.occurrences if row.id == selection.occurrence_id), None
    )
    placement = next(
        (
            row
            for row in snapshot.placements
            if row.occurrence_id == selection.occurrence_id
        ),
        None,
    )
    source = None
    if candidate and occurrence and placement:
        source = ProgrammeStaffingSource(
            requirement.requirement_id,
            requirement.revision_id,
            requirement.version,
            occurrence.id,
            occurrence.version,
            candidate.id,
            candidate.revision_id,
            placement.id,
        )
    if data is None and (
        source is None
        or requirement.lifecycle != "active"
        or candidate is None
        or candidate.lifecycle != "draft"
    ):
        return PlanningControl(
            title,
            None,
            (),
            "Place an active occurrence in an explicit current private draft "
            "before requesting work. Retained history is not an active source.",
        ), extras
    demand_id = binding.demand_id if binding else None
    demand_version = 0
    if binding:
        demand = load_programme_staffing_demand(
            **common, demand_id=binding.demand_id, correlation_id=request.correlation_id
        )
        demand_version = demand.version
    elif operation == "link":
        choices = list_programme_linkable_demands(
            **common,
            correlation_id=request.correlation_id,
            expectation=requirement.expectation,
        )
        extras["staffing_demand_choices"] = choices
        extras["staffing_demand_state"] = selection.hidden_values(
            exclude=frozenset({"demand_id"})
        )
        selected = next((row for row in choices if row.id == selection.demand_id), None)
        if selected is None and data is None:
            return PlanningControl(
                title,
                None,
                (),
                "Choose an identical uncommitted draft below, then preview this "
                "exact link. No matching draft is not a staffing gap "
                "or a permission grant.",
            ), extras
        if selected:
            demand_id, demand_version = selected.id, selected.version
    initial = {
        "action": "staffing_preview",
        "operation": operation,
        "retry_key": uuid4(),
        "binding_id": binding.binding_id if binding else None,
        "expected_binding_version": binding.version if binding else 0,
        "demand_id": demand_id,
        "expected_demand_version": demand_version,
        **(asdict(source) if source else {}),
    }
    form = PlanningStaffingBindingForm(data, initial=initial)
    cast("forms.ChoiceField", form.fields["operation"]).choices = [(operation, title)]
    form.fields["operation"].widget = forms.HiddenInput()
    form.fields["demand_id"].widget = forms.HiddenInput()
    return PlanningControl(
        title,
        form,
        (("staffing_preview", "Preview work impact"),),
        "Preview does not change work. Reconciliation requires no retained "
        "commitments. A successor explicitly preserves and may cancel its "
        "predecessor, then creates a separate draft without copied volunteer "
        "decisions. Applying needs both owners' management authority.",
    ), extras


def compose_planning_staffing(
    scope: SchedulingReadRequest,
    snapshot: SchedulingPlanningSnapshot,
    selection: PlanningSelection,
    *,
    data: QueryDict | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> dict[str, Any]:
    """Build one coherent staffing purpose without widening the timetable base read.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Trusted actor and exact owner scope already admitted by the host.
    snapshot : SchedulingPlanningSnapshot
        Audited visible candidate snapshot; changed host context is rejected.
    selection : PlanningSelection
        Explicit transient selected item, occurrence, requirement and task.
    data : QueryDict | None, default=None
        Original pending command namespace, or None for deliberate fresh input.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Independent private-planning policy.

    Returns
    -------
    dict[str, Any]
        Purpose-limited panel, native control or actionable missing-prerequisite state.

    Raises
    ------
    SchedulingVersionConflictError
        If the visible host snapshot moved before this locked owner composition.
    SchedulingUnavailableError
        If the selected requirement does not belong to the exact visible occurrence.
    ProgrammeStaffingDeniedError
        If a selected work action lacks independent Workforce source authority.
    """
    result: dict[str, Any] = {
        "staffing_active": True,
        "staffing_rows": (),
        "control": None,
    }
    if selection.item_id is None:
        return {
            **result,
            "staffing_guidance": "Select a Programme item and exact occurrence "
            "before defining staffing.",
        }
    request = _request(scope, selection)
    with transaction.atomic():
        lock_programme_staffing_scope(
            organization_id=scope.organization_id, edition_id=scope.edition_id
        )
        fresh = load_scheduling_planning(
            scope, candidate_id=selection.candidate_id, authorizer=authorizer
        )
        if (fresh.control_version, fresh.edition_version) != (
            snapshot.control_version,
            snapshot.edition_version,
        ):
            raise SchedulingVersionConflictError(
                "Reload the changed timetable before editing staffing."
            )
        if selection.mode in {
            "staffing_requirement_history",
            "staffing_binding_history",
        }:
            return {**result, **_history(request, selection)}
        overview = load_programme_staffing_requirements(request)
        requirement = next(
            (
                row
                for row in overview.requirements
                if row.requirement_id == selection.requirement_id
            ),
            None,
        )
        if selection.requirement_id is not None and (
            requirement is None or requirement.occurrence_id != selection.occurrence_id
        ):
            raise SchedulingUnavailableError
        try:
            bindings = load_programme_bindings(request)
        except ProgrammeStaffingDeniedError:
            bindings = ()
            result["staffing_bindings_withheld"] = True
        binding_by_requirement = {row.source.requirement_id: row for row in bindings}
        coverage = (
            load_planning_staffing(
                scope,
                item_id=selection.item_id,
                candidate_id=selection.candidate_id,
                scheduling_authorizer=authorizer,
            )
            if selection.candidate_id
            else ()
        )
        coverage_by_requirement = {row.requirement_id: row for row in coverage}
        can_manage = (
            _can_manage(request)
            and fresh.accepts_writes
            and overview.item_lifecycle == "active"
        )
        result["staffing_can_create"] = (
            can_manage and selection.occurrence_id is not None
        )
        result["staffing_rows"] = tuple(
            {
                "requirement": row,
                "binding": binding_by_requirement.get(row.requirement_id),
                "coverage": coverage_by_requirement.get(row.requirement_id),
                "actions": _row_actions(
                    selection,
                    row,
                    binding_by_requirement.get(row.requirement_id),
                    can_manage=can_manage,
                    work_available=not result.get("staffing_bindings_withheld", False),
                ),
                "state": replace(
                    selection,
                    mode="staffing",
                    occurrence_id=row.occurrence_id,
                    requirement_id=row.requirement_id,
                    binding_id=None,
                    demand_id=None,
                    staffing_through_version=None,
                    staffing_after_version=None,
                ).hidden_values(),
            }
            for row in overview.requirements
        )
        result["staffing_selected_requirement"] = requirement
        result["staffing_create_state"] = replace(
            selection,
            mode="staffing_create",
            requirement_id=None,
            binding_id=None,
            demand_id=None,
        ).hidden_values()
        if selection.mode in REQUIREMENT_ACTIONS:
            result["control"] = _requirement_control(
                request, fresh, selection, overview, requirement, data
            )
        elif selection.mode in BINDING_MODES:
            if result.get("staffing_bindings_withheld"):
                raise ProgrammeStaffingDeniedError
            control, extra = _binding_control(
                request,
                fresh,
                selection,
                requirement,
                binding_by_requirement.get(selection.requirement_id)
                if selection.requirement_id
                else None,
                data,
            )
            result.update(control=control, **extra)
        return result
