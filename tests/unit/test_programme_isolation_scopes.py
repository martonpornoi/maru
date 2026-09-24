"""Closed P12 scope references and private orchestration, not native acceptance."""

import io
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from tests.rehearsals import programme_isolation_scopes as scopes
from tests.rehearsals.programme_setup_scenarios import scenario_from_document
from tests.unit.test_programme_setup_scenarios import _document


@pytest.fixture
def source():
    original = scenario_from_document(_document(), mode="new_foundation")
    expected = scopes.IsolationScopes(*(uuid4() for _ in range(6)))
    return original, expected, json.loads(json.dumps(asdict(expected), default=str))


def test_actual_distinct_scope_reference_roundtrip(source):
    original, expected, document = source
    assert scopes.scopes_from_document(document, original=original) == expected


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "nil",
        "alias",
        "original",
        "uppercase",
        "coercion",
        "envelope",
    ],
)
def test_changed_scope_reference_cannot_become_a_denial_target(source, fault):
    original, _, document = source
    if fault == "missing":
        document.pop("department_id")
    elif fault == "extra":
        document["secret"] = "private synthetic value"
    elif fault == "nil":
        document["organization_id"] = "00000000-0000-0000-0000-000000000000"
    elif fault == "alias":
        document["edition_id"] = document["sibling_edition_id"]
    elif fault == "original":
        document["edition_id"] = str(original.edition_id)
    elif fault == "uppercase":
        document["edition_id"] = "ABCDEFAB-1234-4321-ABCD-123456789012"
    elif fault == "coercion":
        document["edition_id"] = uuid4()
    else:
        document = []
    with pytest.raises(
        scopes.ProgrammeHttpsError, match=r"^fixture_isolation_scope_invalid$"
    ):
        scopes.scopes_from_document(document, original=original)


@pytest.mark.parametrize("fault", [None, "exit", "size", "json", "os", "timeout"])
def test_fixed_child_uses_private_stdin_original_lease_and_real_scope(
    source, monkeypatch, fault
):
    original, expected, document = source
    fixture = SimpleNamespace(
        scenario=original,
        material=SimpleNamespace(administrator_password="private synthetic password"),
        _application_environment={"runtime": "private scope"},
        refresh_workers=Mock(),
        verify_excluded_state=Mock(),
        deadline=100,
    )
    result = SimpleNamespace(
        returncode=2 if fault == "exit" else 0, stdout=json.dumps(document)
    )
    if fault == "size":
        result.stdout = "x" * 2049
    elif fault == "json":
        result.stdout = "private invalid document"
    child = Mock(return_value=result)
    if fault == "os":
        child.side_effect = OSError("private connection")
    elif fault == "timeout":
        child.side_effect = scopes.subprocess.TimeoutExpired("private", 9)
    monkeypatch.setattr(scopes.subprocess, "run", child)
    monkeypatch.setattr(scopes, "remaining_lease", lambda _deadline: 9)
    if fault:
        with pytest.raises(
            scopes.ProgrammeHttpsError, match=r"^fixture_isolation_setup_failed$"
        ):
            scopes.prepare_isolation_scopes(fixture)
        fixture.verify_excluded_state.assert_not_called()
    else:
        assert scopes.prepare_isolation_scopes(fixture) == expected
        fixture.verify_excluded_state.assert_called_once_with()
    fixture.refresh_workers.assert_called_once_with()
    args, kwargs = child.call_args
    assert args[0] == [scopes.sys.executable, "-m", scopes.__name__]
    assert kwargs["env"] is fixture._application_environment
    assert kwargs["timeout"] == 9
    assert kwargs["stderr"] == scopes.subprocess.DEVNULL
    assert kwargs["stdout"] == scopes.subprocess.PIPE
    assert (
        json.loads(kwargs["input"])["administrator_password"]
        == fixture.material.administrator_password
    )
    assert "password" not in " ".join(args[0])


@pytest.mark.parametrize("fault", [None, "environment", "oversized", "json", "prepare"])
def test_child_failure_never_echoes_credentials(source, monkeypatch, fault):
    _, expected, _ = source
    guard, prepare = Mock(), Mock(return_value=expected)
    if fault == "environment":
        guard.side_effect = RuntimeError("private credentials")
    elif fault == "prepare":
        prepare.side_effect = RuntimeError("private setup")
    raw = b'{"secret":"private input"}'
    if fault == "oversized":
        raw = b"x" * 65537
    elif fault == "json":
        raw = b"private invalid JSON"
    output = io.StringIO()
    monkeypatch.setattr(scopes, "require_programme_runtime_environment", guard)
    monkeypatch.setattr(scopes, "_prepare", prepare)
    monkeypatch.setattr(scopes.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    monkeypatch.setattr(scopes.sys, "stdout", output)
    assert scopes._main() == (2 if fault else 0)
    if fault:
        assert output.getvalue() == ""
    else:
        assert "secret" not in output.getvalue()
        prepare.assert_called_once_with({"secret": "private input"})
