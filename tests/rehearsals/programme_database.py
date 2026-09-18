"""Owned disposable database transport, not a complete Programme fixture.

Native use is fenced by tracked policy. No application/schema/profile is
installed here. The administrator credential is only for later isolated
provisioning, never application requests or runtime-privilege proof.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scripts.run_postgres_pool import POSTGRES_IMAGE

from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

LABEL = "io.maru.programme-rehearsal-run"
OWNER_LABEL = "io.maru.programme-rehearsal-owner"
_CONTAINER_ID = re.compile(r"[0-9a-f]{64}\Z")
_INSPECTION = (
    '{"id":{{json .Id}},"name":{{json .Name}},'
    '"labels":{{json .Config.Labels}},"image":{{json .Config.Image}},'
    '"ports":{{json .NetworkSettings.Ports}}}'
)
_LEASE_COMMAND = """
docker-entrypoint.sh postgres &
server_pid=$!
(sleep "$MARU_FIXTURE_LEASE_SECONDS";
 kill -INT "$server_pid" 2>/dev/null;
 sleep 10;
 kill -KILL "$server_pid" 2>/dev/null) &
watchdog_pid=$!
trap 'kill -INT "$server_pid" 2>/dev/null' INT TERM
wait "$server_pid"
result=$?
kill "$watchdog_pid" 2>/dev/null
exit "$result"
"""


class ProgrammeDatabaseError(RuntimeError):
    """Expose a stable failure code without Docker output or connection secrets."""


@dataclass(frozen=True, slots=True)
class ProgrammeDatabaseLease:
    """Exact temporary administrator endpoint; not an application runtime login."""

    run_id: str
    container_id: str
    owner_nonce: str
    database_name: str
    port: int
    admin_password: str = field(repr=False)


class _Docker:
    def __init__(self):
        self.executable = shutil.which(
            "docker.exe" if sys.platform == "win32" else "docker"
        )
        if self.executable is None:
            raise ProgrammeDatabaseError("docker_unavailable")

    def call(self, *arguments, environment=None, timeout=30, allow_failure=False):
        try:
            result = subprocess.run(  # noqa: S603 - fixed executable and argument vector
                [self.executable, *arguments],
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ProgrammeDatabaseError("docker_operation_unavailable") from None
        if result.returncode and not allow_failure:
            raise ProgrammeDatabaseError("docker_operation_failed")
        return result

    def inspect(self, name):
        result = self.call(
            "container", "inspect", "--format", _INSPECTION, name, allow_failure=True
        )
        if result.returncode:
            if (
                "No such container:" in result.stderr
                or "No such object:" in result.stderr
            ):
                return None
            raise ProgrammeDatabaseError("container_inspection_unavailable")
        try:
            value = json.loads(result.stdout)
        except (ValueError, TypeError):
            raise ProgrammeDatabaseError("invalid_container_inspection") from None
        if not isinstance(value, dict):
            raise ProgrammeDatabaseError("invalid_container_inspection")
        return value


def _owned(value, *, name, run_id, owner, container_id=None):
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("id"), str)
        or _CONTAINER_ID.fullmatch(value["id"]) is None
        or value.get("name") != "/" + name
        or not isinstance(value.get("labels"), dict)
        or value["labels"].get(LABEL) != run_id
        or value["labels"].get(OWNER_LABEL) != owner
        or value.get("image") != POSTGRES_IMAGE
        or (container_id is not None and value["id"] != container_id)
    ):
        raise ProgrammeDatabaseError("container_ownership_mismatch")
    return value["id"]


def _port(value):
    ports = value.get("ports")
    if not isinstance(ports, dict) or set(ports) != {"5432/tcp"}:
        raise ProgrammeDatabaseError("invalid_database_port")
    bindings = ports["5432/tcp"]
    if (
        not isinstance(bindings, list)
        or len(bindings) != 1
        or not isinstance(bindings[0], dict)
        or bindings[0].get("HostIp") != "127.0.0.1"
        or not isinstance(bindings[0].get("HostPort"), str)
        or re.fullmatch(r"[1-9][0-9]{3,4}", bindings[0]["HostPort"]) is None
        or not 1024 <= int(bindings[0]["HostPort"]) <= 65535
    ):
        raise ProgrammeDatabaseError("invalid_database_port")
    return int(bindings[0]["HostPort"])


@contextmanager
def isolated_programme_database() -> Iterator[ProgrammeDatabaseLease]:
    """Own one loopback database and clean only that exact labelled resource.

    Yields
    ------
    ProgrammeDatabaseLease
        Fresh administrator transport for isolated migration/runtime provisioning.
        A successful context exit proves neither application nor journey readiness.

    Raises
    ------
    ProgrammeDatabaseError
        For unsupported Docker location, existing name, startup/ownership/port
        failure or unverified cleanup. Raw Docker output and secrets are omitted.

    Notes
    -----
    The tracked policy and explicit request are checked before invoking Docker.
    An in-container supervisor requests fast shutdown at the lease deadline and
    kills its database child after at most ten further seconds, independently of
    this Python process. These native behavior claims still require #102 proof.
    Auto-remove and tmpfs prevent durable fixture data volumes. Native startup,
    crash expiry and teardown have not been executed under the deferred policy.
    """
    request = require_programme_rehearsal_request()
    if os.environ.get("DOCKER_HOST"):
        raise ProgrammeDatabaseError("docker_host_override")
    docker = _Docker()
    endpoint = docker.call(
        "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"
    ).stdout.strip()
    if not endpoint.startswith(("npipe:////./pipe/", "unix:///")):
        raise ProgrammeDatabaseError("nonlocal_docker_context")
    name = f"maru-programme-{request.run_id}"
    if docker.inspect(name) is not None:
        raise ProgrammeDatabaseError("existing_container_name")

    password = secrets.token_urlsafe(32)
    owner = secrets.token_hex(16)
    database_name = f"maru_programme_{request.run_id}"
    environment = {**os.environ, "POSTGRES_PASSWORD": password}
    started = False
    container_id = None
    try:
        # A timeout can leave a created container: mark intent before dispatch and
        # recover only an exact name/label/image match in the finalizer.
        started = True
        result = docker.call(
            "run",
            "--pull",
            "never",
            "--detach",
            "--rm",
            "--name",
            name,
            "--label",
            f"{LABEL}={request.run_id}",
            "--label",
            f"{OWNER_LABEL}={owner}",
            "--publish",
            "127.0.0.1::5432",
            "--mount",
            "type=tmpfs,destination=/var/lib/postgresql/data,tmpfs-size=1073741824",
            "--env",
            "POSTGRES_USER=postgres",
            "--env",
            f"POSTGRES_DB={database_name}",
            "--env",
            "POSTGRES_PASSWORD",
            "--env",
            f"MARU_FIXTURE_LEASE_SECONDS={request.lease_seconds}",
            "--entrypoint",
            "sh",
            POSTGRES_IMAGE,
            "-c",
            _LEASE_COMMAND,
            environment=environment,
            timeout=120,
        )
        returned_id = result.stdout.strip()
        if _CONTAINER_ID.fullmatch(returned_id) is None:
            raise ProgrammeDatabaseError("invalid_container_identity")
        container_id = returned_id
        value = docker.inspect(container_id)
        _owned(
            value,
            name=name,
            run_id=request.run_id,
            owner=owner,
            container_id=container_id,
        )
        port = _port(value)
        deadline = time.monotonic() + min(60, request.lease_seconds)
        while time.monotonic() < deadline:
            result = docker.call(
                "exec",
                container_id,
                "pg_isready",
                "-U",
                "postgres",
                "-d",
                database_name,
                timeout=5,
                allow_failure=True,
            )
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise ProgrammeDatabaseError("database_startup_timeout")
        yield ProgrammeDatabaseLease(
            run_id=request.run_id,
            container_id=container_id,
            owner_nonce=owner,
            database_name=database_name,
            port=port,
            admin_password=password,
        )
    finally:
        if started:
            value = docker.inspect(name)
            if value is not None:
                owned_id = _owned(
                    value,
                    name=name,
                    run_id=request.run_id,
                    owner=owner,
                    container_id=container_id,
                )
                docker.call("container", "rm", "--force", owned_id, allow_failure=True)
                if docker.inspect(owned_id) is not None:
                    raise ProgrammeDatabaseError("container_cleanup_incomplete")
