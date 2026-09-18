"""Own one short-lived native HTTPS fixture; no production or complete-journey claim."""

from __future__ import annotations

import json
import os
import queue
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from tests.rehearsals.programme_database import isolated_programme_database
from tests.rehearsals.programme_fixture_material import (
    ProgrammeFixtureMaterial,
    generate_fixture_material,
)
from tests.rehearsals.programme_https import (
    DEADLINE_ENV,
    DIRECTORY_ENV,
    ProgrammeHttpsError,
    create_loopback_certificate,
    remaining_lease,
)
from tests.rehearsals.programme_provisioning import (
    ROOT,
    _child,
    _child_environment,
    _verify_lease,
    provision_programme_runtime,
)
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRuntimeEnvironment,
    require_programme_rehearsal_request,
)
from tests.rehearsals.programme_setup_scenarios import (
    SETUP_MODES,
    ProgrammeSetupScenario,
    scenario_from_document,
)

_SERVER = (
    "from tests.rehearsals.programme_https import serve_candidate; serve_candidate()"
)
_WORKER = """
from tests.rehearsals.programme_invitation_worker import run_invitation_worker_cycle
run_invitation_worker_cycle()
print("programme-invitation-cycle-verified")
"""


def _stop_owned_process(process):
    """Close only this Popen's keepalive/handles, with bounded termination fallback."""
    if process.stdin is not None:
        process.stdin.close()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if process.stdout is not None:
        process.stdout.close()


def _await_ready(process, *, expected, deadline):
    received = queue.Queue(maxsize=1)

    def read_one_marker():
        try:
            received.put(process.stdout.readline(160))
        except (OSError, ValueError):
            received.put("")

    threading.Thread(target=read_one_marker, daemon=True).start()
    try:
        actual = received.get(timeout=min(180, remaining_lease(deadline)))
    except queue.Empty:
        raise ProgrammeHttpsError("fixture_server_start_timeout") from None
    if actual != expected + "\n" or process.poll() is not None:
        raise ProgrammeHttpsError("fixture_server_start_failed")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _file, _code, _message, _headers, _new_url):
        raise ProgrammeHttpsError("fixture_health_redirect_refused")


