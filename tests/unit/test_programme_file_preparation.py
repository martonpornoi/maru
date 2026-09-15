"""No network or database: exact-byte preparation and fail-closed scanner protocol."""

import hashlib
import socket
from dataclasses import FrozenInstanceError
from datetime import UTC
from itertools import pairwise
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from maru.applications import programme_file_preparation as files

PDF = b"%PDF-1.7\nsynthetic supporting content\n%%EOF\n"


@pytest.fixture
def scanner(monkeypatch, settings):
    settings.MARU_PROGRAMME_FILE_SCANNER = "clamav"
    settings.MARU_PROGRAMME_FILE_SCANNER_HOST = "127.0.0.1"
    settings.MARU_PROGRAMME_FILE_SCANNER_PORT = 3310
    settings.MARU_PROGRAMME_FILE_SCANNER_TIMEOUT_SECONDS = 5.0
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.recv.side_effect = [b"stream: OK\0", b""]
    factory = Mock(return_value=connection)
    monkeypatch.setattr(files.socket, "socket", factory)
    tick = {"now": 100.0}
    monkeypatch.setattr(files.time, "monotonic", lambda: tick["now"])
    return SimpleNamespace(connection=connection, factory=factory, tick=tick)


def test_exact_original_bytes_digest_protocol_and_private_repr(scanner):
    prepared = files.prepare_programme_pdf(data=PDF)
    assert prepared.data is PDF
    assert prepared.sha256 == hashlib.sha256(PDF).hexdigest()
    assert prepared.size_bytes == len(PDF)
    assert prepared.media_type == "application/pdf"
    assert prepared.scanner_code == "clamav-instream@1"
    assert prepared.scanned_at.tzinfo is UTC
    assert "synthetic supporting content" not in repr(prepared)
    assert prepared.sha256 not in repr(prepared)
    with pytest.raises(FrozenInstanceError):
        prepared.media_type = "text/html"
    scanner.factory.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    scanner.connection.connect.assert_called_once_with(("127.0.0.1", 3310))
    assert [call.args[0] for call in scanner.connection.sendall.call_args_list] == [
        b"zINSTREAM\0",
        len(PDF).to_bytes(4, "big") + PDF,
        b"\0\0\0\0",
    ]
    assert scanner.connection.recv.call_count == 2
    scanner.connection.__exit__.assert_called_once()


@pytest.mark.parametrize(
    "parts",
    [
        [b"s", b"tream: ", b"OK", b"\0", b""],
        [bytes([value]) for value in b"stream: OK\0"] + [b""],
    ],
)
def test_fragmentation_is_assembled_until_connection_close(scanner, parts):
    scanner.connection.recv.side_effect = parts
    assert files.prepare_programme_pdf(data=PDF).data == PDF
    assert scanner.connection.recv.call_count == len(parts)


@pytest.mark.parametrize("version", ["1.0", "1.4", "1.7", "2.0"])
@pytest.mark.parametrize("newline", [b"\n", b"\r", b"\r\n"])
def test_supported_pdf_envelope_preserves_every_byte(scanner, version, newline):
    content = b"%PDF-" + version.encode() + newline + b"synthetic\n%%EOF \r\n"
    assert files.prepare_programme_pdf(data=content).data == content


@pytest.mark.parametrize(
    "data",
    [
        None,
        "pdf",
        bytearray(PDF),
        b"",
        b"not a PDF",
        b"%PDF-1.8\nbody\n%%EOF",
        b"%PDF-1.7 body\n%%EOF",
        b"%PDF-1.7\nno end",
        PDF + b"<script>extra</script>",
    ],
)
def test_unsupported_and_oversize_bytes_never_connect(scanner, data):
    with pytest.raises(files.ProgrammeFileRejectedError):
        files.prepare_programme_pdf(data=data)
    scanner.factory.assert_not_called()


def test_oversize_is_rejected_before_scanner_connection(scanner):
    data = b"%PDF-1.7\n" + b"x" * files.MAX_PROGRAMME_FILE_BYTES + b"\n%%EOF"
    with pytest.raises(files.ProgrammeFileRejectedError):
        files.prepare_programme_pdf(data=data)
    scanner.factory.assert_not_called()


def test_exact_maximum_size_and_multiple_chunk_lengths(scanner):
    prefix, suffix = b"%PDF-1.7\n", b"\n%%EOF"
    data = (
        prefix
        + b"x" * (files.MAX_PROGRAMME_FILE_BYTES - len(prefix) - len(suffix))
        + suffix
    )
    result = files.prepare_programme_pdf(data=data)
    assert result.size_bytes == files.MAX_PROGRAMME_FILE_BYTES
    frames = [call.args[0] for call in scanner.connection.sendall.call_args_list][1:-1]
    assert b"".join(frame[4:] for frame in frames) == data
    assert all(int.from_bytes(frame[:4], "big") == len(frame) - 4 for frame in frames)
    assert all(len(frame) <= 64 * 1024 + 4 for frame in frames)


