"""Strict transient page selection, separate from versioned mutation input."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from django import forms
from django.http import QueryDict

from maru.core.forms import (
    CanonicalUUIDField,
    StrictBase10IntegerField,
    StrictInputForm,
)

from .catalogs import MAX_TITLE_LENGTH
from .command_support import SchedulingUnavailableError
from .planning_board import PlanningInventoryState
from .planning_inspector import PlanningItemLayer
from .planning_record_forms import PLANNING_RECORD_OPERATIONS
from .planning_staffing_forms import STAFFING_MODE_LABELS

if TYPE_CHECKING:
    from uuid import UUID

    from .planning_board import PlanningBoardEntry, SchedulingPlanningBoard

_MODES = (
    "overview",
    "placement",
    "create_day",
    "revise_day",
    "history",
    "review",
    "reservation",
    *STAFFING_MODE_LABELS,
    *(operation.value for operation in sorted(PLANNING_RECORD_OPERATIONS)),
)
_UUID_FIELDS = (
    "candidate_id",
    "day_id",
    "space_id",
    "item_id",
    "occurrence_id",
    "history_id",
    "compare_id",
    "conflict_id",
    "requirement_id",
    "binding_id",
    "demand_id",
)
_TEXT_FIELDS = ("text", "state", "mode", "layer")
_INTEGER_FIELDS = (
    "before_version",
    "staffing_through_version",
    "staffing_after_version",
)


@dataclass(frozen=True, slots=True)
class PlanningSelection:
    """Transient selected context; none of these identifiers grants authority.

    Attributes
    ----------
    candidate_id
        Deliberately selected private draft, or no selection.
    day_id
        Optional stable service-day filter or selected day control.
    space_id
        Optional authorized room filter/default, not a physical hold.
    item_id
        Explicit item selection, independently checked against the owner inventory.
    occurrence_id
        Optional exact occurrence, independently checked against the scoped snapshot.
    history_id
        Explicit historical candidate revision, never an inferred current version.
    compare_id
        Optional second exact historical revision for comparison.
    conflict_id
        Explicit saved finding, rechecked by the independently authorized review.
    before_version
        Exclusive native history-page cursor, never an optimistic command version.
    text
        Bounded transient private search text, never persisted in a URL or storage.
    state
        Closed visible inventory filter, or all.
    mode
        Selected native editor, not a mutation dispatch or authorization decision.
    layer
        One explicitly selected Programme inspector layer, or none.
    requirement_id
        Explicit staffing need, independently resolved inside the selected item.
    binding_id
        Exact retained Workforce lineage for the selected history purpose.
    demand_id
        Explicit existing draft selected for linking, not implicit work creation.
    staffing_through_version
        Fixed inclusive ceiling for an explicitly selected staffing history.
    staffing_after_version
        Exclusive cursor within that fixed ceiling, or none at the beginning.
    """

    candidate_id: UUID | None = None
    day_id: UUID | None = None
    space_id: UUID | None = None
    item_id: UUID | None = None
    occurrence_id: UUID | None = None
    history_id: UUID | None = None
    compare_id: UUID | None = None
    conflict_id: UUID | None = None
    before_version: int | None = None
    text: str = ""
    state: str = "all"
    mode: str = "overview"
    layer: PlanningItemLayer | None = None
    requirement_id: UUID | None = None
    binding_id: UUID | None = None
    demand_id: UUID | None = None
    staffing_through_version: int | None = None
    staffing_after_version: int | None = None

    def hidden_values(
        self, *, exclude: frozenset[str] = frozenset()
    ) -> tuple[tuple[str, str], ...]:
        """Render an explicit allowlist of form state without copying owner data.

        Parameters
        ----------
        exclude : frozenset[str], default=frozenset()
            Unprefixed fields supplied by visible controls or clicked buttons instead.

        Returns
        -------
        tuple[tuple[str, str], ...]
            Namespaced single-value fields for the current authenticated page only.
        """
        return tuple(
            (f"ui_{name}", str(value) if value is not None else "")
            for name in (*_UUID_FIELDS, *_TEXT_FIELDS, *_INTEGER_FIELDS)
            if name not in exclude
            for value in (getattr(self, name),)
        )


class PlanningSelectionForm(StrictInputForm):
    """Reject repeated/unknown selection fields before resolving any private target."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Declare closed transient fields, without loading choices or records.

        Parameters
        ----------
        *args : Any
            Ordinary Django form input arguments.
        **kwargs : Any
            Ordinary form options, excluding any new authority or persistence.
        """
        super().__init__(*args, **kwargs)
        for name in _UUID_FIELDS:
            self.fields[f"ui_{name}"] = CanonicalUUIDField(required=False)
        self.fields["ui_before_version"] = StrictBase10IntegerField(
            required=False, min_value=1, max_value=2**63 - 2
        )
        self.fields["ui_staffing_through_version"] = StrictBase10IntegerField(
            required=False, min_value=1, max_value=1001
        )
        self.fields["ui_staffing_after_version"] = StrictBase10IntegerField(
            required=False, min_value=0, max_value=1000
        )
        self.fields["ui_text"] = forms.CharField(
            required=False, max_length=MAX_TITLE_LENGTH
        )
        self.fields["ui_state"] = forms.ChoiceField(
            required=False,
            choices=[
                ("all", "All entries"),
                *((state.value, state.value) for state in PlanningInventoryState),
            ],
        )
        self.fields["ui_mode"] = forms.ChoiceField(
            required=False, choices=[(mode, mode) for mode in _MODES]
        )
        self.fields["ui_layer"] = forms.ChoiceField(
            required=False,
            choices=[(layer.value, layer.value) for layer in PlanningItemLayer],
        )

    def selection(self) -> PlanningSelection | None:
        """Return typed valid selection without silently fixing invalid identifiers.

        Returns
        -------
        PlanningSelection | None
            Explicit selection, or none with errors and original input retained.
        """
        if not self.is_valid():
            return None
        data = self.cleaned_data
        return PlanningSelection(
            **{name: data[f"ui_{name}"] for name in (*_UUID_FIELDS, *_INTEGER_FIELDS)},
            text=data["ui_text"],
            state=data["ui_state"] or "all",
            mode=data["ui_mode"] or "overview",
            layer=PlanningItemLayer(data["ui_layer"]) if data["ui_layer"] else None,
        )


def split_planning_post(data: QueryDict) -> tuple[PlanningSelectionForm, QueryDict]:
    """Separate transport namespaces without dropping unknown or repeated input.

    The caller must prove base Scheduling scope before invoking this parser.
    Unknown ui-prefixed keys remain in the strict selection form; every other
    key remains in the strict query/command form. Nothing is persisted, inferred
    from a URL, used as actor/tenant authority, or merged into command versions.

    Parameters
    ----------
    data : QueryDict
        Original POST body, including single-value multiplicity and CSRF transport.

    Returns
    -------
    tuple[PlanningSelectionForm, QueryDict]
        Unvalidated selection form and exact remaining command input.
    """
    selection_data, command_data = QueryDict(mutable=True), data.copy()
    for name in data:
        if name.startswith("ui_"):
            selection_data.setlist(name, data.getlist(name))
            command_data.pop(name)
    return PlanningSelectionForm(selection_data), command_data


class PlanningQueryForm(StrictInputForm):
    """Keep selection/filter requests outside the mutation dispatch entirely."""

    action = forms.ChoiceField(
        choices=(("select", "Apply selection"), ("clear_filters", "Clear filters"))
    )


def resolve_planning_selection(
    board: SchedulingPlanningBoard, selection: PlanningSelection
) -> tuple[PlanningSelection, PlanningBoardEntry | None]:
    """Resolve explicit scoped selection before filtering, without guessing a target.

    History and finding identifiers are deliberately not resolved here: their
    independent protected queries must authorize them before use or disclosure.

    Parameters
    ----------
    board : SchedulingPlanningBoard
        Complete composition of independently authorized current owner reads.
    selection : PlanningSelection
        Syntactically validated transient selection, never authority.

    Returns
    -------
    tuple[PlanningSelection, PlanningBoardEntry | None]
        Exact selection with occurrence-owned item identity, and selected entry.

    Raises
    ------
    SchedulingUnavailableError
        If a supplied target is absent, inconsistent or outside these scoped reads.
    """
    if (
        selection.candidate_id != (board.candidate.id if board.candidate else None)
        or (selection.day_id and selection.day_id not in {day.id for day in board.days})
        or (
            selection.space_id
            and selection.space_id not in {space.id for space in board.spaces}
        )
    ):
        raise SchedulingUnavailableError
    selected = None
    if selection.occurrence_id:
        selected = next(
            (
                entry
                for entry in board.entries
                if entry.occurrence and entry.occurrence.id == selection.occurrence_id
            ),
            None,
        )
        if selected is None or (
            selection.item_id and selection.item_id != selected.item.item.id
        ):
            raise SchedulingUnavailableError
        selection = replace(selection, item_id=selected.item.item.id)
    elif selection.item_id:
        matches = tuple(
            entry for entry in board.entries if entry.item.item.id == selection.item_id
        )
        if not matches:
            raise SchedulingUnavailableError
        # Selecting the item is not consent to choose its first repeated occurrence.
        selected = next((entry for entry in matches if entry.occurrence is None), None)
    return selection, selected


def filter_planning_board(
    board: SchedulingPlanningBoard, selection: PlanningSelection
) -> SchedulingPlanningBoard:
    """Filter visible cards only, retaining full destination choices and selection.

    Parameters
    ----------
    board : SchedulingPlanningBoard
        Complete authorized board; keep this original for counts and form choices.
    selection : PlanningSelection
        Resolved transient text, state, day and room filters.

    Returns
    -------
    SchedulingPlanningBoard
        Ordered matching inventory and nonempty lanes, not a new complete inventory.
    """
    query = selection.text.casefold()
    entries = tuple(
        entry
        for entry in board.entries
        if (not query or query in entry.item.internal_title.casefold())
        and selection.state in {"all", entry.state}
        and (
            not entry.placement
            or not selection.day_id
            or (entry.day and entry.day.id == selection.day_id)
        )
        and (
            not entry.placement
            or not selection.space_id
            or (entry.space and entry.space.id == selection.space_id)
        )
    )
    keys = {entry.key for entry in entries}
    lanes = tuple(
        replace(lane, entries=matching)
        for lane in board.lanes
        if (matching := tuple(entry for entry in lane.entries if entry.key in keys))
    )
    return replace(board, entries=entries, lanes=lanes)
