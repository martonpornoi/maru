"""Sender-authorized host selection never becomes recipient impersonation."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.programme import change_recipient_queries as queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.host_queries import (
    ProgrammeHostReadRequest,
    ProgrammeHostRosterEntry,
    ProgrammeHostRosterSnapshot,
    ProgrammeHostStateProjection,
)
from maru.programme.queries import ProgrammeQueryUnavailableError


@pytest.fixture
def world(monkeypatch):
    request = ProgrammeHostReadRequest(*(UUID(int=n) for n in range(1, 6)))
    host = ProgrammeHostStateProjection(UUID(int=6), "host", "confirmed", 3, 2)
    selected = ProgrammeHostRosterEntry(
        host, UUID(int=7), person_current=True, display_label="Selected host"
    )
    other = ProgrammeHostRosterEntry(
        replace(host, host_id=UUID(int=8)),
        UUID(int=9),
        person_current=True,
        display_label="Other person not selected",
    )
    roster = Mock(return_value=ProgrammeHostRosterSnapshot(4, (selected, other)))
    monkeypatch.setattr(queries, "load_programme_host_roster", roster)
    return SimpleNamespace(
        request=request, host=host, selected=selected, other=other, roster=roster
    )


def test_exact_sender_request_and_one_minimized_confirmed_recipient(world):
    result = queries.load_host_change_recipient(
        world.request, host_id=world.host.host_id
    )
    world.roster.assert_called_once_with(world.request)
    assert world.request.actor_id != result.account_id
    assert result.item_id == world.request.item_id
    assert result.item_version == 4
    assert result.relationship == world.host
    assert result.display_label == "Selected host"
    assert set(asdict(result)) == {
        "item_id",
        "item_version",
        "account_id",
        "display_label",
        "relationship",
    }
    assert "Other person" not in repr(result)


@pytest.mark.parametrize(
    "error", [ProgrammeAuthorizationDeniedError, ProgrammeQueryUnavailableError]
)
def test_owner_denial_or_incompleteness_is_not_a_recipient(world, error):
    world.roster.side_effect = error
    with pytest.raises(error):
        queries.load_host_change_recipient(world.request, host_id=world.host.host_id)


@pytest.mark.parametrize(
    "fault",
    ["missing", "duplicate", "inactive", "invited", "declined", "withdrawn", "removed"],
)
def test_only_one_exact_current_confirmed_relationship_can_receive_change(world, fault):
    selected = world.selected
    if fault == "missing":
        entries = (world.other,)
    elif fault == "duplicate":
        entries = (selected, selected)
    elif fault == "inactive":
        entries = (replace(selected, person_current=False),)
    else:
        entries = (replace(selected, relationship=replace(world.host, state=fault)),)
    world.roster.return_value = ProgrammeHostRosterSnapshot(4, entries)
    with pytest.raises(ProgrammeQueryUnavailableError):
        queries.load_host_change_recipient(world.request, host_id=world.host.host_id)


@pytest.mark.parametrize("value", [None, "not-a-host-id"])
def test_invalid_selected_id_is_checked_after_independent_roster_admission(
    world, value
):
    with pytest.raises(ValidationError):
        queries.load_host_change_recipient(world.request, host_id=value)
    world.roster.assert_called_once_with(world.request)


def test_null_identity_is_unavailable_like_an_unknown_host(world):
    with pytest.raises(ProgrammeQueryUnavailableError):
        queries.load_host_change_recipient(world.request, host_id=UUID(int=0))
