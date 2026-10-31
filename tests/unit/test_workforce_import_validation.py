"""Offline command boundary, minimized failures and correction workflow."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from maru.workforce import import_validation

EXAMPLE = Path(__file__).resolve().parents[2] / "docs/examples/workforce-import-v1.json"


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--unknown-PRIVATE_SENTINEL"],
        ["one", "two"],
        ["--schema", "PRIVATE_SENTINEL"],
        ["--sche"],
    ],
)
def test_argument_errors_have_fixed_report_and_no_parser_echo(capsys, arguments):
    assert import_validation.main(arguments) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert "PRIVATE_SENTINEL" not in output.out
    report = json.loads(output.out)
    assert report["status"] == "unavailable"
    assert report["issues"][0]["code"] == "invalid_arguments"


def test_help_and_schema_need_no_input_file(capsys):
    with pytest.raises(SystemExit) as error:
        import_validation.main(["--help"])
    assert error.value.code == 0
    assert "--schema" in capsys.readouterr().out
    assert import_validation.main(["--schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["$id"] == "urn:maru:workforce-import:1"


def test_valid_invalid_and_corrected_local_file_are_never_modified(tmp_path, capsys):
    path = tmp_path / "PRIVATE_PATH_SENTINEL.json"
    valid = EXAMPLE.read_bytes()
    for raw, exit_code, status in [
        (valid, 0, "valid"),
        (b'{"PRIVATE_SENTINEL":', 1, "invalid"),
        (valid, 0, "valid"),
    ]:
        path.write_bytes(raw)
        assert import_validation.main([str(path)]) == exit_code
        output = capsys.readouterr()
        assert output.err == ""
        assert "SENTINEL" not in output.out
        assert json.loads(output.out)["status"] == status
        assert path.read_bytes() == raw
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("kind", ["missing", "directory", "too-large"])
def test_file_failures_and_bounded_read(tmp_path, capsys, kind):
    path = tmp_path / "PRIVATE_PATH_SENTINEL"
    if kind == "directory":
        path.mkdir()
    elif kind == "too-large":
        path.write_bytes(b" " * (1_048_576 + 1))
    expected = 1 if kind == "too-large" else 2
    assert import_validation.main([str(path)]) == expected
    output = capsys.readouterr()
    assert output.err == ""
    assert "SENTINEL" not in output.out
    assert json.loads(output.out)["issues"][0]["code"] == (
        "input_too_large" if kind == "too-large" else "unavailable_file"
    )


@pytest.mark.parametrize(
    "path",
    [
        "//server/share/file.json",
        "\\\\?\\C:\\file.json",
        "NUL",
        "NUL.txt",
        "CON ",
        "COM1",
        "LPT9.txt",
        "file:stream",
    ],
)
def test_windows_network_and_device_names_are_refused_before_open(
    monkeypatch, capsys, path
):
    def forbidden(*args):
        pytest.fail("Unsafe namespace reached file opening")

    monkeypatch.setattr(import_validation.os, "open", forbidden)
    assert import_validation.main([path]) == 2
    assert (
        json.loads(capsys.readouterr().out)["issues"][0]["code"] == "unavailable_file"
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX named-pipe nonblocking guard")
def test_named_pipe_is_refused_without_waiting_for_a_writer(tmp_path, capsys):
    path = tmp_path / "proposal-pipe"
    os.mkfifo(path)
    assert import_validation.main([str(path)]) == 2
    assert (
        json.loads(capsys.readouterr().out)["issues"][0]["code"] == "unavailable_file"
    )


def test_read_failure_and_bad_os_path_are_minimized(monkeypatch, capsys):
    def forbidden(*args):
        raise PermissionError("PRIVATE_OS_SENTINEL")

    monkeypatch.setattr(import_validation.os, "open", forbidden)
    assert import_validation.main(["PRIVATE_PATH_SENTINEL"]) == 2
    assert "SENTINEL" not in capsys.readouterr().out
    assert import_validation.main(["bad\x00path"]) == 2
    assert "bad" not in capsys.readouterr().out


def test_nonregular_descriptor_is_rejected_after_open(monkeypatch, capsys):
    monkeypatch.setattr(
        import_validation.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(st_mode=stat.S_IFCHR),
    )
    assert import_validation.main([str(EXAMPLE)]) == 2
    assert (
        json.loads(capsys.readouterr().out)["issues"][0]["code"] == "unavailable_file"
    )


def test_fresh_interpreter_blocks_app_network_processes_and_file_writes():
    script = """
import importlib.abc, os, runpy, sys
class NoApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'django', 'psycopg', 'sqlite3'}:
            raise AssertionError('Application or database import')
def guard(event, args):
    if event.startswith(('socket.', 'subprocess.', 'sqlite3.')):
        raise AssertionError('Network or process access')
    if event in {'os.remove', 'os.rename', 'os.mkdir', 'os.rmdir'}:
        raise AssertionError('File mutation')
    if event == 'open':
        flags = args[2] or 0
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError('Write access')
sys.meta_path.insert(0, NoApplication())
sys.addaudithook(guard)
sys.argv = ['maru.workforce.import_validation', sys.argv[1]]
runpy.run_module('maru.workforce.import_validation', run_name='__main__')
"""
    result = subprocess.run(  # noqa: S603 - fixed script and fictional repository fixture
        [sys.executable, "-B", "-c", script, str(EXAMPLE)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout)["status"] == "valid"
