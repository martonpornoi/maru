"""Real conversion forms preserve exact original intent and separate authority."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock, create_autospec
from uuid import UUID

import pytest
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import resolve

from maru.applications import programme_conversion_queries as queries
from maru.applications import programme_conversion_views as views
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_conversion_commands import (
    ProgrammeConversionResult,
    convert_accepted_programme_proposal,
)
from maru.applications.programme_conversion_sources import (
    ProgrammeConversionConflictError,
)
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.creation_queries import ProgrammeCreationState
from tests.unit.test_application_programme_review_setup_views import hidden, shell, soup

pytestmark = pytest.mark.usefixtures(shell.__name__)


@pytest.fixture
def page(monkeypatch):
    choice = queries.ProgrammeConversionChoice(
        UUID(int=30),
        UUID(int=20),
        UUID(int=22),
        "Synthetic accepted call",
        3,
        datetime(2026, 9, 14, tzinfo=UTC),
        4,
        5,
    )
    source = Mock(
        return_value=queries.ProgrammeConversionSource(
            choice, eligible=True, consumed=False, writable=True
        )
    )
    creation = Mock(return_value=ProgrammeCreationState(3, writable=True))
    queue = Mock(return_value=queries.ProgrammeConversionPage((choice,), UUID(int=30)))
    entry = Mock()
    private = create_autospec(views.load_programme_private_item)
    command = create_autospec(convert_accepted_programme_proposal)
    command.return_value = ProgrammeConversionResult(
        UUID(int=70), UUID(int=80), 1, 4, replayed=False
    )
    monkeypatch.setattr(queries, "get_programme_conversion_source", source)
    monkeypatch.setattr(queries, "list_programme_conversion_choices", queue)
    monkeypatch.setattr(views, "load_programme_creation_state", creation)
    monkeypatch.setattr(views, "authorize_programme_conversion_retry", entry)
    monkeypatch.setattr(views, "load_programme_private_item", private)
    monkeypatch.setattr(views, "convert_accepted_programme_proposal", command)
    return SimpleNamespace(
        source=source,
        creation=creation,
        queue=queue,
        entry=entry,
        private=private,
        command=command,
    )


def request(method="get", values=None, *, queue=False, csrf=True, actor=None):
    req = getattr(RequestFactory(), method)("/", data=values or {})
    req.user = SimpleNamespace(
        pk=UUID(int=1) if actor is None else actor, is_authenticated=True
    )
    req._dont_enforce_csrf_checks = csrf
    return views.programme_conversion(
        req, UUID(int=2), UUID(int=3), UUID(int=4), None if queue else UUID(int=30)
    )


def values(**changes):
    return {
        "action": "convert",
        "retry_key": str(UUID(int=60)),
        "revision_id": str(UUID(int=22)),
        "expected_review_version": "5",
        "expected_programme_version": "3",
        "internal_title": "Private ceremony",
        "working_summary": "Private summary",
        "reason": "Deliberate conversion",
        "confirm": "on",
    } | changes


def test_discovery_is_bounded_labelled_and_never_loads_private_items(page):
    response = request(queue=True, values={"after": str(UUID(int=29))})
    html = soup(response)
    assert response.status_code == 200
    assert len(html.find_all("h1")) == len(html.find_all("main")) == 1
    assert (
        "Synthetic accepted call · Revision 3 · Decision version 4" in html.get_text()
    )
    assert html.find("a", string="Next page of accepted sources")
    assert page.queue.call_args.kwargs["after_id"] == UUID(int=29)
    page.source.assert_not_called()
    page.creation.assert_not_called()
    page.private.assert_not_called()
    page.command.assert_not_called()


def test_fresh_form_requires_deliberate_copy_and_two_original_versions(page):
    response = request()
    html = soup(response)
    assert response.status_code == 200
    assert hidden(response)["revision_id"] == str(UUID(int=22))
    assert hidden(response)["expected_review_version"] == "5"
    assert hidden(response)["expected_programme_version"] == "3"
    assert html.find("input", {"name": "internal_title"}).get("value", "") == ""
    assert not html.find("textarea", {"name": "working_summary"}).get_text().strip()
    assert not html.find("input", {"name": "confirm"}).has_attr("checked")
    assert (
        "All seven readiness concerns start required and unsatisfied" in html.get_text()
    )
    assert (
        html.find("form", {"data-call-command": True})["data-call-pending"] == "false"
    )
    page.private.assert_not_called()
    page.command.assert_not_called()


def test_original_receipt_precedes_fresh_authority_and_item_read_is_independent(page):
    page.source.side_effect = page.creation.side_effect = Denied
    page.command.return_value = replace(page.command.return_value, replayed=True)
    events = []
    page.command.side_effect = lambda **_kwargs: (
        events.append("command") or page.command.return_value
    )
    page.private.side_effect = lambda **_kwargs: events.append("private")
    response = request(
        "post",
        values(internal_title="  Private   ceremony ", reason=" Intent  retained "),
    )
    assert response.status_code == 200
    assert events[0] == "command"
    assert events[1:] == ["private"] * 3
    assert "original conversion receipt was recovered" in soup(response).get_text()
    link = soup(response).find(
        "a", string="Open the independently authorized Programme item"
    )
    assert str(UUID(int=80)) in link["href"]
    page.source.assert_not_called()
    page.creation.assert_not_called()
    kwargs = page.command.call_args.kwargs
    assert kwargs["command"].decision_id == UUID(int=30)
    assert kwargs["command"].revision_id == UUID(int=22)
    assert kwargs["command"].expected_review_version == 5
    assert kwargs["command"].expected_programme_version == 3
    assert kwargs["command"].internal_title == "Private ceremony"
    assert kwargs["retry_key"] == UUID(int=60)
    assert kwargs["reason"] == "Intent retained"
    assert kwargs["source_channel"] == "programme-conversion"
    assert kwargs["department_id"] == UUID(int=4)
    assert page.private.call_args.kwargs["item_id"] == UUID(int=80)


@pytest.mark.parametrize(
    "error", [Denied, ProgrammeAuthorizationDeniedError, DatabaseError]
)
def test_no_private_read_or_unavailable_continuation_does_not_hide_receipt(page, error):
    page.private.side_effect = error
    response = request("post", values())
    assert response.status_code == 200
    html = soup(response)
    assert "Private item creation confirmed" in html.get_text()
    assert "No private-item continuation is currently available" in html.get_text()
    assert not html.find("a", string="Open the independently authorized Programme item")


@pytest.mark.parametrize("when", [1, 2])
def test_disappearing_optional_item_grant_falls_back_to_minimal_receipt(page, when):
    page.private.side_effect = [None] * when + [Denied]
    response = request("post", values())
    assert response.status_code == 200
    assert "Private item creation confirmed" in soup(response).get_text()
    assert not soup(response).find(
        "a", string="Open the independently authorized Programme item"
    )
    page.command.assert_called_once()


def test_receipt_still_requires_current_identity_tenant_and_adapter_admission(page):
    page.entry.side_effect = [None, Denied, Denied]
    response = request("post", values())
    assert response.status_code == 404
    assert "Private ceremony" not in response.content.decode()
    assert str(UUID(int=80)) not in response.content.decode()
    page.command.assert_called_once()


@pytest.mark.parametrize(
    ("error", "status"), [(ProgrammeConversionConflictError, 409), (DatabaseError, 503)]
)
def test_failed_conversion_never_rebases_either_cursor_or_loses_input(
    page, error, status
):
    page.command.side_effect = error
    page.source.return_value = replace(
        page.source.return_value,
        consumed=True,
        choice=replace(page.source.return_value.choice, review_version=8),
    )
    page.creation.return_value = ProgrammeCreationState(11, writable=False)
    response = request("post", values())
    assert response.status_code == status
    html = soup(response)
    assert hidden(response)["expected_review_version"] == "5"
    assert hidden(response)["expected_programme_version"] == "3"
    assert hidden(response)["retry_key"] == str(UUID(int=60))
    assert hidden(response)["revision_id"] == str(UUID(int=22))
    assert html.find("input", {"name": "internal_title"})["value"] == "Private ceremony"
    assert (
        html.find("textarea", {"name": "working_summary"}).get_text().strip()
        == "Private summary"
    )
    assert (
        html.find("textarea", {"name": "reason"}).get_text().strip()
        == "Deliberate conversion"
    )
    assert html.find("input", {"name": "confirm"}).has_attr("checked")
    assert html.find(attrs={"role": "alert", "autofocus": True})
    assert "Current review version 8" in html.get_text()
    assert "Current Programme creation version 11" in html.get_text()
    assert "already converted" in html.get_text()
    page.private.assert_not_called()


@pytest.mark.parametrize(
    "change", [{"eligible": False}, {"consumed": True}, {"writable": False}]
)
def test_ineligible_retained_source_is_explained_without_fresh_form(page, change):
    page.source.return_value = replace(page.source.return_value, **change)
    response = request()
    assert response.status_code == 200
    assert not soup(response).find("form", {"data-call-command": True})
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"confirm": ""},
        {"internal_title": ""},
        {"reason": ""},
        {"extra": "no"},
        {"expected_review_version": "0"},
        {"expected_programme_version": "-1"},
        {"expected_programme_version": "1.0"},
        {"expected_review_version": "1e1"},
        {"expected_review_version": str(2**63 - 1)},
        {"revision_id": "bad"},
        {"retry_key": "bad"},
        {"internal_title": "x" * 241},
        {"working_summary": "x" * 2001},
        {"reason": "x" * 1001},
    ],
)
def test_closed_form_rejects_invalid_or_incomplete_intent_before_writer(page, change):
    assert request("post", values(**change)).status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "values_",
    [{"action": "other"}, {"action": ["convert", "convert"]}, {"reason": "x" * 12001}],
)
def test_closed_transport_rejects_before_writer_or_source(page, values_):
    assert request("post", values(**values_)).status_code == 400
    page.command.assert_not_called()
    page.source.assert_not_called()


def test_actual_csrf_and_method_and_generic_identity_denial(page):
    assert request("post", values(), csrf=False).status_code == 403
    assert request("put").status_code == 405
    assert request(actor=1).status_code == 404
    assert request("post", values(), queue=True).status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize("boundary", ["source", "creation"])
def test_render_rechecks_each_owner_and_releases_nothing_on_revocation(page, boundary):
    target = getattr(page, boundary)
    target.side_effect = [target.return_value, target.return_value, Denied]
    response = request()
    assert response.status_code == 404
    assert "Synthetic accepted call" not in response.content.decode()


def test_dormant_exact_conversion_routes_do_not_fall_into_uuid_case_routes():
    for suffix in ["conversion/", f"conversion/{UUID(int=30)}/"]:
        root = (
            f"/admin/applications/programme-review/{UUID(int=2)}/"
            f"{UUID(int=3)}/{UUID(int=4)}/"
        )
        match = resolve(
            root + suffix, urlconf="maru.applications.programme_review_setup_urls"
        )
        assert match.func is views.programme_conversion
