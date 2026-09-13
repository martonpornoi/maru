"""Fast real-template operator transport tests; owner policy has native DB tests."""

import re
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.scheduling import operator_output_views as views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import SchedulingUnavailableError
from tests.unit.test_programme_operator_rendering import (
    full_sheet as full_sheet,  # noqa: PLC0414
)
from tests.unit.test_programme_operator_rendering import (
    sheet as sheet,  # noqa: PLC0414
)


def request_view(sheet, query="", *, method="get", anonymous=False):
    request = getattr(RequestFactory(), method)(
        "/admin/programme/run-sheets/synthetic/" + query
    )
    request.user = (
        AnonymousUser()
        if anonymous
        else SimpleNamespace(
            pk=uuid4(),
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    )
    return views.operator_run_sheet(
        request,
        organization_id=sheet.organization_id,
        edition_id=sheet.edition_id,
        scope_kind=sheet.kind.value,
        target_id=sheet.target_id,
    )


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_shell_access",
            return_value={"workspace_available": False},
        ),
        patch(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            return_value={},
        ),
    ):
        yield


@pytest.mark.parametrize("output_format", ["html", "print", "json", "calendar"])
def test_every_private_format_gets_fresh_exact_scope_and_no_cache(
    full_sheet, output_format
):
    with (
        patch.object(views, "authorize_operator_scope"),
        patch.object(views, "load_operator_run_sheet", return_value=full_sheet) as load,
    ):
        response = request_view(
            full_sheet,
            f"?format={output_format}&technical=1&accessibility=1&media=1&staffing=1",
        )
    assert response.status_code == 200
    assert load.call_args.args[0].target_id == full_sheet.target_id
    assert load.call_args.args[0].organization_id == full_sheet.organization_id
    assert load.call_args.kwargs["layers"] == full_sheet.layers
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    content = response.content.replace(b"\r\n ", b"")
    assert b"Technical secret" in content
    assert b"Current work briefing" in content
    if output_format in {"html", "print"}:
        assert response.content.count(b"<h1>") == 1
        assert response.content.count(b"<main ") == 1
        assert b"Retained work intervals and states" in response.content
        assert b"Room version 2, venue version 3" in response.content
        assert b"Scope and source" in response.content


def test_shared_navigation_has_one_fresh_nonce_without_relaxing_script_policy(sheet):
    with (
        patch.object(views, "authorize_operator_scope"),
        patch.object(views, "load_operator_run_sheet", return_value=sheet),
    ):
        responses = [request_view(sheet), request_view(sheet)]
        download = request_view(sheet, "?format=json")
    nonces = []
    for response in responses:
        policy = response["Content-Security-Policy"]
        assert "unsafe-inline" not in policy
        nonce = re.search(r"'nonce-([A-Za-z0-9_-]+)'", policy).group(1)
        assert len(nonce) >= 43
        assert response.content.count(f'nonce="{nonce}"'.encode()) == 1
        assert b"closeButton.addEventListener" in response.content
        nonces.append(nonce)
    assert len(set(nonces)) == 2
    assert "nonce-" not in download["Content-Security-Policy"]


@pytest.mark.parametrize(
    "query",
    [
        "?unknown=1",
        "?format=private",
        "?format=json&format=html",
        "?technical=yes",
        "?technical=1&technical=1",
        "?actor_id=someone",
        "?release_id=someone",
        "?room=someone",
    ],
)
def test_malformed_options_are_rejected_only_after_base_admission(sheet, query):
    with (
        patch.object(views, "authorize_operator_scope") as admit,
        patch.object(views, "load_operator_run_sheet") as load,
    ):
        response = request_view(sheet, query)
    assert response.status_code == 400
    admit.assert_called_once()
    load.assert_not_called()
    with patch.object(
        views,
        "authorize_operator_scope",
        side_effect=SchedulingAuthorizationDeniedError,
    ):
        denied = request_view(sheet, query)
    assert denied.status_code == 404


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (SchedulingAuthorizationDeniedError, 404),
        (SchedulingUnavailableError, 503),
        (RuntimeError, 503),
    ],
)
def test_denied_requested_layer_or_audit_failure_has_no_partial_content(
    sheet, error, status
):
    with (
        patch.object(views, "authorize_operator_scope"),
        patch.object(views, "load_operator_run_sheet", side_effect=error),
    ):
        response = request_view(sheet, "?technical=1")
    assert response.status_code == status
    assert b"Reviewed summary" not in response.content
    assert b"Download private" not in response.content
    assert b"No " in response.content


def test_base_default_does_not_request_extra_fields_and_escapes_reviewed_text(sheet):
    changed = replace(
        sheet,
        entries=(
            replace(
                sheet.entries[0],
                copy=replace(
                    sheet.entries[0].copy, title='<script>alert("synthetic")</script>'
                ),
            ),
        ),
    )
    with (
        patch.object(views, "authorize_operator_scope"),
        patch.object(views, "load_operator_run_sheet", return_value=changed) as load,
    ):
        response = request_view(sheet)
    assert response.status_code == 200
    assert load.call_args.kwargs["layers"] == frozenset()
    assert b"&lt;script&gt;" in response.content
    assert b'<script>alert("synthetic")</script>' not in response.content
    assert b"Staffing details were not requested" in response.content


def test_anonymous_or_mutating_requests_never_read_sources(sheet):
    with patch.object(views, "load_operator_run_sheet") as load:
        anonymous = request_view(sheet, anonymous=True)
        mutation = request_view(sheet, method="post")
    assert anonymous.status_code == 302
    assert mutation.status_code == 405
    load.assert_not_called()


def test_operator_routes_remain_absent_from_production(sheet):
    path = (
        f"/admin/programme/run-sheets/{sheet.organization_id}/"
        f"{sheet.edition_id}/room/{sheet.target_id}/"
    )
    # The admin catch-all may resolve, but never to this dormant product adapter.
    try:
        resolved = resolve(path)
    except Resolver404:
        return
    assert resolved.func is not views.operator_run_sheet
