"""Opt-in loopback staffing browser lease; not profile or runtime acceptance.

Run explicitly with MARU_STAFFING_REHEARSAL=1 and an isolated test database.
The visible Finish button closes the lease; passing only proves fixture cleanup.
"""

import os
from dataclasses import replace
from functools import partial
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

from maru.scheduling.planning_views import scheduling_planning_view
from tests.factories import CapabilityGrantFactory
from tests.integration.test_programme_staffing_selection import (
    selection as selection,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import world as world  # noqa: PLC0414
from tests.integration.test_scheduling_staffing_http import (
    staffing_http_world as staffing_http_world,  # noqa: PLC0414
)
from tests.integration.test_workforce_programme_binding import (
    binding_world as binding_world,  # noqa: PLC0414
)
from tests.rehearsals.programme_timetable import (
    AXE_ASSET,
    REHEARSAL_DIRECTORY,
    RehearsalSchedulingPolicy,
    accessibility_asset,
    create_rehearsal_accounts,
    with_accessibility_controls,
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("MARU_STAFFING_REHEARSAL") != "1",
        reason="Explicit isolated synthetic staffing browser rehearsal only",
    ),
    pytest.mark.django_db(transaction=True),
]
urlpatterns = []
MENU = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/static/core/brand/favicon.ico">
<title>Synthetic Programme staffing rehearsal</title></head><body><main>
<h1>Synthetic Programme staffing rehearsal</h1>
<p>Loopback-only component fixture with sealed future policies and synthetic data.
Not profile, runtime, password-login or production acceptance.</p>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf }}">
{% for role in roles %}
<button name="role" value="{{ role }}">Use {{ role }} role</button>{% endfor %}
<button name="role" value="anonymous">Use anonymous role</button></form>
<p><a href="editor/">Open staffing editor</a> ·
<a href="current-profile/">Check current-profile denial</a></p>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf }}">
<button name="control" value="finish">Finish and close synthetic fixture</button></form>
</main></body></html>"""


def test_browser_fixture(staffing_http_world, monkeypatch, settings, live_server):
    """Serve native owner-backed forms under a finite, explicitly opted-in lease."""
    assert connection.settings_dict["NAME"].startswith("test_")
    assert settings.MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER
    assert settings.MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER
    assert live_server.thread.host in {"localhost", "127.0.0.1", "::1"}
    scope = staffing_http_world
    accounts = create_rehearsal_accounts(scope.edition, scope.actor)
    for role in ("view_only", "manage_only", "restricted_layer"):
        codes = ("workforce.view_structure",)
        if role == "view_only":
            codes += ("workforce.view_shifts",)
        for code in codes:
            CapabilityGrantFactory(
                principal=accounts[role],
                organization=scope.edition.organization,
                edition=scope.edition,
                capability_code=code,
            )
    original = scope.selection.policy.authorize

    def programme_policy(**kwargs):
        decision = original(**kwargs)
        if kwargs["principal_id"] == accounts["view_only"].id and kwargs[
            "capability_code"
        ].startswith("programme.manage_"):
            return replace(decision, allowed=False)
        return decision

    monkeypatch.setattr(scope.selection.policy, "authorize", programme_policy)
    policy = RehearsalSchedulingPolicy(accounts)
    finished = Event()

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
                return HttpResponseRedirect("editor/")
            if role == "anonymous":
                logout(request)
                return HttpResponseRedirect("editor/")
            if request.POST.get("control") == "finish":
                Timer(0.5, finished.set).start()
                return HttpResponse(
                    "Synthetic fixture closing; record evidence separately."
                )
            return HttpResponse(status=400)
        return HttpResponse(
            Template(MENU).render(
                Context({"csrf": get_token(request), "roles": accounts})
            )
        )

    def editor(request, *, current_profile=False):
        return with_accessibility_controls(
            scheduling_planning_view(
                request,
                organization_id=scope.edition.organization_id,
                edition_id=scope.edition.id,
                edition_label="Synthetic MaruCon — staffing component rehearsal",
                **({} if current_profile else {"authorizer": policy}),
            )
        )

    monkeypatch.setattr(
        __import__(__name__, fromlist=["urlpatterns"]),
        "urlpatterns",
        [
            path("rehearsal/", menu),
            path("rehearsal/editor/", editor),
            path("rehearsal/current-profile/", partial(editor, current_profile=True)),
            path("rehearsal/axe.js", partial(accessibility_asset, asset=AXE_ASSET)),
            path(
                "rehearsal/accessibility.js",
                partial(
                    accessibility_asset,
                    asset=REHEARSAL_DIRECTORY / "programme_accessibility.js",
                ),
            ),
            path("", include("maru.urls")),
        ],
    )
    settings.ROOT_URLCONF = __name__
    clear_url_caches()
    print(f"\nREHEARSAL_READY {live_server.url}/rehearsal/", flush=True)  # noqa: T201
    assert finished.wait(3600), "Lease expired; browser acceptance is unproven"
    print("REHEARSAL_CLOSED: fixture cleanup only", flush=True)  # noqa: T201
