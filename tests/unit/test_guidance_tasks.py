"""The personal Guides inbox contains only current actionable owner projections."""

import re
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from maru.authorization import guidance_readiness, provenance_readiness
from maru.authorization.guidance_access_queries import GuidanceAccessRequestPage
from maru.events import guidance_activation_queries as owner
from maru.events import guidance_setup_readiness
from maru.identity.models import Account
from maru.knowledge import tasks_views as views


@pytest.fixture
def inbox(monkeypatch):
    setup = SimpleNamespace(request_id=UUID(int=1), can_answer=True, can_apply=False)
    access = SimpleNamespace(request_id=UUID(int=2), can_answer=True)
    setup_query, access_query = (
        Mock(return_value=(setup,)),
        Mock(return_value=GuidanceAccessRequestPage((access,), None)),
    )
    monkeypatch.setattr(views, "list_my_guidance_activation_requests", setup_query)
    monkeypatch.setattr(views, "list_my_guidance_access_requests_page", access_query)
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
    inbox.access_query.return_value = GuidanceAccessRequestPage(tuple(accesses), None)
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
    inbox.access_query.return_value = GuidanceAccessRequestPage((), None)
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


def test_inbox_passes_original_cursor_and_preserves_empty_continuation(inbox):
    inbox.request.GET = RequestFactory().get("/", {"cursor": "original-token"}).GET
    inbox.access_query.return_value = GuidanceAccessRequestPage((), "next-token")
    assert views.guidance_tasks(inbox.request).status_code == 200
    context = inbox.render.call_args.args[1]
    assert context["access_rows"] == ()
    assert context["next_url"].endswith("?cursor=next-token")
    assert context["first_url"] == inbox.request.path
    assert all(
        call.kwargs["cursor"] == "original-token"
        and call.kwargs["pending_only"] is True
        for call in inbox.access_query.call_args_list
    )


def test_changed_access_page_discards_all_rendered_labels(inbox):
    inbox.access_query.side_effect = [
        GuidanceAccessRequestPage((inbox.access,), "next-token"),
        GuidanceAccessRequestPage((), "next-token"),
    ]
    assert views.guidance_tasks(inbox.request).status_code == 409


@pytest.mark.parametrize("query", ["person=someone", "cursor=one&cursor=two"])
def test_inbox_refuses_ambiguous_or_foreign_filters_before_discovery(inbox, query):
    inbox.request.GET = RequestFactory().get("/?" + query).GET
    assert views.guidance_tasks(inbox.request).status_code == 400
    inbox.setup_query.assert_not_called()
    inbox.access_query.assert_not_called()


def test_setup_capacity_does_not_block_independent_live_access_page(inbox):
    inbox.setup_query.side_effect = ValidationError(
        "Too many retained setup requests", code="guidance_setup_capacity"
    )
    assert views.guidance_tasks(inbox.request).status_code == 200
    context = inbox.render.call_args.args[1]
    assert context["setup_unavailable"] is True
    assert context["setup_rows"] == ()
    assert len(context["access_rows"]) == 1
    assert inbox.access_query.call_count == 2


def test_unexpected_setup_owner_failure_keeps_complete_response_closed(inbox):
    inbox.setup_query.side_effect = ValidationError(
        "Private readiness failure", code="integrity_unavailable"
    )
    response = views.guidance_tasks(inbox.request)
    assert response.status_code == 503
    assert b"Private readiness" not in response.content
    inbox.access_query.assert_not_called()
    inbox.render.assert_not_called()


def test_setup_capacity_error_is_a_stable_owner_condition(monkeypatch):
    monkeypatch.setattr(
        guidance_setup_readiness,
        "guidance_setup_database_integrity_is_ready",
        lambda: True,
    )
    query = Mock()
    query.filter.return_value.order_by.return_value.values_list.return_value = tuple(
        UUID(int=index) for index in range(1, 102)
    )
    monkeypatch.setattr(
        owner, "GuidanceActivationRequest", SimpleNamespace(objects=query)
    )
    with pytest.raises(ValidationError) as captured:
        owner.list_my_guidance_activation_requests(
            actor=Account(id=UUID(int=900), is_active=True),
            correlation_id=UUID(int=901),
        )
    assert captured.value.code == "guidance_setup_capacity"


