"""Pure timetable composition tests; never substitute for native or browser proof."""

import io
import json
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import uuid4

import pytest

from maru.authorization.catalog import ScopeLevel
from maru.scheduling import (
    candidate_commands,
    day_commands,
    evaluation_commands,
    occurrence_commands,
    placement_commands,
    planning_review,
)
from maru.scheduling.command_support import (
    SchedulingCommandResult,
    SchedulingVersionConflictError,
)
from maru.scheduling.planning_queries import PlanningCandidate, PlanningPlacement
from tests.rehearsals import programme_planning_scenario as scenario
from tests.rehearsals import programme_runtime
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_items_scenario import _result as _items
from tests.unit.test_programme_proposal_scenario import _result as _proposal
from tests.unit.test_programme_proposal_scenario import _setup
from tests.unit.test_programme_review_scenario import _authentication
from tests.unit.test_programme_review_scenario import _result as _review
from tests.unit.test_programme_setup_scenarios import RUN, _person


def _sources():
    setup = _setup()
    proposal = _proposal(setup)
    review = _review(setup, proposal)
    return setup, proposal, review, _items(setup, review)


def _result(setup, items):
    return scenario.ProgrammePlanningScenario(
        setup.organization_id,
        setup.edition_id,
        (items.accepted.item_id, items.ceremony.item_id),
        (uuid4(), uuid4()),
        uuid4(),
        (uuid4(), uuid4(), uuid4()),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        3,
        (uuid4(), uuid4(), uuid4()),
        uuid4(),
        _person("planner"),
        _person("venue"),
        tuple(uuid4() for _ in range(5)),
    )


def test_result_is_same_source_bounded_and_credentials_are_redacted():
    setup, proposal, review, items = _sources()
    result = _result(setup, items)
    assert (
        scenario.planning_from_document(
            json.loads(json.dumps(asdict(result), default=str)),
            setup=setup,
            proposal=proposal,
            review=review,
            items=items,
        )
        == result
    )
    assert result.planner.password not in repr(result)
    assert result.catalog_person.email not in repr(result)


@pytest.mark.parametrize(
    "change", ["scope", "item", "person", "version", "rooms", "extra", "zero"]
)
def test_result_refuses_mismatched_sources_or_ambiguous_results(change):
    setup, proposal, review, items = _sources()
    result = _result(setup, items)
    doc = json.loads(json.dumps(asdict(result), default=str))
    if change == "scope":
        doc["edition_id"] = str(uuid4())
    elif change == "item":
        doc["item_ids"][0] = str(uuid4())
    elif change == "person":
        doc["planner"] = asdict(proposal.lead)
        doc["planner"]["account_id"] = str(proposal.lead.account_id)
    elif change == "version":
        doc["candidate_version"] = True
    elif change == "rooms":
        doc["room_ids"] *= 2
    elif change == "extra":
        doc["permission"] = "all"
    else:
        doc["room_ids"][0] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(scenario.ProgrammePlanningScenarioError, match="result_invalid"):
        scenario.planning_from_document(
            doc, setup=setup, proposal=proposal, review=review, items=items
        )


def test_placement_separates_room_work_and_explicit_host_presence():
    _, _, _, items = _sources()
    occurrence = SimpleNamespace(object_id=uuid4(), version=2)
    day = SimpleNamespace(object_id=uuid4(), version=1)
    placement = scenario._placement(
        items,
        occurrence=occurrence,
        day=day,
        room=uuid4(),
        host_id=items.accepted.host_id,
        minute=120,
    )
    assert placement.normalized() == placement
    assert (
        placement.host_presences[0].starts_at == placement.envelope.effective_starts_at
    )
    assert placement.host_presences[0].ends_at == placement.envelope.effective_ends_at
    assert placement.envelope.setup_starts_at < placement.host_presences[0].starts_at
    assert placement.envelope.teardown_ends_at > placement.host_presences[0].ends_at


