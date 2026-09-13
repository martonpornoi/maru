"""Fast private HTTP/template checks; native owner authority is integration-tested."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.events.personal_timetable_queries import PersonalTimetableEditionLabel
from maru.scheduling import personal_output_views as views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.release_queries import ProgrammeReleaseState as State
from tests.unit.test_personal_timetable_rendering import (
    personal as personal,  # noqa: PLC0414
)


def request_view(personal, query="", *, method="get", anonymous=False):
    request = getattr(RequestFactory(), method)("/my/synthetic/timetable/" + query)
    request.user = (
        AnonymousUser()
        if anonymous
        else SimpleNamespace(
            pk=personal.actor_id,
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    )
    request.correlation_id = str(uuid4())
    return views.personal_timetable(
        request,
        organization_id=personal.organization_id,
        edition_id=personal.edition_id,
    )


@pytest.fixture(autouse=True)
def shell():
    # Only shared shell discovery is stubbed; the real page/template is rendered.
    with (
        patch.object(views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access"
        ) as access,
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        access.return_value = {"workspace_available": False}
        yield


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
def test_fresh_private_formats_bind_authenticated_actor_and_disable_cache(
    personal, output_format
):
    with patch.object(views, "load_personal_timetable", return_value=personal) as load:
        response = request_view(personal, f"?format={output_format}")
    assert response.status_code == 200
    assert load.call_args.kwargs["actor_id"] == personal.actor_id
    assert load.call_args.kwargs["organization_id"] == personal.organization_id
    assert load.call_args.kwargs["edition_id"] == personal.edition_id
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    if output_format in {"html", "print"}:
        assert response.content.count(b"<h1>") == 1
        assert response.content.count(b"<main ") == 1
        assert b"Private host instructions" in response.content
        assert b"Private handover instructions" in response.content
        assert b"Approved required host presence" in response.content
        assert b"not additional assigned work" in response.content
        assert b"Current work instructions" in response.content
        assert b"2030-08-02 10:45+02:00" in response.content
    else:
        assert 'filename="my-hosting-and-work.' in response["Content-Disposition"]


@pytest.mark.parametrize(
    "query",
    ["?actor_id=other", "?format=json&format=html", "?format=bad", "?day=anything"],
)
def test_query_cannot_select_another_person_or_partial_source(personal, query):
    with patch.object(views, "load_personal_timetable") as load:
        response = request_view(personal, query)
    assert response.status_code == 400
    load.assert_not_called()
    assert b"actor_id=other" not in response.content


def test_anonymous_and_mutations_do_not_load_personal_sources(personal):
    with patch.object(views, "load_personal_timetable") as load:
        anonymous = request_view(personal, anonymous=True)
        mutation = request_view(personal, method="post")
    assert anonymous.status_code == 302
    assert mutation.status_code == 405
    load.assert_not_called()
    assert "no-store" in anonymous["Cache-Control"]


@pytest.mark.parametrize(
    ("error", "status"),
    [(SchedulingAuthorizationDeniedError, 404), (SchedulingUnavailableError, 503)],
)
def test_failures_never_serve_retained_or_partial_source_content(
    personal, error, status
):
    with patch.object(views, "load_personal_timetable", side_effect=error):
        response = request_view(personal)
    assert response.status_code == status
    assert b"Private host instructions" not in response.content
    assert str(personal.edition_id).encode() not in response.content
    assert "private" in response["Cache-Control"]


@pytest.mark.parametrize("state", [State.WITHDRAWN, State.INVALIDATED])
def test_unavailable_hosting_keeps_work_but_withholds_calendar(personal, state):
    reference = replace(personal.hosting.reference, state=state, presences=())
    if state == State.WITHDRAWN:
        reference = replace(reference, release_id=None, published_at=None)
    changed = replace(
        personal, hosting=replace(personal.hosting, reference=reference, rooms=())
    )
    with patch.object(views, "load_personal_timetable", return_value=changed):
        page = request_view(personal)
        calendar = request_view(personal, "?format=calendar")
    assert page.status_code == 200
    assert b"Private handover instructions" in page.content
    assert b"Main Stage" not in page.content
    assert b'href="?format=calendar"' not in page.content
    assert b"Hosting records without an approved time" in page.content
    assert calendar.status_code == 409
    assert calendar["Content-Type"].startswith("text/html")


def test_closed_validation_and_html_escaping_precede_rendering(personal):
    hostile = "<script>synthetic()</script>"
    shift = personal.shifts[0]
    changed = replace(
        personal,
        shifts=(
            replace(shift, instructions=replace(shift.instructions, title=hostile)),
        ),
    )
    with patch.object(views, "load_personal_timetable", return_value=changed):
        response = request_view(personal)
    assert hostile.encode() not in response.content
    assert b"&lt;script&gt;" in response.content
    with patch.object(
        views,
        "load_personal_timetable",
        return_value=replace(personal, shifts=(object(),)),
    ):
        invalid = request_view(personal)
    assert invalid.status_code == 503


def test_print_has_complete_source_and_no_download_controls(personal):
    with patch.object(views, "load_personal_timetable", return_value=personal):
        response = request_view(personal, "?format=print")
    assert b"personal-print-source" in response.content
    assert str(personal.hosting.reference.release_id).encode() in response.content
    assert str(personal.shifts[0].commitment_id).encode() in response.content
    assert (
        str(personal.hosting.reference.presences[0].placement_id).encode()
        in response.content
    )
    assert b"Complete private timetable copies" not in response.content
    assert b"Private handover instructions" in response.content


def test_personal_component_is_not_a_production_route(personal):
    with pytest.raises(Resolver404):
        resolve(f"/my/{personal.organization_id}/{personal.edition_id}/timetable/")


def test_private_page_preserves_empty_adopted_and_unadopted_work_meaning(personal):
    with patch.object(
        views, "load_personal_timetable", return_value=replace(personal, shifts=None)
    ):
        unadopted = request_view(personal)
    with patch.object(
        views, "load_personal_timetable", return_value=replace(personal, shifts=())
    ):
        empty = request_view(personal)
    assert b"Not adopted for this edition" in unadopted.content
    assert b"No retained work records" not in unadopted.content
    assert b"No retained work records" in empty.content


def test_edition_context_is_escaped_on_personal_page(personal):
    changed = replace(
        personal, edition_label=PersonalTimetableEditionLabel("<b>Con</b>", 2)
    )
    with patch.object(views, "load_personal_timetable", return_value=changed):
        response = request_view(personal)
    assert b"<b>Con</b>" not in response.content
    assert b"&lt;b&gt;Con&lt;/b&gt;" in response.content