def _verify_https_health(url, certificate, *, deadline):
    """Trust only this ephemeral leaf; never bypass TLS, proxy or follow redirects."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=str(certificate))
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=context),
        _NoRedirect(),
    )
    try:
        with opener.open(
            url + "/health/ready", timeout=min(15, remaining_lease(deadline))
        ) as response:
            body = response.read(16_385)
            if response.status != 200 or len(body) > 16_384:
                raise ProgrammeHttpsError("fixture_https_health_unavailable")
            document = json.loads(body)
        dependencies = document.get("dependencies")
        if (
            document.get("status") != "ok"
            or not isinstance(dependencies, dict)
            or not dependencies
            or any(value != "ok" for value in dependencies.values())
        ):
            raise ProgrammeHttpsError("fixture_https_health_unavailable")
    except (OSError, urllib.error.URLError, ValueError, AttributeError):
        raise ProgrammeHttpsError("fixture_https_health_unavailable") from None


def _prepare_setup(*, mode, material, environment, deadline):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "tests.rehearsals.programme_setup_scenarios"],
            cwd=ROOT,
            env=environment,
            input=json.dumps(
                {
                    "mode": mode,
                    "administrator_password": material.administrator_password,
                }
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=min(180, remaining_lease(deadline)),
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0 or len(result.stdout) > 16_384:
            raise ProgrammeHttpsError("fixture_setup_process_failed")
        return scenario_from_document(json.loads(result.stdout), mode=mode)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ProgrammeHttpsError("fixture_setup_process_failed") from None


@dataclass(frozen=True, slots=True)
class ProgrammeRunningFixture:
    """Scoped live handle, not P01-P12 acceptance or representative-person evidence."""

    run_id: str
    url: str
    certificate_path: Path
    certificate_sha256: str
    deadline: float
    runtime: ProgrammeRuntimeEnvironment = field(repr=False)
    material: ProgrammeFixtureMaterial = field(repr=False)
    _worker_environment: dict[str, str] = field(repr=False)
    scenario: ProgrammeSetupScenario | None = field(default=None, repr=False)

    def refresh_workers(self):
        """Run actual workers before each long checkpoint; never renew the lease."""
        _child(
            ["-c", _WORKER],
            self._worker_environment,
            timeout=min(180, remaining_lease(self.deadline)),
            expected_output="programme-invitation-cycle-verified",
        )


@contextmanager
def isolated_programme_application(*, setup_mode=None):
    """Prepare, verify and temporarily serve one owned native loopback candidate.

    Parameters
    ----------
    setup_mode
        Optional closed setup scenario. Omit for stopped-foundation/HTTPS checks.
        Credentials travel only through dedicated child pipes and private handles.

    Yields
    ------
    ProgrammeRunningFixture
        Live scoped runtime and secret-bearing bootstrap material. Call real worker
        refresh before long checkpoints; this context does not fabricate acceptance
        or seed Programme content. Setup/people/initial roles require explicit mode.

    Notes
    -----
    Policy is checked before sockets/files/Docker. All phases consume one original
    deadline. The child self-exits on parent EOF or expiry even during a blocked
    request. Normal failure/exit stops only its owned process before disposing the
    newly created certificate directory and verified database context. A controller
    crash can leave expired synthetic PEM files, never a system trust installation;
    remove only the exact recorded owned directory after confirming no live process.
    """
    request = require_programme_rehearsal_request()
    if setup_mode is not None and setup_mode not in SETUP_MODES:
        raise ProgrammeHttpsError("invalid_fixture_setup_mode")
    deadline = time.monotonic() + request.lease_seconds
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
        material = generate_fixture_material(web_port=port)
        with (
            isolated_programme_database() as lease,
            tempfile.TemporaryDirectory(
                prefix=f"programme-https-{request.run_id}-", dir=ROOT / ".tools"
            ) as directory,
        ):
            path = Path(directory).resolve()
            fingerprint = create_loopback_certificate(path, deadline=deadline)
            runtime = provision_programme_runtime(
                lease,
                candidate_schema=True,
                candidate_writes=True,
                fixture_material=material,
            )
            environment = (
                _child_environment(
                    lease,
                    request,
                    role="maru_runtime",
                    password="",
                    secret_key=material.secret_key,
                )
                | dict(material.runtime_configuration)
                | {
                    "MARU_DATABASE_URL": runtime.database_url,
                    "DJANGO_SETTINGS_MODULE": (
                        "tests.rehearsals.programme_runtime_settings"
                    ),
                }
            )
            fixture = ProgrammeRunningFixture(
                request.run_id,
                f"https://127.0.0.1:{port}",
                path / "certificate.pem",
                fingerprint,
                deadline,
                runtime,
                material,
                environment | material.worker_environment(),
            )
            fixture.refresh_workers()
            if setup_mode is not None:
                from dataclasses import replace  # noqa: PLC0415

                fixture = replace(
                    fixture,
                    scenario=_prepare_setup(
                        mode=setup_mode,
                        material=material,
                        environment=environment,
                        deadline=deadline,
                    ),
                )
                fixture.refresh_workers()
            _verify_lease(lease, request)
            remaining_lease(deadline)
            # Reserve while provisioning. A bind race after release fails;
            # never adopt another listener or retry against an arbitrary port.
            reservation.close()
            try:
                process = subprocess.Popen(  # noqa: S603 - fixed interpreter/vector
                    [sys.executable, "-c", _SERVER],
                    cwd=ROOT,
                    env=environment
                    | {
                        DEADLINE_ENV: repr(deadline),
                        DIRECTORY_ENV: str(path),
                    },
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except OSError:
                raise ProgrammeHttpsError(
                    "fixture_server_process_unavailable"
                ) from None
            try:
                _await_ready(
                    process,
                    expected=f"programme-https-ready:{request.run_id}:{port}",
                    deadline=deadline,
                )
                _verify_https_health(
                    fixture.url, fixture.certificate_path, deadline=deadline
                )
                _verify_lease(lease, request)
                yield fixture
            finally:
                _stop_owned_process(process)
