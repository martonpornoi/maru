"""Explicit synthetic loopback HTTP bridge; native fixture HTTPS stays unchanged."""

from __future__ import annotations

import hashlib
import hmac
import http.client
import os
import re
import ssl
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from tests.rehearsals.programme_https import (
    ProgrammeHttpsError,
    remaining_lease,
    require_certificate_directory,
)
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
    require_programme_rehearsal_request,
)

OPT_IN = "MARU_PROGRAMME_LOCAL_HTTP"
MAX_REQUEST = 4 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
MAX_PDF = 10 * 1024 * 1024
MAX_PATH = 8192
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_FILE_INTAKE = re.compile(
    rf"/my/applications/programme/{_UUID}/{_UUID}/{_UUID}/"
    rf"work/answer/{_UUID}/file/intake/"
)
_COOKIES = frozenset({"sessionid", "csrftoken", "messages"})
_REQUEST_HEADERS = (
    "Accept",
    "Accept-Language",
    "Content-Type",
    "X-CSRFToken",
    "X-Request-ID",
)
_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-disposition",
        "content-language",
        "allow",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
        "content-security-policy",
        "content-security-policy-report-only",
        "vary",
    }
)


class ProgrammeBrowserGatewayError(RuntimeError):
    """Expose a stable refusal, never account credentials or private response bytes."""


