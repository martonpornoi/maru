"""Owned real ClamAV preparation; no test-clean adapter or production deployment."""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from tests.rehearsals.programme_database import _Docker
from tests.rehearsals.programme_https import remaining_lease
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

# Official image metadata resolved 2026-09-18; no mutable tag is launched.
# Preloaded definitions avoid a full FreshClam download on every short fixture.
SCANNER_IMAGE = (
    "clamav/clamav:1.5.4@sha256:"
    "9cb27d7660bdf66e9878c832cb433dd8aa152cfbe16f3c2c0084c80b04ae22b4"
)
_LABEL = "io.maru.programme-scanner-run"
_OWNER = "io.maru.programme-scanner-owner"
_ID = re.compile(r"[0-9a-f]{64}\Z")
_LEASE_COMMAND = """
remaining=$((MARU_SCANNER_EXPIRES_EPOCH - $(date +%s)))
[ "$remaining" -gt 0 ] && [ "$remaining" -le "$MARU_SCANNER_LEASE_SECONDS" ] || exit 2
clamd --foreground=yes --config-file=/etc/clamav/clamd.conf &
scanner_pid=$!
(sleep "$remaining";
 kill -TERM "$scanner_pid" 2>/dev/null;
 sleep 5;
 kill -KILL "$scanner_pid" 2>/dev/null) &
expiry_pid=$!
trap 'kill -TERM "$scanner_pid" 2>/dev/null' INT TERM
wait "$scanner_pid"
status=$?
kill "$expiry_pid" 2>/dev/null
exit "$status"
"""


class ProgrammeScannerError(RuntimeError):
    """Expose stable dependency errors without raw daemon or file contents."""


@dataclass(frozen=True, slots=True)
class ProgrammeScannerLease:
    """One verified owned endpoint and observed version, never permanent file safety."""

    run_id: str
    container_id: str
    network_id: str
    owner_nonce: str
    port: int
    engine_version: str
    signature_version: int
    signatures_at: datetime

    def runtime_environment(self):
        """Return the existing owner's strict literal-loopback scanner configuration."""
        return {
            "MARU_PROGRAMME_FILE_SCANNER": "clamav",
            "MARU_PROGRAMME_FILE_SCANNER_HOST": "127.0.0.1",
            "MARU_PROGRAMME_FILE_SCANNER_PORT": str(self.port),
            "MARU_PROGRAMME_FILE_SCANNER_TIMEOUT_SECONDS": "5",
        }


def _network(docker, name):
    result = docker.call("network", "inspect", name, allow_failure=True)
    if result.returncode:
        if (
            "not found" in result.stderr.lower()
            or "no such network" in result.stderr.lower()
        ):
            return None
        raise ProgrammeScannerError("scanner_network_inspection_unavailable")
    try:
        rows = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ProgrammeScannerError("scanner_network_inspection_invalid") from None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ProgrammeScannerError("scanner_network_inspection_invalid")
    return rows[0]


def _owned_network(value, *, name, request, owner, identifier=None, containers=()):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("Id"), str)
        or _ID.fullmatch(value["Id"]) is None
        or (identifier is not None and value["Id"] != identifier)
        or value.get("Name") != name
        or value.get("Driver") != "bridge"
        or value.get("Internal") is not True
        or value.get("Scope") != "local"
        or not isinstance(value.get("Labels"), dict)
        or value.get("Labels", {}).get(_LABEL) != request.run_id
        or value.get("Labels", {}).get(_OWNER) != owner
        or not isinstance(value.get("Containers"), dict)
        or set(value["Containers"]) != set(containers)
    ):
        raise ProgrammeScannerError("scanner_network_ownership_mismatch")
    return value["Id"]


def _owned_container(value, *, name, request, owner, identifier=None):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("id"), str)
        or _ID.fullmatch(value["id"]) is None
        or (identifier is not None and value["id"] != identifier)
        or value.get("name") != "/" + name
        or value.get("image") != SCANNER_IMAGE
        or not isinstance(value.get("labels"), dict)
        or value.get("labels", {}).get(_LABEL) != request.run_id
        or value.get("labels", {}).get(_OWNER) != owner
    ):
        raise ProgrammeScannerError("scanner_container_ownership_mismatch")
    return value["id"]


