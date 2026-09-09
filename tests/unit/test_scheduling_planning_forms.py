"""Database-free strict timetable forms and same-command input-method parity."""

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.http import QueryDict

from maru.scheduling import planning_actions as actions
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.planning_forms import PlanningPlacementForm, PlanningServiceDayForm
from maru.scheduling.planning_queries import SchedulingReadRequest


@pytest.fixture
def placement_values():
    occurrence, day, space, host = (uuid4() for _ in range(4))
    choices = {
        "zone_name": "Europe/Budapest",
        "occurrences": ((occurrence, "Opening panel"),),
        "days": ((day, "Friday"),),
        "spaces": ((space, "Main Stage"),),
        "hosts": ((host, "Host display label"),),
    }
    data = {
        "action": "preview_placement",
        "retry_key": str(uuid4()),
        "candidate_id": str(uuid4()),
        "expected_version": "1",
        "occurrence_id": str(occurrence),
        "occurrence_version": "1",
        "day_id": str(day),
        "day_version": "1",
        "space_selection_id": str(space),
        "capacity_mode": "seated",
        "expected_attendance": "80",
        "reason": "",
        "setup_starts_at": "2030-08-02T10:00+02:00",
        "effective_starts_at": "2030-08-02T10:15+02:00",
        "effective_ends_at": "2030-08-02T11:00+02:00",
        "teardown_ends_at": "2030-08-02T11:15+02:00",
        f"host_{host.hex}_required": "required",
        f"host_{host.hex}_starts_at": "2030-08-02T10:15+02:00",
        f"host_{host.hex}_ends_at": "2030-08-02T11:00+02:00",
    }
    return data, choices


def placement_form(values, **changes):
    data, choices = values
    return PlanningPlacementForm({**data, **changes}, **choices)


def test_complete_placement_form_builds_the_shared_utc_intent(placement_values):
    form = placement_form(placement_values)
    assert form.is_valid(), form.errors
    assert form.placement_intent.envelope.setup_starts_at == datetime(
        2030, 8, 2, 8, tzinfo=UTC
    )
    assert form.placement_intent.host_presences[0].starts_at == datetime(
        2030, 8, 2, 8, 15, tzinfo=UTC
    )
    assert form.data["retry_key"] == placement_values[0]["retry_key"]
    assert form.cleaned_data["reason"] == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("action", "reserve_placement"),
        ("expected_version", "01"),
        ("day_version", "1.0"),
        ("occurrence_version", "+1"),
        ("expected_attendance", True),
        ("expected_attendance", "1e2"),
        ("capacity_mode", "unlimited"),
        ("candidate_id", "{" + str(uuid4()) + "}"),
        ("retry_key", ""),
        ("expected_version", "0"),
        ("reason", "Secret\x00text"),
        ("reason", "x" * 1001),
    ],
)
def test_placement_form_rejects_aliases_and_retains_the_original_input(
    placement_values, field, value
):
    form = placement_form(placement_values, **{field: value})
    assert not form.is_valid()
    assert field in form.errors
    assert form.placement_intent is None
    assert form.data[field] == value
    assert form.data["retry_key"] == (
        value if field == "retry_key" else placement_values[0]["retry_key"]
    )


@pytest.mark.parametrize("field", ["occurrence_id", "day_id", "space_selection_id"])
def test_form_choices_do_not_accept_an_unlisted_owner_identifier(
    placement_values, field
):
    form = placement_form(placement_values, **{field: str(uuid4())})
    assert not form.is_valid()
    assert field in form.errors


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-25T02:30",
        "2026-03-29T02:30",
        "2030-08-02T10:00:30",
        " 2030-08-02T10:00",
        "2030-08-02T10:00+25:00",
        "x" * 33,
    ],
)
def test_form_rejects_ambiguous_nonexistent_and_inexact_minutes(
    placement_values, value
):
    form = placement_form(placement_values, setup_starts_at=value)
    assert not form.is_valid()
    assert "setup_starts_at" in form.errors
    assert form.data["setup_starts_at"] == value


@pytest.mark.parametrize("field", ["expected_version", "reason", "action"])
def test_placement_single_value_fields_cannot_be_submitted_twice(
    placement_values, field
):
    data, choices = placement_values
    submitted = QueryDict(mutable=True)
    submitted.update(data)
    submitted.appendlist(field, data[field])
    form = PlanningPlacementForm(submitted, **choices)
    assert not form.is_valid()
    assert "invalid_input_cardinality" in {
        error.code for error in form.errors.as_data()["__all__"]
    }


def test_hidden_unrelated_host_fields_are_rejected(placement_values):
    form = placement_form(
        placement_values, **{f"host_{uuid4().hex}_required": "required"}
    )
    assert not form.is_valid()
    assert "unknown_input_field" in {
        error.code for error in form.errors.as_data()["__all__"]
    }


def test_selected_host_requires_both_explicit_presence_times(placement_values):
    host = placement_values[1]["hosts"][0][0]
    field = f"host_{host.hex}_starts_at"
    form = placement_form(placement_values, **{field: ""})
    assert not form.is_valid()
    assert field in form.errors


def test_unselected_host_is_not_inferred_from_leftover_input_times(placement_values):
    host = placement_values[1]["hosts"][0][0]
    form = placement_form(placement_values, **{f"host_{host.hex}_required": ""})
    assert form.is_valid(), form.errors
    assert form.placement_intent.host_presences == ()


