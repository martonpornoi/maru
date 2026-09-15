"""Final read-only source checks for the canonically routed timetable workspace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .command_support import SchedulingUnavailableError
from .planning_queries import load_scheduling_planning
from .planning_workspace import compose_planning_workspace

if TYPE_CHECKING:
    from .planning_queries import SchedulingReadRequest


_SOURCE_KEYS = frozenset(
    {
        "snapshot",
        "complete_board",
        "selection",
        "selected_item",
        "inspector",
        "review",
        "reservation",
        "hosts",
        "history",
        "manifest",
        "comparison",
        "changes",
        "mode_choices",
        "available_actions",
        "can_acknowledge",
        "can_start_placement",
    }
)
_TRANSIENT_STAFFING = frozenset({"staffing_preview", "staffing_impact_rows"})


def _facts(context: dict[str, Any]) -> dict[str, Any]:
    return {
        name: value
        for name, value in context.items()
        if name in _SOURCE_KEYS
        or (name.startswith("staffing_") and name not in _TRANSIENT_STAFFING)
    }


def _choices(context: dict[str, Any]) -> tuple[Any, ...]:
    control = context.get("control")
    if control is None or control.form is None:
        return ()
    return tuple(
        (name, tuple(field.widget.choices))
        for name, field in control.form.fields.items()
        if hasattr(field.widget, "choices")
    )


def verify_planning_workspace(
    scope: SchedulingReadRequest, context: dict[str, Any]
) -> None:
    """Reauthorize and compare displayed owner facts without submitting a command.

    Parameters
    ----------
    scope : SchedulingReadRequest
        Trusted authenticated actor and exact route scope.
    context : dict[str, Any]
        Existing native component context, including its original bound control.

    Raises
    ------
    SchedulingUnavailableError
        If a displayed source, permission-dependent control or owner choice changed.

    Notes
    -----
    The ordinary owner reads retain their own policy, completeness and audit checks.
    Recomposition never calls the HTTP dispatcher or a mutation. It neither changes
    the submitted form nor substitutes a fresh version/retry key. Fresh unused form
    keys are not compared or rendered. Preview-only consequences remain pending
    observations, not persisted source facts. Owner denial propagates to the wrapper.
    """
    snapshot = context["snapshot"]
    fresh = load_scheduling_planning(scope, candidate_id=snapshot.selected_candidate_id)
    if fresh != snapshot:
        raise SchedulingUnavailableError
    control = context.get("control")
    form = control.form if control is not None else None
    observed = compose_planning_workspace(
        scope,
        fresh,
        context["selection"],
        data=form.data if form is not None and form.is_bound else None,
    )
    if _facts(observed) != _facts(context) or _choices(observed) != _choices(context):
        raise SchedulingUnavailableError
