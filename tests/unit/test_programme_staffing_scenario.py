"""Pure same-source P06 contracts; no database, real authority or human evidence."""

import io
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.rehearsals import programme_runtime
from tests.rehearsals import programme_staffing_scenario as scenario
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_physical_scenario import _result as _physical
from tests.unit.test_programme_physical_scenario import _sources as _previous
from tests.unit.test_programme_setup_scenarios import RUN, _person


def _sources():
    previous = _previous()
    return (*previous, _physical(previous[0], previous[-1]))


def _result(setup, planning):
    return scenario.ProgrammeStaffingScenario(
        setup.organization_id,
        setup.edition_id,
        planning.candidate_id,
        planning.candidate_revision_id,
        planning.placement_ids,
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        _person("volunteer"),
        (uuid4(), uuid4()),
        tuple(
            scenario.PreparedProgrammeWork(
                uuid4(), uuid4(), uuid4(), uuid4(), 3, uuid4(), 2
            )
            for _ in range(3)
        ),
    )


def _document(value):
    return json.loads(json.dumps(asdict(value), default=str))


def _named(sources):
    return dict(zip(scenario.SOURCE_KEYS, sources, strict=True))


def test_complete_sources_round_trip_without_disclosing_private_personas():
    sources = _sources()
    result = _result(sources[0], sources[4])
    assert (
        scenario.staffing_from_document(_document(result), **_named(sources)) == result
    )
    assert (
        scenario.staffing_sources(
            {key: _document(value) for key, value in _named(sources).items()}
        )
        == sources
    )
    assert result.volunteer.password not in repr(result)
    assert result.volunteer.email not in repr(result)


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
    ],
)
def test_decoder_rejects_ambiguous_or_foreign_results(fault):
    sources = _sources()
    document = _document(_result(sources[0], sources[4]))
    if fault == "scope":
        document["edition_id"] = str(uuid4())
    elif fault == "candidate":
        document["candidate_revision_id"] = str(uuid4())
    elif fault == "placements":
        document["placement_ids"].reverse()
    elif fault == "person":
        document["volunteer"] = _document(sources[-1].reviewer)
    elif fault == "version":
        document["work"][0]["demand_version"] = True
    elif fault == "duplicate":
        document["work"][1]["commitment_id"] = document["work"][0]["commitment_id"]
    elif fault == "zero":
        document["template_id"] = "00000000-0000-0000-0000-000000000000"
    elif fault == "missing":
        document["work"].pop()
    elif fault == "grant":
        document["role_assignment_ids"].append(str(uuid4()))
    else:
        document["secret"] = "synthetic"
    with pytest.raises(scenario.ProgrammeStaffingScenarioError, match="result_invalid"):
        scenario.staffing_from_document(document, **_named(sources))


def test_real_guard_precedes_people_and_each_owner_stage(monkeypatch):
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
        lambda *_a, **_k: (order.append("person"), result.volunteer)[1],
    )
    monkeypatch.setattr(
        scenario,
        "approve_starter",
        lambda *_a: (
            order.append("starter"),
            (result.starter_request_id, result.template_id),
        )[1],
    )
    monkeypatch.setattr(
        scenario,
        "prepare_position_and_assignment",
        lambda *_a: (
            order.append("position"),
            (result.position_id, result.assignment_id),
        )[1],
    )
    monkeypatch.setattr(
        scenario,
        "approve_staffing_roles",
        lambda *_a: (order.append("roles"), result.role_assignment_ids)[1],
    )
    monkeypatch.setattr(
        scenario,
        "prepare_bound_shifts",
        lambda *_a: (
            order.append("shifts"),
            tuple(tuple(asdict(row).values()) for row in result.work),
        )[1],
    )
    assert scenario.prepare_staffing_scenario(*sources) == result
    assert order == ["guard", "person", "starter", "position", "roles", "shifts"]
    order.clear()
    monkeypatch.setattr(
        programme_runtime,
        "build_candidate_application",
        Mock(side_effect=RuntimeError("guard")),
    )
    with pytest.raises(RuntimeError, match="guard"):
        scenario.prepare_staffing_scenario(*sources)
    assert not order


def test_deferral_and_private_input_bounds_precede_commands(monkeypatch):
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        scenario.prepare_staffing_scenario(*_sources())
    monkeypatch.setattr(scenario.sys, "stdin", io.StringIO("x" * 65_537))
    with pytest.raises(ValueError, match=r"^$"):
        scenario._read_input()


def test_private_child_failure_releases_no_owner_detail(monkeypatch):
    monkeypatch.setattr(scenario, "require_programme_runtime_environment", lambda: None)
    monkeypatch.setattr(scenario, "_read_input", lambda: ())
    monkeypatch.setattr(
        scenario, "prepare_staffing_scenario", Mock(side_effect=RuntimeError("private"))
    )
    output = io.StringIO()
    monkeypatch.setattr(scenario.sys, "stdout", output)
    with pytest.raises(SystemExit) as result:
        scenario._main()
    assert result.value.code == 2
    assert output.getvalue() == ""
