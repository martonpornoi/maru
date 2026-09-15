"""Bounded PDF bytes and exact trusted scanner evidence, never intake authority."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from django.conf import settings

MAX_PROGRAMME_FILE_BYTES = 10 * 1024 * 1024
MAX_PROGRAMME_SCAN_SECONDS = 10.0
MAX_PROGRAMME_SCANNER_REPLY_BYTES = 1024
_CHUNK_BYTES = 64 * 1024
_MAX_PORT = 65535
_PDF_HEADER = re.compile(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r\n|\r|\n)")
_FINDING = re.compile(rb"stream: [\x20-\x7e]+ FOUND\x00")
_CLEAN_REPLY = b"stream: OK\x00"


class ProgrammeFileRejectedError(ValueError):
    """Reject unsupported bytes or a malware finding without retaining its details."""


class ProgrammeFileUnavailableError(RuntimeError):
    """Withhold preparation when exact trusted scanner evidence cannot complete."""


@dataclass(frozen=True, slots=True)
class PreparedProgrammeFile:
    """Ephemeral exact bytes and server-computed evidence, not a durable receipt.

    Attributes
    ----------
    data
        Exact immutable bounded bytes scanned, hidden from diagnostic repr.
    sha256
        Server-computed digest of those exact bytes, also hidden from repr.
    size_bytes
        Exact byte length, not an uploaded size assertion.
    media_type
        Code-owned application/pdf, never a trusted browser MIME declaration.
    scanner_code
        Code-owned protocol identifier, not raw scanner findings or a safety promise.
    scanned_at
        Server UTC time after the complete scan; not a freshness or permission lease.
    """

    data: bytes = field(repr=False)
    sha256: str = field(repr=False)
    size_bytes: int
    media_type: str
    scanner_code: str
    scanned_at: datetime


@dataclass(frozen=True, slots=True)
class _Endpoint:
    host: str
    port: int
    family: socket.AddressFamily
    seconds: float


def _configuration() -> _Endpoint:
    if getattr(settings, "MARU_PROGRAMME_FILE_SCANNER", "disabled") != "clamav":
        raise ProgrammeFileUnavailableError("Programme file scanning is unavailable.")
    host = getattr(settings, "MARU_PROGRAMME_FILE_SCANNER_HOST", "")
    port = getattr(settings, "MARU_PROGRAMME_FILE_SCANNER_PORT", 3310)
    seconds = getattr(settings, "MARU_PROGRAMME_FILE_SCANNER_TIMEOUT_SECONDS", 5.0)
    if (
        type(host) is not str
        or not host
        or "%" in host
        or type(port) is not int
        or not 1 <= port <= _MAX_PORT
        or type(seconds) not in (float, int)
        or not 0 < seconds <= MAX_PROGRAMME_SCAN_SECONDS
    ):
        raise ProgrammeFileUnavailableError(
            "Programme scanner configuration is invalid."
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError as error:
        raise ProgrammeFileUnavailableError(
            "Use a literal loopback scanner address."
        ) from error
    if not address.is_loopback or (
        isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None
    ):
        raise ProgrammeFileUnavailableError("Use a literal loopback scanner address.")
    return _Endpoint(
        str(address),
        port,
        socket.AF_INET
        if isinstance(address, ipaddress.IPv4Address)
        else socket.AF_INET6,
        float(seconds),
    )


def _remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise ProgrammeFileUnavailableError("Programme file scanning timed out.")
    return seconds


def _reply(connection: socket.socket, deadline: float) -> bytes:
    result = bytearray()
    while True:
        connection.settimeout(_remaining(deadline))
        part = connection.recv(MAX_PROGRAMME_SCANNER_REPLY_BYTES + 1 - len(result))
        if not part:
            break
        result.extend(part)
        if len(result) > MAX_PROGRAMME_SCANNER_REPLY_BYTES:
            raise ProgrammeFileUnavailableError(
                "Programme scanner evidence is unavailable."
            )
    _remaining(deadline)
    return bytes(result)


def _scan(data: bytes, endpoint: _Endpoint) -> None:
    deadline = time.monotonic() + endpoint.seconds
    try:
        with socket.socket(endpoint.family, socket.SOCK_STREAM) as connection:
            connection.settimeout(_remaining(deadline))
            connection.connect((endpoint.host, endpoint.port))
            connection.settimeout(_remaining(deadline))
            connection.sendall(b"zINSTREAM\x00")
            for offset in range(0, len(data), _CHUNK_BYTES):
                chunk = data[offset : offset + _CHUNK_BYTES]
                connection.settimeout(_remaining(deadline))
                connection.sendall(len(chunk).to_bytes(4, "big") + chunk)
            connection.settimeout(_remaining(deadline))
            connection.sendall(b"\x00\x00\x00\x00")
            reply = _reply(connection, deadline)
    except OSError as error:
        raise ProgrammeFileUnavailableError(
            "Programme file scanning is unavailable."
        ) from error
    if reply == _CLEAN_REPLY:
        return
    if _FINDING.fullmatch(reply):
        raise ProgrammeFileRejectedError(
            "The supporting file was rejected by the scanner."
        )
    raise ProgrammeFileUnavailableError("Programme scanner evidence is unavailable.")


def prepare_programme_pdf(*, data: bytes) -> PreparedProgrammeFile:
    """Prepare exact bounded supporting-file bytes through the sealed scan boundary.

    Parameters
    ----------
    data : bytes
        Actual immutable upload bytes already bounded by an authorized transport;
        browser filename, MIME, size, digest and scanner assertions are not inputs.

    Returns
    -------
    PreparedProgrammeFile
        Exact bytes and server-computed evidence after a complete trusted scan.

    Raises
    ------
    ProgrammeFileRejectedError
        If bytes exceed the bound or do not match the supported PDF envelope.

    Notes
    -----
    A scanner finding also propagates ProgrammeFileRejectedError. Configuration,
    transport, deadline and ambiguous evidence propagate ProgrammeFileUnavailableError.
    The default is disabled; test/rehearsal-clean modes are never accepted. A valid
    PDF envelope and a clean scan do not promise a benign or fully valid document.
    No ORM, storage, authorization, receipt, audit, event, answer or profile write
    is performed. The later owner command must authorize before reading an upload,
    reauthorize after slow work and bind exact provenance/retry before persistence.
    This result is not permission and must not be accepted from a caller as proof.
    """
    if (
        type(data) is not bytes
        or not 0 < len(data) <= MAX_PROGRAMME_FILE_BYTES
        or _PDF_HEADER.match(data) is None
        or not data.rstrip(b" \t\r\n\f").endswith(b"%%EOF")
    ):
        raise ProgrammeFileRejectedError("Use a PDF supporting file of at most 10 MiB.")
    _scan(data, _configuration())
    return PreparedProgrammeFile(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        media_type="application/pdf",
        scanner_code="clamav-instream@1",
        scanned_at=datetime.now(UTC),
    )
