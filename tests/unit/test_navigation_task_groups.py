"""Task grouping preserves the already-authorized registry and current route."""

from dataclasses import replace

import pytest
from django.template.loader import render_to_string
from django.test import RequestFactory

from maru.core import navigation
from maru.core.navigation import NavigationItem
from maru.identity.models import Account


@pytest.mark.parametrize(
    ("code", "section", "label"),
    [
        ("work.today", "Overview", "Original label"),
        ("work.people", "People & teams", "Original label"),
        ("work.workforce", "People & teams", "Original label"),
        ("work.reports", "Registration & shop", "Original label"),
        ("edition.synthetic.registration", "Registration & shop", "Original label"),
        ("edition.synthetic.catalog", "Registration & shop", "Shop & orders"),
        ("edition.synthetic.application-studio", "Applications", "Application forms"),
        ("edition.synthetic.application-review", "Applications", "Review applications"),
        ("edition.synthetic.logistics", "Places & equipment", "Equipment & storage"),
        ("edition.synthetic.venues", "Places & equipment", "Original label"),
        ("edition.synthetic.overview", "Settings", "Event settings"),
        ("organization.synthetic.representation", "Settings", "Original label"),
        ("platform.accounts", "Settings", "Original label"),
        ("record.identity.account", "Advanced records", "Original label"),
        ("my.workforce", "Personal", "Original label"),
    ],
)
def test_task_presentation_preserves_route_scope_and_authorization_fields(
    code, section, label
):
    original = NavigationItem(
        code=code,
        label="Original label",
        url="/already-authorized/",
        section="Personal",
        context_label="Synthetic event",
        description="Authorized description",
        keywords=("existing keyword",),
        profile_destination_kind="exact.existing.kind",
        current=True,
        pinnable=False,
    )

    item = navigation._present_navigation_item(original)

    assert item.section == section
    assert item.label == label
    assert item.code == original.code
    assert item.url == original.url
    assert item.profile_destination_kind == original.profile_destination_kind
    assert item.current is True
    assert item.pinnable is False
    assert item.context_label == (
        "Platform" if code.startswith("platform.") else original.context_label
    )
    assert "existing keyword" in item.search_text
    assert "Original label" in item.search_text


def _project(monkeypatch, items, pins=()):
    request = RequestFactory().get("/admin/")
    request.user = Account(email="synthetic@example.test", is_active=True)
    monkeypatch.setattr(navigation, "_personal_items", lambda *_a, **_kw: [])
    monkeypatch.setattr(navigation, "_management_items", lambda *_a, **_kw: items)
    for name in (
        "_selected_edition_items",
        "_scoped_organization_items",
        "_page_context_items",
        "_platform_items",
        "_specialist_items",
    ):
        monkeypatch.setattr(navigation, name, lambda *_a, **_kw: [])
    monkeypatch.setattr(navigation, "navigation_pin_codes", lambda **_kw: pins)
    return navigation.project_shell_navigation(
        request, page_context={}, personal_surface=False
    )


def test_groups_keep_all_authorized_items_once_and_mark_the_current_group(monkeypatch):
    codes = (
        "work.today",
        "work.setup",
        "work.people",
        "work.workforce",
        "edition.synthetic.registration",
        "edition.synthetic.application-studio",
        "edition.synthetic.logistics",
        "platform.accounts",
        "organization.synthetic.representation",
        "record.identity.account",
    )
    items = [
        NavigationItem(code, code, f"/{code}/", "Original", current="logistics" in code)
        for code in codes
    ]

    result = _project(monkeypatch, items, pins=("work.workforce", "revoked.pin"))
    groups = {group["label"]: group for group in result["groups"]}

    assert tuple(groups) == (
        "Pinned",
        "Overview",
        "People & teams",
        "Registration & shop",
        "Applications",
        "Places & equipment",
        "Settings",
        "Advanced records",
    )
    projected = [item for group in groups.values() for item in group["items"]]
    assert sorted(item.code for item in projected) == sorted(codes)
    assert len(projected) == result["count"]
    assert [item.code for item in groups["Pinned"]["items"]] == ["work.workforce"]
    assert groups["Overview"]["collapsed"] is False
    assert groups["Settings"]["collapsed"] is True
    assert groups["Places & equipment"]["collapsed"] is True
    assert groups["Places & equipment"]["current"] is True
    assert groups["Advanced records"]["current"] is False


def test_current_creation_stays_visible_and_actions_remain_unpinnable(monkeypatch):
    action = NavigationItem(
        "platform.accounts-invite",
        "Invite account",
        "/invite/",
        "Platform",
        current=True,
    )

    result = _project(monkeypatch, [action])

    group = result["groups"][0]
    assert group["label"] == "Actions"
    assert group["search_only"] is True
    assert group["current"] is True
    assert group["items"][0].pinnable is False
    assert (
        navigation._present_navigation_item(
            replace(action, kind="action", section="Actions")
        ).section
        == "Actions"
    )


def test_same_task_in_two_event_contexts_keeps_both_labels_and_one_current_link(
    monkeypatch,
):
    items = [
        NavigationItem(
            "edition.selected.registration",
            "Registration",
            "/selected-event/registration/",
            "Convention",
            context_label="Selected synthetic event",
        ),
        NavigationItem(
            "edition.routed.registration",
            "Registration",
            "/routed-event/registration/",
            "Convention",
            context_label="Routed synthetic event",
            current=True,
        ),
    ]
    projection = _project(monkeypatch, items)
    monkeypatch.setattr(
        "maru.events.templatetags.admin_edition_context.project_shell_navigation",
        lambda *_a, **_kw: projection,
    )

    html = render_to_string(
        "admin/nav_sidebar.html",
        {
            "request": RequestFactory().get("/routed-event/registration/"),
            "csrf_token": "synthetic-token",
        },
    )

    assert html.count("data-navigation-item\n") == 2
    assert 'href="/selected-event/registration/"' in html
    assert 'href="/routed-event/registration/"' in html
    assert 'class="maru-navigation-context">Selected synthetic event</small>' in html
    assert 'class="maru-navigation-context">Routed synthetic event</small>' in html
    assert html.count('aria-current="page"') == 1
