"""Opt-in synthetic browser fixture, not a production route or runtime proof.

Run this file explicitly through pytest with MARU_EDITOR_REHEARSAL=1 and an
isolated test PostgreSQL URL. It is intentionally outside normal test discovery.
The lease ends through the visible Finish button or after one hour. A passing
fixture only confirms cleanup; browser acceptance must be recorded separately.
"""

import os
from dataclasses import replace
from functools import partial
from pathlib import Path
from threading import Event, Timer
from uuid import uuid4

import pytest
from django.contrib.auth import login, logout
from django.db import connection
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.template import Context, Template
from django.urls import clear_url_caches, include, path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from maru.authorization.policy import PolicyDecision
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.programme import queries as programme_queries
from maru.programme import scheduling_queries as programme_source
from maru.programme.queries import ProgrammeQueryUnavailableError
from maru.scheduling import evaluation_sources, planning_workspace
from maru.scheduling.candidate_commands import create_scheduling_candidate
from maru.scheduling.inputs import SchedulingOccurrenceInput
from maru.scheduling.occurrence_commands import create_scheduling_occurrence
from maru.scheduling.planning_queries import load_scheduling_planning
from maru.scheduling.planning_views import scheduling_planning_view
from tests.factories import AccountFactory, CapabilityGrantFactory
from tests.integration.test_programme_commands import _TrustedProgrammeAuthorizer
from tests.integration.test_scheduling_candidates import INSPECTOR_LOADERS, read_request
from tests.integration.test_scheduling_candidates import (
    host_inspection_admitted as host_inspection_admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_candidates import (
    native_http_world as native_http_world,  # noqa: PLC0414
)
from tests.integration.test_scheduling_candidates import (
    planning_world as planning_world,  # noqa: PLC0414
)
from tests.integration.test_scheduling_placements import next_request, place
from tests.integration.test_scheduling_reservations import admit_reservations

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("MARU_EDITOR_REHEARSAL") != "1",
        reason="Explicit isolated synthetic browser rehearsal only",
    ),
    pytest.mark.django_db(transaction=True),
]
urlpatterns = []
REHEARSAL_DIRECTORY = Path(__file__).resolve().parent
AXE_ASSET = (
    REHEARSAL_DIRECTORY.parent.parent
    / "frontends/staff-console/node_modules/axe-core/axe.min.js"
)

ACCESSIBILITY_CONTROLS = b"""
<aside id="rehearsal-accessibility" aria-label="Synthetic fixture diagnostics">
<h2>Synthetic fixture diagnostics</h2>
<p>Checks this rendered component only, not runtime or screen-reader acceptance.</p>
<button type="button" id="rehearsal-run-axe">Run automated accessibility check</button>
<p id="rehearsal-axe-status" role="status"></p>
<pre id="rehearsal-axe-results"
style="white-space:pre-wrap;overflow-wrap:anywhere"></pre>
</aside><script src="/rehearsal/axe.js" defer></script>
<script src="/rehearsal/accessibility.js" defer></script>
"""


def with_accessibility_controls(response):
    if hasattr(response, "render"):
        response.render()
    response.content = response.content.replace(
        b"</body>", ACCESSIBILITY_CONTROLS + b"</body>", 1
    )
    return response


@never_cache
@require_http_methods(["GET"])
def accessibility_asset(_request, *, asset):
    return FileResponse(asset.open("rb"), content_type="text/javascript")


