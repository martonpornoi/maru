"""Real-signature owner composition with mocks; native acceptance stays deferred."""

from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest

from maru.authorization.services import AuthorizationDenied
from maru.programme import staffing_commands, staffing_queries
from maru.workforce import (
    assignment_commands,
    availability_commands,
    programme_binding,
    programme_staffing_queries,
    programme_starter_commands,
    programme_starter_creation,
    programme_starter_queries,
    queries,
    services,
    shift_commands,
    structure_commands,
)
from maru.workforce.models import VolunteerOpportunity
from maru.workforce.programme_starter_selection import _sign_selection
from tests.rehearsals import programme_staffing_preparation as preparation
from tests.unit.test_programme_physical_preparation import _snapshot
from tests.unit.test_programme_review_scenario import _authentication
from tests.unit.test_programme_setup_scenarios import _person
from tests.unit.test_programme_staffing_scenario import _sources


def _stub(monkeypatch, module, name, **options):
    result = create_autospec(getattr(module, name), **options)
    monkeypatch.setattr(module, name, result)
    return result


@pytest.mark.parametrize(
    "failure", [None, "self", "request_retry", "decision_retry", "preview", "review"]
)
def test_starter_uses_original_signed_selection_actual_own_approval_and_retries(
    monkeypatch, failure
):
    _authentication(monkeypatch)
    setup = _sources()[0]
    request_id, template_id = uuid4(), uuid4()

    def preview(**kw):
        return SimpleNamespace(
            selection=None
            if failure == "preview"
            else _sign_selection(
                kw["actor"].id,
                kw["scope"],
                kw["draft"],
                setup.controllers[1].account_id,
            )
        )

    _stub(
        monkeypatch,
        programme_starter_creation,
        "prepare_programme_starter_creation",
        side_effect=preview,
    )
    requested = _stub(
        monkeypatch,
        programme_starter_commands,
        "request_programme_starter",
        side_effect=[
            SimpleNamespace(request_id=request_id),
            SimpleNamespace(
                request_id=uuid4() if failure == "request_retry" else request_id,
                replayed=True,
            ),
        ],
    )
    reviewed = _stub(
        monkeypatch,
        programme_starter_queries,
        "load_programme_starter_workspace",
        return_value=SimpleNamespace(
            requests=() if failure == "review" else (SimpleNamespace(can_approve=True),)
        ),
    )
    approved = _stub(
        monkeypatch,
        programme_starter_commands,
        "decide_programme_starter",
        side_effect=[
            SimpleNamespace(template_id=template_id)
            if failure == "self"
            else AuthorizationDenied("denied", reason_code="test"),
            SimpleNamespace(template_id=template_id),
            SimpleNamespace(
                template_id=uuid4() if failure == "decision_retry" else template_id,
                replayed=True,
            ),
        ],
    )
    if failure:
        with pytest.raises(preparation.ProgrammeStaffingPreparationError):
            preparation.approve_starter(setup)
    else:
        assert preparation.approve_starter(setup) == (request_id, template_id)
        assert (
            requested.call_args_list[0].kwargs["details"].approver_id
            == setup.controllers[1].account_id
        )
        assert (
            requested.call_args_list[0].kwargs["idempotency_key"]
            == requested.call_args_list[1].kwargs["idempotency_key"]
        )
        assert [call.kwargs["actor"].id for call in approved.call_args_list] == [
            setup.controllers[0].account_id,
            setup.controllers[1].account_id,
            setup.controllers[1].account_id,
        ]
        assert reviewed.call_args.kwargs["actor"].id == setup.controllers[1].account_id


