"""Closed rehearsal handles and subprocess failures; no native acceptance claim."""

import io
import json
import subprocess
import time
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from maru.programme.exit_archive_stream import write_programme_exit_archive
from tests.rehearsals import programme_archive_scenario as scenario
from tests.rehearsals.programme_setup_scenarios import scenario_from_document
from tests.unit.test_programme_exit_archive_stream import (
    package as package,  # noqa: PLC0414
)
from tests.unit.test_programme_setup_scenarios import _document


def _inputs():
    setup = scenario_from_document(_document(), mode="new_foundation")
    result = scenario.ProgrammeArchiveScenario(
        setup.organization_id,
        setup.edition_id,
        setup.controllers[0].account_id,
        uuid4(),
        uuid4(),
        "ready",
        1024,
        "a" * 64,
        0.5,
        2048,
    )
    document = json.loads(json.dumps(asdict(result), default=str))
    return setup, result, document


def test_closed_result_roundtrip():
    setup, result, document = _inputs()
    assert scenario.archive_from_document(document, setup=setup) == result


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("organization_id", str(uuid4())),
        ("edition_id", str(uuid4())),
        ("requester_id", str(uuid4())),
        ("task_id", str(uuid4()).replace("-", "x")),
        ("request_key", "00000000-0000-0000-0000-000000000000"),
        ("state", "failed"),
        ("state", []),
        ("artifact_bytes", True),
        ("artifact_bytes", 0),
        ("artifact_bytes", 2097153),
        ("artifact_digest", "private source"),
        ("generation_seconds", 1),
        ("generation_seconds", float("nan")),
        ("generation_seconds", float("inf")),
        ("generation_seconds", 1200.0),
        ("python_peak_bytes", 0),
        ("extra", "private source"),
    ],
)
def test_changed_result_refuses_without_echoing_source(key, value):
    setup, _, document = _inputs()
    document[key] = value
    with pytest.raises(
        scenario.ProgrammeHttpsError, match=r"^fixture_archive_evidence_changed$"
    ):
        scenario.archive_from_document(document, setup=setup)


@pytest.mark.parametrize("document", [None, [], {}, "private source"])
def test_invalid_envelope_is_closed(document):
    setup, _, _ = _inputs()
    with pytest.raises(scenario.ProgrammeHttpsError):
        scenario.archive_from_document(document, setup=setup)


@pytest.mark.parametrize("failure", [None, "exit", "size", "json", "timeout", "os"])
def test_fixed_child_private_pipe_and_bounded_failure(monkeypatch, failure):
    setup, expected, document = _inputs()
    fixture = SimpleNamespace(
        scenario=setup,
        _application_environment={"private": "owned child"},
        refresh_workers=Mock(),
        deadline=time.monotonic() + 300,
    )
    response = SimpleNamespace(returncode=0, stdout=json.dumps(document))
    if failure == "exit":
        response.returncode = 2
    elif failure == "size":
        response.stdout = "private" * 1000
    elif failure == "json":
        response.stdout = "private source"
    run = Mock(return_value=response)
    if failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private", 180)
    elif failure == "os":
        run.side_effect = OSError("private")
    monkeypatch.setattr(scenario.subprocess, "run", run)
    if failure:
        with pytest.raises(
            scenario.ProgrammeHttpsError, match=r"^fixture_archive_process_failed$"
        ):
            scenario.run_archive_phase(fixture)
    else:
        assert scenario.run_archive_phase(fixture) == expected
    fixture.refresh_workers.assert_called_once_with()
    args, kwargs = run.call_args
    assert args[0] == [
        scenario.sys.executable,
        "-m",
        "tests.rehearsals.programme_archive_scenario",
    ]
    assert kwargs["env"] is fixture._application_environment
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["timeout"] == 180
    assert "password" not in " ".join(args[0])


def test_no_fixture_no_child(monkeypatch):
    run = Mock()
    monkeypatch.setattr(scenario.subprocess, "run", run)
    with pytest.raises(scenario.ProgrammeHttpsError, match="dependencies_required"):
        scenario.run_archive_phase(SimpleNamespace(scenario=None))
    run.assert_not_called()


@pytest.mark.parametrize(
    "defect",
    [None, "scope", "members", "anonymous", "other", "header", "digest", "disposed"],
)
def test_attachment_checks_are_independent_of_manifest_claims(
    package, monkeypatch, defect
):
    context = package["context"]
    setup = SimpleNamespace(
        organization_id=context.organization_id,
        edition_id=context.edition_id,
        controllers=(
            SimpleNamespace(account_id=context.requester_id),
            SimpleNamespace(account_id=uuid4()),
        ),
    )
    sink = io.BytesIO()
    encoding = write_programme_exit_archive(**package, sink=sink)
    archive = scenario.ProgrammeArchiveScenario(
        context.organization_id,
        context.edition_id,
        context.requester_id,
        uuid4(),
        uuid4(),
        "ready",
        encoding.size_bytes,
        encoding.sha256,
        0.1,
        1024,
    )
    if defect == "scope":
        archive = replace(archive, requester_id=uuid4())
    elif defect == "digest":
        archive = replace(archive, artifact_digest="0" * 64)
    headers = {
        "Content-Type": "application/zip",
        "Cache-Control": "private, no-store",
        "Content-Disposition": 'attachment; filename="programme-exit-archive.zip"',
    }
    if defect == "header":
        headers["Cache-Control"] = "public"
    anonymous, wrong, owner = Mock(), Mock(), Mock()
    anonymous.request.return_value.status = 200 if defect == "anonymous" else 302
    wrong.request.return_value.status = 200 if defect == "other" else 404
    owner.request.side_effect = [
        SimpleNamespace(status=200),
        SimpleNamespace(status=200, headers=headers, body=sink.getvalue()),
        SimpleNamespace(status=200 if defect == "disposed" else 404),
    ]
    monkeypatch.setattr(
        scenario, "ProgrammeHttpSession", Mock(side_effect=[anonymous, wrong, owner])
    )
    dispose = Mock(return_value=replace(archive, state="cancelled"))
    monkeypatch.setattr(scenario, "run_archive_phase", dispose)
    fixture = SimpleNamespace(scenario=setup)
    files = (
        () if defect == "members" else tuple(file.file_id for file in package["files"])
    )
    if defect:
        with pytest.raises(scenario.ProgrammeHttpsError):
            scenario.verify_archive_http(fixture, archive, expected_files=files)
        if defect != "disposed":
            dispose.assert_not_called()
    else:
        assert (
            scenario.verify_archive_http(fixture, archive, expected_files=files).state
            == "cancelled"
        )
        dispose.assert_called_once_with(fixture, operation="dispose", previous=archive)
