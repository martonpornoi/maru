"""Pure private-stage contracts; not native, browser or human acceptance."""

import io
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.rehearsals import programme_physical_scenario as scenario
from tests.rehearsals import programme_runtime
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_planning_scenario import _result as _plan
from tests.unit.test_programme_planning_scenario import _sources as _previous
from tests.unit.test_programme_setup_scenarios import RUN, _person


def _sources():
    setup, proposal, review, items = _previous()
    return setup, proposal, review, items, _plan(setup, items)


def _result(setup, planning):
    return scenario.ProgrammePhysicalScenario(
        setup.organization_id,
        setup.edition_id,
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.placement_ids,
        tuple(uuid4() for _ in range(3)),
        tuple(uuid4() for _ in range(3)),
        (2, 2, 2),
        tuple(uuid4() for _ in range(3)),
        tuple(uuid4() for _ in range(3)),
        ("1" * 64, "2" * 64, "3" * 64),
        _person("physical-reviewer"),
        tuple(uuid4() for _ in range(3)),
    )


def _document(value):
    return json.loads(json.dumps(asdict(value), default=str))


def _named(sources):
    return dict(
        zip(("setup", "proposal", "review", "items", "planning"), sources, strict=True)
    )


def test_same_source_output_redacts_credentials_and_never_starts_framework():
    sources = _sources()
    result = _result(sources[0], sources[-1])
    assert (
        scenario.physical_from_document(_document(result), **_named(sources)) == result
    )
    assert (
        scenario.physical_sources({k: _document(v) for k, v in _named(sources).items()})
        == sources
    )
    assert result.reviewer.password not in repr(result)
    assert result.reviewer.email not in repr(result)


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "candidate",
        "placement",
        "person",
        "version",
        "duplicate",
        "digest",
        "zero",
        "extra",
    ],
)
def test_decoder_rejects_wrong_sources_ambiguous_handles_or_versions(fault):
    sources = _sources()
    doc = _document(_result(sources[0], sources[-1]))
    if fault == "scope":
        doc["edition_id"] = str(uuid4())
    elif fault == "candidate":
        doc["candidate_revision_id"] = str(uuid4())
    elif fault == "placement":
        doc["placement_ids"].reverse()
    elif fault == "person":
        doc["reviewer"] = _document(sources[-1].planner)
    elif fault == "version":
        doc["booking_versions"][0] = True
    elif fault == "duplicate":
        doc["booking_ids"][1] = doc["booking_ids"][0]
    elif fault == "digest":
        doc["fit_source_digests"][0] = "unknown"
    elif fault == "zero":
        doc["reservation_intent_ids"][0] = "00000000-0000-0000-0000-000000000000"
    else:
        doc["secret"] = "private"
    with pytest.raises(scenario.ProgrammePhysicalScenarioError, match="result_invalid"):
        scenario.physical_from_document(doc, **_named(sources))


def test_guard_and_same_source_validation_precede_every_person_and_owner_action(
    monkeypatch,
):
    sources = _sources()
    expected = _result(sources[0], sources[-1])
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
        lambda *_a, **_k: (order.append("person"), expected.reviewer)[1],
    )
    monkeypatch.setattr(
        scenario,
        "approve_room_roles",
        lambda *_: (order.append("roles"), expected.role_assignment_ids)[1],
    )
    monkeypatch.setattr(
        scenario,
        "reserve_and_approve",
        lambda *_: (
            order.append("holds"),
            (
                expected.reservation_intent_ids,
                expected.booking_ids,
                expected.booking_versions,
            ),
        )[1],
    )
    monkeypatch.setattr(
        scenario,
        "assess_accessibility",
        lambda *_: (
            order.append("fit"),
            (
                expected.blocked_decision_ids,
                expected.fit_decision_ids,
                expected.fit_source_digests,
            ),
        )[1],
    )
    assert scenario.prepare_physical_scenario(*sources) == expected
    assert order == ["guard", "person", "roles", "holds", "fit"]


def test_deferred_policy_blocks_before_any_framework_or_source_processing(monkeypatch):
    guard = Mock()
    monkeypatch.setattr(programme_runtime, "build_candidate_application", guard)
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        scenario.prepare_physical_scenario(None, None, None, None, None)
    guard.assert_not_called()


@pytest.mark.parametrize(
    "raw", ["{}", "null", "private" * 10000], ids=["empty", "null", "oversized"]
)
def test_child_never_echoes_malformed_or_oversized_private_input(
    monkeypatch, capsys, raw
):
    monkeypatch.setattr(scenario, "require_programme_runtime_environment", Mock())
    monkeypatch.setattr(scenario.sys, "stdin", io.StringIO(raw))
    prepare = Mock()
    monkeypatch.setattr(scenario, "prepare_physical_scenario", prepare)
    with pytest.raises(SystemExit) as error:
        scenario._main()
    assert error.value.code == 2
    prepare.assert_not_called()
    assert capsys.readouterr().out == ""
