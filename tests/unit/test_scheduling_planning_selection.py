"""Transient selection is strict, scoped and separate from mutation input."""

from dataclasses import replace
from uuid import uuid4

import pytest
from django.http import QueryDict

from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_inspector import PlanningItemLayer
from maru.scheduling.planning_selection import (
    PlanningQueryForm,
    PlanningSelection,
    filter_planning_board,
    resolve_planning_selection,
    split_planning_post,
)
from tests.unit import test_scheduling_planning_board as helpers

board_inputs = helpers.board_inputs


def post(values):
    data = QueryDict(mutable=True)
    data.update(values)
    return data


def test_selection_round_trip_retains_only_explicit_transient_fields():
    selection = PlanningSelection(
        candidate_id=uuid4(),
        day_id=uuid4(),
        space_id=uuid4(),
        item_id=uuid4(),
        occurrence_id=uuid4(),
        history_id=uuid4(),
        compare_id=uuid4(),
        conflict_id=uuid4(),
        before_version=12,
        text="Private workshop",
        state="placed",
        mode="placement",
        layer=PlanningItemLayer.WORKING,
    )
    selection_form, command = split_planning_post(
        post(
            {
                **dict(selection.hidden_values()),
                "action": "save_placement",
                "expected_version": "2",
                "retry_key": str(uuid4()),
                "reason": "Exact intent",
                "csrfmiddlewaretoken": "synthetic",
            }
        )
    )
    assert selection_form.selection() == selection
    assert command["expected_version"] == "2"
    assert command["reason"] == "Exact intent"
    assert set(command) == {
        "action",
        "expected_version",
        "retry_key",
        "reason",
        "csrfmiddlewaretoken",
    }
    assert "ui_occurrence_id" not in dict(
        selection.hidden_values(exclude=frozenset({"occurrence_id"}))
    )


@pytest.mark.parametrize(
    "name",
    [
        "ui_candidate_id",
        "ui_day_id",
        "ui_item_id",
        "ui_mode",
        "ui_text",
        "ui_before_version",
    ],
)
def test_repeated_selection_values_are_not_flattened_or_last_value_wins(name):
    data = post({name: ""})
    data.appendlist(name, "")
    form, _command = split_planning_post(data)
    assert form.selection() is None
    assert form.data.getlist(name) == ["", ""]


@pytest.mark.parametrize(
    "changes",
    [
        {"ui_candidate_id": uuid4().hex},
        {"ui_day_id": str(uuid4()).upper()},
        {"ui_actor_id": str(uuid4())},
        {"ui_organization_id": str(uuid4())},
        {"ui_mode": "publish"},
        {"ui_mode": "placement_set"},
        {"ui_layer": "proposal_answers"},
        {"ui_state": "published"},
        {"ui_before_version": "01"},
        {"ui_before_version": "0"},
        {"ui_text": "x" * 241},
    ],
)
def test_invalid_selection_never_becomes_typed_or_authoritative(changes):
    form, _command = split_planning_post(post(changes))
    assert form.selection() is None
    for name, value in changes.items():
        assert form.data[name] == value


def test_split_preserves_unknown_mutation_keys_and_repeated_actions():
    original = post(
        {"action": "select", "actor_id": str(uuid4()), "unexpected": "private"}
    )
    original.appendlist("action", "save_placement")
    original_copy = original.copy()
    selection, command = split_planning_post(original)
    assert original == original_copy
    assert selection.selection() == PlanningSelection()
    assert command.getlist("action") == ["select", "save_placement"]
    assert command["actor_id"] == original["actor_id"]
    assert not PlanningQueryForm(command).is_valid()


@pytest.mark.parametrize("action", ["select", "clear_filters"])
def test_native_query_form_accepts_no_command_fields(action):
    assert PlanningQueryForm({"action": action}).is_valid()
    assert not PlanningQueryForm({"action": action, "expected_version": "1"}).is_valid()
    assert not PlanningQueryForm({"action": "candidate_create"}).is_valid()


def test_occurrence_selection_resolves_its_item_but_item_selection_does_not_guess(
    board_inputs,
):
    board = helpers.board(board_inputs)
    occurrence = board_inputs[0].occurrences[0]
    selection, entry = resolve_planning_selection(
        board,
        PlanningSelection(candidate_id=board.candidate.id, occurrence_id=occurrence.id),
    )
    assert selection.item_id == occurrence.item_id
    assert entry.occurrence.id == occurrence.id
    item_selection = replace(selection, occurrence_id=None)
    unchanged, no_guessed_occurrence = resolve_planning_selection(board, item_selection)
    assert unchanged == item_selection
    assert no_guessed_occurrence is None


@pytest.mark.parametrize(
    "field", ["candidate_id", "day_id", "space_id", "item_id", "occurrence_id"]
)
def test_scoped_selection_rejects_absent_or_mismatched_targets(board_inputs, field):
    board = helpers.board(board_inputs)
    selection = PlanningSelection(
        candidate_id=board.candidate.id, occurrence_id=board_inputs[0].occurrences[0].id
    )
    with pytest.raises(SchedulingUnavailableError):
        resolve_planning_selection(board, replace(selection, **{field: uuid4()}))


def test_no_occurrence_item_can_be_selected_without_creating_one(board_inputs):
    board = helpers.board(board_inputs)
    item_id = board_inputs[1][1].item.id
    selection = PlanningSelection(candidate_id=board.candidate.id, item_id=item_id)
    resolved, entry = resolve_planning_selection(board, selection)
    assert resolved == selection
    assert entry.item.item.id == item_id
    assert entry.occurrence is None


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, 4),
        ({"text": "WORKshop"}, 3),
        ({"text": "nothing matches"}, 0),
        ({"state": "placed"}, 1),
        ({"state": "unplaced"}, 1),
        ({"state": "retired"}, 1),
        ({"state": "no_occurrence"}, 1),
    ],
)
def test_filters_keep_complete_choices_and_do_not_erase_selection(
    board_inputs, filters, expected
):
    board = helpers.board(board_inputs)
    selection = PlanningSelection(
        candidate_id=board.candidate.id,
        occurrence_id=board_inputs[0].occurrences[0].id,
        **filters,
    )
    filtered = filter_planning_board(board, selection)
    assert len(filtered.entries) == expected
    assert filtered.days == board.days
    assert filtered.spaces == board.spaces
    assert len(board.entries) == 4
    assert all(
        entry in filtered.entries for lane in filtered.lanes for entry in lane.entries
    )
    resolved, selected = resolve_planning_selection(board, selection)
    assert resolved.occurrence_id == selected.occurrence.id


def test_day_room_filters_conjoin_without_inventing_placement_for_unplaced_items(
    board_inputs,
):
    board = helpers.board(board_inputs)
    selection = PlanningSelection(
        candidate_id=board.candidate.id,
        day_id=board.days[0].id,
        space_id=board.spaces[0].id,
    )
    result = filter_planning_board(board, selection)
    assert len(result.entries) == 2
    assert all(
        entry.day.id == selection.day_id and entry.space.id == selection.space_id
        for entry in result.entries
    )
    assert (
        filter_planning_board(board, replace(selection, state="unplaced")).entries == ()
    )
    assert len(board.entries) == 4
