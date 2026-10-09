"""The personal Guides inbox contains only current actionable owner projections."""

import re
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from maru.identity.models import Account
from maru.knowledge import tasks_views as views


@pytest.fixture
def inbox(monkeypatch):
    setup = SimpleNamespace(request_id=UUID(int=1), can_answer=True, can_apply=False)
    access = SimpleNamespace(request_id=UUID(int=2), can_answer=True)
    setup_query, access_query = (
        Mock(return_value=(setup,)),
        Mock(return_value=(access,)),
    )
    monkeypatch.setattr(views, "list_my_guidance_activation_requests", setup_query)
    monkeypatch.setattr(views, "list_my_guidance_access_requests", access_query)
    monkeypatch.setattr(views.admin.site, "each_context", lambda _request: {})
    render = Mock(return_value="COMPLETE PERSONAL TASKS")
    monkeypatch.setattr(views, "render_to_string", render)
    request = RequestFactory().get("/admin/guidance-tasks/")
    request.user = Account(
        id=UUID(int=3), email="synthetic@example.invalid", is_active=True
    )
    return SimpleNamespace(
        setup=setup,
        access=access,
        setup_query=setup_query,
        access_query=access_query,
        render=render,
        request=request,
    )


def test_inbox_rechecks_both_owners_and_uses_the_actual_person(inbox):
    response = views.guidance_tasks(inbox.request)
    assert response.status_code == 200
    for query in (inbox.setup_query, inbox.access_query):
        assert query.call_count == 2
        assert all(
            call.kwargs["actor"] is inbox.request.user for call in query.call_args_list
        )
    context = inbox.render.call_args.args[1]
    assert len(context["setup_rows"]) == len(context["access_rows"]) == 1
    assert "guidance_scope" not in context


def test_inbox_renders_explicit_links_with_unique_card_context(inbox, monkeypatch):
    setups, accesses = [], []
    for index in (1, 2):
        setups.append(
            SimpleNamespace(
                request_id=UUID(int=10 + index),
                can_answer=True,
                can_apply=False,
                edition_name=f"Synthetic Foxglove {2026 + index}",
                organization_name="Synthetic organizer team",
            )
        )
        accesses.append(
            SimpleNamespace(
                request_id=UUID(int=20 + index),
                can_answer=True,
                edition_name=f"Synthetic Foxglove {2026 + index}",
                recipient=SimpleNamespace(label=f"Synthetic Reader {index}"),
                requested_by=SimpleNamespace(label="Synthetic Juniper"),
            )
        )
    inbox.setup_query.return_value = tuple(setups)
    inbox.access_query.return_value = tuple(accesses)
    monkeypatch.setattr(views, "render_to_string", render_to_string)
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.admin_shell_access",
        lambda _request: {"workspace_available": False},
    )
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.admin_edition_options",
        lambda _request: {},
    )
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.project_shell_navigation",
        lambda *_args, **_kwargs: {},
    )

    response = views.guidance_tasks(inbox.request)
    assert response.status_code == 200
    rendered = response.content.decode()
    assert "Review each request before deciding." in rendered
    assert "Your setup requests" in rendered
    assert "Your own records" in rendered
    assert "proposal" not in rendered.lower()
    cards = dict(
        re.findall(r'<li aria-labelledby="([^"]+)">(.*?)</li>', rendered, re.DOTALL)
    )
    assert len(cards) == 4
    for group, items, label, route in (
        ("setup", setups, "Review setup request", "guidance-activation-detail"),
        ("access", accesses, "Review access request", "guidance-access-detail"),
    ):
        for index, item in enumerate(items, 1):
            heading_id = f"{group}-request-{index}"
            card = cards[heading_id]
            assert rendered.count(f'id="{heading_id}"') == 1
            assert f'<h3 id="{heading_id}">' in card
            assert "<h3><a" not in card
            destination = reverse(route, kwargs={"request_id": item.request_id})
            assert (
                f'<p class="guidance-actions"><a href="{destination}" '
                f'aria-describedby="{heading_id}">{label}</a></p>'
            ) in card


def test_inbox_omits_own_waiting_and_already_answered_items(inbox):
    inbox.setup_query.return_value = (
        SimpleNamespace(request_id=UUID(int=4), can_answer=False, can_apply=False),
    )
    inbox.access_query.return_value = (
        SimpleNamespace(request_id=UUID(int=5), can_answer=False),
    )
    assert views.guidance_tasks(inbox.request).status_code == 200
    context = inbox.render.call_args.args[1]
    assert context["setup_rows"] == context["access_rows"] == ()


def test_one_owner_failure_releases_no_partial_other_task_list(inbox):
    inbox.access_query.side_effect = ValidationError("Private dependency detail")
    response = views.guidance_tasks(inbox.request)
    assert response.status_code == 503
    assert b"Private dependency" not in response.content
    inbox.render.assert_not_called()


def test_final_task_change_does_not_release_the_old_action_link(inbox):
    inbox.setup_query.side_effect = [(inbox.setup,), ()]
    response = views.guidance_tasks(inbox.request)
    assert response.status_code == 409
    assert b"COMPLETE PERSONAL TASKS" not in response.content


def test_personal_inbox_rejects_post_without_any_owner_query(inbox):
    inbox.request.method = "POST"
    assert views.guidance_tasks(inbox.request).status_code == 405
    inbox.setup_query.assert_not_called()
    inbox.access_query.assert_not_called()
