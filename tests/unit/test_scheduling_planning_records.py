"""Database-free record controls, closed dispatch and exact pending-intent parity."""

from unittest.mock import Mock, create_autospec
from uuid import UUID, uuid4

import pytest
from django.http import QueryDict

from maru.scheduling import planning_record_actions as actions
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.catalogs import SchedulingOperation as Op
from maru.scheduling.command_support import SchedulingVersionConflictError
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.planning_record_forms import PlanningRecordForm

CASES = [
    (Op.CANDIDATE_CREATE, "create_scheduling_candidate", "label expected_version"),
    (
        Op.CANDIDATE_COPY,
        "copy_scheduling_candidate",
        "label source_revision_id expected_version",
    ),
    (
        Op.CANDIDATE_RESTORE,
        "restore_scheduling_candidate",
        "candidate_id source_revision_id expected_version confirm",
    ),
    (
        Op.CANDIDATE_ARCHIVE,
        "archive_scheduling_candidate",
        "candidate_id expected_version confirm",
    ),
    (
        Op.PLACEMENT_REMOVE,
        "remove_scheduling_placement",
        "candidate_id occurrence_id expected_version confirm",
    ),
    (Op.DAY_RETIRE, "retire_scheduling_service_day", "day_id expected_version confirm"),
    (
        Op.OCCURRENCE_CREATE,
        "create_scheduling_occurrence",
        "item_id group_key group_sequence expected_version",
    ),
    (
        Op.OCCURRENCE_REVISE,
        "revise_scheduling_occurrence",
        "item_id group_key group_sequence occurrence_id expected_version",
    ),
    (
        Op.OCCURRENCE_RETIRE,
        "retire_scheduling_occurrence",
        "occurrence_id expected_version confirm",
    ),
    (
        Op.EVALUATION_RECORD,
        "evaluate_scheduling_candidate",
        "candidate_id expected_version",
    ),
    (Op.WARNING_ACKNOWLEDGE, "acknowledge_scheduling_warning", "conflict_id"),
    (
        Op.RESERVATION_REPLACE,
        "change_scheduling_reservation",
        "candidate_id candidate_version placement_id previous_booking_id "
        "expected_booking_version confirm",
    ),
    (
        Op.RESERVATION_CANCEL,
        "change_scheduling_reservation",
        "candidate_id candidate_version placement_id previous_booking_id "
        "expected_booking_version confirm",
    ),
]


def values(operation, names):
    all_fields = {
        name: str(uuid4())
        for name in (
            "candidate_id",
            "source_revision_id",
            "occurrence_id",
            "day_id",
            "item_id",
            "group_key",
            "conflict_id",
            "placement_id",
            "previous_booking_id",
        )
    }
    all_fields.update(
        label="Alternative draft",
        expected_version="3",
        group_sequence="2",
        confirm="confirmed",
        candidate_version="5",
        expected_booking_version="7",
    )
    data = {key: all_fields[key] for key in names.split()}
    data.update(
        action=operation.value, reason="Deliberate change", retry_key=str(uuid4())
    )
    if operation in {Op.OCCURRENCE_CREATE, Op.OCCURRENCE_REVISE}:
        data.update(start_group="", new_group_key=str(uuid4()))
    choices = {
        key: ((UUID(all_fields[key]), label),)
        for key, label in (
            ("item_id", "Opening panel"),
            ("group_key", "Opening programme group"),
        )
    }
    return data, choices


@pytest.mark.parametrize(("operation", "writer_name", "names"), CASES)
def test_every_record_action_calls_only_its_existing_command_with_exact_input(
    operation, writer_name, names, monkeypatch
):
    data, choices = values(operation, names)
    form = PlanningRecordForm(data, operation=operation, choices=choices)
    assert form.is_valid(), form.errors
    assert set(form.fields) == set(data)
    writers = {}
    for name in {case[1] for case in CASES}:
        writers[name] = create_autospec(getattr(actions, name))
        monkeypatch.setattr(actions, name, writers[name])
    gate = Mock()
    monkeypatch.setattr(actions, "_authorize", gate)
    request = SchedulingReadRequest(*(uuid4() for _ in range(4)))
    policy = object()
    result = actions.submit_planning_record(request, form, authorizer=policy)
    writer = writers[writer_name]
    assert result is writer.return_value
    gate.assert_called_once_with(request, policy)
    writer.assert_called_once()
    for name, other in writers.items():
        if name != writer_name:
            other.assert_not_called()
    command = writer.call_args.args[0]
    assert command.actor_id == request.actor_id
    assert command.organization_id == request.organization_id
    assert command.edition_id == request.edition_id
    assert command.correlation_id == request.correlation_id
    assert command.idempotency_key == UUID(data["retry_key"])
    assert command.reason == data["reason"]
    assert command.source_channel == "scheduling-planning"
    expected = {
        key: value
        for key, value in form.cleaned_data.items()
        if key not in {"action", "confirm", "reason", "retry_key"}
    }
    expected["authorizer"] = policy
    if operation in {Op.CANDIDATE_CREATE, Op.CANDIDATE_COPY, Op.OCCURRENCE_CREATE}:
        expected["expected_control_version"] = expected.pop("expected_version")
    if form.occurrence_intent is not None:
        assert expected.pop("start_group") == ""
        assert expected.pop("new_group_key") == UUID(data["new_group_key"])
        for key in ("item_id", "group_key", "group_sequence"):
            expected.pop(key)
        expected["occurrence"] = form.occurrence_intent
    if form.reservation_intent is not None:
        expected = {
            "reservation": form.reservation_intent,
            "operation": operation,
            "authorizer": policy,
        }
    assert writer.call_args.kwargs == expected


