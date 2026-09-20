"""Closed transport framing and bounded relay evidence, not real scan verdicts."""

import io
import socket
import subprocess
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.rehearsals import programme_scanner_transport as transport


class Input:
    def __init__(self, data):
        self.data = io.BytesIO(data)
        self.timeouts = []

    def recv(self, count):
        return self.data.read(count)

    def settimeout(self, timeout):
        self.timeouts.append(timeout)


@pytest.mark.parametrize("command", [b"zPING\0", b"zVERSION\0"])
def test_health_transport_preserves_only_one_exact_command(command):
    source = Input(command + b"zSHUTDOWN\0")
    assert transport.read_request(source, deadline=time.monotonic() + 1) == command
    assert source.data.read() == b"zSHUTDOWN\0"


def test_stream_transport_preserves_actual_chunks_without_interpreting_bytes():
    wire = b"zINSTREAM\0\0\0\0\x03abc\0\0\0\x02de\0\0\0\0"
    source = Input(wire)
    assert transport.read_request(source, deadline=time.monotonic() + 1) == wire
    assert all(0 < timeout <= 1 for timeout in source.timeouts)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"zSHUTDOWN\0",
        b"zRELOAD\0",
        b"xPING\0",
        b"zPING",
        b"abcdefghijk",
        b"zINSTREAM\0\0\0",
        b"zINSTREAM\0\0\0\0\x03ab",
        b"zINSTREAM\0\xff\xff\xff\xff",
    ],
)
def test_malformed_control_partial_or_oversized_input_is_not_forwarded(data):
    with pytest.raises(transport.ScannerTransportError):
        transport.read_request(Input(data), deadline=time.monotonic() + 1)


def test_wire_overhead_is_bounded_independently_of_file_size(monkeypatch):
    monkeypatch.setattr(transport, "_MAX_WIRE", 20)
    wire = b"zINSTREAM\0" + (b"\0\0\0\x01a" * 3) + b"\0\0\0\0"
    with pytest.raises(transport.ScannerTransportError, match="too_large"):
        transport.read_request(Input(wire), deadline=time.monotonic() + 1)


def test_payload_limit_applies_across_all_chunks(monkeypatch):
    monkeypatch.setattr(transport, "_MAX_DATA", 4)
    wire = b"zINSTREAM\0\0\0\0\x03abc\0\0\0\x02de\0\0\0\0"
    with pytest.raises(transport.ScannerTransportError, match="too_large"):
        transport.read_request(Input(wire), deadline=time.monotonic() + 1)


def test_exec_uses_pinned_daemon_fixed_command_private_stdin_and_bounded_output(
    monkeypatch,
):
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"PONG\0"))
    monkeypatch.setattr(transport.subprocess, "run", run)
    monkeypatch.setenv("DOCKER_HOST", "remote-untrusted")
    monkeypatch.setenv("DOCKER_CONTEXT", "changed-context")
    docker = SimpleNamespace(
        executable="docker", _host_endpoint="npipe:////./pipe/docker_engine"
    )
    assert (
        transport.exchange(docker, "a" * 64, b"zPING\0", deadline=time.monotonic() + 12)
        == b"PONG\0"
    )
    args, kwargs = run.call_args
    assert args[0] == [
        "docker",
        "--host",
        docker._host_endpoint,
        "exec",
        "-i",
        "a" * 64,
        "sh",
        "-c",
        transport._PIPE,
    ]
    assert kwargs["input"] == b"zPING\0"
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["stdout"] == subprocess.PIPE
    assert 0 < kwargs["timeout"] <= 10
    assert "DOCKER_HOST" not in kwargs["env"]
    assert "DOCKER_CONTEXT" not in kwargs["env"]
    assert "head -c 1025" in transport._PIPE
    assert "timeout 5" in transport._PIPE


@pytest.mark.parametrize(
    "reply",
    [b"", b"PONG", b"PONG\0extra\0", b"x" * 1024 + b"\0"],
    ids=["empty", "partial", "extra", "oversized"],
)
def test_partial_extra_and_oversized_backend_reply_is_unavailable(monkeypatch, reply):
    monkeypatch.setattr(
        transport.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout=reply)),
    )
    with pytest.raises(transport.ScannerTransportError, match="reply_invalid"):
        transport.exchange(
            SimpleNamespace(executable="docker", _host_endpoint="local"),
            "a" * 64,
            b"zPING\0",
            deadline=time.monotonic() + 10,
        )


def test_listener_is_loopback_owned_and_closes_after_context(monkeypatch):
    relay = Mock(return_value=b"PONG\0")
    monkeypatch.setattr(transport, "exchange", relay)
    with transport.scanner_loopback_transport(
        Mock(), "a" * 64, deadline=time.monotonic() + 5
    ) as port:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
            client.sendall(b"zPING\0")
            assert client.recv(1024) == b"PONG\0"
        assert relay.call_args.args[2] == b"zPING\0"
    with pytest.raises((ConnectionRefusedError, TimeoutError)):
        socket.create_connection(("127.0.0.1", port), timeout=0.2)


def test_listener_closes_malformed_input_without_backend_execution(monkeypatch):
    relay = Mock()
    monkeypatch.setattr(transport, "exchange", relay)
    with transport.scanner_loopback_transport(
        Mock(), "a" * 64, deadline=time.monotonic() + 5
    ) as port, socket.create_connection(("127.0.0.1", port), timeout=1) as client:
        client.sendall(b"zSHUTDOWN\0")
        assert client.recv(1024) == b""
    relay.assert_not_called()