@pytest.mark.parametrize("kind", ["setup", "access"])
@pytest.mark.parametrize("failure_at", [1, 2])
def test_inbox_integrity_failure_discards_initial_or_final_result(
    inbox, monkeypatch, kind, failure_at
):
    ready = Mock(side_effect=[True] * (failure_at - 1) + [False])
    if kind == "setup":
        monkeypatch.setattr(
            guidance_setup_readiness,
            "guidance_setup_database_integrity_is_ready",
            ready,
        )
        gate = guidance_setup_readiness.require_guidance_setup_integrity
        query = inbox.setup_query
    else:
        monkeypatch.setattr(
            guidance_readiness, "guidance_authority_database_integrity_is_ready", ready
        )
        monkeypatch.setattr(
            provenance_readiness,
            "authority_provenance_runtime_contract_is_ready",
            lambda: True,
        )
        gate = guidance_readiness.require_guidance_authority_integrity
        query = inbox.access_query

    def load(**_values):
        gate()
        return query.return_value

    query.side_effect = load
    response = views.guidance_tasks(inbox.request)
    assert response.status_code == 503
    assert b"No partial list" in response.content
    assert b"COMPLETE PERSONAL TASKS" not in response.content
    assert b"protection" not in response.content
    assert ready.call_count == failure_at


@pytest.mark.parametrize("failure_at", [1, 2, 3])
def test_setup_integrity_failure_is_not_filtered_as_an_unavailable_person(
    monkeypatch, failure_at
):
    ready = Mock(side_effect=[True] * (failure_at - 1) + [False])
    monkeypatch.setattr(
        guidance_setup_readiness, "guidance_setup_database_integrity_is_ready", ready
    )
    query = Mock()
    query.filter.return_value.order_by.return_value.values_list.return_value = (
        UUID(int=1),
    )
    monkeypatch.setattr(
        owner, "GuidanceActivationRequest", SimpleNamespace(objects=query)
    )

    def denied(**_values):
        guidance_setup_readiness.require_guidance_setup_integrity()
        raise PermissionDenied("Ordinary participant denial")

    monkeypatch.setattr(owner, "load_guidance_activation_request", denied)
    with pytest.raises(guidance_setup_readiness.GuidanceSetupUnavailable):
        owner.list_my_guidance_activation_requests(
            actor=Account(id=UUID(int=900), is_active=True),
            correlation_id=UUID(int=901),
        )
    assert ready.call_count == failure_at


@pytest.mark.parametrize("failure_at", [1, 2])
def test_setup_discovery_integrity_failure_is_not_a_false_no_work(
    monkeypatch, failure_at
):
    ready = Mock(side_effect=[True] * (failure_at - 1) + [False])
    monkeypatch.setattr(
        guidance_setup_readiness, "guidance_setup_database_integrity_is_ready", ready
    )
    query = Mock()
    selected = query.filter.return_value.exclude.return_value.only.return_value
    selected.order_by.return_value = (SimpleNamespace(id=UUID(int=1)),)
    monkeypatch.setattr(
        owner, "GuidanceActivationRequest", SimpleNamespace(objects=query)
    )

    def denied(*_values):
        guidance_setup_readiness.require_guidance_setup_integrity()
        raise PermissionDenied("Ordinary participant denial")

    monkeypatch.setattr(owner, "_admit_request", denied)
    with pytest.raises(guidance_setup_readiness.GuidanceSetupUnavailable):
        owner.has_current_guidance_activation_tasks(
            actor=Account(id=UUID(int=900), is_active=True),
            correlation_id=UUID(int=901),
        )
    assert ready.call_count == failure_at
