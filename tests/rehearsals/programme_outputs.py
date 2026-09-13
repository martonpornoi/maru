"""Opt-in synthetic released-output browser fixture, not production acceptance.

Run explicitly with MARU_OUTPUT_REHEARSAL=1 and isolated test PostgreSQL.
The visible Finish button ends its one-hour lease. A passing process proves
fixture cleanup only; browser/human acceptance must be recorded separately.
"""

import os
from dataclasses import replace
from threading import Event, Timer
from uuid import uuid4

import pytest
from django.db import connection
from django.http import HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.template import Context, Template
from django.urls import clear_url_caches, include, path
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from maru.programme.commands import approve_programme_public_rendition
from maru.programme.models import ProgrammeItem, ProgrammePublicRendition
from maru.scheduling import output_views, public_release_references
from maru.scheduling.command_support import SchedulingUnavailableError
from tests.integration.test_scheduling_public_outputs import (
    admitted as admitted,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    approve,
    end_copy,
    publish,
    scope_arguments,
    withdraw,
)
from tests.integration.test_scheduling_public_outputs import (
    assessed as assessed,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    capture_scope as capture_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    preflight_scope as preflight_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    release_scope as release_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    review_scope as review_scope,  # noqa: PLC0414
)
from tests.integration.test_scheduling_public_outputs import (
    world as world,  # noqa: PLC0414
)
from tests.integration.test_scheduling_release_preflight import load as preflight

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("MARU_OUTPUT_REHEARSAL") != "1",
        reason="Explicit isolated output rehearsal only",
    ),
    pytest.mark.django_db(transaction=True),
]
urlpatterns = []

MENU = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synthetic Programme output rehearsal</title></head><body><main>
<h1>Synthetic Programme output rehearsal</h1>
<p>Loopback, synthetic records and test-only profile admission. Not runtime,
human, screen-reader or production acceptance. No visitor account is needed.</p>
<p><a href="{{ timetable }}">Open public timetable</a></p>
<p>Fixture state: {{ status }}.</p>
<form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="{{ csrf }}">
<button name="control" value="publish">Approve and publish synthetic release</button>
<button name="control" value="source-off">Simulate unavailable source</button>
<button name="control" value="source-on">Restore source</button>
<button name="control" value="admission-off">Use current-profile denial</button>
<button name="control" value="admission-on">Restore synthetic public admission</button>
<button name="control" value="withdraw-copy">Withdraw exact reviewed copy</button>
<button name="control" value="withdraw-release">Withdraw release</button>
<button name="control" value="finish">Finish and close fixture</button>
</form><p>Publication and withdrawals use real owner commands with synthetic
independent principals. Failure/admission controls are fixture diagnostics,
not product permissions. Keep this fixture separate from any real data.</p>
</main></body></html>"""


def test_browser_fixture(review_scope, monkeypatch, settings, live_server):
    """Hold a sealed synthetic fixture while the public browser journey is checked."""
    assert connection.settings_dict["NAME"].startswith("test_")
    assert settings.MARU_ALLOW_SCHEDULING_TEST_AUTHORIZER
    assert settings.MARU_ALLOW_PROGRAMME_TEST_AUTHORIZER
    assert live_server.thread.host in {"localhost", "127.0.0.1", "::1"}
    scope = review_scope
    item = ProgrammeItem.objects.get(id=scope.selection.item_id)
    prior_copy = ProgrammePublicRendition.objects.filter(item=item).latest(
        "rendition_number"
    )
    reviewed = approve_programme_public_rendition(
        **(scope.common | {"actor_id": prior_copy.reviewed_by_id}),
        item_id=item.id,
        source_working_revision_id=prior_copy.source_working_revision_id,
        public_title=(
            "Opening ceremony — a welcoming start for visitors, hosts and volunteers"
        ),
        public_summary=(
            "A synthetic programme introduction with time for questions. " * 8
            + "Literal text, not markup: <script>synthetic</script>."
        ),
        public_content_note=(
            "Flashing-light demonstration is described, not "
            "performed, in this synthetic session."
        ),
        expected_version=item.aggregate_version,
        idempotency_key=uuid4(),
        correlation_id=uuid4(),
        authorizer=scope.policy,
    )
    scope.release_selection = replace(
        scope.release_selection, source_snapshot_digest=preflight(scope).snapshot_digest
    )
    state = {
        "admitted": True,
        "source": True,
        "release": None,
        "status": "No release published",
    }
    finished = Event()
    monkeypatch.setattr(
        public_release_references,
        "profile_allows_adapter",
        lambda *_args: state["admitted"],
    )
    source_query = output_views.load_public_programme_timetable

    def source(**kwargs):
        if not state["source"]:
            raise SchedulingUnavailableError
        return source_query(**kwargs)

    monkeypatch.setattr(output_views, "load_public_programme_timetable", source)
    timetable = (
        f"/programme/{scope.request.organization_id}/"
        f"{scope.request.edition_id}/timetable/"
    )

    @never_cache
    @csrf_protect
    @require_http_methods(["GET", "POST"])
    def menu(request):
        if request.method == "POST":
            control = request.POST.get("control")
            if control == "finish":
                Timer(0.5, finished.set).start()
                return HttpResponse(
                    "Synthetic fixture closing; record browser evidence separately."
                )
            if control == "publish" and state["release"] is None:
                state["release"] = publish(scope, approve(scope))
                state["status"] = "Released"
            elif control == "withdraw-copy" and state["release"] is not None:
                end_copy(scope, reviewed.result_object_id)
                state["status"] = "Exact copy withdrawn; release invalidated"
            elif control == "withdraw-release" and state["release"] is not None:
                withdraw(scope, state["release"])
                state["status"] = "Release withdrawn"
            elif control in {"source-off", "source-on"}:
                state["source"] = control == "source-on"
            elif control in {"admission-off", "admission-on"}:
                state["admitted"] = control == "admission-on"
            else:
                return HttpResponse(status=400)
            return HttpResponseRedirect("/rehearsal/")
        return HttpResponse(
            Template(MENU).render(
                Context(
                    {
                        "csrf": get_token(request),
                        "status": state["status"],
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
            path("", include("maru.scheduling.output_urls")),
        ],
    )
    settings.ROOT_URLCONF = __name__
    clear_url_caches()
    assert source_query(**scope_arguments(scope)).entries == ()
    print(f"\nREHEARSAL_READY {live_server.url}/rehearsal/", flush=True)  # noqa: T201
    assert finished.wait(3600), "Lease expired; browser acceptance is unproven"
    print("REHEARSAL_CLOSED: fixture cleanup only", flush=True)  # noqa: T201
