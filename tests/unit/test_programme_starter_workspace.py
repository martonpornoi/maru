"""Actual shared-shell HTML with explicitly stubbed owning queries and commands."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import resolve, reverse

from maru.identity.models import Account
from maru.workforce import programme_starter_creation_views as creation_views
from maru.workforce import programme_starter_views as views
from maru.workforce.programme_starter_creation import ProgrammeStarterCreation
from maru.workforce.programme_starter_inputs import (
    PROGRAMME_STARTER_DEFINITION,
    ProgrammeStarterScope,
)
from maru.workforce.programme_starter_queries import (
    ProgrammeStarterReview,
    ProgrammeStarterWorkspace,
)
from maru.workforce.programme_starter_selection import (
    _sign_selection,
    verify_programme_starter_selection,
)

NOW = datetime(2030, 8, 1, tzinfo=UTC)
SCOPE = ProgrammeStarterScope(UUID(int=1), UUID(int=2), UUID(int=3))
URLCONF = "maru.workforce.programme_starter_urls"


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
    row = ProgrammeStarterReview(
        UUID(int=6),
        UUID(int=4),
        UUID(int=5),
        "Synthetic author",
        "Synthetic approver",
        NOW,
        NOW + timedelta(days=7),
        "Synthetic shared staffing.",
        "pending",
        "",
        None,
        None,
        None,
        created_output=False,
        can_approve=True,
        can_decline=True,
        can_cancel=False,
    )
    workspace = ProgrammeStarterWorkspace(
        "Synthetic organization",
        "Synthetic edition",
        PROGRAMME_STARTER_DEFINITION,
        can_request=True,
        requests=(row,),
    )
    loader, command, step_up = Mock(return_value=workspace), Mock(), Mock()
    monkeypatch.setattr(views, "load_programme_starter_workspace", loader)
    monkeypatch.setattr(views, "decide_programme_starter", command)
    monkeypatch.setattr(views, "require_recent_step_up", step_up)
    base = ProgrammeStarterCreation(
        "Synthetic organization",
        "Synthetic edition",
        PROGRAMME_STARTER_DEFINITION,
        can_request=True,
    )
    initial = Mock(return_value=base)

    def preview(**kwargs):
        selected = (
            verify_programme_starter_selection(
                actor_id=kwargs["actor"].id,
                scope=kwargs["scope"],
                draft=kwargs["draft"],
                proof=kwargs["proof"],
            )
            if kwargs.get("proof") is not None
            else _sign_selection(
                kwargs["actor"].id, kwargs["scope"], kwargs["draft"], row.approver_id
            )
        )
        return replace(base, selection=selected, approver_name=row.approver_name)

    prepare = Mock(side_effect=preview)
    submit = Mock(return_value=SimpleNamespace(request_id=row.request_id))
    monkeypatch.setattr(creation_views, "load_programme_starter_creation", initial)
    monkeypatch.setattr(creation_views, "prepare_programme_starter_creation", prepare)
    monkeypatch.setattr(creation_views, "request_programme_starter", submit)
    return SimpleNamespace(
        row=row,
        workspace=workspace,
        loader=loader,
        command=command,
        step_up=step_up,
        base=base,
        initial=initial,
        prepare=prepare,
        submit=submit,
    )


def call(
    page,
    data=None,
    *,
    create=False,
    selected=True,
    author=False,
    anonymous=False,
    csrf=False,
    query="",
    method=None,
):
    name = "programme-volunteer-starter" + (
        "-new" if create else "-request" if selected else ""
    )
    kwargs = {
        "organization_id": SCOPE.organization_id,
        "series_id": SCOPE.series_id,
        "edition_id": SCOPE.edition_id,
    }
    if not create and selected:
        kwargs["request_id"] = page.row.request_id
    route = reverse(name, kwargs=kwargs, urlconf=URLCONF)
    factory = RequestFactory()
    if isinstance(data, QueryDict):
        data = dict(data.lists())
    request = (
        factory.post(route + query, data)
        if data is not None
        else factory.generic(method or "GET", route + query)
    )
    request.user = (
        AnonymousUser()
        if anonymous
        else Account(
            id=page.row.author_id if author or create else page.row.approver_id,
            is_active=True,
            email_verified_at=NOW,
        )
    )
    request._dont_enforce_csrf_checks = not csrf
    request.urlconf = URLCONF
    if author and not create:
        page.loader.return_value = replace(
            page.workspace,
            requests=(
                replace(
                    page.row, can_approve=False, can_decline=False, can_cancel=True
                ),
            ),
        )
    handler = (
        creation_views.programme_starter_creation
        if create
        else views.programme_starter_workspace
    )
    return handler(request, **kwargs)


def decision():
    return {
        "action": "approve",
        "reason": "Reviewed exact meaning.",
        "confirmed": "on",
        "idempotency_key": str(uuid4()),
    }


def draft():
    return {
        "action": "preview",
        "approver_email": "approver@example.invalid",
        "reason": "Synthetic shared staffing.",
        "idempotency_key": str(uuid4()),
    }


def confirmed(page):
    values = draft()
    response = call(page, values, create=True)
    soup = BeautifulSoup(response.content, "html.parser")
    values.update(
        action="confirm",
        confirmed="on",
        selection_proof=soup.select_one("input[name=selection_proof]")["value"],
    )
    return values


def test_real_review_template_uses_one_shared_shell_and_exact_consequences(page):
    response = call(page)
    soup = BeautifulSoup(response.content, "html.parser")
    assert response.status_code == 200
    assert len(soup.find_all("h1")) == 1
    assert len(soup.find_all("main")) == 1
    assert "Approval grants nobody access" in soup.get_text()
    assert "Synthetic author" in soup.get_text()
    assert "workforce.view_structure" in soup.get_text()
    assert soup.select_one("input[name=confirmed]")
    assert not soup.select(
        "input[name=actor], input[name=approver_id], input[name=scope]"
    )
    assert page.loader.call_count == 2
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    page.command.assert_not_called()


def test_author_can_cancel_not_approve(page):
    response = call(page, author=True)
    soup = BeautifulSoup(response.content, "html.parser")
    assert [node["value"] for node in soup.select("select[name=action] option")] == [
        "cancel"
    ]
    assert call(page, decision(), author=True).status_code == 400
    page.command.assert_not_called()


def test_decision_requires_recent_authentication_and_retains_original_input(page):
    page.step_up.side_effect = ValidationError("step_up_required")
    values = decision()
    response = call(page, values)
    soup = BeautifulSoup(response.content, "html.parser")
    assert response.status_code == 403
    assert (
        soup.select_one("input[name=idempotency_key]")["value"]
        == values["idempotency_key"]
    )
    assert (
        soup.select_one("textarea[name=reason]").get_text().removeprefix("\n")
        == values["reason"]
    )
    assert soup.select_one('a[target="_blank"][rel="noopener"]')
    page.command.assert_not_called()


def test_valid_own_decision_uses_only_authenticated_actor_and_exact_scope(page):
    values = decision()
    response = call(page, values)
    assert response.status_code == 302
    args = page.command.call_args.kwargs
    assert args["actor"].id == page.row.approver_id
    assert args["scope"] == SCOPE
    assert args["request_id"] == page.row.request_id
    assert str(args["idempotency_key"]) == values["idempotency_key"]
    page.step_up.assert_called_once()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValidationError("Changed intent"), 409),
        (DatabaseError("private database detail"), 503),
    ],
)
def test_decision_failure_preserves_original_key_without_private_error(
    page, error, status
):
    page.command.side_effect = error
    values = decision()
    response = call(page, values)
    assert response.status_code == status
    assert values["idempotency_key"].encode() in response.content
    assert b"private database detail" not in response.content


@pytest.mark.parametrize("create", [False, True])
def test_csrf_and_login_precede_owner_admission(page, create):
    response = call(page, draft() if create else decision(), create=create, csrf=True)
    assert response.status_code == 403
    page.loader.assert_not_called()
    page.initial.assert_not_called()
    assert call(page, create=create, anonymous=True).status_code == 302


@pytest.mark.parametrize("create", [False, True])
def test_unknown_duplicate_or_oversized_input_fails_before_private_queries(
    page, create
):
    values = draft() if create else decision()
    assert call(page, values | {"actor": "foreign"}, create=create).status_code == 400
    assert call(page, values | {"reason": "x" * 4097}, create=create).status_code == 400
    repeated = QueryDict("", mutable=True)
    repeated.update(values)
    repeated.appendlist("reason", "second")
    assert call(page, repeated, create=create).status_code == 400
    assert call(page, create=create, query="?scope=foreign").status_code == 400
    page.loader.assert_not_called()
    page.initial.assert_not_called()


@pytest.mark.parametrize("fault", ["label", "authority", "integrity"])
def test_final_review_change_discards_rendered_private_html(page, fault):
    changed = (
        replace(page.workspace, organization_label="Changed")
        if fault == "label"
        else PermissionDenied("private")
        if fault == "authority"
        else DatabaseError("private")
    )
    page.loader.side_effect = [page.workspace, changed]
    response = call(page)
    assert response.status_code in {404, 409, 503}
    assert b"Synthetic author" not in response.content


def test_preview_and_confirm_use_signed_original_person_and_request_only(page):
    values = confirmed(page)
    page.submit.assert_not_called()
    assert call(page, values, create=True).status_code == 302
    args = page.submit.call_args.kwargs
    assert args["actor"].id == page.row.author_id
    assert args["details"].approver_id == page.row.approver_id
    assert str(args["idempotency_key"]) == values["idempotency_key"]
    page.command.assert_not_called()


def test_changed_original_selector_is_not_silently_reselected(page):
    values = confirmed(page)
    values["approver_email"] = "other@example.invalid"
    response = call(page, values, create=True)
    assert response.status_code == 400
    page.submit.assert_not_called()


def test_missing_confirmation_preserves_verified_original_preview(page):
    values = confirmed(page)
    values.pop("confirmed")
    response = call(page, values, create=True)
    assert response.status_code == 400
    assert b"Synthetic approver" in response.content
    assert values["idempotency_key"].encode() in response.content
    page.submit.assert_not_called()


def test_uncertain_request_retains_original_proof_key_and_safe_message(page):
    values = confirmed(page)
    page.submit.side_effect = DatabaseError("private database detail")
    response = call(page, values, create=True)
    assert response.status_code == 503
    assert values["idempotency_key"].encode() in response.content
    assert values["selection_proof"].encode() in response.content
    assert b"private database detail" not in response.content


def test_current_production_routes_remain_absent():
    kwargs = {
        "organization_id": SCOPE.organization_id,
        "series_id": SCOPE.series_id,
        "edition_id": SCOPE.edition_id,
    }
    for suffix in ("", "-new", "-request"):
        values = kwargs | ({"request_id": UUID(int=6)} if suffix == "-request" else {})
        url = reverse(
            "programme-volunteer-starter" + suffix, kwargs=values, urlconf=URLCONF
        )
        assert resolve(url, urlconf=URLCONF).kwargs == values
        current = resolve(url, urlconf="maru.urls")
        assert current.func not in {
            views.programme_starter_workspace,
            creation_views.programme_starter_creation,
        }
        assert current.url_name != "programme-volunteer-starter" + suffix


@pytest.mark.parametrize("create", [False, True])
def test_files_and_unsupported_methods_do_not_reach_owner(page, create):
    values = draft() if create else decision()
    values["attachment"] = SimpleUploadedFile("synthetic.txt", b"synthetic")
    assert call(page, values, create=create).status_code == 400
    for method in ("PUT", "DELETE", "PATCH"):
        assert call(page, create=create, method=method).status_code == 405
    page.loader.assert_not_called()
    page.initial.assert_not_called()


@pytest.mark.parametrize("fault", ["label", "authority", "integrity"])
def test_final_creation_change_releases_no_private_html(page, fault):
    changed = (
        replace(page.base, organization_label="Changed")
        if fault == "label"
        else PermissionDenied("private")
        if fault == "authority"
        else DatabaseError("private")
    )
    page.initial.side_effect = [page.base, changed]
    response = call(page, create=True)
    assert response.status_code in {404, 409, 503}
    assert b"Synthetic organization" not in response.content
    page.submit.assert_not_called()


def test_preview_final_recheck_uses_original_proof_never_reselects(page):
    assert call(page, draft(), create=True).status_code == 200
    first, final = page.prepare.call_args_list
    assert "proof" not in first.kwargs
    assert final.kwargs["proof"]
    assert first.kwargs["draft"] == final.kwargs["draft"]


def test_terminal_history_has_no_fresh_decision_form(page):
    page.loader.return_value = replace(
        page.workspace,
        requests=(
            replace(
                page.row,
                state="decline",
                decided_at=NOW,
                can_approve=False,
                can_decline=False,
                can_cancel=False,
            ),
        ),
    )
    response = call(page)
    soup = BeautifulSoup(response.content, "html.parser")
    assert "Declined" in soup.get_text()
    assert not soup.select("select[name=action]")


def test_expired_request_offers_only_decline_and_no_new_planning(page):
    page.loader.return_value = replace(
        page.workspace,
        can_request=False,
        requests=(replace(page.row, state="expired", can_approve=False),),
    )
    response = call(page)
    soup = BeautifulSoup(response.content, "html.parser")
    assert [
        option["value"] for option in soup.select("select[name=action] option")
    ] == ["", "decline"]
    assert "The private planning phase has ended" in soup.get_text()


def test_empty_inventory_is_truthful_and_cannot_accept_decisions(page):
    page.loader.return_value = replace(page.workspace, requests=())
    response = call(page, selected=False)
    assert b"No pending unexpired requests" in response.content
    page.loader.reset_mock()
    assert call(page, decision(), selected=False).status_code == 400
    page.loader.assert_not_called()
    page.command.assert_not_called()
