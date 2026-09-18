"""Lease-bound local HTTPS preparation, without system trust or public hosting."""

from __future__ import annotations

import ipaddress
import math
import os
import ssl
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
    require_programme_runtime_environment,
)

DEADLINE_ENV = "MARU_PROGRAMME_REHEARSAL_DEADLINE"
DIRECTORY_ENV = "MARU_PROGRAMME_REHEARSAL_DIRECTORY"
ROOT = Path(__file__).resolve().parents[2]


class ProgrammeHttpsError(RuntimeError):
    """Expose a stable stage code, never paths, credentials or request contents."""


def require_certificate_directory(value, *, run_id):
    """Accept only this run's direct temporary child, never a linked or shared path."""
    directory = Path(value)
    tools = ROOT / ".tools"
    if (
        not directory.is_absolute()
        or directory.is_symlink()
        or tools.is_symlink()
        or not directory.is_dir()
        or directory.resolve().parent != tools.resolve()
        or not directory.name.startswith(f"programme-https-{run_id}-")
        or any(
            path.is_symlink() or not path.is_file()
            for path in (
                directory / "certificate.pem",
                directory / "private-key.pem",
            )
        )
    ):
        raise ProgrammeHttpsError("invalid_fixture_directory")
    return directory


def remaining_lease(deadline):
    """Return the remaining original lease without extending a later phase."""
    if not isinstance(deadline, float) or not math.isfinite(deadline):
        raise ProgrammeHttpsError("invalid_fixture_deadline")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProgrammeHttpsError("fixture_lease_expired")
    return remaining


def create_loopback_certificate(directory, *, deadline):
    """Write a fresh self-signed fixture leaf inside the caller-owned empty folder.

    Parameters
    ----------
    directory
        Newly created owned temporary directory, never a shared or adopted folder.
    deadline
        Original monotonic fixture deadline; no phase receives a renewed lease.

    Returns
    -------
    str
        Public certificate SHA256, not authority or production trust evidence.
    """
    request = require_programme_rehearsal_request()
    remaining = remaining_lease(deadline)
    if remaining > request.lease_seconds:
        raise ProgrammeHttpsError("fixture_deadline_extended")
    path = Path(directory)
    if path.is_symlink() or not path.is_dir() or any(path.iterdir()):
        raise ProgrammeHttpsError("fixture_directory_not_empty")
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Maru isolated Programme rehearsal")]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(seconds=remaining))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.IPv4Address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    # Exclusive creation prevents overwriting an existing file, including a
    # raced symlink. The caller retains this directory until the server exits.
    with (path / "certificate.pem").open("xb") as stream:
        stream.write(certificate.public_bytes(serialization.Encoding.PEM))
    with (path / "private-key.pem").open("xb") as stream:
        stream.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
    return certificate.fingerprint(hashes.SHA256()).hex()


class _QuietHttpsHandler(WSGIRequestHandler):
    def get_environ(self):
        environment = super().get_environ()
        environment["HTTPS"] = "on"
        return environment

    def log_message(self, _format, *_arguments):
        # Never retain credential-bearing query strings or private fixture paths.
        return None


class _HttpsServer(WSGIServer):
    """Bound TLS handshakes/reads so an idle client cannot hold the fixture open."""

    allow_reuse_address = False

    def get_request(self):
        connection, address = self.socket.accept()
        connection.settimeout(5)
        try:
            return self.tls_context.wrap_socket(connection, server_side=True), address
        except BaseException:
            connection.close()
            raise


def serve_candidate():
    """Serve only a genuinely constructed candidate until parent EOF or deadline.

    Notes
    -----
    Called only by the owned launcher with a dedicated stdin keepalive pipe.
    Self-exit closes only this process's sockets/connections; parent cleanup owns
    the verified database and temporary directory. No system trust is installed.
    """
    environment = require_programme_runtime_environment()
    request = require_programme_rehearsal_request()
    try:
        deadline = float(os.environ[DEADLINE_ENV])
    except (KeyError, ValueError):
        raise ProgrammeHttpsError("invalid_fixture_deadline") from None
    remaining = remaining_lease(deadline)
    if remaining > request.lease_seconds or sys.stdin.isatty():
        raise ProgrammeHttpsError("invalid_fixture_supervisor")
    # Arm expiry/parent-death protection before Django/native readiness, which
    # can fail or block. Do not signal a PID supplied by an environment variable.
    watchdog = threading.Timer(remaining, lambda: os._exit(0))
    watchdog.daemon = True
    watchdog.start()

    def parent_disconnected():
        sys.stdin.buffer.read(1)
        os._exit(0)

    threading.Thread(target=parent_disconnected, daemon=True).start()
    from tests.rehearsals.programme_runtime import (  # noqa: PLC0415
        build_candidate_application,
    )

    application, accounted = build_candidate_application()
    from django.conf import settings  # noqa: PLC0415
    from django.contrib.staticfiles.handlers import StaticFilesHandler  # noqa: PLC0415

    prefix = "https://127.0.0.1:"
    origin = settings.MARU_PUBLIC_BASE_URL
    if not origin.startswith(prefix):
        raise ProgrammeHttpsError("invalid_fixture_origin")
    port_text = origin.removeprefix(prefix)
    if not port_text.isdecimal() or str(int(port_text)) != port_text:
        raise ProgrammeHttpsError("invalid_fixture_origin")
    port = int(port_text)
    if not 1024 <= port <= 65535 or settings.STATIC_URL != "/static/":
        raise ProgrammeHttpsError("invalid_fixture_origin")
    directory = require_certificate_directory(
        os.environ.get(DIRECTORY_ENV, ""), run_id=environment.run_id
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(
        directory / "certificate.pem", directory / "private-key.pem"
    )
    with _HttpsServer(("127.0.0.1", port), _QuietHttpsHandler) as server:
        server.tls_context = context
        # The public app static finders do not expose MEDIA_ROOT or fixture keys.
        server.set_app(StaticFilesHandler(application))
        if server.server_address != ("127.0.0.1", port):
            raise ProgrammeHttpsError("fixture_listen_scope_changed")
        if len(accounted) != 3:
            raise ProgrammeHttpsError("fixture_check_contract_changed")
        sys.stdout.write(f"programme-https-ready:{environment.run_id}:{port}\n")
        sys.stdout.flush()
        server.serve_forever(poll_interval=0.2)
