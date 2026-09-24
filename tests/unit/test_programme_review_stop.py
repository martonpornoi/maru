"""Recipient acknowledgement remains live beyond planning, never beyond stop."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.applications import programme_review_commands as commands
from maru.applications.models import ProgrammeReviewAction
from maru.events.programme_stop_queries import ProgrammeStopReference


def scope(*, planning):
    return SimpleNamespace(
        organization_id=uuid4(),
        edition_id=uuid4(),
        accepts_private_planning_writes=planning,
    )


@pytest.mark.parametrize("planning", [False, True])
@pytest.mark.parametrize(
    "reference",
    [None, ProgrammeStopReference(applies=True, is_stopped=True, version=2)],
)
def test_acknowledgement_has_no_terminal_or_unknown_state_exception(
    monkeypatch, planning, reference
):
    monkeypatch.setattr(
        commands, "resolve_programme_stop_reference", lambda **_: reference
    )
    with pytest.raises(commands.ProgrammeReviewConflictError):
        commands._require_review_lifecycle(
            scope(planning=planning), ProgrammeReviewAction.ACKNOWLEDGED
        )


@pytest.mark.parametrize("applies", [False, True])
def test_live_acknowledgement_does_not_require_private_planning(monkeypatch, applies):
    resolver = MagicMock(
        return_value=ProgrammeStopReference(
            applies=applies, is_stopped=False, version=2
        )
    )
    monkeypatch.setattr(commands, "resolve_programme_stop_reference", resolver)
    current = scope(planning=False)
    commands._require_review_lifecycle(current, ProgrammeReviewAction.ACKNOWLEDGED)
    resolver.assert_called_once_with(
        organization_id=current.organization_id, edition_id=current.edition_id
    )


@pytest.mark.parametrize(
    "action",
    [
        action
        for action in ProgrammeReviewAction
        if action is not ProgrammeReviewAction.ACKNOWLEDGED
    ],
)
@pytest.mark.parametrize("planning", [False, True])
def test_other_actions_retain_the_stricter_existing_planning_gate(
    monkeypatch, action, planning
):
    resolver = MagicMock()
    monkeypatch.setattr(commands, "resolve_programme_stop_reference", resolver)
    if planning:
        commands._require_review_lifecycle(scope(planning=planning), action)
    else:
        with pytest.raises(commands.ProgrammeReviewConflictError):
            commands._require_review_lifecycle(scope(planning=planning), action)
    resolver.assert_not_called()
