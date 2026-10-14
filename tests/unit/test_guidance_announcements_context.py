"""Optional current-guide context cannot widen Announcements disclosure."""

from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError
from django.urls import reverse

from maru.announcements import views
from maru.knowledge.contracts import GuidanceCurrentSummary
from maru.knowledge.errors import GuidanceDeniedError, GuidanceNotAvailableError
from tests.unit.test_announcements_forms import (
    announcement_settings as announcement_settings,  # noqa: PLC0414
)
from tests.unit.test_announcements_views import call
from tests.unit.test_announcements_views import page as page  # noqa: PLC0414


@pytest.fixture
def guide():
    return GuidanceCurrentSummary(
        UUID(int=101),
        UUID(int=102),
        "How to announce a lounge closure",
        "en",
        1,
        datetime(2026, 10, 9, tzinfo=UTC),
        date(2027, 1, 1),
        review_due=False,
        owner_label="Guides team for this event",
    )


def _combined(page, monkeypatch):
    reference = replace(page.reference, profile_code="announcements_guidance")
    monkeypatch.setattr(
        views, "announcements_workspace_reference", Mock(return_value=reference)
    )
    return reference


@pytest.mark.parametrize("action", ["new", "edit"])
def test_writer_context_rechecks_current_guides_before_releasing_html(
    page, guide, monkeypatch, action
):
    _combined(page, monkeypatch)
    query = Mock(return_value=SimpleNamespace(items=(guide,)))
    monkeypatch.setattr(views, "load_context_guidance", query)
    response = call(page, action)
    assert response.status_code == 200
    assert b"Guides for this task" in response.content
    assert guide.title.encode() in response.content
    assert (
        reverse(
            "guidance-current",
            args=(page.reference.organization_id, page.reference.edition_id, guide.id),
        ).encode()
        in response.content
    )
    assert query.call_count == 2
    for invocation in query.call_args_list:
        scope = invocation.args[0]
        assert scope.actor_id == page.last_request.user.id
        assert scope.organization_id == page.reference.organization_id
        assert scope.edition_id == page.reference.edition_id
        assert invocation.kwargs == {"context": "announcements.compose", "limit": 3}


@pytest.mark.parametrize(
    "failure", [GuidanceDeniedError, GuidanceNotAvailableError, DatabaseError]
)
def test_unavailable_guides_do_not_disclose_or_block_announcement_writing(
    page, monkeypatch, failure
):
    _combined(page, monkeypatch)
    monkeypatch.setattr(views, "load_context_guidance", Mock(side_effect=failure))
    response = call(page, "new")
    assert response.status_code == 200
    assert b"Guides for this task" not in response.content
    assert b"Write an announcement" in response.content


@pytest.mark.parametrize("action", ["new", "edit", "detail", "review", "settings"])
def test_announcements_only_never_queries_unadopted_guidance(page, monkeypatch, action):
    query = Mock(side_effect=AssertionError("Unadopted owner must not be queried"))
    monkeypatch.setattr(views, "load_context_guidance", query)
    call(page, action)
    query.assert_not_called()


@pytest.mark.parametrize("change", ["withdrawn", "replaced", "revoked"])
def test_changed_context_discards_prepared_html_instead_of_leaking_stale_title(
    page, guide, monkeypatch, change
):
    _combined(page, monkeypatch)
    later = SimpleNamespace(items=())
    if change == "replaced":
        later = SimpleNamespace(
            items=(replace(guide, revision_id=UUID(int=103), number=2),)
        )
    if change == "revoked":
        later = GuidanceDeniedError()
    monkeypatch.setattr(
        views,
        "load_context_guidance",
        Mock(side_effect=[SimpleNamespace(items=(guide,)), later]),
    )
    response = call(page, "new")
    assert response.status_code == 409
    assert guide.title.encode() not in response.content
    assert b"Reload before continuing" in response.content
