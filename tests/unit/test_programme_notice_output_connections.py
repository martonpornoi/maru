"""Real notice views connect only the actual viewer's independently admitted outputs."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

from django.test import override_settings

from maru.scheduling import change_notice_views as views
from maru.scheduling import output_navigation as navigation
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.change_catalogs import ChangeRecipientPurpose
from maru.scheduling.change_inputs import ChangeRecipientSelection
from tests.unit.test_programme_change_notice_views import call, selection
from tests.unit.test_programme_change_notice_views import page as page  # noqa: PLC0414
from tests.unit.test_programme_change_notice_views import (
    shell as shell,  # noqa: PLC0414
)
from tests.unit.test_programme_change_notice_views import (
    world as world,  # noqa: PLC0414
)


def operator_preview(page):
    recipient = uuid4()
    preview = replace(
        page.world.preview,
        recipient=ChangeRecipientSelection(
            ChangeRecipientPurpose.ROOM, uuid4(), recipient
        ),
        recipient_id=recipient,
    )
    page.world.preview = preview
    page.preview.return_value = preview
    return preview


def test_sender_preview_links_use_sender_not_selected_recipient(page, monkeypatch):
    preview = operator_preview(page)
    admit = Mock()
    monkeypatch.setattr(navigation, "_admit", admit)
    monkeypatch.setattr(views, "programme_workspace_links", Mock(return_value=()))
    with override_settings(ROOT_URLCONF="tests.support.programme_output_urls"):
        response = call(page, data=selection(page))
    assert response.status_code == 200
    assert b"Current operator run sheet" in response.content
    assert b"Operator now and next" in response.content
    assert b"Choose another operator scope" in response.content
    assert admit.call_count == 6  # three destinations, before and after rendering
    assert {args.args[1] for args in admit.call_args_list} == {
        "entry",
        "timetable",
        "now",
    }
    for args in admit.call_args_list:
        scope = args.args[0]
        assert scope.actor_id == page.world.request.actor_id
        assert scope.actor_id != preview.recipient.operator_account_id
        assert scope.target_id == preview.recipient.target_id
        assert scope.layers == ()
    for writer in page.submit.values():
        writer.assert_not_called()


def test_sender_authority_alone_does_not_offer_operator_output(page, monkeypatch):
    operator_preview(page)
    monkeypatch.setattr(
        navigation, "_admit", Mock(side_effect=SchedulingAuthorizationDeniedError)
    )
    monkeypatch.setattr(views, "programme_workspace_links", Mock(return_value=()))
    with override_settings(ROOT_URLCONF="tests.support.programme_output_urls"):
        response = call(page, data=selection(page))
    assert response.status_code == 200
    assert b"Programme output tasks" not in response.content
    assert b"/admin/programme/run-sheets/" not in response.content


def test_late_navigation_loss_does_not_redispatch_notice_preparation(page, monkeypatch):
    operator_preview(page)
    page.sender.return_value = replace(page.detail, preview=page.world.preview)
    admit = Mock(
        side_effect=[
            None,
            None,
            None,
            SchedulingAuthorizationDeniedError,
            SchedulingAuthorizationDeniedError,
            SchedulingAuthorizationDeniedError,
        ]
    )
    monkeypatch.setattr(navigation, "_admit", admit)
    monkeypatch.setattr(views, "programme_workspace_links", Mock(return_value=()))
    with override_settings(ROOT_URLCONF="tests.support.programme_output_urls"):
        response = call(page, data=selection(page, action="prepare"))
        assert response.status_code == 302
        response = call(page, query=f"?notice={page.detail.notice_id}")
    assert response.status_code == 200
    assert b"Programme output tasks" not in response.content
    page.submit["prepare"].assert_called_once()


def test_genuine_person_notice_links_cannot_use_another_person(page, monkeypatch):
    page.own = replace(
        page.own,
        preview=replace(
            page.own.preview,
            recipient=ChangeRecipientSelection(ChangeRecipientPurpose.HOST, uuid4()),
            recipient_id=page.world.request.actor_id,
        ),
    )
    page.personal.return_value = page.own
    admit = Mock()
    monkeypatch.setattr(navigation, "_admit", admit)
    with override_settings(ROOT_URLCONF="tests.support.programme_output_urls"):
        response = call(page, personal=True, query=f"?notice={page.own.notice_id}")
    assert response.status_code == 200
    assert b"My current hosting and work timetable" in response.content
    assert b"My Programme now and next" in response.content
    assert all(
        args.args[0].actor_id == page.world.request.actor_id
        for args in admit.call_args_list
    )
