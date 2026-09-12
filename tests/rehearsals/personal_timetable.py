"""Opt-in synthetic private timetable browser fixture with a one-hour lease.

Run only with MARU_PERSONAL_OUTPUT_REHEARSAL=1 and isolated test PostgreSQL.
A passing fixture proves cleanup, not human, browser or production acceptance.
"""

import os
from dataclasses import replace
from threading import Event, Timer

import pytest
from django.contrib.auth import login, logout
from django.db import connection
from django.http import HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.template import Context, Template
from django.urls import clear_url_caches, include, path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from maru.identity.models import Account
from maru.scheduling import personal_output_views
from maru.scheduling.command_support import SchedulingUnavailableError
from tests.factories import AccountFactory
from tests.integration.test_scheduling_personal_outputs import (
    _accepted_independent_work,
    approve,
    arguments,
    preflight,
    publish,
    withdraw,
)
from tests.integration.test_scheduling_personal_outputs import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_personal_outputs import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_personal_outputs import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_personal_outputs import (
    personal_scope as personal_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_personal_outputs import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_personal_outputs import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_personal_outputs import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_personal_outputs import (
    world as world,  # noqa: PLC0414
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("MARU_PERSONAL_OUTPUT_REHEARSAL") != "1",
        reason="Explicit isolated personal output rehearsal only",
    ),
    pytest.mark.django_db(transaction=True),
]
urlpatterns = []

MENU = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synthetic personal timetable rehearsal</title></head><body><main>
<h1>Synthetic personal timetable rehearsal</h1>
<p>Loopback-only synthetic full-profile fixture. Real owner policy and commands;
only dormant host capabilities have test-only profile admission. This is not
Programme-only activation or human acceptance.</p>
<p><a href="{{ timetable }}">Open my hosting and work timetable</a></p>
<p>Release state: {{ status }}.</p>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf }}">
<button name="role" value="owner">Continue as synthetic host and volunteer</button>
<button name="role" value="other">Continue as another synthetic person</button>
<button name="role" value="anonymous">Sign out of the synthetic fixture</button>
<button name="control" value="source-off">Simulate unavailable source</button>
<button name="control" value="source-on">Restore source</button>
<button name="control" value="withdraw">Withdraw synthetic release</button>
<button name="control" value="finish">Finish and close fixture</button>
</form><p>Role changes apply only to isolated synthetic accounts. Withdrawal
uses the real Scheduling command. Work remains an independent retained record.</p>
</main></body></html>"""


def test_browser_fixture(personal_scope, monkeypatch, settings, live_server):
    """Hold real synthetic hosting/work while the private browser journey runs."""
    assert connection.settings_dict["NAME"].startswith("test_")
    assert settings.MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER
    assert settings.MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER
    assert live_server.thread.host in {"localhost", "127.0.0.1", "::1"}
    scope = personal_scope
    _accepted_independent_work(scope)
    scope.release_selection = replace(
        scope.release_selection, source_snapshot_digest=preflight(scope).snapshot_digest
    )
    released = publish(scope, approve(scope))
    inputs = arguments(scope)
    owner = Account.objects.get(id=inputs["actor_id"])
    accounts = {
        "owner": owner,
        "other": AccountFactory(email_verified_at=owner.email_verified_at),
    }
    finished = Event()
    state = {"source": True, "withdrawn": False}
    source_query = personal_output_views.load_personal_timetable

    def source(**kwargs):
        if not state["source"]:
            raise SchedulingUnavailableError
        return source_query(**kwargs)

    monkeypatch.setattr(personal_output_views, "load_personal_timetable", source)
    timetable = f"/my/{inputs['organization_id']}/{inputs['edition_id']}/timetable/"

    @never_cache
    @csrf_protect
    @require_http_methods(["GET", "POST"])
    def menu(request):
        if request.method == "POST":
            role = request.POST.get("role")
            if role in accounts:
                login(
                    request, accounts[role], backend=settings.AUTHENTICATION_BACKENDS[0]
                )
                return HttpResponseRedirect(timetable)
            if role == "anonymous":
                logout(request)
                return HttpResponseRedirect(timetable)
            control = request.POST.get("control")
            if control == "finish":
                Timer(0.5, finished.set).start()
                return HttpResponse(
                    "Synthetic fixture closing; record evidence separately."
                )
            if control in {"source-on", "source-off"}:
                state["source"] = control == "source-on"
            elif control == "withdraw" and not state["withdrawn"]:
                withdraw(scope, released)
                state["withdrawn"] = True
            else:
                return HttpResponse(status=400)
            return HttpResponseRedirect("/rehearsal/")
        return HttpResponse(
            Template(MENU).render(
                Context(
                    {
                        "csrf": get_token(request),
                        "status": "Withdrawn" if state["withdrawn"] else "Released",
                        "timetable": timetable,
                    }
                )
            )
        )

    monkeypatch.setattr(
        __import__(__name__, fromlist=["urlpatterns"]),
        "urlpatterns",
        [
            path("rehearsal/", menu),
            path("", include("tests.support.programme_output_urls")),
        ],
    )
    settings.ROOT_URLCONF = __name__
    clear_url_caches()
    print(f"\nREHEARSAL_READY {live_server.url}/rehearsal/", flush=True)  # noqa: T201
    assert finished.wait(3600), "Lease expired; browser acceptance is unproven"
    print("REHEARSAL_CLOSED: fixture cleanup only", flush=True)  # noqa: T201
