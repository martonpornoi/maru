"""Locking Programme sources cannot invert shared staffing parent locks."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.programme import scope_references as references


@pytest.mark.parametrize("lock", [False, True])
def test_parent_locks_precede_events_only_for_locked_scope(monkeypatch, lock):
    order = []
    expected = object()
    scope = {"organization_id": uuid4(), "edition_id": uuid4()}
    parents = Mock(side_effect=lambda **_kwargs: order.append("parents"))

    def events(**_kwargs):
        order.append("edition")
        return expected

    owner = Mock(side_effect=events)
    monkeypatch.setattr(references, "lock_programme_staffing_scope", parents)
    monkeypatch.setattr(references, "resolve_events_planning_reference", owner)
    assert (
        references.resolve_private_planning_edition_reference(**scope, lock=lock)
        is expected
    )
    assert order == (["parents", "edition"] if lock else ["edition"])
    owner.assert_called_once_with(**scope, lock=False)
    if lock:
        parents.assert_called_once_with(**scope)
    else:
        parents.assert_not_called()


def test_missing_shared_scope_is_unavailable_before_edition_read(monkeypatch):
    monkeypatch.setattr(
        references,
        "lock_programme_staffing_scope",
        Mock(side_effect=ValidationError("Unavailable")),
    )
    events = Mock()
    monkeypatch.setattr(references, "resolve_events_planning_reference", events)
    assert (
        references.resolve_private_planning_edition_reference(
            organization_id=uuid4(), edition_id=uuid4(), lock=True
        )
        is None
    )
    events.assert_not_called()