class _RequestCounts:
    """Ephemeral bounded transport totals, never request or response content."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {}

    def record(self, method, status=None):
        if method not in {"GET", "HEAD", "POST", "PUT"} or (
            status is not None and (type(status) is not int or not 100 <= status <= 599)
        ):
            raise ValueError("invalid_request_count")
        key = (method, status or 0)
        with self._lock:
            self._counts[key] = min(self._counts.get(key, 0) + 1, 2**31 - 1)

    def snapshot(self):
        with self._lock:
            return [
                {
                    "method": method,
                    "state": str(status) if status else "received",
                    "count": count,
                }
                for (method, status), count in sorted(self._counts.items())
            ]


def _require_opt_in():
    request = require_programme_rehearsal_request()
    if os.environ.get(OPT_IN) != "synthetic-loopback-only":
        raise ProgrammeBrowserGatewayError("local_http_opt_in_required")
    return request


def _local_path(value):
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or len(value) > MAX_PATH
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ProgrammeBrowserGatewayError("local_http_path_refused")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ProgrammeBrowserGatewayError("local_http_path_refused")
    return value


class _Bridge:
    def __init__(self, fixture):
        request = _require_opt_in()
        remaining_lease(fixture.deadline)
        if fixture.run_id != request.run_id or fixture.runtime.run_id != request.run_id:
            raise ProgrammeBrowserGatewayError("local_http_fixture_identity_refused")
        expected = f"https://127.0.0.1:{fixture.material.web_port}"
        if fixture.url != expected or not 1024 <= fixture.material.web_port <= 65535:
            raise ProgrammeBrowserGatewayError("local_http_backend_refused")
        directory = require_certificate_directory(
            fixture.certificate_path.parent, run_id=request.run_id
        )
        if fixture.certificate_path != directory / "certificate.pem":
            raise ProgrammeBrowserGatewayError("local_http_certificate_refused")
        pem = fixture.certificate_path.read_text(encoding="ascii")
        digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()
        if not hmac.compare_digest(digest, fixture.certificate_sha256):
            raise ProgrammeBrowserGatewayError("local_http_certificate_refused")
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_verify_locations(cadata=pem)
        self.backend = expected
        self.backend_port = fixture.material.web_port
        self.deadline = fixture.deadline
        self.cookie_prefix = f"maru_rehearsal_{request.run_id}_"
        self.origin = ""  # Bound once after an actual literal-loopback socket bind.
        self.counts = _RequestCounts()

    def _validate_request(self, method, path, headers, size):
        _require_opt_in()
        remaining_lease(self.deadline)
        _local_path(path)
        upload = method == "PUT" and _FILE_INTAKE.fullmatch(path) is not None
        if method not in {"GET", "HEAD", "POST"} and not upload:
            raise ProgrammeBrowserGatewayError("local_http_method_refused")
        if not self.origin or headers.get("Host") != urlsplit(self.origin).netloc:
            raise ProgrammeBrowserGatewayError("local_http_host_refused")
        for name in (
            "Host",
            "Origin",
            "Referer",
            "Cookie",
            "Content-Length",
            "Content-Type",
            "Content-Encoding",
            "X-CSRFToken",
            "X-Maru-File-Intent",
        ):
            if len(headers.get_all(name, [])) > 1:
                raise ProgrammeBrowserGatewayError("local_http_duplicate_header")
        if (
            headers.get("Transfer-Encoding")
            or headers.get("Expect")
            or headers.get("Content-Encoding")
        ):
            raise ProgrammeBrowserGatewayError("local_http_framing_refused")
        budget = MAX_PDF if upload else MAX_REQUEST
        if size < 0 or size > budget or (method not in {"POST", "PUT"} and size):
            raise ProgrammeBrowserGatewayError("local_http_body_refused")
        if upload and (not size or headers.get("Content-Type") != "application/pdf"):
            raise ProgrammeBrowserGatewayError("local_http_upload_refused")
        origin = headers.get("Origin")
        if (
            (origin is not None and origin != self.origin)
            or (method in {"POST", "PUT"} and origin != self.origin)
            or headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            raise ProgrammeBrowserGatewayError("local_http_origin_refused")

    def request_headers(self, method, path, headers, size):
        self._validate_request(method, path, headers, size)
        origin = headers.get("Origin")
        forwarded = {
            name: headers[name] for name in _REQUEST_HEADERS if name in headers
        }
        intent = headers.get("X-Maru-File-Intent")
        if intent is not None:
            if (
                method not in {"GET", "PUT"}
                or _FILE_INTAKE.fullmatch(path) is None
                or not intent
                or not intent.isascii()
                or len(intent) > 2048
            ):
                raise ProgrammeBrowserGatewayError("local_http_file_intent_refused")
            forwarded["X-Maru-File-Intent"] = intent
        if any(
            any(ord(c) < 32 or ord(c) == 127 for c in value)
            for value in forwarded.values()
        ):
            raise ProgrammeBrowserGatewayError("local_http_header_refused")
        forwarded["Host"] = urlsplit(self.backend).netloc
        forwarded["Accept-Encoding"] = "identity"
        if origin is not None:
            forwarded["Origin"] = self.backend
        referer = headers.get("Referer")
        if referer is not None:
            if not referer.startswith(self.origin + "/"):
                raise ProgrammeBrowserGatewayError("local_http_referer_refused")
            forwarded["Referer"] = self.backend + _local_path(
                referer[len(self.origin) :]
            )
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("Cookie", ""))
        except CookieError:
            raise ProgrammeBrowserGatewayError("local_http_cookie_refused") from None
        kept = SimpleCookie()
        for name in _COOKIES:
            incoming = cookies.get(self.cookie_prefix + name)
            if incoming is not None:
                kept[name] = incoming.value
        if kept:
            forwarded["Cookie"] = kept.output(header="", sep=";").strip()
        return forwarded

    def response(self, status, headers, body):
        remaining_lease(self.deadline)
        content_type = headers.get("Content-Type", "").split(";", 1)[0].lower()
        budget = MAX_PDF if content_type == "application/pdf" else MAX_RESPONSE
        if (
            len(body) > budget
            or headers.get("Content-Encoding", "identity") != "identity"
        ):
            raise ProgrammeBrowserGatewayError("local_http_response_refused")
        result = [
            (name, value)
            for name, value in headers.items()
            if name.lower() in _RESPONSE_HEADERS
        ]
        location = headers.get("Location")
        if location is not None:
            if location.startswith(self.backend + "/"):
                location = location[len(self.backend) :]
            result.append(("Location", _local_path(location)))
        for value in headers.get_all("Set-Cookie", []):
            source = SimpleCookie()
            source.load(value)
            for name, morsel in source.items():
                if name not in _COOKIES or morsel["domain"] or morsel["path"] != "/":
                    raise ProgrammeBrowserGatewayError(
                        "local_http_cookie_scope_refused"
                    )
                target = SimpleCookie()
                target[self.cookie_prefix + name] = morsel.value
                cookie = target[self.cookie_prefix + name]
                for attribute in ("path", "expires", "max-age", "httponly", "samesite"):
                    cookie[attribute] = morsel[attribute]
                # Explicit browser-side development exception only. The upstream
                # cookie remains Secure and never enters a shared server cookie jar.
                result.append(("Set-Cookie", target.output(header="").strip()))
        if content_type == "text/html":
            # Map only this fixture's absolute HTML continuation origin. Never
            # rewrite JSON, calendars, archives, signatures or download bytes.
            body = body.replace(
                (self.backend + "/").encode(), (self.origin + "/").encode()
            )
        result.extend(
            [("Cache-Control", "private, no-store"), ("Content-Length", str(len(body)))]
        )
        return status, result, body

    def exchange(self, method, path, headers, body):
        forwarded = self.request_headers(method, path, headers, len(body))
        connection = http.client.HTTPSConnection(
            "127.0.0.1",
            self.backend_port,
            context=self.context,
            timeout=min(15, remaining_lease(self.deadline)),
        )
        try:
            connection.request(method, path, body=body or None, headers=forwarded)
            response = connection.getresponse()
            return self.response(
                response.status, response.headers, response.read(MAX_PDF + 1)
            )
        finally:
            connection.close()


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class _Handler(BaseHTTPRequestHandler):
    server_version = "MaruLocalRehearsal"
    sys_version = ""

    def log_message(self, _format, *_arguments):
        return None

    def _read_request(self):
        if self.client_address[0] != "127.0.0.1":
            raise ProgrammeBrowserGatewayError("local_http_peer_refused")
        raw_size = self.headers.get("Content-Length", "0")
        if not raw_size.isdecimal() or len(raw_size) > 8:
            raise ProgrammeBrowserGatewayError("local_http_framing_refused")
        size = int(raw_size)
        self.server.bridge.request_headers(self.command, self.path, self.headers, size)
        body = self.rfile.read(size)
        if len(body) != size:
            raise ProgrammeBrowserGatewayError("local_http_body_incomplete")
        return self.server.bridge.exchange(self.command, self.path, self.headers, body)

    def _handle(self):
        self.server.bridge.counts.record(self.command)
        try:
            status, headers, content = self._read_request()
        except (
            ProgrammeBrowserGatewayError,
            ProgrammeHttpsError,
            ProgrammeRehearsalEnvironmentError,
            OSError,
            ValueError,
            http.client.HTTPException,
            CookieError,
        ):
            status, headers, content = (
                503,
                [("Cache-Control", "private, no-store")],
                b"Local rehearsal request refused or unavailable.",
            )
        # A chosen response is not proof of browser delivery or domain success.
        self.server.bridge.counts.record(self.command, status)
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()


@dataclass(frozen=True, slots=True)
class ProgrammeLocalBrowser:
    """Public local entry and original expiry, never account or acceptance evidence."""

    url: str
    deadline: float
    _counts: _RequestCounts = field(repr=False)

    def diagnostics(self):
        """Return copy-only aggregate totals for the private local supervisor."""
        return self._counts.snapshot()


@contextmanager
def local_programme_browser(fixture):
    """Bridge one owned HTTPS fixture to explicitly approved synthetic local HTTP.

    Parameters
    ----------
    fixture
        Live owned native fixture. Its actual leaf, run identity and remaining
        original lease are independently checked before opening the HTTP listener.

    Yields
    ------
    ProgrammeLocalBrowser
        Loopback-only browser origin. Domain commands and upstream TLS are unchanged.

    Notes
    -----
    Requires MARU_PROGRAMME_LOCAL_HTTP=synthetic-loopback-only in addition to the
    existing native opt-in. This is not HTTPS acceptance or production hosting.
    The context owns only its listener; the caller still owns fixture disposal.
    """
    bridge = _Bridge(fixture)
    with _Server(("127.0.0.1", 0), _Handler) as server:
        host, port = server.server_address
        if host != "127.0.0.1" or not 1024 <= port <= 65535:
            raise ProgrammeBrowserGatewayError("local_http_listener_refused")
        bridge.origin = f"http://127.0.0.1:{port}"
        server.bridge = bridge
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        expiry = threading.Timer(remaining_lease(fixture.deadline), server.shutdown)
        expiry.daemon = True
        expiry.start()
        try:
            yield ProgrammeLocalBrowser(bridge.origin, fixture.deadline, bridge.counts)
        finally:
            expiry.cancel()
            server.shutdown()
            worker.join(timeout=5)
