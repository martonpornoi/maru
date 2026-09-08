"""Independently authorized owner reads for the dormant native editor workspace."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from maru.programme.queries import list_programme_timetable_items
from maru.venues.timetable_queries import list_venue_timetable_spaces

from .authorization import (
    ACKNOWLEDGE_WARNINGS,
    DEFAULT_SCHEDULING_AUTHORIZER,
    EVALUATE_CANDIDATES,
    MANAGE_CANDIDATES,
    MANAGE_DAYS,
    MANAGE_OCCURRENCES,
    MANAGE_RESERVATIONS,
    VIEW_CONFLICTS,
    VIEW_HISTORY,
    VIEW_PLANNING,
    SchedulingAuthorizationDeniedError,
    authorize_scheduling_scope,
)
from .catalogs import SchedulingOperation as Op
from .command_support import SchedulingUnavailableError
from .planning_board import PlanningInventoryState, build_scheduling_planning_board
from .planning_controls import _TITLES, build_planning_control
from .planning_hosts import load_scheduling_host_requirements
from .planning_inspector import PlanningItemLayer, load_scheduling_item_inspector
from .planning_interactions import compare_planning_placements
from .planning_presentation import describe_planning_findings
from .planning_preview import PREVIEW_FIELDS
from .planning_queries import (
    HISTORY_FIELDS,
    PLANNING_FIELDS,
    list_scheduling_candidate_history,
    load_scheduling_historical_manifest,
)
from .planning_reservations import load_scheduling_reservation_review
from .planning_review import load_scheduling_candidate_review
from .planning_selection import filter_planning_board, resolve_planning_selection

if TYPE_CHECKING:
    from django.http import QueryDict

    from .authorization import SchedulingAuthorizer
    from .planning_board import SchedulingPlanningBoard
    from .planning_queries import SchedulingPlanningSnapshot, SchedulingReadRequest
    from .planning_selection import PlanningSelection


_MODE_CAPABILITIES = {
    "overview": frozenset({VIEW_PLANNING}),
    "history": frozenset({VIEW_HISTORY}),
    "review": frozenset({VIEW_CONFLICTS}),
    "reservation": frozenset({VIEW_CONFLICTS}),
    "placement": frozenset({MANAGE_CANDIDATES, VIEW_CONFLICTS}),
    "create_day": frozenset({MANAGE_DAYS}),
    "revise_day": frozenset({MANAGE_DAYS}),
    Op.DAY_RETIRE: frozenset({MANAGE_DAYS}),
    Op.OCCURRENCE_CREATE: frozenset({MANAGE_OCCURRENCES}),
    Op.OCCURRENCE_REVISE: frozenset({MANAGE_OCCURRENCES}),
    Op.OCCURRENCE_RETIRE: frozenset({MANAGE_OCCURRENCES}),
    Op.CANDIDATE_CREATE: frozenset({MANAGE_CANDIDATES}),
    Op.CANDIDATE_COPY: frozenset({MANAGE_CANDIDATES, VIEW_HISTORY}),
    Op.CANDIDATE_RESTORE: frozenset({MANAGE_CANDIDATES, VIEW_HISTORY}),
    Op.CANDIDATE_ARCHIVE: frozenset({MANAGE_CANDIDATES}),
    Op.PLACEMENT_REMOVE: frozenset({MANAGE_CANDIDATES}),
    Op.EVALUATION_RECORD: frozenset({EVALUATE_CANDIDATES, VIEW_CONFLICTS}),
    Op.WARNING_ACKNOWLEDGE: frozenset({ACKNOWLEDGE_WARNINGS, VIEW_CONFLICTS}),
    Op.RESERVATION_REPLACE: frozenset({MANAGE_RESERVATIONS, VIEW_CONFLICTS}),
    Op.RESERVATION_CANCEL: frozenset({MANAGE_RESERVATIONS, VIEW_CONFLICTS}),
}
_MODE_LABELS = {
    "overview": "Selected item",
    "history": "Draft history and comparison",
    "review": "Current conflict review",
    "reservation": "Current physical hold",
    **_TITLES,
}
_READ_FIELDS = {
    VIEW_PLANNING: PLANNING_FIELDS,
    VIEW_HISTORY: HISTORY_FIELDS,
    VIEW_CONFLICTS: PREVIEW_FIELDS,
}
_REVIEW_MODES = {"review", Op.EVALUATION_RECORD, Op.WARNING_ACKNOWLEDGE}
_RESERVATION_MODES = {"reservation", Op.RESERVATION_REPLACE, Op.RESERVATION_CANCEL}


def _access(
    scope: SchedulingReadRequest, authorizer: SchedulingAuthorizer
) -> frozenset[str]:
    allowed = set()
    for capability in sorted(set().union(*_MODE_CAPABILITIES.values())):
        try:
            authorize_scheduling_scope(
                actor_id=scope.actor_id,
                organization_id=scope.organization_id,
                edition_id=scope.edition_id,
                capability_code=capability,
                requested_fields=_READ_FIELDS.get(capability),
                authorizer=authorizer,
            )
        except SchedulingAuthorizationDeniedError:
            continue
        allowed.add(capability)
    if VIEW_PLANNING not in allowed:
        raise SchedulingAuthorizationDeniedError
    return frozenset(allowed)


def _history(
    scope: SchedulingReadRequest,
    selection: PlanningSelection,
    authorizer: SchedulingAuthorizer,
) -> dict[str, Any]:
    history = None
    if selection.mode == "history" and selection.candidate_id:
        history = list_scheduling_candidate_history(
            scope,
            candidate_id=selection.candidate_id,
            before_version=selection.before_version,
            authorizer=authorizer,
        )
    manifest = (
        load_scheduling_historical_manifest(
            scope, revision_id=selection.history_id, authorizer=authorizer
        )
        if selection.history_id
        else None
    )
    comparison = (
        load_scheduling_historical_manifest(
            scope, revision_id=selection.compare_id, authorizer=authorizer
        )
        if selection.compare_id
        else None
    )
    changes = (
        compare_planning_placements(manifest.placements, comparison.placements)
        if manifest and comparison
        else None
    )
    return {
        "history": history,
        "manifest": manifest,
        "comparison": comparison,
        "changes": changes,
    }


def _layers(
    scope: SchedulingReadRequest,
    snapshot: SchedulingPlanningSnapshot,
    selection: PlanningSelection,
    authorizer: SchedulingAuthorizer,
) -> dict[str, Any]:
    result = _history(scope, selection, authorizer)
    result.update(inspector=None, review=None, reservation=None, hosts=None)
    if selection.item_id and selection.layer:
        result["inspector"] = load_scheduling_item_inspector(
            scope,
            item_id=selection.item_id,
            layer=selection.layer,
            authorizer=authorizer,
        )
    candidate = next(
        (
            candidate
            for candidate in snapshot.candidates
            if candidate.id == selection.candidate_id
        ),
        None,
    )
    if (selection.mode in _REVIEW_MODES or selection.conflict_id) and candidate:
        result["review"] = load_scheduling_candidate_review(
            scope,
            candidate_id=candidate.id,
            expected_version=candidate.version,
            authorizer=authorizer,
        )
    if selection.conflict_id and (
        result["review"] is None
        or selection.conflict_id
        not in {finding.id for finding in result["review"].saved_findings}
    ):
        raise SchedulingUnavailableError
    if selection.mode in _RESERVATION_MODES and selection.occurrence_id:
        result["reservation"] = load_scheduling_reservation_review(
            scope, occurrence_id=selection.occurrence_id, authorizer=authorizer
        )
    if selection.mode == "placement" and candidate and selection.occurrence_id:
        result["hosts"] = load_scheduling_host_requirements(
            scope,
            candidate_id=candidate.id,
            expected_version=candidate.version,
            occurrence_id=selection.occurrence_id,
            authorizer=authorizer,
        )
    return result


def _transport_context(selection: PlanningSelection) -> dict[str, Any]:
    # Query controls name their action once; state and mutation fields never mix.
    overview = replace(
        selection,
        mode="overview",
        history_id=None,
        compare_id=None,
        before_version=None,
        conflict_id=None,
    )
    inventory = replace(overview, layer=None)
    return {
        "selection_state": selection.hidden_values(),
        "filter_state": overview.hidden_values(
            exclude=frozenset({"candidate_id", "day_id", "space_id", "text", "state"})
        ),
        "inventory_state": inventory.hidden_values(
            exclude=frozenset({"item_id", "occurrence_id"})
        ),
        "mode_state": replace(selection, conflict_id=None).hidden_values(
            exclude=frozenset({"mode"})
        ),
        "layer_state": overview.hidden_values(exclude=frozenset({"layer"})),
        "history_state": selection.hidden_values(
            exclude=frozenset({"history_id", "compare_id", "before_version"})
        ),
        "history_page_state": selection.hidden_values(
            exclude=frozenset({"before_version"})
        ),
        "ack_state": replace(selection, mode=Op.WARNING_ACKNOWLEDGE).hidden_values(
            exclude=frozenset({"conflict_id"})
        ),
        "state_choices": tuple(
            (state.value, state.value.replace("_", " ").title())
            for state in PlanningInventoryState
        ),
        "layer_choices": tuple(
            (layer.value, layer.value.replace("_", " ").title())
            for layer in PlanningItemLayer
        ),
    }


def _presentation_context(
    layers: dict[str, Any],
    board: SchedulingPlanningBoard,
    access: frozenset[str],
    *,
    accepts_writes: bool,
) -> dict[str, Any]:
    review, manifest = layers["review"], layers["manifest"]
    labels = {
        entry.occurrence.id: entry.item.internal_title
        for entry in board.entries
        if entry.occurrence
    }
    saved = review.saved_findings if review else ()
    return {
        "review_rows": describe_planning_findings(review.current.findings)
        if review
        else (),
        "saved_review_rows": tuple(
            {**row, "saved": finding}
            for row, finding in zip(
                describe_planning_findings(tuple(finding.finding for finding in saved)),
                saved,
                strict=True,
            )
        ),
        "can_acknowledge": accepts_writes
        and _MODE_CAPABILITIES[Op.WARNING_ACKNOWLEDGE] <= access,
        "history_placements": tuple(
            {
                "placement": placement,
                "current_title": labels.get(placement.occurrence_id),
            }
            for placement in manifest.placements
        )
        if manifest
        else (),
        "change_rows": tuple(
            {"change": change, "current_title": labels.get(change.occurrence_id)}
            for change in layers["changes"] or ()
        ),
    }


def compose_planning_workspace(
    scope: SchedulingReadRequest,
    snapshot: SchedulingPlanningSnapshot,
    selection: PlanningSelection,
    *,
    data: QueryDict | None = None,
    authorizer: SchedulingAuthorizer = DEFAULT_SCHEDULING_AUTHORIZER,
) -> dict[str, Any]:
    """Compose the native page without a cross-owner actor-first transaction.

    The HTTP adapter obtains the base audited snapshot before parsing any POST
    selection. Every owner read below independently authorizes and audits; any
    denial propagates, withholding all previously read private page context.
    An access summary is computed policy, not permission to bypass the owner
    command. Do not surround this composition with an outer transaction: a
    later multi-person owner read must acquire its complete canonical lock set.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Server-resolved authenticated actor, tenant, edition and correlation.
    snapshot : SchedulingPlanningSnapshot
        Audited complete base read for this exact scope and selected candidate.
    selection : PlanningSelection
        Strict transient selection, never actor or mutation attribution.
    data : QueryDict | None, default=None
        Exact command namespace when binding a pending intent; otherwise new form.
    authorizer : SchedulingAuthorizer, default=DEFAULT_SCHEDULING_AUTHORIZER
        Ordinary policy or the existing doubly sealed isolated-test substitute.

    Returns
    -------
    dict[str, Any]
        Template context composed only of current independently authorized layers.

    Raises
    ------
    SchedulingAuthorizationDeniedError
        If current base or selected mode authority is not independently proved.
    """
    access = _access(scope, authorizer)
    if not _MODE_CAPABILITIES.get(selection.mode, frozenset({"unavailable"})) <= access:
        raise SchedulingAuthorizationDeniedError
    items = list_programme_timetable_items(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=scope.correlation_id,
    )
    spaces = list_venue_timetable_spaces(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        correlation_id=scope.correlation_id,
    )
    complete_board = build_scheduling_planning_board(
        snapshot, items=items, spaces=spaces
    )
    selection, entry = resolve_planning_selection(complete_board, selection)
    layers = _layers(scope, snapshot, selection, authorizer)
    control = None
    if selection.mode in _TITLES:
        control = build_planning_control(
            snapshot,
            complete_board,
            selection,
            data=data,
            hosts=layers["hosts"],
            history=layers["manifest"],
            reservation=layers["reservation"],
            review=layers["review"],
        )
    visible = filter_planning_board(complete_board, selection)
    return {
        "snapshot": snapshot,
        "board": visible,
        "complete_board": complete_board,
        "selection": selection,
        "selected_entry": entry,
        "selected_item": next(
            (item for item in items if item.item.id == selection.item_id), None
        ),
        "selection_hidden": entry is not None and entry not in visible.entries,
        "can_select": True,
        "control": control,
        "is_placement": selection.mode == "placement",
        "mode_choices": tuple(
            (mode, _MODE_LABELS[mode])
            for mode, required in _MODE_CAPABILITIES.items()
            if required <= access and (snapshot.accepts_writes or mode not in _TITLES)
        ),
        "access_label": "Read-only edition"
        if not snapshot.accepts_writes
        else "Current independently checked permissions",
        "available_actions": tuple(
            _MODE_LABELS[mode]
            for mode, required in _MODE_CAPABILITIES.items()
            if required <= access and (snapshot.accepts_writes or mode not in _TITLES)
        ),
        **layers,
        **_presentation_context(
            layers, complete_board, access, accepts_writes=snapshot.accepts_writes
        ),
        **_transport_context(selection),
    }