@pytest.mark.parametrize(
    "reply",
    [
        b"",
        b"stream: OK",
        b"stream: OK\n",
        b"stream: OK\0extra",
        b"stream: OK\0stream: Bad FOUND\0",
        b"stream: NOT OK\0",
        b"1: stream: OK\0",
        b"stream: ERROR but OK\0",
        b"stream: size limit exceeded ERROR\0",
        b"\xffstream: OK\0",
        b"stream: UNKNOWN\0",
        b"x" * (files.MAX_PROGRAMME_SCANNER_REPLY_BYTES + 1),
    ],
)
def test_unknown_incomplete_or_extra_evidence_never_succeeds(scanner, reply):
    scanner.connection.recv.side_effect = [reply, b""]
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files.prepare_programme_pdf(data=PDF)
    scanner.connection.__exit__.assert_called_once()


def test_extra_reply_in_later_packet_is_not_ignored(scanner):
    scanner.connection.recv.side_effect = [b"stream: OK\0", b"stream: Bad FOUND\0", b""]
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files.prepare_programme_pdf(data=PDF)


def test_fragmented_malware_finding_is_rejected_without_finding_disclosure(scanner):
    scanner.connection.recv.side_effect = [
        b"stream: Private-Name-",
        b"Signature FOUND\0",
        b"",
    ]
    with pytest.raises(files.ProgrammeFileRejectedError) as caught:
        files.prepare_programme_pdf(data=PDF)
    assert "Private-Name" not in str(caught.value)
    scanner.connection.__exit__.assert_called_once()


@pytest.mark.parametrize("operation", ["connect", "sendall", "recv"])
@pytest.mark.parametrize("error", [OSError("private failure"), TimeoutError("timeout")])
def test_transport_failures_close_socket_and_release_no_prepared_value(
    scanner, operation, error
):
    getattr(scanner.connection, operation).side_effect = error
    with pytest.raises(files.ProgrammeFileUnavailableError) as caught:
        files.prepare_programme_pdf(data=PDF)
    assert "private failure" not in str(caught.value)
    scanner.connection.__exit__.assert_called_once()


@pytest.mark.parametrize("stage", ["connect", "send", "reply", "close"])
def test_one_absolute_deadline_includes_all_io_and_eof(scanner, stage):
    def expire(*_args):
        scanner.tick["now"] = 105.0

    if stage == "connect":
        scanner.connection.connect.side_effect = expire
    elif stage == "send":
        scanner.connection.sendall.side_effect = expire
    else:
        count = 0

        def receive(_length):
            nonlocal count
            count += 1
            if stage == "reply" or count == 2:
                expire()
            return b"stream: OK\0" if count == 1 else b""

        scanner.connection.recv.side_effect = receive
    with pytest.raises(files.ProgrammeFileUnavailableError, match="timed out"):
        files.prepare_programme_pdf(data=PDF)
    scanner.connection.__exit__.assert_called_once()


def test_fragmented_slow_reply_cannot_renew_timeout(scanner):
    remaining = iter(bytes([value]) for value in b"stream: OK\0")

    def trickle(_length):
        scanner.tick["now"] += 1.0
        return next(remaining)

    scanner.connection.recv.side_effect = trickle
    with pytest.raises(files.ProgrammeFileUnavailableError, match="timed out"):
        files.prepare_programme_pdf(data=PDF)
    assert scanner.connection.recv.call_count == 5
    timeouts = [call.args[0] for call in scanner.connection.settimeout.call_args_list]
    assert all(left >= right for left, right in pairwise(timeouts))


@pytest.mark.parametrize(
    "mode", ["disabled", "test_clean", "local_rehearsal_clean", "", True, "other"]
)
def test_no_unscanned_or_unknown_adapter_can_succeed(scanner, settings, mode):
    settings.MARU_PROGRAMME_FILE_SCANNER = mode
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files.prepare_programme_pdf(data=PDF)
    scanner.factory.assert_not_called()


@pytest.mark.parametrize(
    "host",
    [
        "",
        "localhost",
        "scanner.internal",
        "10.0.0.1",
        "169.254.169.254",
        "8.8.8.8",
        "::ffff:127.0.0.1",
        "::1%lo",
        "http://127.0.0.1",
        127001,
    ],
)
def test_no_dns_public_or_non_loopback_transport(scanner, settings, host):
    settings.MARU_PROGRAMME_FILE_SCANNER_HOST = host
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files.prepare_programme_pdf(data=PDF)
    scanner.factory.assert_not_called()


def test_literal_ipv6_loopback_uses_ipv6_socket(scanner, settings):
    settings.MARU_PROGRAMME_FILE_SCANNER_HOST = "::1"
    files.prepare_programme_pdf(data=PDF)
    scanner.factory.assert_called_once_with(socket.AF_INET6, socket.SOCK_STREAM)
    scanner.connection.connect.assert_called_once_with(("::1", 3310))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PORT", 0),
        ("PORT", 65536),
        ("PORT", True),
        ("PORT", "3310"),
        ("TIMEOUT_SECONDS", 0),
        ("TIMEOUT_SECONDS", -1),
        ("TIMEOUT_SECONDS", 11),
        ("TIMEOUT_SECONDS", True),
        ("TIMEOUT_SECONDS", float("nan")),
        ("TIMEOUT_SECONDS", float("inf")),
        ("TIMEOUT_SECONDS", 10**500),
        ("TIMEOUT_SECONDS", "5"),
    ],
)
def test_invalid_config_never_opens_socket(scanner, settings, key, value):
    setattr(settings, "MARU_PROGRAMME_FILE_SCANNER_" + key, value)
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files.prepare_programme_pdf(data=PDF)
    scanner.factory.assert_not_called()
