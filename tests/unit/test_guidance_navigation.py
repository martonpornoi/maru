"""Guide discovery uses exact profiles, route scope and independent capabilities."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from maru.announcements.errors import AnnouncementDeniedError
from maru.core import navigation
from maru.events.knowledge_workspace_queries import KnowledgeWorkspaceReference
from maru.identity.models import Account
from maru.knowledge.errors import GuidanceDeniedError


@pytest.fixture
def reference():
    return KnowledgeWorkspaceReference(
        UUID(int=1),
        UUID(int=2),
        "Synthetic organizer",
        "Synthetic convention",
        "Synthetic edition",
        "Europe/Budapest",
        "guidance_only",
        1,
    )


@pytest.fixture
def request_actor():
    request = RequestFactory().get("/admin/")
    request.user = Account(
        id=UUID(int=3), email="synthetic@example.test", is_active=True
    )
    return request


@pytest.mark.parametrize("working_only", [False, True])
def test_current_reader_or_working_reader_can_find_their_own_guides(
    reference, request_actor, monkeypatch, working_only
):
    authorize = Mock(
        side_effect=[GuidanceDeniedError(), None] if working_only else None
    )
    monkeypatch.setattr(navigation, "authorize_guidance_scope", authorize)
    items = navigation._guidance_destinations(request_actor, reference)
    assert len(items) == 1
    assert items[0].label == "Guides"
    assert items[0].section == "Overview"
    assert items[0].url == reverse(
        "guidance-inventory", args=(reference.organization_id, reference.edition_id)
    )
    assert (
        items[0].context_label
        == "Synthetic organizer / Synthetic convention / Synthetic edition"
    )
    assert [entry.kwargs["capability"] for entry in authorize.call_args_list] == (
        ["knowledge.view_current", "knowledge.view_working"]
        if working_only
        else ["knowledge.view_current"]
    )
    assert all(
        entry.args[0].actor_id == request_actor.user.id
        for entry in authorize.call_args_list
    )


@pytest.mark.parametrize(
    ("code", "version"),
    [
        ("guidance_only", 2),
        ("guidance_only", True),
        ("announcements_only", 1),
        ("full_convention", 1),
        ("unknown", 1),
    ],
)
def test_unadopted_or_malformed_profile_never_queries_guidance_authority(
    reference, request_actor, monkeypatch, code, version
):
    authorize = Mock()
    monkeypatch.setattr(navigation, "authorize_guidance_scope", authorize)
    assert (
        navigation._guidance_destinations(
            request_actor,
            replace(reference, profile_code=code, profile_version=version),
        )
        == []
    )
    authorize.assert_not_called()


def test_revocation_removes_guide_discovery(reference, request_actor, monkeypatch):
    monkeypatch.setattr(
        navigation, "authorize_guidance_scope", Mock(side_effect=GuidanceDeniedError)
    )
    assert navigation._guidance_destinations(request_actor, reference) == []


def test_combined_route_does_not_turn_guides_access_into_announcements_access(
    reference, request_actor, monkeypatch
):
    combined = replace(reference, profile_code="announcements_guidance")
    monkeypatch.setattr(navigation, "authorize_guidance_scope", Mock())
    announcements = Mock(side_effect=AnnouncementDeniedError)
    monkeypatch.setattr(navigation, "authorize_announcements_scope", announcements)
    items = navigation._guidance_route_items(
        request_actor, {"guidance_scope": combined}
    )
    assert [item.label for item in items] == ["Guides"]
    assert announcements.call_args.args[0].edition_id == combined.edition_id


def test_guidance_route_context_keeps_generic_unadopted_work_hidden(
    reference, request_actor, monkeypatch
):
    monkeypatch.setattr(
        navigation, "admin_shell_access", lambda _request: {"workspace_available": True}
    )
    monkeypatch.setattr(
        navigation,
        "admin_edition_options",
        Mock(
            side_effect=AssertionError(
                "Route scope must precede selected-event fallback"
            )
        ),
    )
    items = navigation._management_items(
        request_actor, page_context={"guidance_scope": reference}
    )
    assert [(item.code, item.profile_destination_kind) for item in items] == [
        ("work.security", "work.security")
    ]


@pytest.mark.parametrize(
    "available",
    [
        False,
        None,
        1,
        "true",
        True,
        navigation.GuidanceTaskDiscovery(has_current_work=False, access_cursor=None),
        navigation.GuidanceTaskDiscovery(has_current_work=True, access_cursor=None),
        navigation.GuidanceTaskDiscovery(
            has_current_work=False, access_cursor="signed-next"
        ),
    ],
)
def test_personal_decisions_require_actual_current_task_admission(
    request_actor, monkeypatch, available
):
    query = Mock(return_value=available)
    monkeypatch.setattr(navigation, "discover_guidance_tasks", query)
    items = navigation.guidance_decision_items(request_actor)
    assert [item.code for item in items] == (
        ["my.guidance-decisions"]
        if isinstance(available, navigation.GuidanceTaskDiscovery)
        and (available.has_current_work or available.access_cursor)
        else []
    )
    assert query.call_args.kwargs["actor"] is request_actor.user
    assert navigation.guidance_decision_items(request_actor) == items
    query.assert_called_once()


@pytest.mark.parametrize(
    "error",
    [navigation.PermissionDenied, navigation.ValidationError, navigation.DatabaseError],
)
def test_unavailable_personal_decisions_do_not_break_ordinary_navigation(
    request_actor, monkeypatch, error
):
    monkeypatch.setattr(
        navigation,
        "discover_guidance_tasks",
        Mock(side_effect=error("Private failure")),
    )
    assert navigation.guidance_decision_items(request_actor) == []


def test_inactive_person_has_no_guidance_decision_lookup(request_actor, monkeypatch):
    request_actor.user.is_active = False
    query = Mock()
    monkeypatch.setattr(navigation, "discover_guidance_tasks", query)
    assert navigation.guidance_decision_items(request_actor) == []
    query.assert_not_called()


def test_unexamined_candidates_use_truthful_signed_personal_continuation(
    request_actor, monkeypatch
):
    monkeypatch.setattr(
        navigation,
        "discover_guidance_tasks",
        Mock(
            return_value=navigation.GuidanceTaskDiscovery(
                has_current_work=False, access_cursor="signed-next"
            )
        ),
    )
    (item,) = navigation.guidance_decision_items(request_actor)
    assert item.label == "Check Guides requests"
    assert "cursor=signed-next" in item.url
    assert "Some may no longer be available" in item.description


def test_home_continuation_does_not_claim_an_unproved_pending_decision(
    request_actor, monkeypatch
):
    monkeypatch.setattr(
        navigation,
        "discover_guidance_tasks",
        Mock(
            return_value=navigation.GuidanceTaskDiscovery(
                has_current_work=False, access_cursor="signed-next"
            )
        ),
    )
    template_request = RequestFactory().get("/my/")
    template_request.user = AnonymousUser()
    template_request.session = {}
    html = render_to_string(
        "core/my_maru.html",
        {
            "request": template_request,
            "maru_personal_surface": True,
            "guidance_decisions": navigation.guidance_decision_items(request_actor),
        },
    )
    assert "Guides requests</h2>" in html
    assert "Check Guides requests" in html
    assert "Some may no longer be available" in html
    assert "Waiting for your decision" not in html
