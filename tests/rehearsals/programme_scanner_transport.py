"""Bounded loopback transport to the real scanner on an unpublished internal network.

Docker Desktop cannot publish an internal-only bridge endpoint. This fixture
forwards three closed ClamAV commands through a fixed Docker exec, without giving
the daemon external networking or replacing its replies with test verdicts.
"""

import os
import re
import socketserver
import subprocess
import threading
import time
from contextlib import contextmanager

from tests.rehearsals.programme_https import remaining_lease

_MAX_DATA = 10 * 1024 * 1024
_MAX_WIRE = _MAX_DATA + 64 * 1024
_MAX_REPLY = 1024
_PIPE = "timeout 5 nc 127.0.0.1 3310 | head -c 1025"


class ScannerTransportError(RuntimeError):
    """Refuse unsupported or unbounded protocol without exposing file contents."""


def _read_exact(connection, count, deadline):
    result = bytearray()
    while len(result) < count:
        connection.settimeout(remaining_lease(deadline))
        part = connection.recv(min(65536, count - len(result)))
        if not part:
            raise ScannerTransportError("scanner_transport_incomplete")
        result.extend(part)
    return bytes(result)


def read_request(connection, *, deadline):
    """Accept only bounded PING, VERSION or INSTREAM; never daemon control."""
    command = bytearray()
    while len(command) < 10:
        command.extend(_read_exact(connection, 1, deadline))
        if command[-1] == 0:
            break
    if bytes(command) in (b"zPING\0", b"zVERSION\0"):
        return bytes(command)
    if bytes(command) != b"zINSTREAM\0":
        raise ScannerTransportError("scanner_transport_command_invalid")
    request = command
    total = 0
    while len(request) < _MAX_WIRE:
        header = _read_exact(connection, 4, deadline)
        length = int.from_bytes(header, "big")
        if total + length > _MAX_DATA or len(request) + 4 + length > _MAX_WIRE:
            raise ScannerTransportError("scanner_transport_input_too_large")
        request.extend(header)
        if length == 0:
            return bytes(request)
        total += length
        request.extend(_read_exact(connection, length, deadline))
    raise ScannerTransportError("scanner_transport_input_too_large")


def exchange(docker, container_id, request, *, deadline):
    """Relay exact bytes to a fixed daemon; bounded head/timeout limit replies."""
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise ScannerTransportError("scanner_transport_identity_invalid")
    endpoint = docker._host_endpoint
    if not isinstance(endpoint, str) or not endpoint:
        raise ScannerTransportError("scanner_transport_endpoint_missing")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DOCKER_HOST", "DOCKER_CONTEXT"}
    }
    result = subprocess.run(  # noqa: S603 - fixed command; private bytes only on stdin
        [
            docker.executable,
            "--host",
            endpoint,
            "exec",
            "-i",
            container_id,
            "sh",
            "-c",
            _PIPE,
        ],
        input=request,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        timeout=min(10.0, remaining_lease(deadline)),
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if (
        result.returncode != 0
        or not result.stdout
        or len(result.stdout) > _MAX_REPLY
        or not result.stdout.endswith(b"\0")
        or b"\0" in result.stdout[:-1]
    ):
        raise ScannerTransportError("scanner_transport_reply_invalid")
    return result.stdout


@contextmanager
def scanner_loopback_transport(docker, container_id, *, deadline):
    """Own one loopback listener and at most two bounded real-scanner exchanges."""
    slots = threading.BoundedSemaphore(2)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            if self.client_address[0] != "127.0.0.1" or not slots.acquire(
                blocking=False
            ):
                return
            try:
                expires = min(deadline, time.monotonic() + 12.0)
                request = read_request(
                    self.request, deadline=min(expires, time.monotonic() + 5.0)
                )
                reply = exchange(docker, container_id, request, deadline=expires)
                self.request.settimeout(remaining_lease(expires))
                self.request.sendall(reply)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                return
            finally:
                slots.release()

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = False
        request_queue_size = 2

        def handle_error(self, request, client_address):
            # Transport failures close the socket, never log private request bytes.
            pass

    remaining_lease(deadline)
    with Server(("127.0.0.1", 0), Handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        thread.start()
        try:
            yield port
        finally:
            server.shutdown()
            thread.join(timeout=2.0)
