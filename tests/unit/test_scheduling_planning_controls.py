"""Exact new-intent prefill and unchanged retry binding for native controls."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from django.http import QueryDict
from django.template.loader import render_to_string

from maru.programme.host_queries import (
    ProgrammeHostRosterEntry,
    ProgrammeHostRosterSnapshot,
    ProgrammeHostStateProjection,
)
from maru.scheduling.catalogs import SchedulingConflictCode, SchedulingConflictSeverity
from maru.scheduling.catalogs import SchedulingOperation as Op
from maru.scheduling.command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.conflicts import SchedulingFinding
from maru.scheduling.planning_controls import build_planning_control
from maru.scheduling.planning_hosts import PlanningHostRequirements
from maru.scheduling.planning_preview import SchedulingPlanningPreview
from maru.scheduling.planning_queries import (
    PlanningHistoricalManifest,
    PlanningHistoryEntry,
)
from maru.scheduling.planning_record_forms import (
    PLANNING_RECORD_OPERATIONS,
    PlanningRecordForm,
)
from maru.scheduling.planning_reservations import (
    PlanningActiveReservation,
    PlanningReservationState,
    SchedulingReservationReview,
)
from maru.scheduling.planning_review import (
    PlanningReviewState,
    PlanningSavedFinding,
    SchedulingPlanningReview,
)
from maru.scheduling.planning_selection import PlanningSelection
from maru.scheduling.time_rules import SchedulingHostPresence
from tests.unit import test_scheduling_planning_board as helpers

board_inputs = helpers.board_inputs


@pytest.fixture
def controls(board_inputs):
    snapshot, _items, spaces = board_inputs
    board = helpers.board(board_inputs)
    occurrence, placement = snapshot.occurrences[0], snapshot.placements[0]
    candidate = snapshot.candidates[0]
    host_id = uuid4()
    hosts = PlanningHostRequirements(
        candidate.version,
        occurrence.id,
        occurrence.item_id,
        placement.id,
        (
            SchedulingHostPresence(
                host_id,
                placement.envelope.effective_starts_at,
                placement.envelope.effective_ends_at,
            ),
        ),
        ProgrammeHostRosterSnapshot(
            2,
            (
                ProgrammeHostRosterEntry(
                    ProgrammeHostStateProjection(host_id, "host", "confirmed", 2, 1),
                    account_id=uuid4(),
                    person_current=True,
                    display_label="Synthetic host",
                ),
            ),
        ),
    )
    history = PlanningHistoricalManifest(
        candidate.id,
        PlanningHistoryEntry(
            uuid4(),
            1,
            "Earlier label",
            "candidate_create",
            None,
            0,
            uuid4(),
            "Earlier reason",
            placement.envelope.setup_starts_at,
        ),
        (),
    )
    hold = PlanningActiveReservation(
        uuid4(), 2, uuid4(), spaces[0].id, placement.envelope, uuid4(), 4, "approved"
    )
    reservation = SchedulingReservationReview(
        occurrence.id, PlanningReservationState.ACTIVE, hold
    )
    finding = PlanningSavedFinding(
        uuid4(),
        SchedulingFinding(
            "programme",
            SchedulingConflictCode.HOST_OUTSIDE_PREFERENCE,
            SchedulingConflictSeverity.WARNING,
            occurrence.id,
        ),
        acknowledged=False,
        eligible_for_acknowledgement=True,
    )
    review = SchedulingPlanningReview(
        SchedulingPlanningPreview(
            candidate.id,
            candidate.version,
            None,
            (finding.finding,),
            (),
            (),
            complete=True,
        ),
        PlanningReviewState.CURRENT,
        uuid4(),
        placement.envelope.setup_starts_at,
        saved_complete=True,
        saved_findings=(finding,),
    )
    selection = PlanningSelection(
        candidate_id=candidate.id,
        day_id=snapshot.days[0].id,
        item_id=occurrence.item_id,
        occurrence_id=occurrence.id,
        history_id=history.entry.revision_id,
        conflict_id=finding.id,
    )
    return (
        snapshot,
        board,
        selection,
        {
            "hosts": hosts,
            "history": history,
            "reservation": reservation,
            "review": review,
        },
    )


def control(values, mode, **kwargs):
    snapshot, board, selection, sources = values
    return build_planning_control(
        snapshot, board, replace(selection, mode=mode), **{**sources, **kwargs}
    )


def submitted(form, action, **changes):
    data = QueryDict(mutable=True)
    for field in form:
        if field.name != "action":
            value = field.value()
            data[field.name] = "" if value is None else str(value)
    data["action"] = str(action)
    for name, value in changes.items():
        data[name] = str(value)
    return data


@pytest.mark.parametrize(
    "mode",
    [
        "placement",
        "create_day",
        "revise_day",
        *(op.value for op in sorted(PLANNING_RECORD_OPERATIONS)),
    ],
)
def test_every_control_has_one_native_form_and_only_its_closed_buttons(controls, mode):
    result = control(controls, mode)
    assert result.form is not None
    assert not result.form.is_bound
    assert result.form.initial["retry_key"]
    html = render_to_string(
        "scheduling/_planning_form.html",
        {
            "form": result.form,
            "form_id": "planning-editor",
            "is_placement": mode == "placement",
            "submit_actions": result.button_choices,
            "csrf_token": "synthetic",
        },
    )
    identifiers = [
        attrs["id"] for _, attrs in helpers.Elements(html).elements if "id" in attrs
    ]
    assert 'type="hidden" name="action"' not in html
    for action in result.button_choices:
        assert f'value="{action["value"]}"' in html
        assert action["label"] in html
    if mode == "placement":
        assert html.index('value="preview_placement"') < html.index(
            'value="save_placement"'
        )
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("create_day", 8),
        (Op.CANDIDATE_CREATE, 8),
        (Op.OCCURRENCE_CREATE, 8),
        (Op.CANDIDATE_COPY, 8),
        ("revise_day", 1),
        (Op.DAY_RETIRE, 1),
        (Op.OCCURRENCE_REVISE, 1),
        (Op.CANDIDATE_RESTORE, 3),
        (Op.EVALUATION_RECORD, 3),
    ],
)
def test_fresh_controls_choose_shared_control_or_exact_target_version(
    controls, mode, expected
):
    result = control(controls, mode)
    assert result.form.initial["expected_version"] == expected
    assert (
        result.form.initial["retry_key"]
        != control(controls, mode).form.initial["retry_key"]
    )


def test_placement_prefill_keeps_four_instants_and_required_hosts_not_availability(
    controls,
):
    snapshot, _board, _selection, sources = controls
    result = control(controls, "placement")
    data = submitted(result.form, "preview_placement")
    bound = control(controls, "placement", data=data).form
    assert bound.is_valid(), bound.errors
    assert bound.placement_intent.envelope == snapshot.placements[0].envelope
    assert bound.placement_intent.host_presences == sources["hosts"].presences
    assert bound.cleaned_data["expected_version"] == snapshot.candidates[0].version
    assert bound.initial == {}
    assert "availability" not in " ".join(bound.fields)
    assert data["effective_starts_at"].endswith("+02:00")


@pytest.mark.parametrize(
    "mode",
    [
        "placement",
        "revise_day",
        Op.CANDIDATE_ARCHIVE,
        Op.OCCURRENCE_CREATE,
        Op.RESERVATION_CANCEL,
    ],
)
def test_bound_failure_keeps_exact_input_retry_and_versions_without_rebase(
    controls, mode
):
    original = control(controls, mode)
    data = submitted(
        original.form,
        original.submit_actions[0][0],
        reason="Retain this exact pending intent",
    )
    if "expected_version" in data:
        data["expected_version"] = "1"
    data["unexpected_private_input"] = "kept for strict rejection"
    rebound = control(controls, mode, data=data).form
    assert rebound.initial == {}
    assert rebound.data == data
    assert not rebound.is_valid()
    assert str(rebound["retry_key"].value()) == data["retry_key"]
    assert rebound["reason"].value() == data["reason"]


def test_read_only_transition_hides_new_forms_but_does_not_rewrite_pending_retry(
    controls,
):
    original = control(controls, Op.CANDIDATE_ARCHIVE)
    data = submitted(
        original.form,
        Op.CANDIDATE_ARCHIVE,
        reason="Explicit archive",
        confirm="confirmed",
    )
    snapshot, board, selection, sources = controls
    readonly = (replace(snapshot, accepts_writes=False), board, selection, sources)
    assert control(readonly, Op.CANDIDATE_ARCHIVE).form is None
    rebound = control(readonly, Op.CANDIDATE_ARCHIVE, data=data).form
    assert rebound.data == data
    assert rebound.initial == {}
    assert rebound.is_valid(), rebound.errors


def test_physical_cancel_keeps_original_source_while_replace_uses_current_draft(
    controls,
):
    snapshot, _board, _selection, sources = controls
    active = sources["reservation"].active
    cancel = control(controls, Op.RESERVATION_CANCEL).form.initial
    replacement = control(controls, Op.RESERVATION_REPLACE).form.initial
    assert cancel["candidate_id"] == active.candidate_id != snapshot.candidates[0].id
    assert cancel["candidate_version"] == active.candidate_version
    assert cancel["placement_id"] == active.placement_id
    assert replacement["candidate_id"] == snapshot.candidates[0].id
    assert replacement["placement_id"] == snapshot.placements[0].id
    for values in (cancel, replacement):
        assert values["previous_booking_id"] == active.booking_id
        assert values["expected_booking_version"] == 4


def test_new_hold_is_explicit_and_has_zero_previous_version(controls):
    reservation = controls[3]["reservation"]
    missing = replace(
        reservation, active=None, state=PlanningReservationState.NOT_REQUESTED
    )
    result = control(controls, Op.RESERVATION_REPLACE, reservation=missing).form.initial
    assert result["previous_booking_id"] is None
    assert result["expected_booking_version"] == 0
    assert control(controls, Op.RESERVATION_CANCEL, reservation=missing).form is None


@pytest.mark.parametrize(
    "mismatch", ["hosts", "host_version", "hold", "history", "missing_history"]
)
def test_inconsistent_owner_readouts_withhold_the_control(controls, mismatch):
    sources = controls[3]
    if mismatch == "hosts":
        operation, changes, error = (
            "placement",
            {"hosts": replace(sources["hosts"], item_id=uuid4())},
            SchedulingUnavailableError,
        )
    elif mismatch == "host_version":
        operation, changes, error = (
            "placement",
            {"hosts": replace(sources["hosts"], candidate_version=1)},
            SchedulingVersionConflictError,
        )
    elif mismatch == "hold":
        operation, changes, error = (
            Op.RESERVATION_CANCEL,
            {"reservation": replace(sources["reservation"], occurrence_id=uuid4())},
            SchedulingUnavailableError,
        )
    elif mismatch == "history":
        operation, changes, error = (
            Op.CANDIDATE_RESTORE,
            {"history": replace(sources["history"], candidate_id=uuid4())},
            SchedulingUnavailableError,
        )
    else:
        operation, changes, error = (
            Op.CANDIDATE_COPY,
            {"history": None},
            SchedulingUnavailableError,
        )
    with pytest.raises(error):
        control(controls, operation, **changes)


def test_warning_action_requires_exact_eligible_fresh_readout(controls):
    review = controls[3]["review"]
    assert (
        control(controls, Op.WARNING_ACKNOWLEDGE).form.initial["conflict_id"]
        == review.saved_findings[0].id
    )
    stale = replace(
        review,
        saved_findings=(
            replace(review.saved_findings[0], eligible_for_acknowledgement=False),
        ),
    )
    assert control(controls, Op.WARNING_ACKNOWLEDGE, review=stale).form is None
    mismatched = replace(review, current=replace(review.current, candidate_version=1))
    assert control(controls, Op.WARNING_ACKNOWLEDGE, review=mismatched).form is None


def test_first_group_is_explicit_and_retained_without_extra_occurrence_creation(
    controls,
):
    result = control(controls, Op.OCCURRENCE_CREATE)
    data = submitted(
        result.form,
        Op.OCCURRENCE_CREATE,
        reason="Start an explicit group",
        group_key="",
        group_sequence="1",
        start_group="new",
    )
    rebound = control(controls, Op.OCCURRENCE_CREATE, data=data).form
    assert rebound.is_valid(), rebound.errors
    assert rebound.occurrence_intent.group_key == UUID(data["new_group_key"])
    assert rebound.occurrence_intent.group_sequence == 1
    assert rebound.initial == {}
    assert (
        control(controls, Op.OCCURRENCE_CREATE, data=data).form["new_group_key"].value()
        == data["new_group_key"]
    )


@pytest.mark.parametrize(
    "change",
    [
        {"group_sequence": ""},
        {"new_group_key": ""},
        {"new_group_key": "not-a-uuid"},
        {"start_group": "automatic"},
    ],
)
def test_starting_group_cannot_infer_missing_sequence_or_retry_identity(
    controls, change
):
    result = control(controls, Op.OCCURRENCE_CREATE)
    data = submitted(
        result.form,
        Op.OCCURRENCE_CREATE,
        reason="Explicit group",
        group_key="",
        group_sequence="1",
        start_group="new",
    )
    for key, value in change.items():
        data[key] = value
    assert not control(controls, Op.OCCURRENCE_CREATE, data=data).form.is_valid()


def test_cannot_select_existing_and_new_group_together(controls):
    result = control(controls, Op.OCCURRENCE_REVISE)
    data = submitted(
        result.form, Op.OCCURRENCE_REVISE, reason="Correct grouping", start_group="new"
    )
    rebound = control(controls, Op.OCCURRENCE_REVISE, data=data).form
    assert not rebound.is_valid()
    assert "not both" in str(rebound.non_field_errors())


def test_new_group_fields_remain_closed_to_non_occurrence_commands():
    form = PlanningRecordForm(operation=Op.CANDIDATE_CREATE)
    assert "new_group_key" not in form.fields
    assert "start_group" not in form.fields


@pytest.mark.parametrize(
    "mode",
    [
        "placement",
        "revise_day",
        Op.DAY_RETIRE,
        Op.OCCURRENCE_REVISE,
        Op.OCCURRENCE_RETIRE,
        Op.CANDIDATE_RESTORE,
        Op.CANDIDATE_ARCHIVE,
        Op.EVALUATION_RECORD,
        Op.PLACEMENT_REMOVE,
        Op.RESERVATION_CANCEL,
    ],
)
def test_missing_targets_are_not_replaced_with_first_available_records(controls, mode):
    snapshot, board, selection, sources = controls
    board = replace(board, candidate=None)
    selection = replace(
        selection, candidate_id=None, item_id=None, occurrence_id=None, day_id=None
    )
    result = control((snapshot, board, selection, sources), mode)
    assert result.form is None
    assert result.guidance


def test_copy_current_or_historical_revision_is_explicit_not_a_fallback(controls):
    snapshot, board, selection, sources = controls
    selection = replace(selection, history_id=None)
    sources = {**sources, "history": None}
    result = control((snapshot, board, selection, sources), Op.CANDIDATE_COPY)
    assert result.form.initial["source_revision_id"] == board.candidate.revision_id
    assert result.form.initial["expected_version"] == snapshot.control_version
    board = replace(board, candidate=None)
    selection = replace(selection, candidate_id=None)
    assert (
        control((snapshot, board, selection, sources), Op.CANDIDATE_COPY).form is None
    )


def test_unplaced_occurrence_has_blank_times_but_keeps_old_hold_cancellation(controls):
    snapshot, board, selection, sources = controls
    board = replace(
        board,
        entries=tuple(
            replace(entry, placement=None, day=None, space=None)
            for entry in board.entries
        ),
    )
    sources = {
        **sources,
        "hosts": replace(sources["hosts"], placement_id=None, presences=()),
    }
    values = (snapshot, board, selection, sources)
    form = control(values, "placement").form
    assert "effective_starts_at" not in form.initial
    assert "capacity_mode" not in form.initial
    assert control(values, Op.PLACEMENT_REMOVE).form is None
    assert control(values, Op.RESERVATION_REPLACE).form is None
    cancel = control(values, Op.RESERVATION_CANCEL).form
    assert cancel.initial["placement_id"] == sources["reservation"].active.placement_id
    no_day = (snapshot, board, replace(selection, day_id=None), sources)
    assert control(no_day, "placement").form is None


def test_unavailable_roster_is_not_treated_as_no_hosts(controls):
    with pytest.raises(SchedulingUnavailableError):
        control(controls, "placement", hosts=None)


@pytest.mark.parametrize("mode", ["overview", "publish"])
def test_non_command_modes_do_not_build_a_mutation_form(controls, mode):
    with pytest.raises(SchedulingUnavailableError):
        control(controls, mode)


def test_archived_candidate_is_copyable_but_not_offered_as_editable_placement(controls):
    snapshot, board, selection, sources = controls
    board = replace(board, candidate=replace(board.candidate, lifecycle="archived"))
    values = (snapshot, board, selection, sources)
    assert control(values, "placement").form is None
    assert control(values, Op.CANDIDATE_COPY).form is not None
