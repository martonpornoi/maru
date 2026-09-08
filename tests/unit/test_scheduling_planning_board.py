"""Pure complete inventory composition and native server-rendered board contracts."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from uuid import uuid4

import pytest
from django.template.loader import render_to_string

from maru.programme.queries import (
    ProgrammeItemProjection,
    ProgrammeTimetableItemProjection,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_board import (
    PlanningInventoryState,
    build_scheduling_planning_board,
)
from maru.scheduling.planning_forms import PlanningPlacementForm
from maru.scheduling.planning_queries import (
    PlanningCandidate,
    PlanningDay,
    PlanningOccurrence,
    PlanningPlacement,
    SchedulingPlanningSnapshot,
)
from maru.scheduling.time_rules import SchedulingEnvelope, SchedulingWindow
from maru.venues.timetable_queries import VenueTimetableSpace
from tests.unit import test_scheduling_planning_forms as form_helpers

placement_values = form_helpers.placement_values


@pytest.fixture
def board_inputs():
    starts = datetime(2030, 8, 2, 20, tzinfo=UTC)
    items = tuple(
        ProgrammeTimetableItemProjection(
            ProgrammeItemProjection(uuid4(), "organizer", "organizer", "active", 1),
            title,
            1,
        )
        for title in ("Opening workshop", "Item before an occurrence")
    )
    day = PlanningDay(
        uuid4(),
        uuid4(),
        1,
        "Friday overnight",
        "active",
        SchedulingWindow(starts, starts + timedelta(hours=12)),
        5,
    )
    space = VenueTimetableSpace(
        uuid4(),
        1,
        "Workshop room",
        "Seated",
        "active",
        uuid4(),
        1,
        "Main building",
        "active",
    )
    group = uuid4()
    occurrences = tuple(
        PlanningOccurrence(
            uuid4(),
            uuid4(),
            1,
            items[0].item.id,
            "retired" if sequence == 3 else "active",
            group,
            sequence,
        )
        for sequence in (1, 2, 3)
    )
    placements = tuple(
        PlanningPlacement(
            uuid4(),
            occurrence.id,
            occurrence.revision_id,
            day.revision_id,
            space.id,
            "seated",
            60,
            SchedulingEnvelope(
                starts + timedelta(hours=hour),
                starts + timedelta(hours=hour, minutes=15),
                starts + timedelta(hours=hour + 1),
                starts + timedelta(hours=hour + 1, minutes=15),
            ),
            day.id,
        )
        for occurrence, hour in ((occurrences[0], 6), (occurrences[2], 1))
    )
    candidate = PlanningCandidate(
        uuid4(), uuid4(), 3, "Working alternative", "draft", 2
    )
    snapshot = SchedulingPlanningSnapshot(
        control_version=8,
        edition_version=1,
        accepts_writes=True,
        days=(day,),
        occurrences=occurrences,
        candidates=(candidate,),
        selected_candidate_id=candidate.id,
        placements=placements,
        zone_name="Europe/Budapest",
    )
    return snapshot, items, (space,)


def board(inputs):
    snapshot, items, spaces = inputs
    return build_scheduling_planning_board(snapshot, items=items, spaces=spaces)


def test_board_preserves_every_inventory_state_and_distinct_occurrence(board_inputs):
    result = board(board_inputs)
    assert len(result.entries) == 4
    assert {entry.state for entry in result.entries} == {
        PlanningInventoryState.PLACED,
        PlanningInventoryState.UNPLACED,
        PlanningInventoryState.RETIRED,
        PlanningInventoryState.NO_OCCURRENCE,
    }
    assert len({entry.key for entry in result.entries}) == 4
    assert len(result.lanes) == 1
    assert [entry.occurrence.group_sequence for entry in result.lanes[0].entries] == [
        3,
        1,
    ]
    assert len(result.days) == len(result.spaces) == 1


def test_board_retains_stable_day_after_metadata_revision_changes(board_inputs):
    snapshot, items, spaces = board_inputs
    revised = replace(
        snapshot.days[0], revision_id=uuid4(), version=2, label="Revised day"
    )
    result = board((replace(snapshot, days=(revised,)), items, spaces))
    assert result.lanes[0].day.id == snapshot.days[0].id
    assert result.lanes[0].day.label == "Revised day"
    assert all(entry.metadata_changed for entry in result.lanes[0].entries)
    assert {entry.placement.envelope for entry in result.lanes[0].entries} == {
        placement.envelope for placement in snapshot.placements
    }


def test_no_selected_candidate_does_not_call_occurrences_globally_unplaced(
    board_inputs,
):
    snapshot, items, spaces = board_inputs
    result = board(
        (replace(snapshot, selected_candidate_id=None, placements=()), items, spaces)
    )
    assert result.candidate is None
    assert result.lanes == ()
    assert PlanningInventoryState.NO_CANDIDATE in {
        entry.state for entry in result.entries
    }
    assert PlanningInventoryState.UNPLACED not in {
        entry.state for entry in result.entries
    }


@pytest.mark.parametrize(
    "missing", ["item", "space", "day", "occurrence", "candidate", "count"]
)
def test_board_withholds_incomplete_references_instead_of_hiding_work(
    board_inputs, missing
):
    snapshot, items, spaces = board_inputs
    if missing == "item":
        items = items[1:]
    elif missing == "space":
        spaces = ()
    elif missing == "day":
        snapshot = replace(snapshot, days=())
    elif missing == "occurrence":
        snapshot = replace(snapshot, occurrences=snapshot.occurrences[1:])
    elif missing == "candidate":
        snapshot = replace(snapshot, selected_candidate_id=uuid4())
    else:
        snapshot = replace(
            snapshot, candidates=(replace(snapshot.candidates[0], placement_count=1),)
        )
    with pytest.raises(SchedulingUnavailableError):
        board((snapshot, items, spaces))


@pytest.mark.parametrize(
    "duplicate", ["item", "space", "days", "occurrences", "candidates", "placements"]
)
def test_board_rejects_duplicate_projections_not_silent_dictionary_overwrite(
    board_inputs, duplicate
):
    snapshot, items, spaces = board_inputs
    if duplicate == "item":
        items = (*items, items[0])
    elif duplicate == "space":
        spaces = (*spaces, spaces[0])
    else:
        values = getattr(snapshot, duplicate)
        snapshot = replace(snapshot, **{duplicate: (*values, values[0])})
    with pytest.raises(SchedulingUnavailableError):
        board((snapshot, items, spaces))


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def rendered(board_inputs, **extra):
    return render_to_string(
        "scheduling/planning_board.html",
        {
            "board": board(board_inputs),
            "edition_label": "Synthetic weekend",
            "csrf_token": "synthetic-test-token",
            **extra,
        },
    )


def test_board_renders_one_heading_landmark_unique_ids_and_explicit_overnight_times(
    board_inputs,
):
    html = rendered(board_inputs)
    elements = Elements(html).elements
    assert sum(tag == "h1" for tag, _ in elements) == 1
    assert sum(tag == "main" for tag, _ in elements) == 1
    identifiers = [attrs["id"] for _, attrs in elements if "id" in attrs]
    assert len(identifiers) == len(set(identifiers))
    for text in (
        "Europe/Budapest",
        "Friday overnight",
        "3 Aug 2030",
        "+0200",
        "Preparation starts",
        "Delivery ends",
        "Teardown ends",
        "No occurrence yet",
        "Retired item or occurrence",
        "not published or a room reservation",
    ):
        assert text in html
    assert sum("data-planning-placement" in attrs for _, attrs in elements) == 2
    assert sum("data-planning-entry" in attrs for _, attrs in elements) == 4


def test_board_autoescapes_authorized_but_untrusted_owner_labels(board_inputs):
    snapshot, items, spaces = board_inputs
    attack = '</h4><script>alert("private")</script>'
    items = (replace(items[0], internal_title=attack), items[1])
    html = rendered((snapshot, items, spaces))
    assert attack not in html
    assert "&lt;script&gt;" in html
    assert not any(tag == "script" for tag, _ in Elements(html).elements)


def test_native_placement_render_supplies_action_once_and_defaults_to_preview(
    board_inputs, placement_values
):
    data, choices = placement_values
    form = PlanningPlacementForm(data, **choices)
    html = rendered(board_inputs, placement_form=form)
    elements = Elements(html).elements
    actions = [(tag, attrs) for tag, attrs in elements if attrs.get("name") == "action"]
    assert [tag for tag, _ in actions] == ["button", "button"]
    assert [attrs["value"] for _, attrs in actions] == [
        "preview_placement",
        "save_placement",
    ]
    identifiers = [attrs["id"] for _, attrs in elements if "id" in attrs]
    assert len(identifiers) == len(set(identifiers))
    assert any(attrs.get("name") == "csrfmiddlewaretoken" for _, attrs in elements)
    assert any(
        attrs.get("name") == "retry_key" and attrs.get("value") == data["retry_key"]
        for _, attrs in elements
    )


def test_native_form_error_summary_links_to_retained_fields(
    board_inputs, placement_values
):
    data, choices = placement_values
    form = PlanningPlacementForm(
        {**data, "effective_ends_at": "not an instant"}, **choices
    )
    html = rendered(board_inputs, placement_form=form)
    assert "Review this form" in html
    assert 'href="#id_effective_ends_at"' in html
    assert 'value="not an instant"' in html
    assert 'name="retry_key"' in html
