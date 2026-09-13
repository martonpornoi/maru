"""Real notice forms and shared-shell HTTP, with governed boundaries stubbed."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.http import QueryDict
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.scheduling import change_notice_views as views
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.change_catalogs import ChangeNoticeReview
from maru.scheduling.change_notice_forms import NoticeAcknowledgeForm
from maru.scheduling.change_notice_queries import (
    PersonalProgrammeChangeNotice,
    ProgrammeChangeNotice,
)
from maru.scheduling.command_support import (
    SchedulingIdempotencyConflictError,
    SchedulingLifecycleConflictError,
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from tests.unit.test_programme_change_notice_commands import (
    world as world,  # noqa: PLC0414
)


@pytest.fixture(autouse=True)
def shell():
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


@pytest.fixture
def page(world, monkeypatch):
    detail = ProgrammeChangeNotice(
        world.notice.id, world.preview, world.state, world.notice.reason
    )
    own = PersonalProgrammeChangeNotice(
        world.notice.id,
        replace(world.preview, recipient_label="You"),
        2,
        handed_off=False,
        acknowledged=False,
    )
    authorize = Mock(return_value=SimpleNamespace(accepts_writes=True))
    monkeypatch.setattr(views, "authorize_scheduling_scope", authorize)
    inventory = Mock(return_value=(detail,))
    sender = Mock(return_value=detail)
    personal = Mock(return_value=own)
    monkeypatch.setattr(views, "load_programme_change_notice_inventory", inventory)
    monkeypatch.setattr(views, "load_programme_change_notice", sender)
    monkeypatch.setattr(views, "load_personal_programme_change_notice", personal)
    preview = Mock(return_value=world.preview)
    monkeypatch.setattr(views, "preview_programme_change_notice", preview)
    submit = {}
    for action, name in {
        "prepare": "prepare_programme_change_notice",
        "review": "review_programme_change_notice",
        "handoff": "handoff_programme_change_notice",
        "acknowledge": "acknowledge_programme_change_notice",
    }.items():
        submit[action] = Mock(return_value=SimpleNamespace(object_id=world.notice.id))
        monkeypatch.setattr(views, name, submit[action])
    return SimpleNamespace(
        world=world,
        detail=detail,
        own=own,
        authorize=authorize,
        inventory=inventory,
        sender=sender,
        personal=personal,
        preview=preview,
        submit=submit,
    )


def call(
    page,
    *,
    data=None,
    query="",
    personal=False,
    anonymous=False,
    csrf=False,
    method=None,
):
    if data is not None:
        encoded = data if isinstance(data, QueryDict) else QueryDict("", mutable=True)
        if not isinstance(data, QueryDict):
            encoded.update(data)
        request = RequestFactory().post(
            "/synthetic/notices/" + query,
            data=encoded.urlencode(),
            content_type="application/x-www-form-urlencoded",
        )
    else:
        request = RequestFactory().generic(
            method or "GET", "/synthetic/notices/" + query
        )
    request.user = (
        AnonymousUser()
        if anonymous
        else SimpleNamespace(
            pk=page.world.request.actor_id,
            is_authenticated=True,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    )
    request._dont_enforce_csrf_checks = not csrf
    view = (
        views.personal_programme_changes if personal else views.programme_change_notices
    )
    return view(
        request,
        organization_id=page.world.request.organization_id,
        edition_id=page.world.request.edition_id,
    )


def selection(page, action="preview"):
    preview = page.world.preview
    data = {
        "action": action,
        "release_id": str(preview.release_id),
        "occurrence_id": str(preview.occurrence_id),
        "purpose": preview.recipient.purpose.value,
        "target_id": str(preview.recipient.target_id),
        "operator_account_id": str(preview.recipient_id),
    }
    if action == "prepare":
        data.update(
            expected_pointer_version=str(preview.pointer_version),
            snapshot_digest=preview.snapshot_digest,
            retry_key=str(UUID(int=90)),
            reason="Synthetic reason",
        )
    return data


def decision(page, action):
    data = {
        "action": action,
        "notice_id": str(page.detail.notice_id),
        "expected_version": "2",
        "snapshot_digest": page.world.preview.snapshot_digest,
        "retry_key": str(UUID(int=91)),
    }
    if action != "acknowledge":
        data["reason"] = "Independent synthetic decision"
    return data


def test_inventory_uses_shared_shell_and_truthful_distinct_states(page):
    response = call(page)
    assert response.status_code == 200
    assert response.content.count(b"<h1>") == 1
    assert response.content.count(b"<main ") == 1
    for phrase in (
        b"Manual communication only",
        b"No manual handoff recorded",
        b"Not acknowledged",
        b"not a delivery-completeness report",
    ):
        assert phrase in response.content
    assert "private" in response["Cache-Control"]
    assert "no-store" in response["Cache-Control"]
    assert "nonce-" in response["Content-Security-Policy"]
    assert "form-action 'self'" in response["Content-Security-Policy"]
    assert page.inventory.call_args.args[0].actor_id == page.world.request.actor_id


def test_personal_detail_does_not_render_reason_actors_or_reason_control(page):
    response = call(page, personal=True, query=f"?notice={page.detail.notice_id}")
    assert response.status_code == 200
    assert page.world.notice.reason.encode() not in response.content
    assert str(page.world.state.preparer_id).encode() not in response.content
    assert b'name="reason"' not in response.content
    assert b"Acknowledge exact change" in response.content
    assert "reason" not in NoticeAcknowledgeForm.base_fields
    assert b"No manual handoff recorded" in response.content
    page.sender.assert_not_called()


def test_preview_does_not_mutate_and_preparation_binds_displayed_source(page):
    response = call(page, data=selection(page))
    assert response.status_code == 200
    assert b"Comparison is suppressed" in response.content
    assert page.world.preview.snapshot_digest.encode() in response.content
    for command in page.submit.values():
        command.assert_not_called()
    response = call(page, data=selection(page, "prepare"))
    assert response.status_code == 302
    assert response["Location"] == f"/synthetic/notices/?notice={page.detail.notice_id}"
    command, intent = page.submit["prepare"].call_args.args
    assert command.actor_id == page.world.request.actor_id
    assert command.idempotency_key == UUID(int=90)
    assert intent.snapshot_digest == page.world.preview.snapshot_digest
    assert intent.expected_pointer_version == page.world.preview.pointer_version


@pytest.mark.parametrize("action", ["approve", "reject", "handoff", "acknowledge"])
def test_each_action_delegates_exact_intent_to_its_governed_boundary(page, action):
    response = call(page, data=decision(page, action), personal=action == "acknowledge")
    assert response.status_code == 302
    command = page.submit["review" if action in {"approve", "reject"} else action]
    actual, intent = command.call_args.args
    assert actual.actor_id == page.world.request.actor_id
    assert intent.notice_id == page.detail.notice_id
    assert intent.expected_version == 2
    assert intent.snapshot_digest == page.world.preview.snapshot_digest
    if action == "acknowledge":
        assert not hasattr(actual, "reason")
        assert command.call_args.kwargs["idempotency_key"] == UUID(int=91)
    if action in {"approve", "reject"}:
        assert command.call_args.kwargs["action"].value == action


@pytest.mark.parametrize(
    "extra",
    [
        "reason",
        "actor_id",
        "recipient_id",
        "operator_account_id",
        "approved",
        "message",
    ],
)
def test_personal_input_rejects_other_people_reasons_or_authority(page, extra):
    data = decision(page, "acknowledge") | {extra: "PRIVATE ATTACK"}
    response = call(page, data=data, personal=True)
    assert response.status_code == 400
    assert b"PRIVATE ATTACK" not in response.content
    page.submit["acknowledge"].assert_not_called()


@pytest.mark.parametrize("action", ["prepare", "approve", "handoff", "preview"])
def test_personal_adapter_has_no_organizer_action(page, action):
    response = call(page, data={"action": action}, personal=True)
    assert response.status_code == 400
    for command in page.submit.values():
        command.assert_not_called()


@pytest.mark.parametrize(
    "query", ["?actor_id=private", "?notice=bad", "?release=a&release=b"]
)
def test_denial_precedes_private_input_parsing_or_discovery(page, query):
    page.authorize.side_effect = SchedulingAuthorizationDeniedError
    response = call(page, query=query)
    assert response.status_code == 404
    page.inventory.assert_not_called()
    assert b"private" not in response.content


@pytest.mark.parametrize(
    "error",
    [
        SchedulingVersionConflictError,
        SchedulingLifecycleConflictError,
        SchedulingIdempotencyConflictError,
    ],
)
def test_stale_mutations_never_replace_the_submitted_version_or_show_old_content(
    page, error
):
    page.submit["handoff"].side_effect = error
    response = call(page, data=decision(page, "handoff"))
    assert response.status_code == 409
    assert page.world.preview.snapshot_digest.encode() not in response.content
    page.sender.assert_not_called()
    assert page.submit["handoff"].call_args.args[1].expected_version == 2


@pytest.mark.parametrize(
    "error", [SchedulingUnavailableError, SchedulingLimitError, RuntimeError]
)
def test_failed_inventory_discloses_no_partial_detail(page, error):
    page.inventory.side_effect = error
    response = call(page)
    assert response.status_code == 503
    assert str(page.detail.notice_id).encode() not in response.content
    assert page.world.notice.reason.encode() not in response.content


def test_independent_review_and_rejection_controls_are_not_inferred(page):
    page.sender.return_value = replace(
        page.detail,
        state=replace(page.detail.state, preparer_id=page.world.request.actor_id),
    )
    response = call(page, query=f"?notice={page.detail.notice_id}")
    assert b"Approve package" not in response.content
    page.sender.return_value = replace(
        page.detail,
        state=replace(
            page.detail.state,
            review=ChangeNoticeReview.REJECTED,
            reviewer_id=UUID(int=71),
            version=2,
        ),
    )
    response = call(page, query=f"?notice={page.detail.notice_id}")
    assert b"This package was rejected" in response.content
    assert b"Record my manual handoff" not in response.content
    assert b"Recipient-only acknowledgement link" not in response.content


def test_read_only_authority_hides_actions_but_does_not_substitute_for_command_policy(
    page,
):
    def authorize(**kwargs):
        if kwargs["capability_code"] not in {
            views.VIEW_CHANGE_NOTICES,
            views.VIEW_CHANGE_SELF,
        }:
            raise SchedulingAuthorizationDeniedError
        return SimpleNamespace(accepts_writes=True)

    page.authorize.side_effect = authorize
    response = call(page, query=f"?notice={page.detail.notice_id}")
    assert response.status_code == 200
    assert b"Approve package" not in response.content
    response = call(page, data=decision(page, "approve"))
    assert response.status_code == 404
    page.submit["review"].assert_not_called()


def test_validation_keeps_safe_reason_and_exact_retry_key(page):
    data = selection(page, "prepare") | {"expected_pointer_version": "02"}
    response = call(page, data=data)
    assert response.status_code == 400
    assert b"Synthetic reason" in response.content
    assert str(UUID(int=90)).encode() in response.content
    page.submit["prepare"].assert_not_called()


def test_duplicate_actions_and_host_person_substitution_are_rejected(page):
    data = QueryDict("action=preview&action=prepare", mutable=True)
    assert call(page, data=data).status_code == 400
    data = selection(page) | {"purpose": "host"}
    assert call(page, data=data).status_code == 400
    page.preview.assert_not_called()


def test_hostile_content_is_escaped_and_never_made_executable(page):
    page.sender.return_value = replace(
        page.detail, reason='<script>alert("x")</script>'
    )
    response = call(page, query=f"?notice={page.detail.notice_id}")
    assert b'<script>alert("x")' not in response.content
    assert b"&lt;script&gt;" in response.content


def test_reused_shell_context_cannot_retain_prior_detail_on_denial(page):
    response = call(page, query=f"?notice={page.detail.notice_id}")
    assert page.world.notice.reason.encode() in response.content
    page.authorize.side_effect = SchedulingAuthorizationDeniedError
    denied = call(page)
    assert denied.status_code == 404
    assert page.world.notice.reason.encode() not in denied.content
    assert str(page.detail.notice_id).encode() not in denied.content


def test_manual_package_shares_only_a_recipient_link_not_organizer_rationale(page):
    page.sender.return_value = replace(
        page.detail,
        state=replace(
            page.detail.state,
            review=ChangeNoticeReview.APPROVED,
            reviewer_id=UUID(int=71),
            version=2,
        ),
    )
    response = call(page, query=f"?notice={page.detail.notice_id}")
    soup = BeautifulSoup(response.content, "html.parser")
    message = soup.find("textarea", id="notice-manual-message")
    assert message is not None
    assert message.has_attr("readonly")
    assert page.world.notice.reason not in message.get_text()
    assert "http://testserver/my/" in message.get_text()
    assert str(page.detail.notice_id) in message.get_text()


def test_login_csrf_and_method_boundaries_precede_source_discovery(page):
    assert call(page, anonymous=True).status_code == 302
    assert call(page, data=decision(page, "approve"), csrf=True).status_code == 403
    assert call(page, method="DELETE").status_code == 405
    page.authorize.assert_not_called()


def test_new_component_routes_remain_dormant(page):
    scope = f"{page.world.request.organization_id}/{page.world.request.edition_id}"
    for url in (
        f"/admin/programme/changes/{scope}/",
        f"/my/{scope}/programme-changes/",
    ):
        try:
            matched = resolve(url)
        except Resolver404:
            continue
        assert matched.func not in {
            views.programme_change_notices,
            views.personal_programme_changes,
        }
