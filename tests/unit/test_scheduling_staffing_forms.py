"""Native staffing forms retain exact intent and never infer consequential actions."""

from uuid import UUID, uuid4

import pytest
from django.http import QueryDict

from maru.scheduling.planning_staffing_forms import (
    PlanningStaffingBindingForm,
    PlanningStaffingRequirementForm,
)


def data(values):
    result = QueryDict(mutable=True)
    result.update({key: str(value) for key, value in values.items()})
    return result


def requirement_payload(**changes):
    return data(
        {
            "action": "staffing_create",
            "retry_key": uuid4(),
            "reason": "Explicit work need",
            "requirement_id": "",
            "expected_item_version": "1",
            "expected_requirement_version": "0",
            "expected_occurrence_version": "1",
            "expected_edition_version": "1",
            "position_id": uuid4(),
            "title": " Stage preparation ",
            "location_label": "East stage",
            "briefing": "Prepare the stage safely",
            "supervision_note": "",
            "starts_at": "2030-08-02T10:00+02:00",
            "ends_at": "2030-08-02T12:00+02:00",
            "required_headcount": "2",
            "break_minutes": "5",
            "minimum_rest_minutes": "30",
            **changes,
        }
    )


def requirement_form(payload, operation="staffing_create"):
    return PlanningStaffingRequirementForm(
        payload,
        operation=operation,
        zone_name="Europe/Budapest",
        position_choices=((UUID(payload["position_id"]), "Stage preparation Position"),)
        if "position_id" in payload
        else (),
    )


def binding_payload(**changes):
    return data(
        {
            "action": "staffing_preview",
            "retry_key": uuid4(),
            "reason": "Explicit work request",
            "operation": "create",
            "requirement_id": uuid4(),
            "requirement_revision_id": uuid4(),
            "requirement_version": "1",
            "occurrence_id": uuid4(),
            "occurrence_version": "1",
            "candidate_id": uuid4(),
            "candidate_revision_id": uuid4(),
            "placement_id": uuid4(),
            "binding_id": "",
            "expected_binding_version": "0",
            "demand_id": "",
            "expected_demand_version": "0",
            "preview_digest": "",
            "confirm": "",
            **changes,
        }
    )


def test_requirement_form_normalizes_explicit_work_and_retains_retry_identity():
    payload = requirement_payload()
    form = requirement_form(payload)
    result = form.change(item_id=uuid4(), occurrence_id=uuid4())
    assert result is not None
    assert result.expectation.title == "Stage preparation"
    assert result.expectation.starts_at.hour == 8
    assert result.expectation.required_headcount == 2
    assert str(form.cleaned_data["retry_key"]) == payload["retry_key"]
    assert form.data["title"] == " Stage preparation "


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_headcount", "0"),
        ("required_headcount", "02"),
        ("required_headcount", "2.0"),
        ("break_minutes", "120"),
        ("minimum_rest_minutes", "-1"),
        ("expected_item_version", "0"),
        ("expected_occurrence_version", "True"),
        ("ends_at", "2030-08-02T09:00+02:00"),
        ("starts_at", "2030-03-31T02:30"),
        ("starts_at", "2030-10-27T02:30"),
        ("action", "staffing_revise"),
    ],
)
def test_requirement_form_rejects_noncanonical_or_unsafe_intent(field, value):
    payload = requirement_payload(**{field: value})
    form = requirement_form(payload)
    assert form.change(item_id=uuid4(), occurrence_id=uuid4()) is None
    assert form.errors
    assert form.data[field] == value


def test_creation_label_cannot_be_used_to_revise_an_existing_requirement():
    form = requirement_form(
        requirement_payload(requirement_id=uuid4(), expected_requirement_version=1)
    )
    assert form.change(item_id=uuid4(), occurrence_id=uuid4()) is None
    assert form.non_field_errors()


@pytest.mark.parametrize("confirmed", [False, True])
def test_retirement_requires_explicit_confirmation_and_no_work_replacement(confirmed):
    payload = requirement_payload(
        action="staffing_retire", requirement_id=uuid4(), expected_requirement_version=1
    )
    for name in (
        "position_id",
        "title",
        "location_label",
        "briefing",
        "supervision_note",
        "starts_at",
        "ends_at",
        "required_headcount",
        "break_minutes",
        "minimum_rest_minutes",
    ):
        del payload[name]
    if confirmed:
        payload["confirm"] = "on"
    form = requirement_form(payload, operation="staffing_retire")
    result = form.change(item_id=uuid4(), occurrence_id=uuid4())
    if confirmed:
        assert result.retire is True
        assert result.expectation is None
    else:
        assert result is None
        assert "confirm" in form.errors


def test_unknown_and_repeated_fields_are_not_discarded():
    payload = requirement_payload(actor_id=uuid4())
    payload.appendlist("title", "Unexpected second work title")
    form = requirement_form(payload)
    assert form.change(item_id=uuid4(), occurrence_id=uuid4()) is None
    assert form.non_field_errors()


@pytest.mark.parametrize("operation", ["create", "link", "reconcile", "successor"])
def test_binding_forms_preserve_closed_explicit_action_and_source(operation):
    extra = {}
    if operation != "create":
        extra.update(demand_id=uuid4(), expected_demand_version=3)
    if operation in {"reconcile", "successor"}:
        extra.update(binding_id=uuid4(), expected_binding_version=2)
    payload = binding_payload(operation=operation, **extra)
    form = PlanningStaffingBindingForm(payload)
    change = form.change()
    assert change is not None
    assert change.action == operation
    assert str(change.source.candidate_revision_id) == payload["candidate_revision_id"]
    assert str(form.cleaned_data["retry_key"]) == payload["retry_key"]
    assert not form.cleaned_data["confirm"]


@pytest.mark.parametrize(
    ("digest", "confirm", "valid"),
    [("", "", False), ("a" * 64, "", False), ("", "on", False), ("a" * 64, "on", True)],
)
def test_apply_requires_exact_preview_and_affirmative_impact_review(
    digest, confirm, valid
):
    form = PlanningStaffingBindingForm(
        binding_payload(action="staffing_apply", preview_digest=digest, confirm=confirm)
    )
    assert (form.change() is not None) is valid


@pytest.mark.parametrize(
    "changes",
    [
        {"operation": "automatic"},
        {"operation": "link"},
        {"operation": "reconcile", "demand_id": uuid4(), "expected_demand_version": 1},
        {"operation": "create", "demand_id": uuid4(), "expected_demand_version": 1},
        {"preview_digest": "A" * 64},
        {"preview_digest": "a" * 64 + "\n"},
        {"reason": "x" * 241},
        {"action": "open"},
        {"requirement_version": "01"},
    ],
)
def test_binding_form_does_not_reinterpret_invalid_actions_or_evidence(changes):
    form = PlanningStaffingBindingForm(binding_payload(**changes))
    assert form.change() is None
    assert form.errors
