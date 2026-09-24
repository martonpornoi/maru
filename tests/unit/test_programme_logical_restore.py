"""Owned restore scope and bounded private subprocess transport failures."""

import io
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.rehearsals import programme_logical_restore as restore
from tests.rehearsals.programme_runtime_environment import ProgrammeRuntimeEnvironment


@pytest.fixture
def transport(monkeypatch):
    calls = []

    class Process:
        def __init__(self, output=b"PGDMP", code=0):
            self.stdout = io.BytesIO(output)
            self.stdin = None
            self.returncode = None
            self.code = code
            self.killed = False

        def wait(self, **_kwargs):
            if self.returncode is None:
                self.returncode = self.code

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

    processes = []
    options = {"output": b"PGDMP", "code": 0, "expire": False}

    def start(arguments, **kwargs):
        calls.append((arguments, kwargs))
        process = Process(options["output"], options["code"])
        if kwargs["stdin"] == restore.subprocess.PIPE:
            process.stdin = io.BytesIO()
        processes.append(process)
        return process

    class Timer:
        def __init__(self, duration, callback):
            assert duration == 7
            self.callback = callback

        def start(self):
            if options["expire"]:
                self.callback()

        def cancel(self):
            pass

    monkeypatch.setattr(restore, "remaining_lease", lambda _deadline: 7)
    monkeypatch.setattr(restore, "_check_container", lambda *_args: None)
    monkeypatch.setattr(restore.subprocess, "Popen", start)
    monkeypatch.setattr(restore.threading, "Timer", Timer)
    return SimpleNamespace(
        calls=calls,
        processes=processes,
        options=options,
        docker=SimpleNamespace(
            executable="docker", _host_endpoint="unix:///owned.sock"
        ),
        lease=SimpleNamespace(container_id="a" * 64),
    )


def test_dump_transport_pins_owned_daemon_and_bounds_output(transport):
    assert (
        restore._dump_command(
            transport.docker, transport.lease, 100, "pg_dump", "--format=custom"
        )
        == b"PGDMP"
    )
    assert transport.calls[0][0] == [
        "docker",
        "--host",
        "unix:///owned.sock",
        "exec",
        "a" * 64,
        "pg_dump",
        "--format=custom",
    ]
    assert transport.calls[0][1]["stderr"] == restore.subprocess.DEVNULL
    assert transport.processes[0].stdout.closed
    assert not transport.processes[0].killed


def test_oversized_dump_kills_only_its_owned_process(transport, monkeypatch):
    monkeypatch.setattr(restore, "MAX_DUMP_BYTES", 4)
    transport.options["output"] = b"PGDMP-private-contents"
    with pytest.raises(
        restore.ProgrammeLogicalRestoreError, match=r"^restore_dump_limit_exceeded$"
    ):
        restore._dump_command(transport.docker, transport.lease, 100, "pg_dump")
    assert transport.processes[0].killed
    assert transport.processes[0].stdout.closed


def test_dump_deadline_never_becomes_success(transport):
    transport.options["expire"] = True
    with pytest.raises(
        restore.ProgrammeLogicalRestoreError, match=r"^restore_transport_timeout$"
    ):
        restore._dump_command(transport.docker, transport.lease, 100, "pg_dump")
    assert transport.processes[0].killed


def test_dump_nonzero_exit_does_not_expose_captured_bytes(transport):
    transport.options.update(code=1, output=b"private-credential-and-payload")
    with pytest.raises(
        restore.ProgrammeLogicalRestoreError, match=r"^restore_dump_command_failed$"
    ):
        restore._dump_command(transport.docker, transport.lease, 100, "pg_dump")


def test_restore_payload_uses_stdin_and_never_command_arguments(transport):
    transport.options["output"] = b""
    assert (
        restore._dump_command(
            transport.docker,
            transport.lease,
            100,
            "pg_restore",
            payload=b"private-dump",
        )
        == b""
    )
    assert "-i" in transport.calls[0][0]
    assert b"private-dump" not in transport.calls[0][0]
    assert transport.processes[0].stdin.closed


def test_expired_lease_never_starts_dump(transport, monkeypatch):
    def expired(_deadline):
        raise RuntimeError("synthetic_expired_lease")

    monkeypatch.setattr(restore, "remaining_lease", expired)
    with pytest.raises(RuntimeError, match=r"^synthetic_expired_lease$"):
        restore._dump_command(transport.docker, transport.lease, 100, "pg_dump")
    assert not transport.calls


