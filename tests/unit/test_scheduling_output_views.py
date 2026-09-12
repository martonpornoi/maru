"""Fast rendered adapters; real public admission is covered by integration tests."""

from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.scheduling import output_views as views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.release_queries import ProgrammeReleaseState
from tests.unit.test_scheduling_output_rendering import (
    snapshot as snapshot,  # noqa: PLC0414
)


def request_view(query="", *, method="get"):
    request = getattr(RequestFactory(), method)(
        "/programme/synthetic/timetable/" + query
    )
    return views.public_programme_timetable(
        request, organization_id=uuid4(), edition_id=uuid4()
    )


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
def test_all_formats_obtain_a_fresh_complete_projection_and_disable_cache(
    snapshot, output_format
):
    with patch.object(
        views, "load_public_programme_timetable", return_value=snapshot
    ) as load:
        result = request_view(f"?format={output_format}")
    load.assert_called_once()
    assert result.status_code == 200
    assert "no-store" in result["Cache-Control"]
    assert result["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'none'" in result["Content-Security-Policy"]
    assert str(snapshot.release_id).encode() in result.content
    expected_type = {
        "html": "text/html",
        "print": "text/html",
        "json": "application/json",
        "calendar": "text/calendar",
    }[output_format]
    assert result["Content-Type"].startswith(expected_type)
    if output_format in {"json", "calendar"}:
        assert result["Content-Disposition"].startswith("attachment;")
    else:
        assert result.content.count(b"<main ") == 1
        assert result.content.count(b"<h1>") == 1
        assert b"Time zone: Europe/Budapest" in result.content


def test_rendered_copy_is_escaped_and_complete_print_hides_interactive_controls(
    snapshot,
):
    row = snapshot.entries[0]
    hostile = '<script>alert("synthetic")</script>'
    changed = replace(
        snapshot,
        entries=(replace(row, copy=replace(row.copy, title=hostile, summary=hostile)),),
    )
    with patch.object(views, "load_public_programme_timetable", return_value=changed):
        result = request_view("?format=print")
    assert result.status_code == 200
    assert hostile.encode() not in result.content
    assert b"&lt;script&gt;" in result.content
    assert b"<form" not in result.content
    assert b"Complete timetable copies" not in result.content
    assert (
        b"browser&#x27;s Print" in result.content
        or b"browser's Print" in result.content
    )
    assert b"Exact release:" in result.content


def test_filtered_list_has_truthful_counts_and_complete_download_links(snapshot):
    first = snapshot.entries[0]
    second = replace(
        first,
        occurrence_id=UUID(int=20),
        day_id=UUID(int=21),
        day_starts_at=first.day_starts_at + timedelta(days=1),
        day_ends_at=first.day_ends_at + timedelta(days=1),
        starts_at=first.starts_at + timedelta(days=1),
        ends_at=first.ends_at + timedelta(days=1),
        room=replace(first.room, space_id=UUID(int=22), room_name="Second room"),
    )
    data = replace(snapshot, entries=(first, second))
    with patch.object(views, "load_public_programme_timetable", return_value=data):
        filtered = request_view(f"?day={first.day_id}")
        empty = request_view(f"?day={first.day_id}&room={second.room.space_id}")
    assert b"Showing 1 of 2" in filtered.content
    assert b'href="?format=calendar"' in filtered.content
    assert b"Showing 0 of 2" in empty.content
    assert b"No matching occurrences" in empty.content
    assert b"No timetable published yet" not in empty.content


@pytest.mark.parametrize(
    "query",
    [
        "?unknown=1",
        "?format=html&format=json",
        "?format=private",
        "?day=wrong",
        "?day=" + "a" * 300,
        "?room=wrong",
        "?actor_id=someone",
        "?day=&day=",
        "?format=json&day=" + str(UUID(int=4)),
    ],
)
def test_invalid_request_is_generic_and_never_loads_a_source(query):
    with patch.object(views, "load_public_programme_timetable") as load:
        response = request_view(query)
    assert response.status_code == 400
    load.assert_not_called()
    assert "no-store" in response["Cache-Control"]


def test_unknown_filter_identity_is_not_echoed_or_treated_as_empty(snapshot):
    foreign = uuid4()
    with patch.object(views, "load_public_programme_timetable", return_value=snapshot):
        response = request_view(f"?room={foreign}")
    assert response.status_code == 400
    assert str(foreign).encode() not in response.content


@pytest.mark.parametrize(
    ("error", "status"),
    [(SchedulingAuthorizationDeniedError, 404), (SchedulingUnavailableError, 503)],
)
def test_denied_and_dependency_failures_have_no_prior_content(error, status):
    with patch.object(views, "load_public_programme_timetable", side_effect=error):
        response = request_view()
    assert response.status_code == status
    assert b"Exact release:" not in response.content
    assert b"Download complete" not in response.content
    assert b"Reload" in response.content


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ProgrammeReleaseState.ABSENT, b"No timetable published yet"),
        (ProgrammeReleaseState.WITHDRAWN, b"Timetable withdrawn"),
        (ProgrammeReleaseState.INVALIDATED, b"Timetable needs review"),
    ],
)
def test_non_available_state_never_renders_entries_or_download_controls(
    snapshot, state, expected
):
    changed = replace(snapshot, state=state, entries=())
    if state is not ProgrammeReleaseState.INVALIDATED:
        changed = replace(
            changed,
            release_id=None,
            published_at=None,
            pointer_version=0 if state is ProgrammeReleaseState.ABSENT else 2,
        )
    with patch.object(views, "load_public_programme_timetable", return_value=changed):
        response = request_view()
        calendar = request_view("?format=calendar")
    assert response.status_code == 200
    assert expected in response.content
    assert b"Download complete" not in response.content
    assert b"<article" not in response.content
    assert calendar.status_code == 409
    assert calendar["Content-Type"].startswith("text/html")


def test_each_request_observes_source_withdrawal_without_reusing_a_previous_result(
    snapshot,
):
    withdrawn = replace(
        snapshot,
        state=ProgrammeReleaseState.WITHDRAWN,
        entries=(),
        release_id=None,
        published_at=None,
        pointer_version=2,
    )
    with patch.object(
        views, "load_public_programme_timetable", side_effect=(snapshot, withdrawn)
    ):
        first = request_view()
        second = request_view()
    assert b"Opening" in first.content
    assert b"Opening" not in second.content
    assert b"Timetable withdrawn" in second.content


def test_oversized_rendered_html_is_not_returned_as_partial_content(snapshot):
    with (
        patch.object(views, "load_public_programme_timetable", return_value=snapshot),
        patch.object(views, "MAX_TIMETABLE_OUTPUT_BYTES", 1),
    ):
        response = request_view()
    assert response.status_code == 503
    assert b"Opening" not in response.content


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_public_adapter_is_read_only(method):
    with patch.object(views, "load_public_programme_timetable") as load:
        response = request_view(method=method)
    assert response.status_code == 405
    load.assert_not_called()


def test_output_route_is_not_mounted_by_production_urls():
    with pytest.raises(Resolver404):
        resolve(f"/programme/{uuid4()}/{uuid4()}/timetable/", urlconf="maru.urls")
