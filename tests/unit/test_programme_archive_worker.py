"""Worker supervision keeps time, process, output and concurrency contracts closed."""

import io
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from maru.programme import archive_worker as worker
from maru.programme.management.commands import programme_archive_run_once as child
from maru.programme.management.commands import programme_archive_worker as command


@pytest.mark.parametrize(
    ("code", "expected"),
    [(0, "completed"), (1, "failed"), (3, "busy"), (4, "idle"), (99, "failed")],
)
def test_supervisor_fixed_command_silent_bounded_child(monkeypatch, code, expected):
    run = MagicMock(return_value=SimpleNamespace(returncode=code))
    monkeypatch.setattr(worker.subprocess, "run", run)
    assert worker.supervise_archive_queue_once() == expected
    args, kwargs = run.call_args
    assert args[0][-1] == "programme_archive_run_once"
    assert kwargs["timeout"] == 1200
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert "shell" not in kwargs


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (subprocess.TimeoutExpired("synthetic", 1200), "timed_out"),
        (OSError("PRIVATE"), "failed"),
    ],
)
def test_supervisor_failure_returns_no_process_output(monkeypatch, failure, expected):
    monkeypatch.setattr(worker.subprocess, "run", MagicMock(side_effect=failure))
    assert worker.supervise_archive_queue_once() == expected


@pytest.mark.parametrize("cycles", [0, -1, 5, True])
def test_management_pass_count_is_finite(cycles):
    with pytest.raises(CommandError, match="between 1 and 4"):
        call_command("programme_archive_worker", max_cycles=cycles)


@pytest.mark.parametrize("result", ["completed", "idle", "busy"])
def test_management_logs_only_closed_results_and_stops_when_idle(monkeypatch, result):
    supervise = MagicMock(return_value=result)
    monkeypatch.setattr(command, "supervise_archive_queue_once", supervise)
    output = io.StringIO()
    call_command("programme_archive_worker", max_cycles=2, stdout=output)
    assert supervise.call_count == (2 if result == "completed" else 1)
    assert result in output.getvalue()


@pytest.mark.parametrize("result", ["failed", "timed_out"])
def test_management_reports_safe_nonzero_failures(monkeypatch, result):
    monkeypatch.setattr(command, "supervise_archive_queue_once", lambda: result)
    with pytest.raises(CommandError, match=result):
        call_command("programme_archive_worker")


@pytest.mark.parametrize(("result", "code"), [("busy", 3), ("idle", 4), ("failed", 1)])
def test_child_uses_closed_exit_codes(monkeypatch, result, code):
    monkeypatch.setattr(child, "process_archive_queue_once", lambda: result)
    with pytest.raises(SystemExit) as error:
        call_command("programme_archive_run_once")
    assert error.value.code == code


def test_child_suppresses_private_exception_output(monkeypatch):
    monkeypatch.setattr(
        child,
        "process_archive_queue_once",
        MagicMock(side_effect=RuntimeError("PRIVATE")),
    )
    with pytest.raises(SystemExit) as error:
        call_command("programme_archive_run_once")
    assert str(error.value) == "1"
    assert error.value.__suppress_context__


@pytest.mark.parametrize("result", ["ready", "skipped", "expired"])
def test_child_success_prints_no_private_detail(monkeypatch, result):
    monkeypatch.setattr(child, "process_archive_queue_once", lambda: result)
    output = io.StringIO()
    call_command("programme_archive_run_once", stdout=output)
    assert output.getvalue() == ""
