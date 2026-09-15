"""Real chooser HTML revalidates complete owner evidence after final rendering."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from bs4 import BeautifulSoup
from django.test import RequestFactory
from django.urls import Resolver404, resolve

from maru.identity.queries import ActiveVerifiedPersonReference
from maru.scheduling import personal_discovery_views as views
from maru.scheduling import personal_navigation as navigation
from tests.unit.test_application_programme_call_views import shell
from tests.unit.test_personal_timetable_discovery import world

__all__ = ["shell", "world"]


def page(world, method="get", suffix="", actor=None):
    request = getattr(RequestFactory(), method)("/my/programme/timetables/" + suffix)
    request.user = SimpleNamespace(
        pk=world.actor if actor is None else actor,
        is_authenticated=True,
        is_active=True,
        is_staff=False,
    )
    request.session = {}
    request.urlconf = "tests.support.programme_personal_urls"
    return views.personal_timetable_editions(request)


def test_real_query_html_minimal_labels_current_route_and_security(world):
    response = page(world)
    assert response.status_code == 200
    document = BeautifulSoup(response.content, "html.parser")
    assert len(document.select("h1")) == len(document.select("main")) == 1
    assert len(document.select("details > summary")) == 1
    link = document.select_one(".personal-agenda a")
    assert link.get_text() == "Example 2026"
    target = resolve(link["href"], urlconf="tests.support.programme_personal_urls")
    assert target.view_name == "my-hosting-work-timetable"
    assert target.kwargs == {
        "organization_id": world.organization,
        "edition_id": world.edition,
    }
    assert b"Codes: example / con / 2026" in response.content
    assert not document.select(".personal-timetable form")
    assert "no-store" in response["Cache-Control"]
    assert "frame-ancestors 'none'" in response["Content-Security-Policy"]
    assert world.mocks["append_audit"].call_count == 4


@pytest.mark.parametrize(
    ("method", "suffix", "status"),
    [
        ("post", "", 405),
        ("get", "?actor=other", 400),
        ("get", "?edition=x", 400),
        ("head", "", 200),
    ],
)
def test_closed_safe_transport(world, method, suffix, status):
    assert page(world, method, suffix).status_code == status
    if status != 200:
        world.mocks["personal_host_scope_candidates"].assert_not_called()


def test_zero_actor_never_discovers(world):
    assert page(world, actor=UUID(int=0)).status_code == 404
    world.mocks["personal_host_scope_candidates"].assert_not_called()


def test_empty_and_unavailable_are_distinct(world):
    for name in ("personal_host_scope_candidates", "personal_shift_scope_candidates"):
        mock = world.mocks[name]
        mock.return_value = replace(mock.return_value, scopes=())
    response = page(world)
    assert response.status_code == 200
    assert b"No retained timetable purposes" in response.content
    assert b"Example 2026" not in response.content


@pytest.mark.parametrize(
    "changed", ["labels", "permission", "audit", "candidate", "route"]
)
def test_after_final_render_movement_releases_no_original_labels(
    world, monkeypatch, changed
):
    original = views.render_to_string

    def render(*args, **kwargs):
        content = original(*args, **kwargs)
        if changed == "labels":
            mock = world.mocks["resolve_personal_timetable_edition_choice"]
            mock.return_value = replace(mock.return_value, name="Moved")
        elif changed == "permission":
            world.mocks["authorize_personal_timetable_scope"].side_effect = views.Denied
        elif changed == "audit":
            world.mocks["append_audit"].side_effect = RuntimeError("audit failed")
        elif changed == "candidate":
            mock = world.mocks["personal_host_scope_candidates"]
            mock.return_value = replace(mock.return_value, scopes=())
        else:
            monkeypatch.setattr(views, "resolve", Mock(side_effect=Resolver404))
        return content

    monkeypatch.setattr(views, "render_to_string", render)
    response = page(world)
    assert response.status_code == 503
    assert b"Example" not in response.content


def test_html_escapes_owner_labels(world):
    mock = world.mocks["resolve_personal_timetable_edition_choice"]
    mock.return_value = replace(mock.return_value, name="<script>Example</script>")
    response = page(world)
    assert response.status_code == 200
    assert b"&lt;script&gt;Example&lt;/script&gt;" in response.content
    assert b"<script>Example</script>" not in response.content


def test_chooser_is_not_in_production_routes():
    with pytest.raises(Resolver404):
        resolve("/my/programme/timetables/", urlconf="maru.urls")


def test_return_link_uses_actual_person_without_purpose_inventory(world, monkeypatch):
    person = Mock(return_value=ActiveVerifiedPersonReference(world.actor))
    monkeypatch.setattr(navigation, "resolve_active_verified_person_reference", person)
    monkeypatch.setattr(
        navigation,
        "authorize_programme_self_entry_scope",
        Mock(side_effect=navigation.ApplicationsProgrammeAuthorizationDeniedError),
    )
    monkeypatch.setattr(
        navigation,
        "authorize_programme_scope",
        Mock(side_effect=navigation.ProgrammeAuthorizationDeniedError),
    )
    links = navigation.personal_programme_task_links(
        actor_id=world.actor,
        organization_id=world.organization,
        edition_id=world.edition,
        current="timetable",
        urlconf="tests.support.programme_personal_urls",
    )
    assert [link.code for link in links] == ["editions"]
    assert (
        resolve(links[0].url, urlconf="tests.support.programme_personal_urls").kwargs
        == {}
    )
    person.assert_called_once_with(account_id=world.actor)
    world.mocks["personal_host_scope_candidates"].assert_not_called()
