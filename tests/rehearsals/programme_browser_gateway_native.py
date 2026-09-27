"""Host-only bridge checks using real authentication and native runtime roles."""

import http.cookiejar
import urllib.error
import urllib.request
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from tests.rehearsals.programme_browser_gateway import OPT_IN, local_programme_browser
from tests.rehearsals.programme_http_session import _LoginForm
from tests.rehearsals.programme_runner import isolated_programme_application
from tests.rehearsals.programme_runtime_environment import (
    require_programme_rehearsal_request,
)

require_programme_rehearsal_request()
pytestmark = pytest.mark.integration


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _file, _code, _message, _headers, _url):
        return None


def _request(opener, origin, path, *, form=None, extra=None):
    headers = {"Origin": origin, "Referer": origin + path}
    headers.update(extra or {})
    request = urllib.request.Request(  # noqa: S310 - owned literal loopback fixture
        origin + path,
        headers=headers,
        data=None if form is None else urlencode(form).encode(),
    )
    try:
        response = opener.open(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read(2_097_153)


def test_native_local_login_logout_csrf_account_switch_and_denials(monkeypatch):
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv(OPT_IN, "synthetic-loopback-only")
    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(cookies),
        _NoRedirect(),
    )
    with (
        isolated_programme_application(
            setup_mode="new_foundation", with_isolation=True
        ) as fixture,
        local_programme_browser(fixture) as browser,
    ):
        origin = browser.url
        assert origin.startswith("http://127.0.0.1:")
        assert fixture.url.startswith("https://127.0.0.1:")
        assert _request(opener, origin, "/health/ready")[0] == 200
        assert _request(opener, origin, "/admin/")[0] == 302
        assert (
            _request(
                opener, origin, "/health/ready", extra={"Host": "foreign.invalid"}
            )[0]
            == 503
        )
        assert (
            _request(
                opener,
                origin,
                "/accounts/login/",
                form={},
                extra={"Origin": "https://foreign.invalid"},
            )[0]
            == 503
        )
        assert _request(opener, origin, "/accounts/login/", form={})[0] == 403
        previous_session = None
        for person in fixture.scenario.controllers:
            status, _, page = _request(opener, origin, "/accounts/login/")
            assert status == 200
            login = _LoginForm()
            login.feed(page.decode())
            assert len(login.tokens) == 1
            status, response, _ = _request(
                opener,
                origin,
                "/accounts/login/",
                form={
                    "username": person.email,
                    "password": person.password,
                    "csrfmiddlewaretoken": login.tokens[0],
                    "next": "/admin/",
                },
            )
            assert status == 302
            assert response["Location"] == "/admin/"
            sessions = [
                cookie for cookie in cookies if cookie.name.endswith("_sessionid")
            ]
            assert len(sessions) == 1
            assert not sessions[0].secure
            assert sessions[0].has_nonstandard_attr("HttpOnly")
            assert sessions[0].value != previous_session
            previous_session = sessions[0].value
            assert _request(opener, origin, "/admin/")[0] == 200
            csrf = next(
                cookie.value for cookie in cookies if cookie.name.endswith("_csrftoken")
            )
            status, response, _ = _request(
                opener,
                origin,
                "/admin/context/edition/",
                form={
                    "csrfmiddlewaretoken": csrf,
                    "edition_id": str(fixture.scenario.edition_id),
                    "next": "/admin/",
                },
            )
            assert status == 302
            assert response["Location"] == "/admin/"
            assert any(cookie.name.endswith("_messages") for cookie in cookies)
            status, _, page = _request(opener, origin, "/admin/")
            assert status == 200
            assert b"Convention workspace changed to" in page
            assert b"Synthetic Programme rehearsal" in page
            assert not any(cookie.name.endswith("_messages") for cookie in cookies)
            assert (
                b"Convention workspace changed to"
                not in _request(opener, origin, "/admin/")[2]
            )
            assert (
                _request(
                    opener,
                    origin,
                    "/accounts/logout/",
                    form={"csrfmiddlewaretoken": csrf},
                )[0]
                == 302
            )
            assert _request(opener, origin, "/admin/")[0] == 302
            assert not [
                cookie for cookie in cookies if cookie.name.endswith("_sessionid")
            ]
        fixture.verify_excluded_state()


def test_native_planning_fixture_preflights_independently_admitted_host_editor(
    monkeypatch,
):
    """Exercise the real editor prerequisite, not a substituted roster authorizer."""
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_RUN_ID", uuid4().hex)
    monkeypatch.setenv("MARU_PROGRAMME_REHEARSAL_LEASE_SECONDS", "3600")
    with isolated_programme_application(
        setup_mode="new_foundation", with_scanner=True, with_isolation=True
    ) as fixture:
        proposal = fixture.prepare_proposal()
        reviewed = fixture.prepare_review(proposal)
        items = fixture.prepare_items(proposal, reviewed)
        # Preparation must independently approve hosting and read every editor
        # roster as the actual planner before returning the strict handoff.
        planning = fixture.prepare_planning(proposal, reviewed, items)
        assert len(planning.role_assignment_ids) == 8
        assert len(set(planning.role_assignment_ids)) == 8
        assert len(planning.occurrence_ids) == 3
        assert planning.candidate_version == 3
        fixture.verify_excluded_state()