MENU = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/static/core/brand/favicon.ico">
<title>Synthetic Programme editor rehearsal</title></head><body><main>
<h1>Synthetic Programme editor rehearsal</h1>
<p>Test-policy and database-owner component fixture. Not runtime/profile,
password-login, screen-reader or production acceptance. Loopback only.</p>
<p>Each role button sets an ordinary session for a pre-created synthetic account.
No account, grant or real identity is created by the browser button.</p>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf }}">
{% for role in roles %}
<button name="role" value="{{ role }}">Use {{ role }} role</button>{% endfor %}
<button name="role" value="anonymous">Use anonymous role</button></form>
<p><a href="editor/">Open editor</a> ·
<a href="current-profile/">Check current-profile denial</a></p>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf }}">
<button name="control" value="stale">Create concurrent private draft</button>
<button name="control" value="source-off">Simulate unavailable title source</button>
<button name="control" value="source-on">Restore title source</button>
<button name="control" value="finish">Finish and close synthetic fixture</button></form>
<p>Fault controls are fixture setup, not application permissions or user actions.
The stale control advances the shared edition control, not an existing draft.</p>
</main></body></html>"""


class RehearsalSchedulingPolicy:
    def __init__(self, accounts):
        self.accounts = accounts

    def authorize(self, **kwargs):
        actor = kwargs["principal_id"]
        capability = kwargs["capability_code"]
        role = next(
            (name for name, account in self.accounts.items() if account.id == actor),
            None,
        )
        allowed = role in {"planner", "restricted_layer"}
        if role == "view_only":
            allowed = capability.startswith("scheduling.view_")
        elif role == "manage_only":
            allowed = capability.startswith("scheduling.manage_")
        return PolicyDecision(
            allowed=allowed,
            fields=kwargs["requested_fields"] or frozenset(),
            obligations=frozenset({"audit", "reason"}),
            reason_code="sealed_future_profile_harness",
        )


class RehearsalProgrammePolicy(_TrustedProgrammeAuthorizer):
    def __init__(self, restricted_actor):
        super().__init__()
        self.restricted_actor = restricted_actor

    def authorize(self, **kwargs):
        decision = super().authorize(**kwargs)
        if (
            kwargs["principal_id"] == self.restricted_actor
            and kwargs["capability_code"] == "programme.view_delivery"
        ):
            return replace(decision, allowed=False, fields=frozenset())
        return decision


def seed_repeated_occurrence(world):
    placed = place(world)
    snapshot = load_scheduling_planning(read_request(world), authorizer=world.policy)
    create_scheduling_occurrence(
        next_request(world),
        occurrence=SchedulingOccurrenceInput(snapshot.occurrences[0].item_id),
        expected_control_version=placed.control_version,
        authorizer=world.policy,
    )


def test_browser_fixture(
    native_http_world, host_inspection_admitted, monkeypatch, settings, live_server
):
    """Hold one explicitly requested, sealed synthetic fixture for browser work."""
    assert connection.settings_dict["NAME"].startswith("test_")
    assert settings.MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER
    assert settings.MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER
    assert live_server.thread.host in {"localhost", "127.0.0.1", "::1"}
    world = native_http_world
    edition = EventEdition.objects.get(id=world.request.edition_id)
    planner = Account.objects.get(id=world.request.actor_id)
    accounts = {"planner": planner}
    for role in ("view_only", "manage_only", "restricted_layer"):
        account = AccountFactory(display_name=f"Synthetic {role}")
        accounts[role] = account
        CapabilityGrantFactory(
            principal=account,
            organization=edition.organization,
            edition=edition,
            capability_code="venues.view_workspace",
        )
    policy = RehearsalSchedulingPolicy(accounts)
    owner_policy = RehearsalProgrammePolicy(accounts["restricted_layer"].id)
    admit_reservations(world, monkeypatch)
    monkeypatch.setattr(
        evaluation_sources, "profile_allows_conflict_source", lambda *_args: True
    )
    monkeypatch.setattr(
        evaluation_sources,
        "load_programme_scheduling_dependencies",
        partial(
            programme_source.load_programme_scheduling_dependencies,
            authorizer=owner_policy,
        ),
    )
    for module, name in INSPECTOR_LOADERS.values():
        monkeypatch.setattr(
            module, name, partial(getattr(module, name), authorizer=owner_policy)
        )
    source_state = {"available": True}

    def titles(**kwargs):
        if not source_state["available"]:
            raise ProgrammeQueryUnavailableError
        return programme_queries.list_programme_timetable_items(
            **kwargs, authorizer=owner_policy
        )

    monkeypatch.setattr(planning_workspace, "list_programme_timetable_items", titles)
    seed_repeated_occurrence(world)
    finished = Event()

    @never_cache
    @csrf_protect
    @require_http_methods(["GET", "POST"])
    def menu(request):
        if request.method == "POST":
            role = request.POST.get("role")
            if role in accounts:
                login(
                    request,
                    accounts[role],
                    backend=settings.AUTHENTICATION_BACKENDS[0],
                )
                return HttpResponseRedirect("editor/")
            if role == "anonymous":
                logout(request)
                return HttpResponseRedirect("editor/")
            control = request.POST.get("control")
            if control == "finish":
                Timer(0.5, finished.set).start()
                return HttpResponse(
                    "Synthetic fixture is closing; record browser evidence separately."
                )
            if control in {"source-on", "source-off"}:
                source_state["available"] = control == "source-on"
            elif control == "stale":
                current = load_scheduling_planning(
                    read_request(world), authorizer=world.policy
                )
                create_scheduling_candidate(
                    next_request(world),
                    label=f"Concurrent alternative {uuid4().hex[:8]}",
                    expected_control_version=current.control_version,
                    authorizer=world.policy,
                )
            else:
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
                organization_id=edition.organization_id,
                edition_id=edition.id,
                edition_label="Synthetic MaruCon — component rehearsal",
                **({} if current_profile else {"authorizer": policy}),
            )
        )

    patterns = [
        path("rehearsal/", menu),
        path("rehearsal/axe.js", partial(accessibility_asset, asset=AXE_ASSET)),
        path(
            "rehearsal/accessibility.js",
            partial(
                accessibility_asset,
                asset=REHEARSAL_DIRECTORY / "programme_accessibility.js",
            ),
        ),
        path("rehearsal/editor/", editor),
        path("rehearsal/current-profile/", partial(editor, current_profile=True)),
        path("", include("maru.urls")),
    ]
    monkeypatch.setattr(
        __import__(__name__, fromlist=["urlpatterns"]), "urlpatterns", patterns
    )
    settings.ROOT_URLCONF = __name__
    clear_url_caches()
    print(f"\nREHEARSAL_READY {live_server.url}/rehearsal/", flush=True)  # noqa: T201
    assert finished.wait(3600), (
        "Synthetic fixture lease expired; browser acceptance is unproven"
    )
    print(  # noqa: T201 - explicit synthetic fixture lifecycle output
        "REHEARSAL_CLOSED: fixture cleanup only, not automatic browser acceptance",
        flush=True,
    )
