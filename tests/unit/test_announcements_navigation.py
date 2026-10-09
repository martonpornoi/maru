"""Standalone discovery remains profile-bound and independently authorized."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.contrib.auth.forms import AuthenticationForm
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import resolve, reverse

from maru.announcements.errors import AnnouncementDeniedError
from maru.core import navigation
from maru.events.admin_context import ADMIN_EDITION_SESSION_KEY
from maru.events.announcements_workspace_queries import AnnouncementsWorkspaceReference
from maru.events.models import EventEdition
from maru.identity.models import Account
from maru.organizations.models import ConventionSeries, Organization


def reference():
    return AnnouncementsWorkspaceReference(
        UUID(int=1),
        UUID(int=2),
        "Synthetic organizer",
        "Synthetic convention",
        "Synthetic edition",
        "announcements_only",
        1,
    )


def test_announcements_route_registry_keeps_scope_group_and_words(monkeypatch):
    scope = reference()
    url = reverse(
        "announcements-inventory", args=(scope.organization_id, scope.edition_id)
    )
    request = RequestFactory().get(url)
    request.user = Account(
        id=UUID(int=3), email="synthetic@example.test", is_active=True
    )
    authorize = Mock()
    monkeypatch.setattr(navigation, "authorize_announcements_scope", authorize)
    items = navigation._announcements_route_items(
        request, {"announcements_scope": scope}
    )
    assert len(items) == 1
    assert items[0].current
    assert (
        items[0].context_label
        == "Synthetic organizer / Synthetic convention / Synthetic edition"
    )
    assert items[0].profile_destination_kind == "edition.announcements"
    assert navigation._present_navigation_item(items[0]).section == "Overview"
    assert "social" in items[0].search_text
    assert authorize.call_args.args[0].edition_id == scope.edition_id


def test_other_profiles_and_revoked_access_cannot_discover_announcements(monkeypatch):
    request = RequestFactory().get("/admin/")
    request.user = Account(
        id=UUID(int=3), email="synthetic@example.test", is_active=True
    )
    authorize = Mock(side_effect=AnnouncementDeniedError)
    monkeypatch.setattr(navigation, "authorize_announcements_scope", authorize)
    assert (
        navigation._announcements_destinations(
            request, replace(reference(), profile_code="workforce_only")
        )
        == []
    )
    authorize.assert_not_called()
    assert navigation._announcements_destinations(request, reference()) == []


def test_shipped_and_baseline_route_sets_resolve_canonical_setup_and_workspace():
    for urlconf in ("maru.urls", "maru.baseline_urls"):
        assert (
            resolve(
                "/admin/platform/setup/announcements/new/", urlconf=urlconf
            ).url_name
            == "announcements-setup-new"
        )
        assert (
            resolve(
                f"/admin/announcements/{UUID(int=1)}/{UUID(int=2)}/", urlconf=urlconf
            ).url_name
            == "announcements-inventory"
        )


@pytest.fixture
def shell(monkeypatch):
    scope = reference()
    url = reverse(
        "announcements-inventory", args=(scope.organization_id, scope.edition_id)
    )
    request = RequestFactory().get(url)
    request.resolver_match = resolve(url)
    request.user = Account(
        id=UUID(int=3), email="synthetic@example.test", is_active=True
    )
    request.session = {}
    options = {"selected": None}
    authorize = Mock()
    monkeypatch.setattr(navigation, "authorize_announcements_scope", authorize)
    monkeypatch.setattr(
        navigation, "admin_shell_access", lambda _request: {"workspace_available": True}
    )
    monkeypatch.setattr(navigation, "admin_edition_options", lambda _request: options)
    monkeypatch.setattr(navigation, "resolve_edition_target", lambda **_kwargs: None)
    monkeypatch.setattr(
        navigation, "decide", lambda **_kwargs: SimpleNamespace(allowed=False)
    )
    monkeypatch.setattr(navigation, "navigation_pin_codes", lambda **_kwargs: ())
    for name in (
        "_personal_items",
        "_scoped_organization_items",
        "_page_context_items",
        "_platform_items",
        "_specialist_items",
        "_programme_destinations",
    ):
        monkeypatch.setattr(navigation, name, lambda *_args, **_kwargs: [])
    return SimpleNamespace(
        request=request, scope=scope, options=options, authorize=authorize
    )


def shell_items(shell, value):
    result = navigation.project_shell_navigation(
        shell.request,
        page_context={"announcements_scope": value},
        personal_surface=False,
    )
    return {item.code: item for group in result["groups"] for item in group["items"]}


def test_announcements_deep_link_filters_generic_work_without_selecting_event(shell):
    items = shell_items(shell, shell.scope)
    code = f"edition.{shell.scope.edition_id}.announcements"
    assert set(items) == {"work.security", code}
    assert items[code].current
    assert items[code].context_label.endswith("Synthetic edition")
    assert shell.request.session == {}
    shell.authorize.assert_called_once()
    assert (
        shell.authorize.call_args.args[0].organization_id == shell.scope.organization_id
    )
    assert shell.authorize.call_args.args[0].edition_id == shell.scope.edition_id


def test_route_filter_preserves_other_selected_event_destinations_and_context(shell):
    organization = Organization(
        id=UUID(int=10), name="Other organizer", slug="other-organizer"
    )
    series = ConventionSeries(
        id=UUID(int=11),
        organization=organization,
        name="Other series",
        slug="other-series",
    )
    edition = EventEdition(
        id=UUID(int=12),
        organization=organization,
        series=series,
        name="Other event",
        slug="other-event",
        adoption_profile_code="full_convention",
        adoption_profile_version=1,
    )
    shell.options.update(
        selected=edition,
        selected_can_view_structure=True,
        selected_can_manage_registration=True,
    )
    shell.request.session[ADMIN_EDITION_SESSION_KEY] = str(edition.id)
    before = dict(shell.request.session)
    items = shell_items(shell, shell.scope)
    route_code = f"edition.{shell.scope.edition_id}.announcements"
    assert set(items) == {
        "work.security",
        route_code,
        f"edition.{edition.id}.structure",
        f"edition.{edition.id}.registration",
    }
    assert items[route_code].current
    for code, route_name in (
        (f"edition.{edition.id}.structure", "organization-structure"),
        (f"edition.{edition.id}.registration", "registration-setup"),
    ):
        assert (
            items[code].context_label == "Other organizer / Other series / Other event"
        )
        assert not items[code].current
        assert items[code].url == reverse(
            route_name, args=(organization.slug, series.slug, edition.slug)
        )
    assert shell.request.session == before


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        replace(reference(), edition_id="not-an-edition"),
        replace(reference(), organization_id=UUID(int=0)),
        replace(reference(), profile_code="full_convention"),
        replace(reference(), profile_version=2),
        replace(reference(), profile_version=True),
    ],
)
def test_malformed_or_unsupported_route_reference_adds_no_scoped_items(shell, value):
    assert shell_items(shell, value) == {}
    shell.authorize.assert_not_called()
    assert shell.request.session == {}


def test_foreign_route_reference_does_not_disclose_labels_or_add_authority(shell):
    foreign = replace(
        shell.scope, organization_id=UUID(int=91), organization_name="Foreign organizer"
    )
    shell.authorize.side_effect = AnnouncementDeniedError
    items = shell_items(shell, foreign)
    assert set(items) == {"work.security"}
    assert not any("Foreign organizer" in item.context_label for item in items.values())
    shell.authorize.assert_called_once()
    assert shell.authorize.call_args.args[0].organization_id == foreign.organization_id
    assert shell.request.session == {}


def test_login_copy_uses_plain_account_language_and_preserves_return_destination():
    html = render_to_string(
        "core/login.html",
        {"form": AuthenticationForm(), "next": "/synthetic-convention-task/"},
    )
    assert "<title>Sign in · Maru</title>" in html
    assert '<button type="submit">Sign in</button>' in html
    assert "Sign in to continue your convention work and manage your account." in html
    assert "Use your account's email address or username." in html
    assert 'name="next" value="/synthetic-convention-task/"' in html
    assert 'autocomplete="username"' in html
    assert 'autocomplete="current-password"' in html
    assert "rehearsal" not in html.casefold()
