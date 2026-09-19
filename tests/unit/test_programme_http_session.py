"""TLS policy and HTTP/CSRF boundary feedback, without a native service or database."""

import io
import ssl
import urllib.error
from http.cookiejar import Cookie
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs

import pytest

from tests.rehearsals import programme_http_session as http
from tests.rehearsals import programme_https as https
from tests.rehearsals.programme_runtime_environment import (
    ProgrammeRehearsalEnvironmentError,
)


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    guard = Mock(return_value=SimpleNamespace(run_id="a" * 32, lease_seconds=600))
    monkeypatch.setattr(http, "require_programme_rehearsal_request", guard)
    monkeypatch.setattr(https, "require_programme_rehearsal_request", guard)
    monkeypatch.setattr(https.time, "monotonic", lambda: 100.0)
    fingerprint = https.create_loopback_certificate(tmp_path, deadline=400.0)
    return SimpleNamespace(
        deadline=400.0,
        url="https://127.0.0.1:50412/",
        material=SimpleNamespace(web_port=50412),
        certificate_path=tmp_path / "certificate.pem",
        certificate_sha256=fingerprint,
    )


class Response(io.BytesIO):
    def __init__(self, content=b"safe", status=200, **headers):
        super().__init__(content)
        self.code = status
        self.headers = headers


def _cookie(name, value, *, secure=True, rest=None):
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain="127.0.0.1",
        domain_specified=False,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=secure,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest=rest or {},
    )


def _session(fixture):
    session = http.ProgrammeHttpSession(fixture)
    session.opener = Mock()
    return session


def test_real_leaf_context_and_no_proxy_or_redirect_policy(fixture, monkeypatch):
    build = Mock()
    monkeypatch.setattr(http.urllib.request, "build_opener", build)
    http.ProgrammeHttpSession(fixture)
    proxy, tls, cookies, redirects = build.call_args.args
    assert proxy.proxies == {}
    assert tls._context.verify_mode == ssl.CERT_REQUIRED
    assert tls._context.check_hostname
    assert tls._context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert len(tls._context.get_ca_certs(binary_form=True)) == 0  # leaf, not a CA
    assert isinstance(cookies.cookiejar, http.http.cookiejar.CookieJar)
    assert (
        redirects.redirect_request(
            None, None, 302, None, None, "https://elsewhere.invalid"
        )
        is None
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:50412/",
        "https://localhost:50412/",
        "https://127.0.0.1:50413/",
        "https://user@127.0.0.1:50412/",
        "https://127.0.0.1:50412/path",
        "https://127.0.0.1:50412/?token=private",
        "https://127.0.0.1:50412/#fragment",
    ],
)
def test_foreign_or_ambiguous_origin_is_refused_before_certificate(fixture, url):
    fixture.url = url
    fixture.certificate_path = Mock()
    with pytest.raises(http.ProgrammeHttpsError, match="origin_invalid"):
        http.ProgrammeHttpSession(fixture)
    fixture.certificate_path.read_text.assert_not_called()


def test_certificate_fingerprint_change_is_refused(fixture):
    fixture.certificate_sha256 = "0" * 64
    with pytest.raises(http.ProgrammeHttpsError, match="certificate_invalid"):
        http.ProgrammeHttpSession(fixture)


def test_deferral_precedes_fixture_access(monkeypatch):
    monkeypatch.setattr(
        http,
        "require_programme_rehearsal_request",
        Mock(side_effect=ProgrammeRehearsalEnvironmentError("deferred")),
    )
    with pytest.raises(ProgrammeRehearsalEnvironmentError, match="deferred"):
        http.ProgrammeHttpSession(None)


@pytest.mark.parametrize(
    "path",
    [
        "https://elsewhere.invalid/",
        "//elsewhere.invalid/",
        "relative",
        "/path#fragment",
        "/\\elsewhere.invalid",
        "/path\nInjected: secret",
    ],
)
def test_request_never_leaves_fixed_origin(fixture, path):
    session = _session(fixture)
    with pytest.raises(http.ProgrammeHttpsError, match="path_invalid"):
        session.request(path)
    session.opener.open.assert_not_called()


def test_no_domain_mutation_transport_and_expired_lease(fixture):
    session = _session(fixture)
    with pytest.raises(http.ProgrammeHttpsError, match="path_invalid"):
        session.request("/admin/programme/change/", form={"action": "publish"})
    session.deadline = 99.0
    with pytest.raises(http.ProgrammeHttpsError, match="lease_expired"):
        session.request("/programme/")
    session.opener.open.assert_not_called()