def test_position_applicant_assignment_and_availability_use_distinct_owners(
    monkeypatch,
):
    _authentication(monkeypatch)
    setup, _, _, items, _, _ = _sources()
    person = _person("volunteer")
    template, position, opportunity, assignment = (uuid4() for _ in range(4))
    _stub(
        monkeypatch,
        queries,
        "project_edition_structure",
        return_value=SimpleNamespace(state="complete", aggregate_version=3),
    )
    create = _stub(
        monkeypatch,
        structure_commands,
        "create_position",
        side_effect=[
            SimpleNamespace(position_id=position, resulting_version=4),
            SimpleNamespace(position_id=position, replayed=True),
        ],
    )
    publish = _stub(monkeypatch, structure_commands, "update_position_opportunity")
    manager = Mock()
    manager.get.return_value = SimpleNamespace(id=opportunity)
    monkeypatch.setattr(VolunteerOpportunity, "objects", manager)
    apply = _stub(monkeypatch, services, "submit_volunteer_application")
    propose = _stub(
        monkeypatch,
        assignment_commands,
        "propose_position_assignment",
        return_value=SimpleNamespace(assignment_id=assignment, resulting_version=1),
    )
    approve = _stub(
        monkeypatch,
        assignment_commands,
        "approve_position_assignment",
        return_value=SimpleNamespace(assignment_id=assignment, status="active"),
    )
    availability = _stub(monkeypatch, availability_commands, "save_person_availability")
    assert preparation.prepare_position_and_assignment(
        setup, items, person, template
    ) == (position, assignment)
    assert create.call_args.kwargs["department_id"] == setup.department_id
    assert create.call_args.kwargs["template_id"] == template
    assert publish.call_args.kwargs["expected_version"] == 4
    assert publish.call_args.kwargs["status"] == "published"
    assert apply.call_args.kwargs["actor"].id == person.account_id
    assert apply.call_args.kwargs["opportunity_id"] == opportunity
    assert propose.call_args.kwargs["actor"].id == setup.controllers[0].account_id
    assert approve.call_args.kwargs["actor"].id == setup.controllers[1].account_id
    assert propose.call_args.kwargs["account_id"] == person.account_id
    assert availability.call_args.kwargs["actor"].id == person.account_id
    assert availability.call_args.kwargs["status"] == "submitted"
    assert (
        availability.call_args.kwargs["windows"][0].starts_at
        == items.availability_starts_at
    )
    assert manager.get.call_args.kwargs == {
        "position_id": position,
        "position__organization_id": setup.organization_id,
        "position__edition_id": setup.edition_id,
    }


def test_exact_source_binding_uses_explicit_terms_and_preview_not_implicit_claim(
    monkeypatch,
):
    _authentication(monkeypatch)
    setup, _, _, items, planning, _ = _sources()
    snapshot = _snapshot(planning, items)
    snapshot.edition_version = 2
    occurrence = SimpleNamespace(
        id=planning.occurrence_ids[0], version=3, item_id=items.ceremony.item_id
    )
    placement = snapshot.placements[0]
    position = uuid4()
    request = _stub(
        monkeypatch,
        staffing_queries,
        "load_programme_staffing_requirements",
        return_value=SimpleNamespace(item_version=7),
    )
    requirement = SimpleNamespace(
        requirement_id=uuid4(), revision_id=uuid4(), resulting_requirement_version=1
    )
    change = _stub(
        monkeypatch,
        staffing_commands,
        "change_programme_staffing_requirement",
        return_value=requirement,
    )
    preview = _stub(
        monkeypatch,
        programme_binding,
        "preview_programme_staffing_binding",
        return_value=SimpleNamespace(
            demand=None,
            impact=SimpleNamespace(retained_commitments=0),
            digest="exact-preview",
        ),
    )
    bound = SimpleNamespace(binding_id=uuid4(), demand_id=uuid4())
    apply = _stub(
        monkeypatch,
        programme_binding,
        "apply_programme_staffing_binding",
        return_value=bound,
    )
    _stub(
        monkeypatch,
        programme_staffing_queries,
        "load_programme_staffing_demand",
        return_value=SimpleNamespace(status="draft", retained_commitments=0),
    )
    assert preparation._create_bound_work(
        setup, planning, position, snapshot, occurrence, placement
    ) == (requirement, bound)
    submitted = change.call_args.kwargs["change"]
    assert submitted.expected_item_version == 7
    assert submitted.expected_edition_version == 2
    assert submitted.expectation.position_id == position
    assert submitted.expectation.starts_at == placement.envelope.setup_starts_at
    assert submitted.expectation.ends_at == placement.envelope.teardown_ends_at
    assert submitted.expectation.required_headcount == 1
    assert submitted.expectation.minimum_rest_minutes == 0
    assert apply.call_args.kwargs["preview_digest"] == "exact-preview"
    assert preview.call_args.kwargs["change"] == apply.call_args.kwargs["change"]
    assert (
        preview.call_args.kwargs["change"].source.candidate_revision_id
        == planning.candidate_revision_id
    )
    assert request.call_args.args[0].actor_id == planning.planner.account_id


