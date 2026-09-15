"""Guided real forms and final-byte disclosure checks without native database proof."""

from dataclasses import replace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup

from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.scheduling import change_notice_views as views
from maru.scheduling.change_notice_selection import (
    NoticeHostChoice,
    NoticeHostSelection,
    NoticeOccurrenceChoice,
)
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.planning_queries import PlanningOccurrence
from maru.scheduling.workspace_navigation import ProgrammeWorkspaceLink
from tests.unit.test_programme_change_notice_commands import (
    world as world,  # noqa: PLC0414
)
from tests.unit.test_programme_change_notice_views import (
    call,
    decision,
    selection,
)
from tests.unit.test_programme_change_notice_views import (
    page as page,  # noqa: PLC0414
)
from tests.unit.test_programme_change_notice_views import (
    shell as shell,  # noqa: PLC0414
)


@pytest.fixture
def guided(page, monkeypatch):
    occurrence = PlanningOccurrence(uuid4(), uuid4(), 1, uuid4(), "active", None, None)
    observation = NoticeHostSelection(
        page.world.preview.release_id,
        2,
        (
            NoticeOccurrenceChoice(
                occurrence, "Opening <ceremony> · occurrence 1", 1, 1
            ),
        ),
        (NoticeHostChoice(uuid4(), "Synthetic <host> · host", uuid4(), 1, 1),),
    )
    loader = Mock(return_value=observation)
    monkeypatch.setattr(views, "load_notice_host_selection", loader)
    return loader


def test_guided_get_uses_labels_and_only_owner_relationship_values(page, guided):
    result = guided.return_value
    response = call(
        page, query=f"?task=hosts&occurrence={result.occurrences[0].occurrence.id}"
    )
    assert response.status_code == 200
    soup = BeautifulSoup(response.content, "html.parser")
    assert len(soup.select("h1")) == len(soup.select("main")) == 1
    assert (
        soup.select_one('select[name="occurrence"] option[selected]').get_text()
        == result.occurrences[0].label
    )
    assert (
        soup.select_one(
            'select[name="target_id"] option[value="'
            + str(result.hosts[0].host_id)
            + '"]'
        ).get_text()
        == result.hosts[0].label
    )
    assert str(result.hosts[0].account_id).encode() not in response.content
    assert b"<ceremony>" not in response.content
    assert b"<host>" not in response.content
    assert soup.select_one('input[name="release_id"]')["type"] == "hidden"
    assert soup.select_one('input[name="purpose"]')["value"] == "host"
    page.preview.assert_not_called()
    for command in page.submit.values():
        command.assert_not_called()
    assert guided.call_count == 2


@pytest.mark.parametrize("empty", ["release", "hosts", "occurrences"])
def test_guided_empty_states_have_no_executable_preview(page, guided, empty):
    observation = guided.return_value
    guided.return_value = replace(
        observation,
        **{
            "release": {"release_id": None, "pointer_version": 0},
            "hosts": {"hosts": ()},
            "occurrences": {"occurrences": (), "hosts": ()},
        }[empty],
    )
    query = "?task=hosts"
    if empty != "occurrences":
        query += f"&occurrence={observation.occurrences[0].occurrence.id}"
    response = call(page, query=query)
    assert response.status_code == 200
    assert b"Preview this host&#x27;s change" not in response.content
    assert not BeautifulSoup(response.content, "html.parser").select(
        'select[name="target_id"]'
    )


@pytest.mark.parametrize(
    "query",
    [
        "?task=unknown",
        "?task=hosts&task=hosts",
        "?task=hosts&occurrence=not-a-uuid",
        f"?task=hosts&notice={uuid4()}",
        f"?occurrence={uuid4()}",
    ],
)
def test_closed_guided_input_does_not_discover_private_choices(page, guided, query):
    assert call(page, query=query).status_code == 400
    guided.assert_not_called()


def test_personal_surface_cannot_select_other_hosts(page, guided):
    assert call(page, query="?task=hosts", personal=True).status_code == 400
    guided.assert_not_called()


@pytest.mark.parametrize(
    "change", ["label", "release", "person", "denied", "unavailable"]
)
def test_guided_final_check_never_releases_moved_or_denied_labels(page, guided, change):
    before = guided.return_value
    after = {
        "label": replace(
            before, occurrences=(replace(before.occurrences[0], label="Moved title"),)
        ),
        "release": replace(before, release_id=uuid4(), pointer_version=3),
        "person": replace(
            before, hosts=(replace(before.hosts[0], account_id=uuid4()),)
        ),
        "denied": ProgrammeAuthorizationDeniedError(),
        "unavailable": SchedulingUnavailableError(),
    }[change]
    guided.side_effect = [before, after]
    response = call(
        page, query=f"?task=hosts&occurrence={before.occurrences[0].occurrence.id}"
    )
    assert response.status_code == {"denied": 404, "unavailable": 503}.get(change, 409)
    assert b"Synthetic" not in response.content
    assert b"Opening" not in response.content


@pytest.mark.parametrize("surface", ["preview", "detail", "personal", "inventory"])
def test_notice_content_is_rechecked_after_actual_template_render(
    page, monkeypatch, surface
):
    original = views.render_to_string

    def render(*args, **kwargs):
        content = original(*args, **kwargs)
        if surface == "inventory":
            page.inventory.return_value = ()
        elif surface == "preview":
            page.preview.return_value = replace(
                page.world.preview, recipient_label="Moved"
            )
        elif surface == "personal":
            page.personal.return_value = replace(page.own, version=8)
        else:
            page.sender.return_value = replace(page.detail, reason="Moved reason")
        return content

    monkeypatch.setattr(views, "render_to_string", render)
    response = call(
        page,
        data=selection(page) if surface == "preview" else None,
        query=f"?notice={page.detail.notice_id}"
        if surface in {"detail", "personal"}
        else "",
        personal=surface == "personal",
    )
    assert response.status_code == 409
    assert page.detail.reason.encode() not in response.content
    assert b"Exact change package" not in response.content


def test_successful_write_is_never_dispatched_twice_for_render_check(page):
    response = call(page, data=decision(page, "handoff"))
    assert response.status_code == 302
    page.submit["handoff"].assert_called_once()
    page.sender.assert_not_called()


def test_moved_optional_navigation_is_removed_without_replacing_forms(
    page, monkeypatch
):
    monkeypatch.setattr(
        views,
        "programme_workspace_links",
        Mock(
            side_effect=[
                (
                    ProgrammeWorkspaceLink(
                        "items", "Programme items", "/synthetic/items/"
                    ),
                ),
                (),
            ]
        ),
    )
    response = call(page, data=selection(page))
    assert response.status_code == 200
    assert b"/synthetic/items/" not in response.content
    soup = BeautifulSoup(response.content, "html.parser")
    assert (
        soup.select_one('input[name="snapshot_digest"]')["value"]
        == page.world.preview.snapshot_digest
    )
    assert len(soup.select('input[name="retry_key"]')) == 1
