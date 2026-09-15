"""Actual operator-entry HTML and final-render denial without database access."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.db import DatabaseError
from django.test import RequestFactory
from django.urls import resolve

from maru.scheduling import operator_entry_views as views
from maru.scheduling import output_navigation
from maru.scheduling.operator_scope import OperatorScopeKind
from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink
from tests.unit import test_programme_operator_entry as queries
from tests.unit.test_application_programme_call_views import shell
from tests.unit.test_programme_operator_entry import world

__all__ = ["shell", "world"]


@pytest.fixture
def page(world, monkeypatch):
    monkeypatch.setattr(views, "uuid4", lambda: world.scope.correlation_id)
    monkeypatch.setattr(output_navigation, "_operator", Mock())
    monkeypatch.setattr(output_navigation, "_adapter", Mock())
    navigation = Mock(return_value=())
    monkeypatch.setattr(views, "programme_workspace_links", navigation)
    return world, navigation


def request_page(world, *, method="get", suffix="", actor=None):
    scope = world.scope
    request = getattr(RequestFactory(), method)(
        f"/admin/programme/run-sheets/{scope.organization_id}/{scope.edition_id}/"
        + suffix
    )
    request.user = SimpleNamespace(
        pk=actor if actor is not None else scope.actor_id,
        is_authenticated=True,
        is_active=True,
        is_staff=False,
    )
    request.session = {}
    request.urlconf = "maru.scheduling.output_urls"
    return views.operator_entry(
        request, organization_id=scope.organization_id, edition_id=scope.edition_id
    )


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
def test_real_query_and_html_offer_only_exact_default_scope_links(page, kind):
    world, _navigation = page
    _kind, target = queries.allow(world, kind)
    response = request_page(world)
    assert response.status_code == 200
    document = BeautifulSoup(response.content, "html.parser")
    assert len(document.select("h1")) == 1
    assert len(document.select("main")) == 1
    assert len(document.select("details > summary")) == 1
    links = document.select(".operator-run-sheet li a")
    assert len(links) == 2
    for link in links:
        assert "?" not in link["href"]
        result = resolve(link["href"], urlconf="maru.scheduling.output_urls")
        assert result.kwargs == {
            "organization_id": world.scope.organization_id,
            "edition_id": world.scope.edition_id,
            "scope_kind": kind.value,
            "target_id": target,
        }
    assert not document.select(".operator-run-sheet form")
    assert "private, no-store" in response["Cache-Control"]
    assert "nonce-" in response["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]


def test_empty_is_explicit_without_hidden_names(page):
    world, _ = page
    response = request_page(world)
    assert response.status_code == 200
    assert b"No on-site Programme purposes" in response.content
    assert b"Room 1" not in response.content
    assert b"Convention Hotel" not in response.content


@pytest.mark.parametrize(
    ("method", "suffix", "status"),
    [("post", "", 405), ("get", "?technical=1", 400), ("get", "?actor=other", 400)],
)
def test_transport_does_not_accept_writes_or_unselected_layers(
    page, method, suffix, status
):
    world, _ = page
    assert request_page(world, method=method, suffix=suffix).status_code == status
    world.actor.assert_not_called()


def test_zero_principal_is_denied_before_discovery(page):
    world, _ = page
    assert request_page(world, actor=UUID(int=0)).status_code == 404
    world.actor.assert_not_called()


@pytest.mark.parametrize("change", ["label", "authority", "audit"])
def test_final_render_rechecks_actual_query_and_withholds_old_bytes(
    page, monkeypatch, change
):
    world, _ = page
    kind, target = queries.allow(world)
    original = views.render_to_string

    def render(*args, **kwargs):
        content = original(*args, **kwargs)
        if change == "label":
            world.room_labels[target] = replace(
                world.room_labels[target], label="Changed after render"
            )
        elif change == "authority":
            world.grants[(kind, target, queries.entry._OWNERS[0][0])] = queries.DENIED
        else:
            world.audit.side_effect = DatabaseError
        return content

    monkeypatch.setattr(views, "render_to_string", render)
    response = request_page(world)
    assert response.status_code == 503
    assert b"Room 1" not in response.content
    assert b"Convention Hotel" not in response.content


def test_optional_links_can_disappear_without_replacing_catalog(page):
    world, navigation = page
    queries.allow(world)
    navigation.side_effect = [
        (ProgrammeWorkspaceLink("items", "Programme items", "/synthetic-items/"),),
        (),
    ]
    response = request_page(world)
    assert response.status_code == 200
    assert b"Room 1" in response.content
    assert b"/synthetic-items/" not in response.content
    assert b"output links are currently unavailable" in response.content
    assert world.audit.call_count == 6


def test_markup_labels_are_escaped_and_route_stays_dormant(page):
    world, _ = page
    _kind, target = queries.allow(world)
    world.room_labels[target] = replace(
        world.room_labels[target], label="<script>untrusted</script>"
    )
    response = request_page(world)
    assert b"&lt;script&gt;untrusted&lt;/script&gt;" in response.content
    assert b"<script>untrusted</script>" not in response.content
    resolved = resolve(
        f"/admin/programme/run-sheets/{world.scope.organization_id}/{world.scope.edition_id}/"
    )
    assert resolved.view_name != "programme-operator-entry"
    assert resolved.func != views.operator_entry
