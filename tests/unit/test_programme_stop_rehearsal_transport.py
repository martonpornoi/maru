"""Private clone orchestration and closed child protocols, not native evidence."""

import io
import json
import subprocess
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_stop_races as races
from tests.rehearsals import programme_stopped_restore as restore
from tests.rehearsals.programme_setup_scenarios import scenario_from_document
from tests.unit.test_programme_setup_scenarios import _document


@pytest.mark.parametrize("module", [races, restore])
@pytest.mark.parametrize("failure", [None, "exit", "output", "os", "timeout", "source"])
def test_clone_transport_is_private_bounded_and_disposed(monkeypatch, module, failure):
    observed = []
    fixture = SimpleNamespace(
        scenario=scenario_from_document(_document(), mode="new_foundation"),
        runtime=object(),
        deadline=100,
        refresh_workers=Mock(),
        verify_excluded_state=Mock(),
        _worker_environment={"worker": "private"},
        _application_environment={"application": "private"},
    )
    clone = SimpleNamespace(database_url="private-clone-url", run_id="clone-id")

    @contextmanager
    def restored(actual):
        assert actual is fixture
        observed.append("open")
        try:
            yield clone, "original-source"
        finally:
            observed.append("disposed")

    worker = Mock()
    token = (
        "programme-stop-race-verified"
        if module is races
        else "programme-stopped-restore-verified"
    )
    run = Mock(
        return_value=SimpleNamespace(
            returncode=2 if failure == "exit" else 0,
            stdout="private unexpected output" if failure == "output" else token,
        )
    )
    if failure == "os":
        run.side_effect = OSError("private connection")
    elif failure == "timeout":
        run.side_effect = subprocess.TimeoutExpired("private command", 17)
    monkeypatch.setattr(module, "_restored_database", restored)
    monkeypatch.setattr(module, "_child", worker)
    monkeypatch.setattr(module, "remaining_lease", lambda _deadline: 17)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(
        module,
        "_runtime_data_state",
        lambda _runtime: "changed" if failure == "source" else "original-source",
    )
    operation = (
        races.verify_stop_races
        if module is races
        else restore.verify_stopped_logical_restore
    )
    if failure:
        with pytest.raises(RuntimeError) as caught:
            operation(fixture)
        assert "private" not in str(caught.value)
        assert observed == ["open", "disposed"]
    else:
        operation(fixture)
        count = 3 if module is races else 1
        assert observed == ["open", "disposed"] * count
        assert run.call_count == count
        assert fixture.verify_excluded_state.call_count == (3 if module is races else 2)
    fixture.refresh_workers.assert_called_once_with()
    for call in worker.call_args_list:
        assert call.kwargs["timeout"] == 17
        assert call.args[1] == {
            "worker": "private",
            "MARU_DATABASE_URL": "private-clone-url",
            "MARU_PROGRAMME_REHEARSAL_RUN_ID": "clone-id",
        }
    for call in run.call_args_list:
        args, kwargs = call
        assert args[0] == [module.sys.executable, "-m", module.__name__]
        assert kwargs["timeout"] == 17
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["env"]["MARU_DATABASE_URL"] == "private-clone-url"
        document = json.loads(kwargs["input"])
        assert set(document) == ({"setup", "order"} if module is races else {"setup"})
        assert "password" not in " ".join(args[0])


@pytest.mark.parametrize("module", [races, restore])
@pytest.mark.parametrize(
    "failure", [None, "environment", "oversized", "json", "verify"]
)
def test_child_main_closes_errors_without_echoing_private_input(
    monkeypatch, module, failure
):
    environment, verify = Mock(), Mock()
    if failure == "environment":
        environment.side_effect = RuntimeError("private environment")
    elif failure == "verify":
        verify.side_effect = RuntimeError("private input")
    raw = b'{"private": "synthetic input"}'
    if failure == "oversized":
        raw = b"p" * 65537
    elif failure == "json":
        raw = b"private invalid JSON"
    output = io.StringIO()
    monkeypatch.setattr(module, "require_programme_runtime_environment", environment)
    monkeypatch.setattr(module, "_verify", verify)
    monkeypatch.setattr(module.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    monkeypatch.setattr(module.sys, "stdout", output)
    assert module._main() == (2 if failure else 0)
    if failure:
        assert output.getvalue() == ""
    else:
        assert output.getvalue().endswith("-verified")
        verify.assert_called_once_with({"private": "synthetic input"})
    if failure in {"environment", "oversized", "json"}:
        verify.assert_not_called()
