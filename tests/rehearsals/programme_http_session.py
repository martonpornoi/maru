"""Bounded private HTTP transport for the owned native fixture, never a browser."""

import hashlib
import http.cookiejar
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

from tests.rehearsals.programme_https import ProgrammeHttpsError, remaining_lease
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

MAX_RESPONSE_BYTES = 2_097_152
_LOGIN = "/accounts/login/"
_LOGOUT = "/accounts/logout/"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _file, _code, _message, _headers, _url):
        return None


@dataclass(frozen=True, slots=True)
class ProgrammeHttpResponse:
    """Keep response bodies and cookies out of diagnostic representations."""

    status: int
    headers: object = field(repr=False)
    body: bytes = field(repr=False)


class _LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tokens = []
        self.post_form = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form":
            self.post_form = values.get("method", "").lower() == "post" and values.get(
                "action", ""
            ) in {"", _LOGIN}
        if (
            self.post_form
            and tag == "input"
            and values.get("name") == "csrfmiddlewaretoken"
        ):
            self.tokens.append(values.get("value", ""))

    def handle_endtag(self, tag):
        if tag == "form":
            self.post_form = False


class ProgrammeHttpSession:
    """Use real TLS, cookies and CSRF only against one opted-in loopback fixture."""

    def __init__(self, fixture):
        require_programme_rehearsal_request()
        remaining_lease(fixture.deadline)
        parsed = urlsplit(fixture.url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != fixture.material.web_port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ProgrammeHttpsError("fixture_http_origin_invalid")
        certificate = fixture.certificate_path
        if certificate.is_symlink():
            raise ProgrammeHttpsError("fixture_http_certificate_invalid")
        try:
            pem = certificate.read_text(encoding="ascii")
            der = ssl.PEM_cert_to_DER_cert(pem)
            _verify_fingerprint(der, fixture.certificate_sha256)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_verify_locations(cadata=pem)
        except (OSError, ValueError):
            raise ProgrammeHttpsError("fixture_http_certificate_invalid") from None
        self.origin = f"https://127.0.0.1:{parsed.port}"
        self.deadline = fixture.deadline
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(self.cookies),
            _NoRedirect(),
        )

    def request(self, path, *, form=None):
        """Return bounded bytes without following even same-origin redirects."""
        require_programme_rehearsal_request()
        parsed = urlsplit(path)
        if (
            not path.startswith("/")
            or path.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or "\\" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or (form is not None and path not in {_LOGIN, _LOGOUT})
        ):
            raise ProgrammeHttpsError("fixture_http_path_invalid")
        timeout = min(15, remaining_lease(self.deadline))
        headers = {"Accept-Encoding": "identity"}
        if form is not None:
            headers.update(
                {
                    "Origin": self.origin,
                    "Referer": self.origin + path,
                    "Content-Type": "application/x-www-form-urlencoded",
                }
            )
        request = urllib.request.Request(  # noqa: S310 - pinned HTTPS loopback origin
            self.origin + path,
            data=None if form is None else urlencode(form).encode("ascii"),
            headers=headers,
        )
        try:
            try:
                response = self.opener.open(request, timeout=timeout)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                if response.headers.get("Content-Encoding", "identity") != "identity":
                    raise ProgrammeHttpsError("fixture_http_encoding_invalid")
                content = response.read(MAX_RESPONSE_BYTES + 1)
                remaining_lease(self.deadline)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise ProgrammeHttpsError("fixture_http_response_oversized")
                return ProgrammeHttpResponse(response.code, response.headers, content)
        except (OSError, ValueError, urllib.error.URLError):
            raise ProgrammeHttpsError("fixture_http_transport_failed") from None

    def login(self, person, *, destination):
        """Submit the actual login form; never force a session or claim person proof."""
        response = self.request(_LOGIN + "?" + urlencode({"next": destination}))
        parser = _LoginForm()
        try:
            parser.feed(response.body.decode("utf-8"))
        except UnicodeError:
            raise ProgrammeHttpsError("fixture_http_login_form_invalid") from None
        if (
            response.status != 200
            or len(parser.tokens) != 1
            or re.fullmatch(r"[A-Za-z0-9]{64}", parser.tokens[0]) is None
        ):
            raise ProgrammeHttpsError("fixture_http_login_form_invalid")
        signed_in = self.request(
            _LOGIN,
            form={
                "username": person.email,
                "password": person.password,
                "csrfmiddlewaretoken": parser.tokens[0],
                "next": destination,
            },
        )
        sessions = [cookie for cookie in self.cookies if cookie.name == "sessionid"]
        if (
            signed_in.status != 302
            or signed_in.headers.get("Location") != destination
            or len(sessions) != 1
            or not sessions[0].secure
            or not sessions[0].has_nonstandard_attr("HttpOnly")
        ):
            raise ProgrammeHttpsError("fixture_http_login_failed")

    def logout(self):
        """Invalidate this session through the owner endpoint, then forget cookies."""
        try:
            csrf = [
                cookie.value for cookie in self.cookies if cookie.name == "csrftoken"
            ]
            if len(csrf) != 1:
                raise ProgrammeHttpsError("fixture_http_logout_failed")
            response = self.request(_LOGOUT, form={"csrfmiddlewaretoken": csrf[0]})
            if response.status != 302 or response.headers.get("Location") != _LOGIN:
                raise ProgrammeHttpsError("fixture_http_logout_failed")
        finally:
            self.cookies.clear()


def _verify_fingerprint(der, expected):
    if hashlib.sha256(der).hexdigest() != expected:
        raise ProgrammeHttpsError("fixture_http_certificate_invalid")