@pytest.mark.parametrize(
    "failure",
    [None, "stale", "incomplete", "source", "missing_conflict", "still_blocked"],
)
def test_evaluation_requires_real_complete_current_sources(monkeypatch, failure):
    _authentication(monkeypatch)
    setup = _setup()
    planner = _person("planner")
    identifier, candidate = uuid4(), uuid4()
    command = create_autospec(
        evaluation_commands.evaluate_scheduling_candidate,
        return_value=SchedulingCommandResult(uuid4(), identifier, 1, 9),
    )
    monkeypatch.setattr(evaluation_commands, "evaluate_scheduling_candidate", command)
    codes = ["candidate_room_overlap", "host_overlap", "venue_capacity"]
    if failure == "missing_conflict":
        codes.pop()
    report = SimpleNamespace(
        state="stale" if failure == "stale" else "current",
        evaluation_id=identifier,
        saved_complete=failure != "incomplete",
        current=SimpleNamespace(
            complete=True,
            sources=(SimpleNamespace(available=failure != "source"),),
            findings=tuple(SimpleNamespace(code=c, severity="blocker") for c in codes),
        ),
    )
    query = create_autospec(
        planning_review.load_scheduling_candidate_review, return_value=report
    )
    monkeypatch.setattr(planning_review, "load_scheduling_candidate_review", query)
    if failure is None:
        assert (
            scenario._evaluate(setup, planner, candidate, 4, conflicted=True)
            == identifier
        )
    else:
        with pytest.raises(scenario.ProgrammePlanningScenarioError):
            scenario._evaluate(
                setup, planner, candidate, 4, conflicted=failure != "still_blocked"
            )
    assert command.call_args.args[0].actor_id == planner.account_id
    assert "authorizer" not in command.call_args.kwargs
    assert query.call_args.kwargs == {"candidate_id": candidate, "expected_version": 4}


def _mock_planning(monkeypatch, *, accept_stale=False):
    _authentication(monkeypatch)
    state = {"control": 0, "candidates": {}, "manifests": {}, "events": []}

    def result(identifier, version=1):
        state["control"] += 1
        return SchedulingCommandResult(uuid4(), identifier, version, state["control"])

    def create_day(request, *, day, expected_control_version):
        request.normalized()
        day.normalized()
        assert expected_control_version == state["control"]
        state["events"].append(("day", day))
        return result(uuid4())

    def create_occurrence(request, *, occurrence, expected_control_version):
        request.normalized()
        occurrence.normalized()
        assert expected_control_version == state["control"]
        state["events"].append(("occurrence", occurrence))
        return result(uuid4())

    def create_candidate(request, *, label, expected_control_version):
        request.normalized()
        assert expected_control_version == state["control"]
        identifier = uuid4()
        state["candidates"][identifier] = PlanningCandidate(
            identifier, uuid4(), 1, label, "draft", 0
        )
        state["manifests"][identifier] = ()
        return result(identifier)

    def copy(request, *, source_revision_id, label, expected_control_version):
        source = next(
            c
            for c in state["candidates"].values()
            if c.revision_id == source_revision_id
        )
        answer = create_candidate(
            request, label=label, expected_control_version=expected_control_version
        )
        state["manifests"][answer.object_id] = state["manifests"][source.id]
        state["candidates"][answer.object_id] = replace(
            state["candidates"][answer.object_id], placement_count=3
        )
        return answer

    def place(request, *, candidate_id, expected_version, placement):
        request.normalized()
        placement.normalized()
        old = state["candidates"][candidate_id]
        if old.version != expected_version and not accept_stale:
            raise SchedulingVersionConflictError
        manifest = tuple(
            p
            for p in state["manifests"][candidate_id]
            if p.occurrence_id != placement.occurrence_id
        )
        manifest += (
            PlanningPlacement(
                uuid4(),
                placement.occurrence_id,
                uuid4(),
                uuid4(),
                placement.space_selection_id,
                placement.capacity_mode,
                placement.expected_attendance,
                placement.envelope,
                placement.day_id,
            ),
        )
        state["manifests"][candidate_id] = manifest
        state["candidates"][candidate_id] = replace(
            old,
            revision_id=uuid4(),
            version=old.version + 1,
            placement_count=len(manifest),
        )
        state["events"].append(("place", placement))
        return result(candidate_id, old.version + 1)

    def snapshot(setup, planner, candidate=None):
        return SimpleNamespace(
            control_version=state["control"],
            days=(),
            occurrences=(),
            candidates=tuple(state["candidates"].values()),
            accepts_writes=True,
            selected_candidate_id=candidate,
            placements=state["manifests"].get(candidate, ()),
        )

    for owner, name, operation in (
        (day_commands, "create_scheduling_service_day", create_day),
        (occurrence_commands, "create_scheduling_occurrence", create_occurrence),
        (candidate_commands, "create_scheduling_candidate", create_candidate),
        (candidate_commands, "copy_scheduling_candidate", copy),
        (placement_commands, "set_scheduling_placement", place),
    ):
        monkeypatch.setattr(
            owner, name, create_autospec(getattr(owner, name), side_effect=operation)
        )
    monkeypatch.setattr(scenario, "_snapshot", snapshot)
    monkeypatch.setattr(scenario, "_evaluate", Mock(return_value=uuid4()))
    return state