def test_required_presence_cannot_extend_beyond_the_room_envelope(placement_values):
    host = placement_values[1]["hosts"][0][0]
    form = placement_form(
        placement_values, **{f"host_{host.hex}_ends_at": "2030-08-02T13:00+02:00"}
    )
    assert not form.is_valid()
    assert form.placement_intent is None


def test_save_requires_human_reason_but_preview_does_not(placement_values):
    form = placement_form(placement_values, action="save_placement")
    assert not form.is_valid()
    assert "reason" in form.errors
    reasoned = placement_form(
        placement_values,
        action="save_placement",
        reason="Move after the opening briefing",
    )
    assert reasoned.is_valid(), reasoned.errors


def test_structurally_valid_draft_does_not_claim_to_have_checked_capacity(
    placement_values,
):
    form = placement_form(placement_values, expected_attendance="9000")
    assert form.is_valid(), form.errors
    assert form.placement_intent.expected_attendance == 9000


@pytest.mark.parametrize("overflow", [False, True])
def test_unbounded_or_duplicate_trusted_host_roster_is_not_silently_truncated(
    placement_values, overflow
):
    data, choices = placement_values
    hosts = (
        tuple((uuid4(), "Host") for _ in range(101))
        if overflow
        else choices["hosts"] * 2
    )
    with pytest.raises(ValueError, match="complete bounded distinct"):
        PlanningPlacementForm(data, **{**choices, "hosts": hosts})


@pytest.fixture
def day_values():
    return {
        "action": "create_day",
        "retry_key": str(uuid4()),
        "reason": "Plan Friday overnight",
        "expected_version": "0",
        "label": "Friday overnight",
        "precision_minutes": "5",
        "starts_at": "2030-08-02T22:00+02:00",
        "ends_at": "2030-08-03T06:00+02:00",
    }


def test_service_day_preserves_overnight_boundaries(day_values):
    form = PlanningServiceDayForm(day_values, zone_name="Europe/Budapest")
    assert form.is_valid(), form.errors
    assert form.day_intent.window.starts_at == datetime(2030, 8, 2, 20, tzinfo=UTC)
    assert form.day_intent.window.ends_at == datetime(2030, 8, 3, 4, tzinfo=UTC)


@pytest.mark.parametrize(
    "changes",
    [
        {"precision_minutes": "7"},
        {"action": "revise_day"},
        {"action": "revise_day", "day_id": str(uuid4())},
        {"day_id": str(uuid4())},
        {"reason": ""},
        {"ends_at": "2030-08-02T22:00+02:00"},
    ],
)
def test_day_form_requires_explicit_valid_command_preconditions(day_values, changes):
    form = PlanningServiceDayForm(
        {**day_values, **changes}, zone_name="Europe/Budapest"
    )
    assert not form.is_valid()
    assert form.day_intent is None


def read_request():
    return SchedulingReadRequest(*(uuid4() for _ in range(4)))


def test_preview_adapter_never_calls_the_placement_writer(
    placement_values, monkeypatch
):
    monkeypatch.setattr(actions, "_authorize", lambda *_args: None)
    reader, writer = Mock(), Mock()
    monkeypatch.setattr(actions, "preview_scheduling_candidate", reader)
    monkeypatch.setattr(actions, "set_scheduling_placement", writer)
    form, request = placement_form(placement_values), read_request()
    assert actions.submit_planning_placement(request, form) is reader.return_value
    writer.assert_not_called()
    assert reader.call_args.args == (request,)
    assert reader.call_args.kwargs["placement"] == form.placement_intent


def test_keyboard_and_pointer_prefill_use_the_same_command_and_exact_retry_key(
    placement_values, monkeypatch
):
    monkeypatch.setattr(actions, "_authorize", lambda *_args: None)
    writer = Mock()
    monkeypatch.setattr(actions, "set_scheduling_placement", writer)
    request = read_request()
    forms = [
        placement_form(
            placement_values, action="save_placement", reason="Deliberate placement"
        )
        for _ in range(2)
    ]
    for form in forms:
        actions.submit_planning_placement(request, form)
    assert writer.call_args_list[0] == writer.call_args_list[1]
    command = writer.call_args.args[0]
    assert command.actor_id == request.actor_id
    assert str(command.idempotency_key) == placement_values[0]["retry_key"]
    assert command.reason == "Deliberate placement"
    assert command.source_channel == "scheduling-planning"


def test_submission_authorizes_before_binding_private_input(
    placement_values, monkeypatch
):
    def denied(*args):
        raise SchedulingAuthorizationDeniedError

    monkeypatch.setattr(actions, "_authorize", denied)
    form = placement_form(placement_values)
    validator = Mock(
        side_effect=AssertionError("Private input was bound before authorization")
    )
    monkeypatch.setattr(form, "is_valid", validator)
    with pytest.raises(SchedulingAuthorizationDeniedError):
        actions.submit_planning_placement(read_request(), form)
    validator.assert_not_called()


def test_invalid_submission_keeps_form_without_preview_or_write(
    placement_values, monkeypatch
):
    monkeypatch.setattr(actions, "_authorize", lambda *_args: None)
    preview, writer = Mock(), Mock()
    monkeypatch.setattr(actions, "preview_scheduling_candidate", preview)
    monkeypatch.setattr(actions, "set_scheduling_placement", writer)
    form = placement_form(placement_values, expected_version="stale text")
    assert actions.submit_planning_placement(read_request(), form) is None
    preview.assert_not_called()
    writer.assert_not_called()
    assert form.data["expected_version"] == "stale text"
