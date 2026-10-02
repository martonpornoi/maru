"""Real archive forms and HTML with sealed substitutes, not browser proof."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import resolve

from maru.programme import archive_views as views
from maru.programme.archive_queries import ProgrammeArchiveInspection
from maru.programme.archive_tasks import (
    ProgrammeArchiveCapacityError,
    ProgrammeArchiveConflictError,
    ProgrammeArchiveUnavailableError,
)
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture
def page(monkeypatch):
    actor, organization, edition, task_id = (UUID(int=i) for i in range(1, 5))
    observed = datetime(2026, 9, 20, tzinfo=UTC)
    result = ProgrammeArchiveInspection(
        task_id=task_id,
        version=3,
        state="ready",
        requested_at=observed,
        expires_at=observed + timedelta(hours=24),
        failure_code="",
        expired=False,
        source_changed=False,
        size_bytes=5,
        sha256="a" * 64,
        chunks=(b"PKzip",),
    )
    auth, read, queue, cancel = (
        Mock(),
        Mock(return_value=result),
        Mock(return_value=task_id),
        Mock(),
    )
    monkeypatch.setattr(views, "authorize_programme_archive_scope", auth)
    monkeypatch.setattr(views, "inspect_programme_archive", read)
    monkeypatch.setattr(views, "request_programme_archive", queue)
    monkeypatch.setattr(views, "cancel_programme_archive", cancel)
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
        yield SimpleNamespace(
            actor=actor,
            organization=organization,
            edition=edition,
            task_id=task_id,
            result=result,
            auth=auth,
            read=read,
            queue=queue,
            cancel=cancel,
        )


def call(
    page,
    *,
    task=False,
    download=False,
    data=None,
    query="",
    anonymous=False,
    csrf=False,
    method="GET",
):
    root = f"/admin/programme/archive/{page.organization}/{page.edition}/"
    path = root + (f"{page.task_id}/" if task or download else "")
    path += "download/" if download else ""
    factory = RequestFactory()
    if data is not None:
        encoded = data if isinstance(data, QueryDict) else QueryDict("", mutable=True)
        if not isinstance(data, QueryDict):
            encoded.update(data)
        request = factory.post(
            path + query,
            data=encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    else:
        request = factory.generic(method, path + query)
    request.user = (
        AnonymousUser()
        if anonymous
        else SimpleNamespace(
            pk=page.actor,
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    )
    request._dont_enforce_csrf_checks = not csrf
    args = {"organization_id": page.organization, "edition_id": page.edition}
    if task or download:
        args["task_id"] = page.task_id
    return (views.programme_archive_download if download else views.programme_archive)(
        request, **args
    )


def test_static_preview_is_deliberate_private_and_has_one_heading_without_source_reads(
    page,
):
    response = call(page)
    assert response.status_code == 200
    html = BeautifulSoup(response.content, "html.parser")
    assert len(html.select("h1")) == 1
    assert html.select_one('input[name="confirm"][required]')
    assert html.select_one('input[name="request_key"][type="hidden"]')
    assert "restricted C3" in html.get_text()
    assert "private, no-store" in response["Cache-Control"]
    assert response["Referrer-Policy"] == "same-origin"
    page.read.assert_not_called()
    page.queue.assert_not_called()


@pytest.mark.parametrize(
    "state", ["queued", "running", "ready", "failed", "cancelled", "expired"]
)
def test_task_html_only_offers_current_phase_actions(page, state):
    page.read.return_value = replace(page.result, state=state, chunks=())
    response = call(page, task=True)
    html = BeautifulSoup(response.content, "html.parser")
    assert response.status_code == 200
    assert response["Referrer-Policy"] == "same-origin"
    assert bool(html.select('a[href$="download/"]')) == (state == "ready")
    assert html.select_one('input[name="action"]')["value"] == (
        "cancel" if state in {"queued", "running", "ready"} else "retry"
    )
    page.read.assert_called_once()


def test_expired_ready_task_does_not_offer_download_or_claim_worker_disposal(page):
    page.read.return_value = replace(page.result, expired=True)
    response = call(page, task=True)
    html = BeautifulSoup(response.content, "html.parser")
    assert not html.select('a[href$="download/"]')
    assert "does not prove" in html.get_text()


def test_request_redirect_binds_signed_in_actor_route_scope_and_retained_key(page):
    key = uuid4()
    response = call(
        page, data={"action": "request", "request_key": str(key), "confirm": "on"}
    )
    assert response.status_code == 302
    args = page.queue.call_args.kwargs
    assert args["scope"].actor_id == page.actor
    assert args["scope"].organization_id == page.organization
    assert args["scope"].edition_id == page.edition
    assert args["request_key"] == key
    assert args["previous_task_id"] is None
    assert str(page.task_id) in response["Location"]


@pytest.mark.parametrize("action", ["retry", "cancel"])
def test_task_mutations_use_url_task_and_exact_confirmed_input(page, action):
    data = {"action": action, "confirm": "on"}
    data.update(
        {"expected_version": "3"}
        if action == "cancel"
        else {"request_key": str(uuid4())}
    )
    assert call(page, task=True, data=data).status_code == 302
    if action == "cancel":
        assert page.cancel.call_args.kwargs["task_id"] == page.task_id
        assert page.cancel.call_args.kwargs["expected_version"] == 3
    else:
        assert page.queue.call_args.kwargs["previous_task_id"] == page.task_id


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProgrammeArchiveCapacityError(), 409),
        (ProgrammeArchiveConflictError(), 409),
        (DatabaseError("PRIVATE"), 503),
    ],
)
def test_submission_failure_preserves_same_key_without_private_exception_details(
    page, error, status
):
    key = str(uuid4())
    page.queue.side_effect = error
    response = call(
        page, data={"action": "request", "request_key": key, "confirm": "on"}
    )
    assert response.status_code == status
    assert response["Referrer-Policy"] == "same-origin"
    html = BeautifulSoup(response.content, "html.parser")
    assert html.select_one('input[name="request_key"]')["value"] == key
    assert "PRIVATE" not in html.get_text()
    assert html.select_one('[role="alert"]')


@pytest.mark.parametrize(
    "data",
    [
        {"action": "request", "request_key": str(UUID(int=0)), "confirm": "on"},
        {"action": "request", "request_key": "invalid", "confirm": "on"},
        {"action": "request", "request_key": str(UUID(int=1))},
        {
            "action": "request",
            "request_key": str(UUID(int=1)),
            "confirm": "on",
            "actor_id": "other",
        },
        {"action": "unknown"},
    ],
)
def test_invalid_or_unconfirmed_requests_do_not_queue(page, data):
    assert call(page, data=data).status_code == 400
    page.queue.assert_not_called()


def test_duplicate_values_and_query_overrides_are_refused(page):
    values = QueryDict("action=request&confirm=on&request_key=x&request_key=y")
    assert call(page, data=values).status_code == 400
    assert call(page, query="?actor_id=other").status_code == 400
    page.queue.assert_not_called()


def test_authentication_csrf_and_unsupported_methods_are_enforced(page):
    assert call(page, anonymous=True).status_code == 302
    assert call(page, data={"action": "request"}, csrf=True).status_code == 403
    assert call(page, method="DELETE").status_code == 405
    assert call(page, download=True, method="POST").status_code == 405
    page.queue.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProgrammeAuthorizationDeniedError(), 404),
        (ProgrammeArchiveUnavailableError(), 404),
        (DatabaseError("PRIVATE"), 503),
    ],
)
def test_private_inspection_failure_shows_no_task_content(page, error, status):
    page.read.side_effect = error
    response = call(page, task=True)
    assert response.status_code == status
    assert str(page.task_id).encode() not in response.content
    assert b"PRIVATE" not in response.content


def test_download_is_verified_before_stream_with_fixed_private_attachment_headers(page):
    response = call(page, download=True)
    assert response.status_code == 200
    assert page.read.call_args.kwargs["download"] is True
    assert b"".join(response.streaming_content) == b"PKzip"
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Length"] == "5"
    assert (
        response["Content-Disposition"]
        == 'attachment; filename="programme-exit-archive.zip"'
    )
    assert "private, no-store" in response["Cache-Control"]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "no-referrer"


def test_download_failure_returns_no_stream_and_no_query_override(page):
    page.read.side_effect = ProgrammeArchiveUnavailableError
    response = call(page, download=True)
    assert response.status_code == 404
    assert not response.streaming
    assert call(page, download=True, query="?task=other").status_code == 404


def test_reserved_routes_are_not_default_production_routes(page):
    path = f"/admin/programme/archive/{page.organization}/{page.edition}/"
    assert (
        resolve(path, urlconf="maru.programme.archive_urls").url_name
        == "programme-archive"
    )
    assert resolve(path, urlconf="maru.urls").url_name != "programme-archive"