@pytest.mark.parametrize(("operation", "_writer", "names"), CASES)
@pytest.mark.parametrize("attack", ["wrong_action", "duplicate", "extra_scope"])
def test_record_forms_reject_ambiguous_action_and_scope_injection(
    operation, _writer, names, attack
):
    data, choices = values(operation, names)
    submitted = QueryDict(mutable=True)
    submitted.update(data)
    if attack == "wrong_action":
        submitted["action"] = "save_placement"
    elif attack == "duplicate":
        submitted.appendlist("action", data["action"])
    else:
        submitted["organization_id"] = str(uuid4())
    form = PlanningRecordForm(submitted, operation=operation, choices=choices)
    assert not form.is_valid()
    assert form.occurrence_intent is None
    assert form.reservation_intent is None
    assert form.data["retry_key"] == data["retry_key"]


@pytest.mark.parametrize(
    ("operation", "_writer", "names"), [case for case in CASES if "confirm" in case[2]]
)
def test_high_impact_record_control_requires_explicit_confirmation(
    operation, _writer, names
):
    data, choices = values(operation, names)
    data.pop("confirm")
    form = PlanningRecordForm(data, operation=operation, choices=choices)
    assert not form.is_valid()
    assert "confirm" in form.errors


@pytest.mark.parametrize(
    "operation", ["candidate_create", Op.DAY_CREATE, Op.DAY_REVISE, Op.PLACEMENT_SET]
)
def test_record_constructor_does_not_accept_untyped_or_other_editor_operations(
    operation,
):
    with pytest.raises(ValueError, match="supported"):
        PlanningRecordForm(operation=operation)


@pytest.mark.parametrize(
    "changes",
    [
        {"group_key": "", "group_sequence": "2"},
        {"group_sequence": ""},
        {"group_sequence": "2001"},
        {"group_key": str(uuid4())},
        {"item_id": str(uuid4())},
        {"expected_version": "03"},
        {"expected_version": "-1"},
    ],
)
def test_explicit_occurrence_group_is_not_an_inferred_or_foreign_recurrence(changes):
    operation, _, names = CASES[6]
    data, choices = values(operation, names)
    form = PlanningRecordForm({**data, **changes}, operation=operation, choices=choices)
    assert not form.is_valid()
    assert form.occurrence_intent is None


def test_ungrouped_occurrence_and_zero_initial_control_are_valid():
    operation, _, names = CASES[6]
    data, choices = values(operation, names)
    form = PlanningRecordForm(
        {**data, "group_key": "", "group_sequence": "", "expected_version": "0"},
        operation=operation,
        choices=choices,
    )
    assert form.is_valid(), form.errors
    assert form.occurrence_intent.group_key is None
    assert form.occurrence_intent.group_sequence is None
    assert form.cleaned_data["expected_version"] == 0


def test_copy_requires_a_positive_existing_edition_control_version():
    operation, _, names = CASES[1]
    data, choices = values(operation, names)
    form = PlanningRecordForm(
        {**data, "expected_version": "0"}, operation=operation, choices=choices
    )
    assert not form.is_valid()
    assert "expected_version" in form.errors


@pytest.mark.parametrize(
    "changes",
    [
        {"previous_booking_id": ""},
        {"expected_booking_version": "0"},
        {"candidate_version": "0"},
        {"reason": ""},
        {"reason": "\x00"},
    ],
)
def test_physical_change_requires_exact_booking_pair_and_human_reason(changes):
    operation, _, names = CASES[-1]
    data, choices = values(operation, names)
    form = PlanningRecordForm({**data, **changes}, operation=operation, choices=choices)
    assert not form.is_valid()
    assert form.reservation_intent is None


def test_only_initial_replacement_accepts_no_old_physical_booking():
    operation, _, names = CASES[-2]
    data, _ = values(operation, names)
    data.update(previous_booking_id="", expected_booking_version="0")
    form = PlanningRecordForm(data, operation=operation)
    assert form.is_valid(), form.errors
    assert form.reservation_intent.previous_booking_id is None
    assert "Venues" in form.fields["reason"].help_text
    assert "does not approve" in form.fields["confirm"].help_text


def test_record_submission_denies_before_binding_private_input(monkeypatch):
    operation, _, names = CASES[0]
    data, choices = values(operation, names)
    form = PlanningRecordForm(data, operation=operation, choices=choices)
    gate = Mock(side_effect=SchedulingAuthorizationDeniedError)
    validator = Mock(
        side_effect=AssertionError("Input inspected before read authority")
    )
    monkeypatch.setattr(actions, "_authorize", gate)
    monkeypatch.setattr(form, "is_valid", validator)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        actions.submit_planning_record(
            SchedulingReadRequest(*(uuid4() for _ in range(4))), form
        )
    validator.assert_not_called()


@pytest.mark.parametrize("failure", ["invalid", "stale"])
def test_record_submission_preserves_pending_intent_without_silent_rebase(
    failure, monkeypatch
):
    operation, name, names = CASES[0]
    data, choices = values(operation, names)
    if failure == "invalid":
        data["label"] = ""
    form = PlanningRecordForm(data, operation=operation, choices=choices)
    monkeypatch.setattr(actions, "_authorize", Mock())
    writer = Mock(side_effect=SchedulingVersionConflictError)
    monkeypatch.setattr(actions, name, writer)
    request = SchedulingReadRequest(*(uuid4() for _ in range(4)))
    if failure == "invalid":
        assert actions.submit_planning_record(request, form) is None
        writer.assert_not_called()
    else:
        with pytest.raises(SchedulingVersionConflictError):
            actions.submit_planning_record(request, form)
        writer.assert_called_once()
    assert form.data == data
    assert form.data["expected_version"] == "3"