def _port(value):
    ports = value.get("ports")
    if not isinstance(ports, dict) or set(ports) - {"3310/tcp", "7357/tcp"}:
        raise ProgrammeScannerError("scanner_port_scope_changed")
    # The upstream image declares milter, but it is never launched or published.
    if ports.get("7357/tcp") is not None:
        raise ProgrammeScannerError("scanner_port_scope_changed")
    binding = ports.get("3310/tcp")
    if (
        not isinstance(binding, list)
        or len(binding) != 1
        or not isinstance(binding[0], dict)
        or binding[0].get("HostIp") != "127.0.0.1"
        or not isinstance(binding[0].get("HostPort"), str)
        or re.fullmatch(r"[1-9][0-9]{3,4}", binding[0]["HostPort"]) is None
        or not 1024 <= int(binding[0]["HostPort"]) <= 65535
    ):
        raise ProgrammeScannerError("scanner_port_scope_changed")
    return int(binding[0]["HostPort"])


def _reply(port, command, *, deadline):
    if command not in (b"zPING\0", b"zVERSION\0"):
        raise ProgrammeScannerError("scanner_health_command_invalid")
    expires = min(deadline, time.monotonic() + 5.0)
    try:
        with socket.create_connection(
            ("127.0.0.1", port), timeout=remaining_lease(expires)
        ) as connection:
            connection.settimeout(remaining_lease(expires))
            connection.sendall(command)
            result = bytearray()
            while len(result) <= 1024:
                connection.settimeout(remaining_lease(expires))
                part = connection.recv(1025 - len(result))
                if not part:
                    break
                result.extend(part)
            remaining_lease(expires)
    except OSError:
        raise ProgrammeScannerError("scanner_health_unavailable") from None
    if len(result) > 1024:
        raise ProgrammeScannerError("scanner_health_unavailable")
    return bytes(result)