def test_plan_retains_conflicted_source_and_explicit_same_host_repetition(monkeypatch):
    state = _mock_planning(monkeypatch)
    setup, _, _, items = _sources()
    result = scenario._compose_plan(
        setup, items, _person("planner"), (uuid4(), uuid4())
    )
    assert len(result[1]) == 3
    assert result[2] != result[4]
    assert result[6] == 3
    occurrences = [v for kind, v in state["events"] if kind == "occurrence"]
    assert occurrences[0].group_key is None
    assert occurrences[1].group_key == occurrences[2].group_key
    assert [o.group_sequence for o in occurrences] == [None, 1, 2]
    placements = [v for kind, v in state["events"] if kind == "place"]
    assert [p.expected_attendance for p in placements] == [30, 120, 30, 30, 30]
    assert placements[1].host_presences == placements[2].host_presences
    assert placements[1].space_selection_id != placements[2].space_selection_id
    assert [
        call.kwargs["conflicted"] for call in scenario._evaluate.call_args_list
    ] == [True, False]


def test_composition_refuses_silently_accepted_stale_write(monkeypatch):
    _mock_planning(monkeypatch, accept_stale=True)
    setup, _, _, items = _sources()
    with pytest.raises(
        scenario.ProgrammePlanningScenarioError, match="stale_write_accepted"
    ):
        scenario._compose_plan(setup, items, _person("planner"), (uuid4(), uuid4()))


def test_preparation_uses_guarded_startup_then_real_narrow_role_recipes(monkeypatch):
    sources = _sources()
    setup, _, _, items = sources
    expected = _result(setup, items)
    order = []
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(return_value=SimpleNamespace(run_id=RUN)),
    )
    monkeypatch.setattr(
        programme_runtime, "build_candidate_application", lambda: order.append("guard")
    )
    monkeypatch.setattr(
        scenario,
        "_create_person",
        Mock(side_effect=(expected.planner, expected.catalog_person)),
    )
    grant = Mock(side_effect=lambda *_a, **kw: (order.append(kw["code"]), uuid4())[1])
    monkeypatch.setattr(scenario, "approve_synthetic_role", grant)
    monkeypatch.setattr(
        scenario,
        "prepare_rooms",
        Mock(return_value=(expected.room_ids, (uuid4(), uuid4()))),
    )
    plan = tuple(
        getattr(expected, k)
        for k in (
            "day_id",
            "occurrence_ids",
            "conflicted_candidate_id",
            "conflicted_revision_id",
            "candidate_id",
            "candidate_revision_id",
            "candidate_version",
            "placement_ids",
            "evaluation_id",
        )
    )
    monkeypatch.setattr(scenario, "_compose_plan", Mock(return_value=plan))
    result = scenario.prepare_planning_scenario(*sources)
    assert order == ["guard", "planner", "venue-catalog", "venue-selection"]
    assert [c.kwargs["level"] for c in grant.call_args_list] == [
        ScopeLevel.EDITION,
        ScopeLevel.ORGANIZATION,
        ScopeLevel.EDITION,
    ]
    assert all(c.kwargs["people"] == setup.controllers for c in grant.call_args_list)
    assert result.candidate_id == expected.candidate_id


def test_policy_fence_precedes_framework_people_or_actions(monkeypatch):
    guard = Mock()
    monkeypatch.setattr(programme_runtime, "build_candidate_application", guard)
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        scenario.prepare_planning_scenario(None, None, None, None)
    guard.assert_not_called()


@pytest.mark.parametrize(
    "raw", ["{}", "null", "secret" * 12000], ids=["empty", "null", "oversized"]
)
def test_fixed_child_protocol_never_echoes_bad_private_input(monkeypatch, capsys, raw):
    monkeypatch.setattr(scenario, "require_programme_runtime_environment", Mock())
    monkeypatch.setattr(scenario.sys, "stdin", io.StringIO(raw))
    prepare = Mock()
    monkeypatch.setattr(scenario, "prepare_planning_scenario", prepare)
    with pytest.raises(SystemExit) as error:
        scenario._main()
    assert error.value.code == 2
    prepare.assert_not_called()
    assert capsys.readouterr().out == ""
