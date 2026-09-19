"""Closed source/lease/identity contracts; native acceptance is still deferred."""

import io
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.rehearsals import programme_release_outputs, programme_runtime
from tests.rehearsals import programme_release_scenario as scenario
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_setup_scenarios import RUN, _person
from tests.unit.test_programme_staffing_scenario import _result as _staffing
from tests.unit.test_programme_staffing_scenario import _sources as _previous


def _sources():
    previous = _previous()
    return (*previous, _staffing(previous[0], previous[4]))


def _result(setup, planning):
    return scenario.ProgrammeReleaseScenario(
        setup.organization_id,
        setup.edition_id,
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.placement_ids,
        _person("release-reviewer"),
        tuple(uuid4() for _ in range(13)),
        uuid4(),
        uuid4(),
        1,
        "0123456789abcdef" * 4,
    )


def _document(value):
    return json.loads(json.dumps(asdict(value), default=str))


def _named(sources):
    return dict(zip(scenario.SOURCE_KEYS, sources, strict=True))


def test_complete_source_chain_round_trip_retains_private_original_people():
    sources = _sources()
    result = _result(sources[0], sources[4])
    assert (
        scenario.release_from_document(_document(result), **_named(sources)) == result
    )
    assert (
        scenario.release_sources({k: _document(v) for k, v in _named(sources).items()})
        == sources
    )
    assert result.reviewer.password not in repr(result)
    assert result.reviewer.email not in repr(result)


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "candidate",
        "placements",
        "person",
        "version",
        "duplicate",
        "zero",
        "missing",
        "extra",
        "grant",
        "digest",
    ],
)
def test_decoder_rejects_changed_ambiguous_or_foreign_evidence(fault):
    sources = _sources()
    document = _document(_result(sources[0], sources[4]))
    if fault == "scope":
        document["edition_id"] = str(uuid4())
    elif fault == "candidate":
        document["candidate_revision_id"] = str(uuid4())
    elif fault == "placements":
        document["placement_ids"].reverse()
    elif fault == "person":
        document["reviewer"] = _document(sources[-1].volunteer)
    elif fault == "version":
        document["pointer_version"] = True
    elif fault == "duplicate":
        document["approval_id"] = document["release_id"]
    elif fault == "zero":
        document["release_id"] = "00000000-0000-0000-0000-000000000000"
    elif fault == "missing":
        document.pop("approval_id")
    elif fault == "grant":
        document["role_assignment_ids"][1] = document["role_assignment_ids"][0]
    elif fault == "digest":
        document["source_digest"] = "A" * 64
    else:
        document["private"] = "synthetic"
    with pytest.raises(scenario.ProgrammeReleaseScenarioError, match="result_invalid"):
        scenario.release_from_document(document, **_named(sources))


def test_guard_precedes_all_owner_actions_and_outputs_follow_publication(monkeypatch):
    sources = _sources()
    result = _result(sources[0], sources[4])
    order = []
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        lambda: SimpleNamespace(run_id=RUN),
    )
    monkeypatch.setattr(
        programme_runtime, "build_candidate_application", lambda: order.append("guard")
    )
    monkeypatch.setattr(
        scenario,
        "_create_person",
        lambda *_a, **_k: (order.append("person"), result.reviewer)[1],
    )
    monkeypatch.setattr(
        scenario,
        "approve_release_roles",
        lambda *_a: (order.append("roles"), result.role_assignment_ids)[1],
    )
    monkeypatch.setattr(
        scenario,
        "prepare_first_release",
        lambda *_a: (
            order.append("release"),
            (result.approval_id, result.release_id, 1, result.source_digest),
        )[1],
    )
    monkeypatch.setattr(
        programme_release_outputs,
        "verify_release_outputs",
        lambda *_a: order.append("outputs"),
    )
    assert scenario.prepare_release_scenario(*sources) == result
    assert order == ["guard", "person", "roles", "release", "outputs"]
    order.clear()
    monkeypatch.setattr(
        programme_runtime,
        "build_candidate_application",
        Mock(side_effect=RuntimeError("guard")),
    )
    with pytest.raises(RuntimeError, match="guard"):
        scenario.prepare_release_scenario(*sources)
    assert not order


def test_deferral_and_bounded_input_precede_all_commands(monkeypatch):
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        scenario.prepare_release_scenario(*_sources())
    monkeypatch.setattr(scenario.sys, "stdin", io.StringIO("x" * 65_537))
    with pytest.raises(ValueError, match=r"^$"):
        scenario._read_input()


def test_child_failure_cannot_emit_private_owner_error(monkeypatch):
    monkeypatch.setattr(scenario, "require_programme_runtime_environment", lambda: None)
    monkeypatch.setattr(scenario, "_read_input", lambda: ())
    monkeypatch.setattr(
        scenario, "prepare_release_scenario", Mock(side_effect=RuntimeError("private"))
    )
    output = io.StringIO()
    monkeypatch.setattr(scenario.sys, "stdout", output)
    with pytest.raises(SystemExit) as result:
        scenario._main()
    assert result.value.code == 2
    assert output.getvalue() == ""