def _version(reply):
    match = re.fullmatch(
        rb"ClamAV (1\.5\.4)/([1-9][0-9]{0,9})/([^\x00\r\n]{1,80})\x00", reply
    )
    if match is None:
        raise ProgrammeScannerError("scanner_version_unavailable")
    try:
        observed = parsedate_to_datetime(match[3].decode("ascii"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=UTC)  # Container TZ is explicitly UTC.
        observed = observed.astimezone(UTC)
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise ProgrammeScannerError("scanner_version_unavailable") from None
    now = datetime.now(UTC)
    if not now - timedelta(days=7) <= observed <= now + timedelta(minutes=5):
        raise ProgrammeScannerError("scanner_signatures_stale")
    return match[1].decode("ascii"), int(match[2]), observed


def _observe_health(port, *, deadline):
    if _reply(port, b"zPING\0", deadline=deadline) != b"PONG\0":
        raise ProgrammeScannerError("scanner_health_unexpected")
    return _version(_reply(port, b"zVERSION\0", deadline=deadline))


def _ready(port, *, deadline):
    startup_deadline = min(deadline, time.monotonic() + 180.0)
    while remaining_lease(startup_deadline) > 0:
        try:
            return _observe_health(port, deadline=startup_deadline)
        except ProgrammeScannerError as error:
            if str(error) != "scanner_health_unavailable":
                raise
        time.sleep(min(0.5, remaining_lease(startup_deadline)))
    raise ProgrammeScannerError("scanner_startup_expired")


def _cleanup(docker, *, name, network_name, request, owner, container_id, network_id):
    value = docker.inspect(name)
    if value is not None:
        identifier = _owned_container(
            value, name=name, request=request, owner=owner, identifier=container_id
        )
        docker.call("container", "rm", "--force", identifier, allow_failure=True)
        if docker.inspect(identifier) is not None:
            raise ProgrammeScannerError("scanner_cleanup_incomplete")
    value = _network(docker, network_name)
    if value is not None:
        identifier = _owned_network(
            value,
            name=network_name,
            request=request,
            owner=owner,
            identifier=network_id,
        )
        docker.call("network", "rm", identifier)
        if _network(docker, identifier) is not None:
            raise ProgrammeScannerError("scanner_network_cleanup_incomplete")


@contextmanager
def isolated_programme_scanner(*, deadline):
    """Prepare one real loopback scanner within the existing fixture deadline.

    Parameters
    ----------
    deadline
        Original owning runner's finite monotonic deadline, never a renewed lease.

    Yields
    ------
    ProgrammeScannerLease
        Same-run owned daemon with exact engine and recent actual signature evidence.
        A healthy daemon is not clean-file evidence; the public owner scans each PDF.

    Notes
    -----
    Required policy precedes any Docker/network work. Only a locally cached pinned
    official image is accepted. No download, signature update, host bind mount,
    external endpoint, persistent data volume or production service is created.
    The daemon uses an owned internal bridge, non-root identity, read-only image,
    bounded tmpfs/resources, no capabilities and an independent expiry watchdog.
    Cleanup verifies exact nonce/IDs and never removes a nonempty foreign network.
    """
    request = require_programme_rehearsal_request()
    if remaining_lease(deadline) > request.lease_seconds:
        raise ProgrammeScannerError("scanner_deadline_extended")
    if os.environ.get("DOCKER_HOST"):
        raise ProgrammeScannerError("scanner_nonlocal_docker")
    docker = _Docker()
    endpoint = docker.call(
        "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
    ).stdout.strip()
    if not endpoint.startswith(("npipe:////./pipe/", "unix:///")):
        raise ProgrammeScannerError("scanner_nonlocal_docker")
    docker._host_endpoint = endpoint
    # Docker <28 can expose localhost publications to same-L2 machines.
    engine = docker.call("version", "--format", "{{.Server.Version}}").stdout.strip()
    if (
        re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:\+[A-Za-z0-9.]+)?", engine) is None
        or int(engine.split(".")[0]) < 28
    ):
        raise ProgrammeScannerError("scanner_docker_version_unsupported")
    name = f"maru-programme-scanner-{request.run_id}"
    network_name = name + "-network"
    if docker.inspect(name) is not None or _network(docker, network_name) is not None:
        raise ProgrammeScannerError("scanner_resource_already_exists")
    owner = secrets.token_hex(16)
    container_id = network_id = None
    try:
        created = docker.call(
            "network",
            "create",
            "--driver",
            "bridge",
            "--internal",
            "--opt",
            "com.docker.network.bridge.gateway_mode_ipv4=nat",
            "--label",
            f"{_LABEL}={request.run_id}",
            "--label",
            f"{_OWNER}={owner}",
            network_name,
        ).stdout.strip()
        if _ID.fullmatch(created) is None:
            raise ProgrammeScannerError("scanner_network_identity_invalid")
        network_id = created
        _owned_network(
            _network(docker, network_name),
            name=network_name,
            request=request,
            owner=owner,
            identifier=network_id,
        )
        seconds = int(remaining_lease(deadline))
        if seconds < 1:
            raise ProgrammeScannerError("scanner_startup_expired")
        expires_epoch = int(time.time() + remaining_lease(deadline))
        created = docker.call(
            "run",
            "--pull",
            "never",
            "--detach",
            "--rm",
            "--name",
            name,
            "--label",
            f"{_LABEL}={request.run_id}",
            "--label",
            f"{_OWNER}={owner}",
            "--network",
            network_id,
            "--publish",
            "127.0.0.1::3310",
            "--read-only",
            "--user",
            "clamav",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--pids-limit",
            "64",
            "--log-driver",
            "none",
            "--no-healthcheck",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m,mode=1777",  # noqa: S108 - owned tmpfs
            "--tmpfs",
            "/var/log/clamav:rw,noexec,nosuid,size=1m,uid=100,mode=0700",
            "--env",
            "TZ=Etc/UTC",
            "--env",
            f"MARU_SCANNER_LEASE_SECONDS={seconds + 1}",
            "--env",
            f"MARU_SCANNER_EXPIRES_EPOCH={expires_epoch}",
            "--entrypoint",
            "sh",
            SCANNER_IMAGE,
            "-c",
            _LEASE_COMMAND,
            timeout=min(120, remaining_lease(deadline)),
        ).stdout.strip()
        if _ID.fullmatch(created) is None:
            raise ProgrammeScannerError("scanner_container_identity_invalid")
        container_id = created
        value = docker.inspect(container_id)
        _owned_container(
            value, name=name, request=request, owner=owner, identifier=container_id
        )
        port = _port(value)
        _owned_network(
            _network(docker, network_name),
            name=network_name,
            request=request,
            owner=owner,
            identifier=network_id,
            containers=(container_id,),
        )
        engine_version, signature_version, signatures_at = _ready(
            port, deadline=deadline
        )
        yield ProgrammeScannerLease(
            request.run_id,
            container_id,
            network_id,
            owner,
            port,
            engine_version,
            signature_version,
            signatures_at,
        )
    finally:
        _cleanup(
            docker,
            name=name,
            network_name=network_name,
            request=request,
            owner=owner,
            container_id=container_id,
            network_id=network_id,
        )