@pytest.mark.parametrize("status", [200, 302, 400, 404, 503])
def test_bounded_response_and_http_failure_not_automatic_redirect(fixture, status):
    session = _session(fixture)
    response = Response(
        b"private payload", status, Location="https://elsewhere.invalid"
    )
    if status == 200:
        session.opener.open.return_value = response
    else:
        session.opener.open.side_effect = urllib.error.HTTPError(
            session.origin,
            status,
            "private",
            response.headers,
            response,
        )
    result = session.request("/programme/")
    assert result.status == status
    assert result.body == b"private payload"
    assert "private" not in repr(result)
    assert "elsewhere" not in repr(result)
    assert response.closed
    assert session.opener.open.call_count == 1
    assert session.opener.open.call_args.kwargs == {"timeout": 15}


@pytest.mark.parametrize("fault", ["oversize", "compression", "io", "lease"])
def test_response_failure_discloses_no_payload(fixture, fault):
    session = _session(fixture)
    response = Response(b"private")
    session.opener.open.return_value = response
    if fault == "oversize":
        response = Response(b"x" * (http.MAX_RESPONSE_BYTES + 1))
        session.opener.open.return_value = response
    elif fault == "compression":
        response.headers["Content-Encoding"] = "gzip"
    elif fault == "io":
        session.opener.open.side_effect = urllib.error.URLError("private")
    else:

        def expire(*args, **kwargs):
            session.deadline = 99.0
            return response

        session.opener.open.side_effect = expire
    with pytest.raises(http.ProgrammeHttpsError) as caught:
        session.request("/programme/")
    assert "private" not in str(caught.value)
    if fault != "io":
        assert response.closed


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "no_csrf",
        "duplicate",
        "foreign_form",
        "bad_token",
        "failed_login",
        "redirect",
        "insecure",
        "httponly",
    ],
)
def test_actual_form_submission_and_cookie_policy(fixture, fault):
    session = _session(fixture)
    token = "a" * 64
    form = (
        f'<form method="post"><input name="csrfmiddlewaretoken" value="{token}"></form>'
    )
    if fault == "no_csrf":
        form = "<form></form>"
    elif fault == "duplicate":
        form *= 2
    elif fault == "foreign_form":
        form = form.replace(
            'method="post"', 'method="post" action="https://elsewhere.invalid"'
        )
    elif fault == "bad_token":
        form = form.replace(token, "bad")
    response = Response(form.encode())
    person = SimpleNamespace(
        email="person@example.invalid", password="private-password"
    )
    destination = "/my/example/timetable/"

    def submit(request, **kwargs):
        if request.data is None:
            return response
        assert request.full_url == session.origin + "/accounts/login/"
        assert request.headers["Origin"] == session.origin
        assert request.headers["Referer"] == session.origin + "/accounts/login/"
        assert parse_qs(request.data.decode()) == {
            "username": [person.email],
            "password": [person.password],
            "csrfmiddlewaretoken": [token],
            "next": [destination],
        }
        session.cookies.set_cookie(
            _cookie(
                "sessionid",
                "secret",
                secure=fault != "insecure",
                rest={} if fault == "httponly" else {"HttpOnly": None},
            )
        )
        return Response(
            status=200 if fault == "failed_login" else 302,
            Location="https://elsewhere.invalid"
            if fault == "redirect"
            else destination,
        )

    session.opener.open.side_effect = submit
    if fault:
        with pytest.raises(http.ProgrammeHttpsError, match="login"):
            session.login(person, destination=destination)
    else:
        session.login(person, destination=destination)
    expected_requests = (
        1 if fault in {"no_csrf", "duplicate", "foreign_form", "bad_token"} else 2
    )
    assert session.opener.open.call_count == expected_requests


@pytest.mark.parametrize("failure", [False, True])
def test_logout_posts_csrf_and_always_forgets_private_cookies(fixture, failure):
    session = _session(fixture)
    session.cookies.set_cookie(_cookie("csrftoken", "a" * 32))
    session.cookies.set_cookie(_cookie("sessionid", "secret"))
    session.opener.open.return_value = Response(
        status=500 if failure else 302, Location="/accounts/login/"
    )
    if failure:
        with pytest.raises(http.ProgrammeHttpsError, match="logout_failed"):
            session.logout()
    else:
        session.logout()
    assert not list(session.cookies)
    request = session.opener.open.call_args.args[0]
    assert request.full_url.endswith("/accounts/logout/")
    assert parse_qs(request.data.decode()) == {"csrfmiddlewaretoken": ["a" * 32]}
