"""Opt-in synthetic operator run-sheet rehearsal with a one-hour lease.

Use MARU_OPERATOR_REHEARSAL=1 with isolated test PostgreSQL only. The Finish
button proves fixture cleanup, never browser, human or production acceptance.
"""

import os
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
from maru.scheduling import operator_output_views
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_scope import OPERATOR_CAPABILITIES, OperatorScopeKind
from maru.workforce import operator_links
from tests.factories import AccountFactory
from tests.integration.test_programme_operator_outputs import (
    _ready_with_retained_work,
    approve,
    operator_request,
    publish,
    withdraw,
)
from tests.integration.test_programme_operator_outputs import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_programme_operator_outputs import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_programme_operator_outputs import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_programme_operator_outputs import (
    operator_world as operator_world,  # noqa: PLC0414
)
from tests.integration.test_programme_operator_outputs import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_programme_operator_outputs import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_programme_operator_outputs import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_programme_operator_outputs import (
    world as world,  # noqa: PLC0414
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("MARU_OPERATOR_REHEARSAL") != "1",
        reason="Explicit isolated operator rehearsal only",
    ),
    pytest.mark.django_db(transaction=True),
]
urlpatterns = []
MENU = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synthetic operator rehearsal</title></head><body><main>
<h1>Synthetic operator rehearsal</h1>
<p>Loopback-only full-profile fixture, real owner commands and read policy with
test-only dormant admission. Not Programme-only activation or human acceptance.</p>
<p>Release state: {{ status }}.</p>
<ul>{% for label, url in links %}
<li><a href="{{ url }}">{{ label }}</a></li>{% endfor %}</ul>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf }}">
<button name="role" value="operator">Continue as full edition operator</button>
<button name="role" value="room">Continue as room-only basic operator</button>
<button name="role" value="other">Continue as ungranted person</button>
<button name="role" value="anonymous">Sign out</button>
<button name="control" value="publish">Approve and publish synthetic release</button>
<button name="control" value="withdraw">Withdraw synthetic release</button>
<button name="control" value="source-off">Simulate unavailable source</button>
<button name="control" value="source-on">Restore source</button>
<button name="control" value="finish">Finish and close fixture</button>
</form></main></body></html>"""


def test_browser_fixture(operator_world, monkeypatch, settings, live_server):
    """Hold independently granted operator purposes and retained synthetic work."""
    assert connection.settings_dict["NAME"].startswith("test_")
    assert settings.MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER
    assert settings.MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER
    assert live_server.thread.host in {"localhost", "127.0.0.1", "::1"}
    scope = operator_world
    work = _ready_with_retained_work(scope, monkeypatch)
    monkeypatch.setattr(operator_links, "profile_allows_adapter", lambda *_args: True)
    full = operator_request(scope, capabilities=tuple(sorted(OPERATOR_CAPABILITIES)))
    room = operator_request(scope, kind=OperatorScopeKind.ROOM)
    accounts = {
        "operator": Account.objects.get(id=full.actor_id),
        "room": Account.objects.get(id=room.actor_id),
        "other": AccountFactory(),
    }
    prefix = f"/admin/programme/run-sheets/{full.organization_id}/{full.edition_id}/"
    links = (
        ("Edition run sheet", f"{prefix}edition/{full.target_id}/"),
        ("Room run sheet", f"{prefix}room/{room.target_id}/"),
        (
            "Department with linked work, no room",
            f"{prefix}department/{work.position.department_id}/",
        ),
    )
    finished = Event()
    state = {"source": True, "release": None, "status": "No release published"}
    source_query = operator_output_views.load_operator_run_sheet

    def source(*args, **kwargs):
        if not state["source"]:
            raise SchedulingUnavailableError
        return source_query(*args, **kwargs)

    monkeypatch.setattr(operator_output_views, "load_operator_run_sheet", source)

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
                return HttpResponseRedirect("/rehearsal/")
            if role == "anonymous":
                logout(request)
                return HttpResponseRedirect("/rehearsal/")
            control = request.POST.get("control")
            if control == "finish":
                Timer(0.5, finished.set).start()
                return HttpResponse(
                    "Synthetic fixture closing; record evidence separately."
                )
            if control == "publish" and state["release"] is None:
                state["release"] = publish(scope, approve(scope))
                state["status"] = "Released"
            elif control == "withdraw" and state["status"] == "Released":
                withdraw(scope, state["release"])
                state["status"] = "Withdrawn"
            elif control in {"source-on", "source-off"}:
                state["source"] = control == "source-on"
            else:
                return HttpResponse(status=400)
            return HttpResponseRedirect("/rehearsal/")
        return HttpResponse(
            Template(MENU).render(
                Context(
                    {
                        "csrf": get_token(request),
                        "status": state["status"],
                        "links": links,
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
