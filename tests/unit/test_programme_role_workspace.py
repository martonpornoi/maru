"""Real shared-shell HTML and closed forms with explicitly stubbed owner boundaries."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import resolve

from maru.authorization import programme_role_views as views
from maru.authorization.programme_role_forms import ProgrammeRoleDecisionForm
from maru.authorization.programme_role_inputs import ProgrammeRoleDecision
from maru.authorization.programme_role_queries import (
    ProgrammeRoleReview,
    ProgrammeRoleWorkspace,
)
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.identity.models import Account

NOW = datetime(2026, 9, 17, 20, tzinfo=UTC)
URLCONF = "maru.authorization.programme_role_urls"


def review():
    return ProgrammeRoleReview(
        request_id=UUID(int=6),
        author_id=UUID(int=3),
        approver_id=UUID(int=4),
        recipient_id=UUID(int=5),
        author_name="Synthetic author",
        approver_name="Synthetic approver",
        recipient_name="Synthetic recipient",
        recipe=PROGRAMME_ROLE_RECIPES[("coverage-reader", 1)],
        requested_at=NOW,
        approval_deadline=NOW + timedelta(days=7),
        not_before=None,
        expires_at=None,
        reason="Synthetic limited coverage",
        state="pending",
        decision_reason="",
        decided_at=None,
        role_assignment_id=None,
        can_approve=True,
        can_decline=True,
        can_cancel=False,
    )


@pytest.fixture(autouse=True)
def shell():
    with (
        patch.object(views.admin.site, "each_context", return_value={}),
        patch(
            "maru.events.templatetags.admin_edition_context.admin_edition_options",
            return_value={},
        ),
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


@pytest.fixture
def page(monkeypatch):
    row = review()
    workspace = ProgrammeRoleWorkspace(
        "Synthetic organizers / Synthetic Programme", "Synthetic Programme", (row,)
    )
    loader = Mock(return_value=workspace)
    command = Mock(return_value=object())
    monkeypatch.setattr(views, "load_programme_role_workspace", loader)
    monkeypatch.setattr(views, "decide_programme_role", command)
    return SimpleNamespace(row=row, workspace=workspace, loader=loader, command=command)


def call(
    page,
    data=None,
    *,
    selected=True,
    author=False,
    anonymous=False,
    csrf=False,
    query="",
    level="edition",
    method=None,
):
    route = f"/admin/programme/access/{UUID(int=1)}/{UUID(int=2)}/{level}/"
    if selected:
        route += f"{page.row.request_id}/"
    request = RequestFactory().generic(
        method or ("POST" if data is not None else "GET"), route + query
    )
    if data is not None:
        request = RequestFactory().post(route + query, data)
    request.user = (
        AnonymousUser()
        if anonymous
        else Account(
            id=page.row.author_id if author else page.row.approver_id,
            display_name="Synthetic reviewer",
            is_active=True,
            email_verified_at=NOW,
        )
    )
    request._dont_enforce_csrf_checks = not csrf
    request.urlconf = URLCONF
    if author:
        original = page.loader.return_value.requests[0]
        page.loader.return_value = replace(
            page.workspace,
            requests=(
                replace(
                    original,
                    can_approve=False,
                    can_decline=False,
                    can_cancel=original.decided_at is None,
                ),
            ),
        )
    return views.programme_role_workspace(
        request,
        UUID(int=1),
        UUID(int=2),
        level=level,
        request_id=page.row.request_id if selected else None,
    )


def decision_data(action="approve"):
    return {
        "action": action,
        "reason": "Synthetic reviewed decision",
        "confirmed": "on",
        "idempotency_key": str(uuid4()),
    }


def test_detail_shows_scope_consequences_and_independent_own_decision(page):
    response = call(page)
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == 1
    assert len(soup.find_all("main")) == 1
    assert soup.select_one('link[href="/static/authorization/programme_role.css"]')
    assert "Synthetic recipient" in soup.get_text()
    assert "workforce.view_shifts" in soup.get_text()
    assert "A request grants nothing" in soup.get_text()
    assert soup.select_one("input[name=confirmed]")
    assert soup.select_one("textarea[name=reason]").get("id")
    assert soup.select_one("input[name=idempotency_key]").get("type") == "hidden"
    assert not soup.select(
        "input[name=approver_id], input[name=recipient_id], input[name=scope]"
    )
    assert page.loader.call_count == 2
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    page.command.assert_not_called()


def test_open_inventory_uses_labelled_links_without_decision_form(page):
    response = call(page, selected=False)
    soup = BeautifulSoup(response.content, "html.parser")
    assert response.status_code == 200
    assert (
        soup.find("a", string="Programme coverage reader for Synthetic recipient")
        is not None
    )
    assert "not a history export" in soup.get_text()
    assert not soup.select("form[data-programme-command]")


def test_empty_inventory_is_truthful_and_does_not_infer_global_absence(page):
    page.loader.return_value = replace(page.workspace, requests=())
    response = call(page, selected=False)
    assert response.status_code == 200
    assert b"No open requests you authored" in response.content
    assert b"does not imply" in response.content


def test_author_can_cancel_but_not_approve_for_another_person(page):
    response = call(page, author=True)
    soup = BeautifulSoup(response.content, "html.parser")
    assert [
        option["value"] for option in soup.select("select[name=action] option")
    ] == ["cancel"]
    assert b"not approve it for the named person" in response.content


def test_expired_request_offers_decline_not_approval(page):
    page.loader.return_value = replace(
        page.workspace,
        requests=(replace(page.row, state="expired", can_approve=False),),
    )
    response = call(page)
    soup = BeautifulSoup(response.content, "html.parser")
    assert "approve" not in [
        option["value"] for option in soup.select("select[name=action] option")
    ]
    assert b"new request is required" in response.content


def test_author_terminal_receipt_has_no_new_cancel_control(page):
    page.loader.return_value = replace(
        page.workspace,
        requests=(
            replace(
                page.row,
                state="cancel",
                decided_at=NOW,
                decision_reason="Original cancellation",
                can_approve=False,
                can_decline=False,
                can_cancel=False,
            ),
        ),
    )
    response = call(page, author=True)
    assert b"Cancelled" in response.content
    assert b"data-programme-command" not in response.content


@pytest.mark.parametrize("state", ["approve", "decline", "cancel"])
def test_terminal_page_is_read_only_and_never_claims_effective_authority(page, state):
    terminal = replace(
        page.row,
        state=state,
        decided_at=NOW,
        decision_reason="Retained rationale",
        role_assignment_id=uuid4() if state == "approve" else None,
        can_approve=False,
        can_decline=False,
        can_cancel=False,
    )
    page.loader.return_value = replace(page.workspace, requests=(terminal,))
    response = call(page)
    assert response.status_code == 200
    assert b"Retained rationale" in response.content
    assert b"data-programme-command" not in response.content
    if state == "approve":
        assert b"does not establish current effective access" in response.content
    else:
        assert b"decision granted no access" in response.content
    page.command.assert_not_called()


def test_organization_scope_explains_shared_venue_consequence(page):
    response = call(page, level="organization")
    assert response.status_code == 200
    assert b"not just this edition" in response.content
    assert b"does not itself revoke" in response.content


@pytest.mark.parametrize("action", ["approve", "decline", "cancel"])
def test_post_uses_actual_actor_exact_scope_original_key_and_canonical_command(
    page, action
):
    data = decision_data(action)
    response = call(page, data, author=action == "cancel")
    assert response.status_code == 302
    assert response["Location"].endswith(f"/{page.row.request_id}/")
    args = page.command.call_args.kwargs
    assert args["actor"].id == (
        page.row.author_id if action == "cancel" else page.row.approver_id
    )
    assert args["request_id"] == page.row.request_id
    assert args["idempotency_key"] == UUID(data["idempotency_key"])
    assert args["action"] is ProgrammeRoleDecision(action)
    assert args["reason"] == data["reason"]
    assert args["scope"].organization_id == UUID(int=1)
    assert args["scope"].programme_edition_id == UUID(int=2)
    assert args["source_channel"] == "html"
    assert page.command.call_count == 1


def test_terminal_post_can_recover_original_approved_retry_without_new_ui_controls(
    page,
):
    page.loader.return_value = replace(
        page.workspace,
        requests=(
            replace(
                page.row,
                state="approve",
                decided_at=NOW,
                can_approve=False,
                can_decline=False,
            ),
        ),
    )
    response = call(page, decision_data())
    assert response.status_code == 302
    page.command.assert_called_once()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValidationError("Source changed", code="conflict"), 409),
        (DatabaseError("Synthetic dependency"), 503),
    ],
)
def test_command_failure_keeps_original_input_and_retry_without_resubmit(
    page, error, status
):
    data = decision_data()
    page.command.side_effect = error
    response = call(page, data)
    soup = BeautifulSoup(response.content, "html.parser")
    assert response.status_code == status
    assert (
        soup.select_one("input[name=idempotency_key]")["value"]
        == data["idempotency_key"]
    )
    assert soup.select_one("textarea[name=reason]").get_text().strip() == data["reason"]
    assert soup.select_one("form[data-programme-pending=true]") is not None
    assert soup.select_one("[role=alert][autofocus]") is not None
    page.command.assert_called_once()


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": ""},
        {"reason": ""},
        {"action": "unknown"},
        {"reason": "x" * 241},
        {"idempotency_key": "not-a-uuid"},
    ],
)
def test_invalid_form_does_not_attempt_command(page, changes):
    response = call(page, decision_data() | changes)
    assert response.status_code == 400
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "key",
    [
        "actor",
        "approver_id",
        "recipient_id",
        "organization_id",
        "scope",
        "preview_person",
    ],
)
def test_extra_authority_or_preview_input_is_rejected_before_reads(page, key):
    response = call(page, decision_data() | {key: str(uuid4())})
    assert response.status_code == 400
    page.loader.assert_not_called()
    page.command.assert_not_called()


@pytest.mark.parametrize(
    "field", ["action", "reason", "confirmed", "idempotency_key", "csrfmiddlewaretoken"]
)
def test_duplicate_input_is_rejected_before_owner_read(page, field):
    data = decision_data() | {field: ["first", "second"]}
    assert call(page, data).status_code == 400
    page.loader.assert_not_called()


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PermissionDenied("Hidden person"), 404),
        (DatabaseError("Hidden content"), 503),
        (ValidationError("Overflow hidden count"), 503),
    ],
)
def test_initial_or_final_read_failure_suppresses_private_content(
    page, initial, error, status
):
    page.loader.side_effect = [error] if initial else [page.workspace, error]
    response = call(page)
    assert response.status_code == status
    assert b"Synthetic recipient" not in response.content
    assert b"Synthetic limited coverage" not in response.content
    assert b"Hidden" not in response.content


def test_changed_rendered_source_suppresses_the_prepared_private_page(page):
    page.loader.side_effect = [
        page.workspace,
        replace(page.workspace, scope_label="Changed scope"),
    ]
    response = call(page)
    assert response.status_code == 409
    assert b"Synthetic recipient" not in response.content
    assert b"No private content" in response.content


def test_overflow_guidance_is_bounded_without_count_or_partial_names(page):
    page.loader.side_effect = ValidationError(
        "Hidden count", code="programme_role_inventory_overflow"
    )
    response = call(page, selected=False)
    assert response.status_code == 503
    assert b"Review known original request links" in response.content
    assert b"Synthetic recipient" not in response.content
    assert b"Hidden count" not in response.content


def test_command_permission_loss_suppresses_original_private_form(page):
    page.command.side_effect = PermissionDenied
    response = call(page, decision_data())
    assert response.status_code == 404
    assert b"Synthetic reviewed decision" not in response.content


def test_csrf_is_required_before_query_or_command(page):
    assert call(page, decision_data(), csrf=True).status_code == 403
    page.loader.assert_not_called()
    page.command.assert_not_called()


def test_anonymous_is_sent_to_actual_sign_in_without_read(page):
    assert call(page, anonymous=True).status_code == 302
    page.loader.assert_not_called()


@pytest.mark.parametrize(
    "variant", ["query", "post_inventory", "method", "long_raw", "bad_scope"]
)
def test_unsupported_transport_fails_closed(page, variant):
    kwargs = {
        "query": {"query": "?actor=other"},
        "post_inventory": {"selected": False, "data": decision_data()},
        "method": {"method": "DELETE"},
        "long_raw": {"data": decision_data() | {"reason": "x" * 4097}},
        "bad_scope": {"level": "everything"},
    }[variant]
    response = call(page, **kwargs)
    assert response.status_code in {400, 405}
    page.loader.assert_not_called()


@pytest.mark.parametrize(
    ("level", "tail"),
    [
        ("organization", "organization/"),
        ("edition", "edition/"),
        ("department", f"department/{UUID(int=7)}/"),
        ("resource", f"room/{UUID(int=7)}/{UUID(int=8)}/"),
    ],
)
def test_all_reserved_scope_routes_resolve_only_in_isolated_urlconf(level, tail):
    url = f"/admin/programme/access/{UUID(int=1)}/{UUID(int=2)}/{tail}"
    match = resolve(url, urlconf=URLCONF)
    assert match.func is views.programme_role_workspace
    assert match.kwargs["level"] == level
    assert resolve(url).func is not views.programme_role_workspace


def test_direct_form_rejects_duplicate_or_unknown_fields():
    data = QueryDict(
        "action=approve&action=decline&reason=test&confirmed=on&idempotency_key="
        + str(uuid4())
    )
    form = ProgrammeRoleDecisionForm(data, is_author=False)
    assert not form.is_valid()
    assert form.non_field_errors().as_data()[0].code == "invalid_input_cardinality"
    form = ProgrammeRoleDecisionForm(
        decision_data() | {"actor": "other"}, is_author=False
    )
    assert not form.is_valid()
    assert form.non_field_errors().as_data()[0].code == "unknown_input_field"