def test_oversized_restore_input_never_starts_process(transport, monkeypatch):
    monkeypatch.setattr(restore, "MAX_DUMP_BYTES", 4)
    with pytest.raises(
        restore.ProgrammeLogicalRestoreError, match=r"^restore_dump_limit_exceeded$"
    ):
        restore._dump_command(
            transport.docker, transport.lease, 100, "pg_restore", payload=b"PGDMP"
        )
    assert not transport.calls


@pytest.mark.parametrize(
    "changed",
    [
        {"run_id": "b" * 32},
        {"database_name": "another_database"},
        {"port": 51920},
        {"database_url": "postgresql://maru_runtime:secret@127.0.0.1:invalid/db"},
        {"database_url": "postgresql://maru_runtime:secret@[invalid/db"},
        {
            "database_url": "postgresql://maru_runtime:secret@remote.invalid:51919/"
            "maru_programme_" + "a" * 32
        },
        {
            "database_url": "postgresql://postgres:secret@127.0.0.1:51919/maru_programme_"
            + "a" * 32
        },
        {
            "database_url": "postgresql://maru_runtime:secret@127.0.0.1:51919/"
            "another_database"
        },
        {
            "database_url": "postgresql://maru_runtime:secret@127.0.0.1:51919/maru_programme_"
            + "a" * 32
            + "?options=unsafe"
        },
    ],
)
def test_foreign_runtime_cannot_reach_dump_or_database_creation(monkeypatch, changed):
    runtime = ProgrammeRuntimeEnvironment(
        "a" * 32,
        "maru_programme_" + "a" * 32,
        51919,
        3600,
        "postgresql://maru_runtime:secret@127.0.0.1:51919/maru_programme_" + "a" * 32,
    )
    fixture = SimpleNamespace(
        runtime=replace(runtime, **changed),
        deadline=100,
        _database_lease=SimpleNamespace(
            run_id=runtime.run_id,
            database_name=runtime.database_name,
            port=runtime.port,
        ),
    )
    monkeypatch.setattr(restore, "require_programme_rehearsal_request", object)
    monkeypatch.setattr(restore, "_verify_lease", lambda *_args: None)

    def unexpected(*_args):
        pytest.fail("Foreign scope must fail before accessing Docker or a database.")

    monkeypatch.setattr(restore, "_docker_for_lease", unexpected)
    with (
        pytest.raises(
            restore.ProgrammeLogicalRestoreError, match=r"^restore_source_run_mismatch$"
        ),
        restore._restored_database(fixture),
    ):
        pytest.fail("Foreign restored scope must never be yielded.")


@pytest.mark.parametrize(
    "failure",
    [
        "restore_data_snapshot_mismatch",
        "restore_source_changed",
        "restore_transport_timeout",
    ],
)
def test_partial_backup_requires_the_exact_copy_failure(monkeypatch, failure):
    observed = []
    fixture = SimpleNamespace(verify_excluded_state=lambda: observed.append("verified"))

    @contextmanager
    def rejected(actual, *, omit_journal_for_negative=False):
        assert actual is fixture
        assert omit_journal_for_negative is True
        raise restore.ProgrammeLogicalRestoreError(failure)
        yield  # pragma: no cover -- context manager intentionally never admits restore.

    monkeypatch.setattr(restore, "_restored_database", rejected)
    if failure == "restore_data_snapshot_mismatch":
        restore.verify_incomplete_backup_rejected(fixture)
        assert observed == ["verified"]
    else:
        with pytest.raises(restore.ProgrammeLogicalRestoreError, match=failure):
            restore.verify_incomplete_backup_rejected(fixture)
        assert not observed


def test_partial_backup_never_accepts_an_unexpected_success(monkeypatch):
    @contextmanager
    def accepted(*_args, **_kwargs):
        yield

    monkeypatch.setattr(restore, "_restored_database", accepted)
    with pytest.raises(
        restore.ProgrammeLogicalRestoreError,
        match=r"^restore_partial_backup_was_accepted$",
    ):
        restore.verify_incomplete_backup_rejected(object())
