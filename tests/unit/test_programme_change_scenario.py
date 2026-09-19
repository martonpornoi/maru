"""Closed exact lineage and private guard protocol, not native acceptance."""

import io
import json
from dataclasses import asdict, replace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.rehearsals import programme_change_scenario as scenario
from tests.rehearsals import (
    programme_notice_preparation,
    programme_release_outputs,
    programme_runtime,
    programme_successor_release,
    programme_successor_work,
)
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)
from tests.unit.test_programme_release_scenario import _result as _release
from tests.unit.test_programme_release_scenario import _sources as _previous


def _sources():
    sources = _previous()
    return (*sources, _release(sources[0], sources[4]))


def _result(sources):
    setup, _, _, _, _, _, staffing, release = sources
    old = staffing.work[0]
    work = replace(
        old, requirement_revision_id=uuid4(), demand_id=uuid4(), commitment_id=uuid4()
    )
    return scenario.ProgrammeChangeScenario(
        setup.organization_id,
        setup.edition_id,
        release.release_id,
        old.demand_id,
        old.commitment_id,
        work,
        uuid4(),
        uuid4(),
        "f" * 64,
        2,
        tuple(uuid4() for _ in range(9)),
        tuple(uuid4() for _ in range(3)),
    )


def _document(value):
    return json.loads(json.dumps(asdict(value), default=str))


def _decode(document, sources):
    return scenario.change_from_document(
        document, setup=sources[0], staffing=sources[6], release=sources[7]
    )


def test_full_chain_and_exact_lineage_round_trip():
    sources = _sources()
    result = _result(sources)
    assert _decode(_document(result), sources) == result
    assert (
        scenario.change_sources(
            dict(zip(scenario.SOURCE_KEYS, map(_document, sources), strict=True))
        )
        == sources
    )


@pytest.mark.parametrize(
    "fault",
    [
        "scope",
        "prior_release",
        "prior_work",
        "binding",
        "revision",
        "demand",
        "commitment",
        "version",
        "zero",
        "notice",
        "grant",
        "digest",
        "extra",
        "missing",
    ],
)
def test_decoder_rejects_forged_changed_or_ambiguous_handles(fault):
    sources = _sources()
    result = _result(sources)
    document = _document(result)
    original = sources[6].work[0]
    if fault in {"scope", "prior_release", "prior_work"}:
        key = {
            "scope": "edition_id",
            "prior_release": "previous_release_id",
            "prior_work": "predecessor_commitment_id",
        }[fault]
        document[key] = str(uuid4())
    elif fault == "binding":
        document["work"]["binding_id"] = str(uuid4())
    elif fault == "revision":
        document["work"]["requirement_revision_id"] = str(
            original.requirement_revision_id
        )
    elif fault == "demand":
        document["work"]["demand_id"] = str(original.demand_id)
    elif fault == "commitment":
        document["work"]["commitment_id"] = str(original.commitment_id)
    elif fault == "version":
        document["work"]["commitment_version"] = True
    elif fault == "zero":
        document["release_id"] = "00000000-0000-0000-0000-000000000000"
    elif fault == "notice":
        document["notice_ids"][1] = document["notice_ids"][0]
    elif fault == "grant":
        document["role_assignment_ids"].pop()
    elif fault == "digest":
        document["source_digest"] = sources[7].source_digest
    elif fault == "extra":
        document["authority"] = True
    else:
        document.pop("pointer_version")
    with pytest.raises(scenario.ProgrammeChangeScenarioError, match="result_invalid"):
        _decode(document, sources)


def test_guarded_composition_preserves_sources_and_distinct_own_notice_purposes(
    monkeypatch,
):
    sources, order = _sources(), []
    result = _result(sources)
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        lambda: order.append("environment"),
    )
    monkeypatch.setattr(
        programme_runtime,
        "build_candidate_application",
        lambda: order.append("application"),
    )
    monkeypatch.setattr(
        programme_notice_preparation,
        "approve_notice_roles",
        lambda *_a: result.role_assignment_ids,
    )
    monkeypatch.setattr(
        programme_successor_work,
        "prepare_successor_work",
        lambda *_a: (order.append("work"), result.work)[1],
    )
    monkeypatch.setattr(
        programme_successor_release,
        "republish_after_work_change",
        lambda *_a: (
            order.append("release"),
            (result.approval_id, result.release_id, result.source_digest),
        )[1],
    )
    monkeypatch.setattr(programme_successor_work, "_own_work", lambda *_a: {})
    notices = Mock(side_effect=result.notice_ids)
    monkeypatch.setattr(
        programme_notice_preparation, "prepare_review_handoff_ack", notices
    )
    monkeypatch.setattr(
        programme_release_outputs,
        "verify_public_output",
        lambda *_a: order.append("public"),
    )
    monkeypatch.setattr(
        programme_successor_release,
        "verify_successor_operator_output",
        lambda *_a: order.append("operator"),
    )
    assert scenario.prepare_change_scenario(*sources) == result
    assert order == [
        "environment",
        "application",
        "work",
        "release",
        "public",
        "operator",
    ]
    assert [call.args[4].purpose.value for call in notices.call_args_list] == [
        "host",
        "work",
        "room",
    ]
    assert [call.args[3].account_id for call in notices.call_args_list] == [
        sources[3].ceremony_host.account_id,
        sources[6].volunteer.account_id,
        sources[5].reviewer.account_id,
    ]
    assert notices.call_args_list[1].args[4].target_id == result.work.commitment_id
    order.clear()
    monkeypatch.setattr(
        programme_runtime,
        "build_candidate_application",
        Mock(side_effect=RuntimeError("guard")),
    )
    with pytest.raises(RuntimeError, match="guard"):
        scenario.prepare_change_scenario(*sources)
    assert order == ["environment"]


def test_deferral_input_ceiling_and_child_error_suppression(monkeypatch):
    monkeypatch.setattr(
        scenario,
        "require_programme_runtime_environment",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        scenario.prepare_change_scenario(*_sources())
    monkeypatch.setattr(scenario.sys, "stdin", io.StringIO("x" * 65_537))
    with pytest.raises(ValueError, match=r"^$"):
        scenario._read_input()
    monkeypatch.setattr(scenario, "require_programme_runtime_environment", lambda: None)
    monkeypatch.setattr(scenario, "_read_input", lambda: ())
    monkeypatch.setattr(
        scenario, "prepare_change_scenario", Mock(side_effect=RuntimeError("private"))
    )
    output = io.StringIO()
    monkeypatch.setattr(scenario.sys, "stdout", output)
    with pytest.raises(SystemExit) as result:
        scenario._main()
    assert result.value.code == 2
    assert not output.getvalue()