@pytest.mark.parametrize(
    "failure", [None, "self", "stale", "retry", "claimed", "confirmed", "locked"]
)
def test_claim_is_personal_confirmation_independent_and_lock_never_accepts_underfill(
    monkeypatch, failure
):
    _authentication(monkeypatch)
    setup, _, _, _, planning, _ = _sources()
    person, demand, commitment = _person("volunteer"), uuid4(), uuid4()
    states = [
        SimpleNamespace(version=1),
        SimpleNamespace(claimed=1, confirmed=1 if failure == "claimed" else 0),
        SimpleNamespace(
            version=2, claimed=0, confirmed=0 if failure == "confirmed" else 1
        ),
        SimpleNamespace(
            status="open" if failure == "locked" else "locked", claimed=0, confirmed=1
        ),
    ]
    _stub(
        monkeypatch,
        programme_staffing_queries,
        "load_programme_staffing_demand",
        side_effect=states,
    )
    _stub(
        monkeypatch,
        shift_commands,
        "open_shift_demand",
        return_value=SimpleNamespace(resulting_version=2),
    )
    claim = _stub(
        monkeypatch,
        shift_commands,
        "claim_shift",
        side_effect=[
            SimpleNamespace(commitment_id=commitment, resulting_version=1),
            SimpleNamespace(
                commitment_id=uuid4() if failure == "retry" else commitment,
                replayed=True,
            ),
        ],
    )
    confirm = _stub(
        monkeypatch,
        shift_commands,
        "confirm_shift_commitment",
        side_effect=[
            SimpleNamespace()
            if failure == "self"
            else shift_commands.ShiftAuthorizationDeniedError(),
            SimpleNamespace(resulting_version=2),
            SimpleNamespace()
            if failure == "stale"
            else shift_commands.ShiftVersionConflictError(),
        ],
    )
    lock = _stub(
        monkeypatch,
        shift_commands,
        "lock_shift_demand",
        return_value=SimpleNamespace(resulting_version=3),
    )
    if failure:
        with pytest.raises(preparation.ProgrammeStaffingPreparationError):
            preparation._claim_confirm_lock(setup, planning.planner, person, demand)
    else:
        assert preparation._claim_confirm_lock(
            setup, planning.planner, person, demand
        ) == (commitment, 2, 3)
        assert {call.kwargs["actor"].id for call in claim.call_args_list} == {
            person.account_id
        }
        assert [call.kwargs["actor"].id for call in confirm.call_args_list] == [
            person.account_id,
            planning.planner.account_id,
            planning.planner.account_id,
        ]
        assert lock.call_args.kwargs["allow_understaffed"] is False
        assert lock.call_args.kwargs["expected_version"] == 2


def test_staffing_adds_only_existing_workforce_and_staffing_recipes(monkeypatch):
    setup, _, _, _, planning, _ = _sources()
    grant = _stub(
        monkeypatch,
        preparation,
        "approve_synthetic_role",
        side_effect=[uuid4(), uuid4()],
    )
    assert len(preparation.approve_staffing_roles(setup, planning.planner)) == 2
    assert [call.kwargs["code"] for call in grant.call_args_list] == [
        "staffing",
        "workforce",
    ]
    assert all(
        call.kwargs["recipient"] == planning.planner for call in grant.call_args_list
    )


@pytest.mark.parametrize("changed", [False, True])
def test_all_three_placements_are_bound_and_candidate_is_unchanged(
    monkeypatch, changed
):
    setup, _, _, items, planning, _ = _sources()
    snapshot = _snapshot(planning, items)
    snapshot.occurrences = tuple(
        SimpleNamespace(id=value) for value in planning.occurrence_ids
    )
    final = SimpleNamespace(**vars(snapshot))
    if changed:
        final.placements = snapshot.placements[:-1]
    monkeypatch.setattr(preparation, "_snapshot", Mock(side_effect=[snapshot, final]))
    bind = Mock(
        side_effect=lambda *_a: (
            SimpleNamespace(requirement_id=uuid4(), revision_id=uuid4()),
            SimpleNamespace(binding_id=uuid4(), demand_id=uuid4()),
        )
    )
    monkeypatch.setattr(preparation, "_create_bound_work", bind)
    monkeypatch.setattr(
        preparation,
        "_claim_confirm_lock",
        Mock(side_effect=lambda *_a: (uuid4(), 2, 3)),
    )
    if changed:
        with pytest.raises(
            preparation.ProgrammeStaffingPreparationError, match="edited_candidate"
        ):
            preparation.prepare_bound_shifts(
                setup, planning, _person("volunteer"), uuid4()
            )
    else:
        result = preparation.prepare_bound_shifts(
            setup, planning, _person("volunteer"), uuid4()
        )
        assert len(result) == 3
    assert [call.args[-1].id for call in bind.call_args_list] == list(
        planning.placement_ids
    )
