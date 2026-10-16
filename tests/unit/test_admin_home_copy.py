"""The first organizer page explains tasks before technical profile details."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.template import Context
from django.template.loader import get_template
from django.template.loader_tags import BlockNode
from django.test import RequestFactory
from django.urls import reverse

from maru.announcements.errors import AnnouncementDeniedError
from maru.core import navigation
from maru.core.navigation import NavigationItem
from maru.events.adoption import adoption_profile
from maru.events.announcements_workspace_queries import AnnouncementsWorkspaceReference
from maru.events.templatetags.admin_edition_context import maru_home_navigation
from maru.identity.models import Account


def _render_home(
    monkeypatch, profile, *, request=None, items=(), selected=True, workspace=True
):
    if request is None:
        monkeypatch.setattr(
            "maru.events.templatetags.admin_edition_context.project_shell_navigation",
            lambda *_a, **_kw: {"groups": ({"items": items},)},
        )
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.admin_edition_options",
        lambda _request: {
            "selected": SimpleNamespace(name="Synthetic event") if selected else None,
            "selected_profile": profile,
        },
    )
    template = get_template("admin/index.html").template
    content = next(
        block
        for block in template.nodelist.get_nodes_by_type(BlockNode)
        if block.name == "content"
    )
    return content.render(
        Context(
            {
                "request": request
                or SimpleNamespace(
                    user=SimpleNamespace(is_platform_administrator=False)
                ),
                "maru_shell_access": {"workspace_available": workspace},
            }
        )
    )


def _item(code, *, kind="destination", pinned=False):
    return NavigationItem(
        code=code,
        label={"work.workforce": "Team workspace", "work.setup": "Setup guide"}.get(
            code, code
        ),
        url="/admitted/" + code + "/",
        section="Pinned" if pinned else "Overview",
        description="Authorized destination",
        profile_destination_kind=code,
        kind=kind,
        pinned=pinned,
    )


@pytest.mark.parametrize("profile_code", ["full_convention", "workforce_only"])
def test_supported_home_uses_admitted_links_and_secondary_setup(
    monkeypatch, profile_code
):
    profile = adoption_profile(profile_code, 1)
    assert profile is not None
    html = _render_home(
        monkeypatch, profile, items=(_item("work.workforce"), _item("work.setup"))
    )

    introduction, disclosure = html.split(
        '<details class="maru-admin-profile-details">', 1
    )
    details, _rest = disclosure.split("</details>", 1)
    assert "Work on Synthetic event" in introduction
    assert profile.description not in introduction
    assert "<summary>Technical setup details</summary>" in details
    assert html.count(profile.description) == 1
    assert "<summary>Setup steps</summary>" in html
    assert "Team workspace" in html
    assert 'href="/admitted/work.workforce/"' in html
    assert 'href="/admitted/work.setup/"' in html
    assert html.index("Team workspace") < html.index("Setup steps")
    assert "Continue setup" not in html
    assert "Continue setting up" not in html
    assert "Registration desk" not in html


@pytest.mark.parametrize("profile_code", ["full_convention", "workforce_only"])
def test_profile_alone_does_not_create_home_permissions(monkeypatch, profile_code):
    html = _render_home(monkeypatch, adoption_profile(profile_code, 1))
    assert "No work tools are available on this home for your current access." in html
    assert "Setup steps" not in html
    assert "Team workspace" not in html
    assert "Nothing to do" not in html
    assert reverse("management-console") not in html


@pytest.mark.parametrize("platform", [False, True])
def test_no_event_has_safe_role_specific_recovery(monkeypatch, platform):
    items = (_item("platform.organizations"),) if platform else ()
    html = _render_home(monkeypatch, None, selected=False, items=items)
    assert "Choose an event" in html
    assert "Use Change event at the top of the page" in html
    assert "ask an event organizer to check your access" in html
    assert ("Open Organizations" in html) is platform
    assert ('href="/admitted/platform.organizations/"' in html) is platform
    assert "Continue convention setup" not in html
    assert "Setup steps" not in html


def test_no_workspace_does_not_project_work_or_platform_links(monkeypatch):
    html = _render_home(
        monkeypatch,
        None,
        selected=False,
        workspace=False,
        items=(_item("platform.organizations"),),
    )
    assert "Your Maru account" in html
    assert "ask its organizer to check your access" in html
    assert "/admitted/" not in html


def test_home_projection_retains_exact_scoped_urls_and_reauthorized_pins():
    guide = NavigationItem(
        code="edition.synthetic.guidance",
        label="Guides",
        url="/admin/guidance/exact-organization/exact-edition/",
        section="Pinned",
        profile_destination_kind="edition.guidance",
        pinned=True,
    )
    setup = _item("work.setup")
    registry = {
        "groups": (
            {"items": (guide,)},
            {
                "items": (
                    setup,
                    _item("record.secret"),
                    _item("work.people", kind="action"),
                )
            },
        )
    }
    projected = maru_home_navigation(registry, object())
    assert projected["work"] == (guide,)
    assert projected["work"][0] is guide
    assert projected["setup"] == (setup,)
    assert maru_home_navigation(registry, None)["work"] == ()
    assert maru_home_navigation(registry, None)["setup"] == ()
    assert maru_home_navigation({"groups": ()}, object())["work"] == ()


def test_home_does_not_read_or_disclose_admin_log_history():
    template = get_template("admin/index.html").template
    sidebar = next(
        block
        for block in template.nodelist.get_nodes_by_type(BlockNode)
        if block.name == "sidebar"
    )
    assert sidebar.render(Context({})) == ""


def test_unknown_home_setup_explains_next_step_without_offering_unavailable_work(
    monkeypatch,
):
    html = _render_home(monkeypatch, None)

    assert "This event uses tools that this version of Maru cannot open." in html
    assert "Choose another event or ask an administrator to check its setup." in html
    assert "adoption profile" not in html
    assert "Technical setup details" not in html
    assert "Continue setup" not in html
    assert "Team workspace" not in html
    assert "Registration desk" not in html


@pytest.mark.parametrize(
    ("profile_code", "profile_version", "allowed", "active", "pinned", "visible"),
    [
        ("announcements_only", 1, True, True, False, True),
        ("announcements_only", 1, True, True, True, True),
        ("announcements_only", 1, False, True, True, False),
        ("announcements_only", 1, True, False, False, False),
        ("announcements_only", 2, True, True, False, False),
        ("workforce_only", 1, True, True, False, False),
        ("full_convention", 1, True, True, False, False),
    ],
)
def test_home_announcements_continuation_reuses_current_authorized_registry(
    monkeypatch, profile_code, profile_version, allowed, active, pinned, visible
):
    scope = AnnouncementsWorkspaceReference(
        UUID(int=1),
        UUID(int=2),
        "Synthetic organizer",
        "Synthetic convention",
        "Synthetic event",
        profile_code,
        profile_version,
    )
    request = RequestFactory().get("/admin/")
    request.user = Account(
        id=UUID(int=3), email="synthetic@example.invalid", is_active=active
    )
    authorize = Mock(side_effect=None if allowed else AnnouncementDeniedError)
    monkeypatch.setattr(navigation, "authorize_announcements_scope", authorize)
    # Keep the real profile/current-authority projection and template tag;
    # unrelated owner menus are outside this home-composition check.
    for name in (
        "_personal_items",
        "_management_items",
        "_scoped_organization_items",
        "_page_context_items",
        "_platform_items",
        "_specialist_items",
    ):
        monkeypatch.setattr(navigation, name, lambda *_a, **_kw: [])
    monkeypatch.setattr(
        navigation,
        "_selected_edition_items",
        lambda current_request: navigation._announcements_destinations(
            current_request, scope
        ),
    )
    monkeypatch.setattr(
        navigation,
        "navigation_pin_codes",
        lambda **_kw: (f"edition.{scope.edition_id}.announcements",) if pinned else (),
    )

    html = _render_home(
        monkeypatch,
        adoption_profile(profile_code, profile_version),
        request=request,
    )
    url = reverse(
        "announcements-inventory", args=(scope.organization_id, scope.edition_id)
    )

    assert html.count(f'href="{url}"') == int(visible)
    assert ("<strong>Announcements</strong>" in html) is visible
    if visible:
        assert "Work on Synthetic event" in html
        assert "Choose a tool to continue your event work." in html
        assert "Registration desk" not in html
        assert "Team workspace" not in html
    if profile_code == "announcements_only" and profile_version == 1 and active:
        authorize.assert_called_once()
        call = authorize.call_args
        assert call.args[0].actor_id == request.user.id
        assert call.args[0].organization_id == scope.organization_id
        assert call.args[0].edition_id == scope.edition_id
        assert call.kwargs == {"capability": "announcements.view"}
    else:
        authorize.assert_not_called()
