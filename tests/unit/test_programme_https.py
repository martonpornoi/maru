"""Database-free TLS material and fixture fencing; no listener or native execution."""

import io
import ipaddress
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.x509.oid import ExtendedKeyUsageOID

from tests.rehearsals import programme_https as https
from tests.rehearsals import programme_runtime
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)

RUN = "1234567890abcdef1234567890abcdef"


@pytest.fixture
def permitted(monkeypatch):
    monkeypatch.setattr(
        https,
        "require_programme_rehearsal_request",
        Mock(return_value=SimpleNamespace(run_id=RUN, lease_seconds=600)),
    )
    monkeypatch.setattr(https.time, "monotonic", lambda: 100.0)


def test_real_certificate_is_short_lived_loopback_leaf_and_matches_key(
    permitted, tmp_path
):
    before = datetime.now(UTC)
    fingerprint = https.create_loopback_certificate(tmp_path, deadline=400.0)
    certificate = x509.load_pem_x509_certificate(
        (tmp_path / "certificate.pem").read_bytes()
    )
    key = serialization.load_pem_private_key(
        (tmp_path / "private-key.pem").read_bytes(), password=None
    )
    assert (
        certificate.public_key().public_numbers() == key.public_key().public_numbers()
    )
    assert certificate.fingerprint(hashes.SHA256()).hex() == fingerprint
    assert certificate.subject == certificate.issuer
    assert certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address("127.0.0.1")]
    assert not certificate.extensions.get_extension_for_class(
        x509.BasicConstraints
    ).value.ca
    assert list(
        certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    ) == [ExtendedKeyUsageOID.SERVER_AUTH]
    assert before - timedelta(minutes=2) < certificate.not_valid_before_utc <= before
    assert (
        before + timedelta(seconds=299)
        <= certificate.not_valid_after_utc
        <= datetime.now(UTC) + timedelta(seconds=300)
    )
    with pytest.raises(https.ProgrammeHttpsError, match="directory_not_empty"):
        https.create_loopback_certificate(tmp_path, deadline=400.0)


@pytest.mark.parametrize(
    "deadline", [None, True, 200, "200", float("nan"), float("inf")]
)
def test_deadline_is_finite_original_monotonic_value(deadline, permitted):
    with pytest.raises(https.ProgrammeHttpsError, match="invalid_fixture_deadline"):
        https.remaining_lease(deadline)


@pytest.mark.parametrize("deadline", [99.0, 100.0, 701.0])
def test_expired_or_extended_lease_creates_no_files(deadline, permitted, tmp_path):
    with pytest.raises(https.ProgrammeHttpsError, match=r"expired|extended"):
        https.create_loopback_certificate(tmp_path, deadline=deadline)
    assert list(tmp_path.iterdir()) == []


def test_deferred_policy_precedes_crypto_or_files(monkeypatch, tmp_path):
    monkeypatch.setattr(
        https,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("postgresql_deferred")),
    )
    key = Mock()
    monkeypatch.setattr(https.ec, "generate_private_key", key)
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="postgresql_deferred"):
        https.create_loopback_certificate(tmp_path, deadline=400.0)
    key.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_only_own_run_directory_with_both_regular_files_is_accepted(
    monkeypatch, permitted, tmp_path
):
    monkeypatch.setattr(https, "ROOT", tmp_path)
    tools = tmp_path / ".tools"
    tools.mkdir()
    directory = tools / f"programme-https-{RUN}-owned"
    directory.mkdir()
    with pytest.raises(https.ProgrammeHttpsError, match="invalid_fixture_directory"):
        https.require_certificate_directory(directory, run_id=RUN)
    https.create_loopback_certificate(directory, deadline=400.0)
    assert https.require_certificate_directory(directory, run_id=RUN) == directory
    with pytest.raises(https.ProgrammeHttpsError, match="invalid_fixture_directory"):
        https.require_certificate_directory(directory, run_id="f" * 32)
    for foreign in (".", tmp_path, tools, directory / ".." / directory.name):
        # Normalized same-owned-directory spelling is harmless, not another target.
        if hasattr(foreign, "resolve") and foreign.resolve() == directory:
            continue
        with pytest.raises(
            https.ProgrammeHttpsError, match="invalid_fixture_directory"
        ):
            https.require_certificate_directory(foreign, run_id=RUN)
    monkeypatch.setattr(https.Path, "is_symlink", lambda _self: True)
    with pytest.raises(https.ProgrammeHttpsError, match="invalid_fixture_directory"):
        https.require_certificate_directory(directory, run_id=RUN)


def test_tls_handshake_failure_closes_only_accepted_connection():
    server = object.__new__(https._HttpsServer)
    connection = Mock()
    server.socket = Mock()
    server.socket.accept.return_value = (connection, ("127.0.0.1", 12345))
    server.tls_context = Mock()
    server.tls_context.wrap_socket.side_effect = OSError("handshake failed")
    with pytest.raises(OSError, match="handshake failed"):
        server.get_request()
    connection.settimeout.assert_called_once_with(5)
    connection.close.assert_called_once_with()
    server.socket.close.assert_not_called()


def test_wsgi_marks_tls_without_retaining_request_log(monkeypatch):
    monkeypatch.setattr(
        https.WSGIRequestHandler, "get_environ", lambda _self: {"PATH_INFO": "/"}
    )
    handler = object.__new__(https._QuietHttpsHandler)
    assert handler.get_environ() == {"PATH_INFO": "/", "HTTPS": "on"}
    assert handler.log_message("token=%s", "synthetic-private") is None


def test_expiry_and_parent_pipe_are_armed_before_native_startup(permitted, monkeypatch):
    monkeypatch.setattr(https, "require_programme_runtime_environment", Mock())
    monkeypatch.setenv(https.DEADLINE_ENV, "400.0")
    stdin = Mock()
    stdin.isatty.return_value = False
    stdin.buffer = io.BytesIO(b"")
    monkeypatch.setattr(https.sys, "stdin", stdin)
    timer = Mock()
    thread = Mock()
    monkeypatch.setattr(https.threading, "Timer", timer)
    monkeypatch.setattr(https.threading, "Thread", thread)
    stop = Mock()
    monkeypatch.setattr(https.os, "_exit", stop)

    def unavailable():
        timer.return_value.start.assert_called_once_with()
        thread.return_value.start.assert_called_once_with()
        raise RuntimeError("native startup intentionally not executed")

    monkeypatch.setattr(programme_runtime, "build_candidate_application", unavailable)
    with pytest.raises(RuntimeError, match="intentionally not executed"):
        https.serve_candidate()
    assert timer.call_args.args[0] == 300.0
    assert timer.return_value.daemon is True
    timer.call_args.args[1]()
    stop.assert_called_once_with(0)
    stop.reset_mock()
    thread.call_args.kwargs["target"]()
    stop.assert_called_once_with(0)
    assert thread.call_args.kwargs["daemon"] is True
