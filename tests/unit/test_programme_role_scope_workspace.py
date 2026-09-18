"""Real reserved chooser HTML; owner boundaries are explicitly stubbed, not native."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import NoReverseMatch, Resolver404, resolve

from maru.authorization import programme_role_scope_views as views
from maru.authorization import programme_role_views as review
from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_scope_choices import (
    ProgrammeRoleScopeCatalog,
    ProgrammeRoleScopeChoice,
)
from tests.unit.test_programme_role_scope_choices import (
    CONTEXT,
    DEPARTMENT,
    EDITION,
    ORG,
    PERSON,
    ROOM,
)

URLCONF = "maru.authorization.programme_role_urls"
ROUTE = f"/admin/programme/access/{ORG}/{EDITION}/"
CATALOG = ProgrammeRoleScopeCatalog(
    "Synthetic convention",
    tuple(
        ProgrammeRoleScopeChoice(replace(CONTEXT, level=level, **extra), label)
        for level, label, extra in (
            (ScopeLevel.ORGANIZATION, "Synthetic organizer", {}),
            (ScopeLevel.EDITION, "Synthetic edition", {}),
            (
                ScopeLevel.DEPARTMENT,
                "Synthetic department",
                {"department_id": DEPARTMENT},
            ),
            (
                ScopeLevel.RESOURCE,
                "Synthetic room",
                {
                    "department_id": DEPARTMENT,
                    "resource_binding_id": ROOM,
                    "resource_kind": "venue.edition_space",
                },
            ),
        )
    ),
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
    loader = Mock(return_value=CATALOG)
    monkeypatch.setattr(views, "load_programme_role_scope_choices", loader)
    return loader


def request(method="GET", query="", body="", user=PERSON):
    value = RequestFactory().generic(method, ROUTE + query, data=body)
    value.user = user
    value.urlconf = URLCONF
    return value


def call(**changes):
    return views.programme_role_scopes(request(**changes), ORG, EDITION)


def test_real_shared_shell_lists_exact_labelled_destinations_and_broader_warning(page):
    response = call()
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.find_all("h1")) == len(soup.find_all("main")) == 1
    cards = soup.select(".programme-cards > li")
    assert len(cards) == 4
    assert "broader than this edition" in cards[0].get_text()
    assert "named approver must decide in their own session" in soup.get_text()
    assert not soup.select('input[name="department_id"], input[name="actor_id"]')
    for card, choice in zip(cards, CATALOG.choices, strict=True):
        assert card.h2.get_text() == choice.label
        for link in card.find_all("a"):
            assert choice.label in link["aria-label"]
            match = resolve(link["href"], urlconf=URLCONF)
            assert match.kwargs["organization_id"] == ORG
            assert match.kwargs["edition_id"] == EDITION
            assert match.kwargs["level"] == choice.scope.level.value
            assert match.kwargs.get("department_id") == choice.scope.department_id
            assert (
                match.kwargs.get("resource_binding_id")
                == choice.scope.resource_binding_id
            )
    assert page.call_count == 2
    assert response["Cache-Control"].startswith("private, no-store")
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert response["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "HEAD"])
def test_read_only_methods_never_call_owner(page, method):
    assert call(method=method).status_code == 405
    page.assert_not_called()


@pytest.mark.parametrize(
    "changes", [{"query": "?scope=other"}, {"body": "actor=other"}]
)
def test_no_scope_override_or_body_is_accepted(page, changes):
    assert call(**changes).status_code == 400
    page.assert_not_called()


def test_anonymous_redirects_without_read(page):
    with patch("django.shortcuts.resolve_url", return_value="/staff/login/"):
        assert call(user=AnonymousUser()).status_code == 302
    page.assert_not_called()


def test_non_account_principal_is_neutral_denial(page):
    assert call(user=SimpleNamespace(is_authenticated=True)).status_code == 404
    page.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PermissionDenied("secret"), 404),
        (ValidationError("secret overflow"), 503),
        (DatabaseError("secret"), 503),
    ],
)
@pytest.mark.parametrize("at_final", [False, True])
def test_failure_before_or_after_render_withholds_all_names(
    page, error, status, at_final
):
    page.side_effect = [CATALOG, error] if at_final else error
    response = call()
    assert response.status_code == status
    assert b"Synthetic" not in response.content
    assert b"secret" not in response.content
    assert response["Cache-Control"].startswith("private, no-store")


def test_source_change_discards_rendered_private_html(page):
    page.side_effect = [CATALOG, replace(CATALOG, choices=CATALOG.choices[1:])]
    response = call()
    assert response.status_code == 409
    assert b"Synthetic" not in response.content


def test_narrow_scope_displays_no_sibling_card_or_broader_warning(page):
    page.return_value = replace(CATALOG, choices=(CATALOG.choices[-1],))
    soup = BeautifulSoup(call().content, "html.parser")
    assert len(soup.select(".programme-cards > li")) == 1
    assert "Synthetic room" in soup.get_text()
    assert "Synthetic organizer" not in soup.get_text()
    assert "Shared organization-wide" not in soup.get_text()


def test_untrusted_labels_are_escaped(page):
    page.return_value = replace(
        CATALOG, context_label='<script>alert("context")</script>'
    )
    response = call()
    assert b'<script>alert("context")</script>' not in response.content
    assert b"&lt;script&gt;" in response.content


@pytest.mark.parametrize("error", [NoReverseMatch(), Resolver404()])
def test_missing_or_unmounted_destination_has_no_partial_list(page, monkeypatch, error):
    monkeypatch.setattr(views, "resolve", Mock(side_effect=error))
    response = call()
    assert response.status_code == 503
    assert b"Synthetic" not in response.content


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("url_name", "catchall"),
        ("func", lambda _request: HttpResponse()),
        ("kwargs", {}),
    ],
)
def test_same_url_does_not_admit_wrong_handler_name_or_scope(
    page, monkeypatch, field, value
):
    actual = resolve(ROUTE + "organization/", urlconf=URLCONF)
    fake = SimpleNamespace(
        url_name=actual.url_name, func=actual.func, kwargs=actual.kwargs
    )
    setattr(fake, field, value)
    monkeypatch.setattr(views, "resolve", Mock(return_value=fake))
    assert call().status_code == 503


def test_missing_backlink_is_not_rendered_as_dead_destination(monkeypatch):
    assert review._scope_choices_url(request(), CONTEXT) == ROUTE
    monkeypatch.setattr(review, "reverse", Mock(side_effect=NoReverseMatch()))
    assert review._scope_choices_url(request(), CONTEXT) == ""


def test_wrong_backlink_handler_is_not_rendered(monkeypatch):
    monkeypatch.setattr(
        review,
        "resolve",
        Mock(
            return_value=SimpleNamespace(
                url_name="programme-access-scopes", func=lambda: None, kwargs={}
            )
        ),
    )
    assert review._scope_choices_url(request(), CONTEXT) == ""


def test_oversized_render_never_releases_partial_html(page, monkeypatch):
    monkeypatch.setattr(
        views, "render_to_string", Mock(return_value="Synthetic" * (300 * 1024))
    )
    response = call()
    assert response.status_code == 503
    assert b"Synthetic" not in response.content


def test_reserved_chooser_route_is_not_mounted_in_production():
    assert resolve(ROUTE, urlconf=URLCONF).func is views.programme_role_scopes
    try:
        production = resolve(ROUTE, urlconf="maru.urls")
    except Resolver404:
        return
    assert production.func is not views.programme_role_scopes
