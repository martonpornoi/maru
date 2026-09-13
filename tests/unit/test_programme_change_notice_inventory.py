"""Notice inventory admission, bounded discovery and per-owner read isolation."""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from maru.scheduling import change_notice_inventory as inventory
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.command_support import (
    SchedulingLimitError,
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.planning_queries import SchedulingReadRequest


@pytest.fixture
def scope():
    return SchedulingReadRequest(*(UUID(int=n) for n in range(1, 5)))


@pytest.fixture
def discovery(monkeypatch):
    manager = MagicMock()
    rows = manager.filter.return_value
    rows.filter.return_value = rows
    rows.order_by.return_value.values_list.return_value.__getitem__.return_value = [
        UUID(int=10)
    ]
    monkeypatch.setattr(inventory.SchedulingChangeNotice, "objects", manager)
    read = Mock(side_effect=lambda _request, **kw: kw["loader"](None))
    monkeypatch.setattr(inventory, "_read", read)
    return SimpleNamespace(manager=manager, rows=rows, read=read)


def test_personal_candidates_filter_actor_and_approval_before_selecting_only_ids(
    scope, discovery
):
    actual = inventory._identifiers(scope, personal=True, release_id=UUID(int=11))
    assert actual == (UUID(int=10),)
    discovery.manager.filter.assert_called_once_with(
        organization_id=scope.organization_id, edition_id=scope.edition_id
    )
    discovery.rows.filter.assert_any_call(
        recipient_id=scope.actor_id, evidence__action="approve"
    )
    discovery.rows.filter.assert_any_call(release_id=UUID(int=11))
    discovery.rows.order_by.return_value.values_list.assert_called_once_with(
        "id", flat=True
    )
    assert discovery.read.call_args.kwargs["fields"] == frozenset(
        {"own_change_notices"}
    )


def test_candidate_overflow_fails_instead_of_releasing_a_partial_list(scope, discovery):
    selected = discovery.rows.order_by.return_value.values_list.return_value
    selected.__getitem__.return_value = [UUID(int=10)] * (
        inventory.MAX_CHANGE_NOTICE_INVENTORY + 1
    )
    with pytest.raises(SchedulingLimitError):
        inventory._identifiers(scope, personal=False, release_id=None)


def test_candidate_denial_precedes_filter_validation_and_database_discovery(
    scope, discovery
):
    discovery.read.side_effect = SchedulingAuthorizationDeniedError
    with pytest.raises(SchedulingAuthorizationDeniedError):
        inventory._identifiers(scope, personal=False, release_id="private malformed")
    discovery.manager.filter.assert_not_called()


@pytest.mark.parametrize("personal", [False, True])
def test_each_detail_is_independently_recomposed_and_inventory_read_again(
    scope, monkeypatch, personal
):
    identifiers = Mock(return_value=(UUID(int=10), UUID(int=11)))
    monkeypatch.setattr(inventory, "_identifiers", identifiers)
    sender, own = (
        Mock(side_effect=["first", "second"]),
        Mock(side_effect=["first", "second"]),
    )
    monkeypatch.setattr(inventory, "load_programme_change_notice", sender)
    monkeypatch.setattr(inventory, "load_personal_programme_change_notice", own)
    assert inventory.load_programme_change_notice_inventory(
        scope, personal=personal
    ) == ("first", "second")
    assert identifiers.call_count == 2
    used, unused = (own, sender) if personal else (sender, own)
    assert used.call_count == 2
    unused.assert_not_called()


@pytest.mark.parametrize(
    "error", [SchedulingAuthorizationDeniedError, SchedulingVersionConflictError]
)
def test_stale_and_denied_candidates_leave_no_record_or_hidden_count(
    scope, monkeypatch, error
):
    monkeypatch.setattr(
        inventory, "_identifiers", Mock(return_value=(UUID(int=10), UUID(int=11)))
    )
    monkeypatch.setattr(
        inventory, "load_programme_change_notice", Mock(side_effect=[error, "visible"])
    )
    assert inventory.load_programme_change_notice_inventory(scope) == ("visible",)


def test_dependency_failure_does_not_release_a_partial_inventory(scope, monkeypatch):
    monkeypatch.setattr(
        inventory, "_identifiers", Mock(return_value=(UUID(int=10), UUID(int=11)))
    )
    monkeypatch.setattr(
        inventory,
        "load_programme_change_notice",
        Mock(side_effect=["visible", SchedulingUnavailableError]),
    )
    with pytest.raises(SchedulingUnavailableError):
        inventory.load_programme_change_notice_inventory(scope)


def test_candidate_movement_prevents_mixed_inventory(scope, monkeypatch):
    monkeypatch.setattr(
        inventory, "_identifiers", Mock(side_effect=[(UUID(int=10),), ()])
    )
    monkeypatch.setattr(
        inventory, "load_programme_change_notice", Mock(return_value="visible")
    )
    with pytest.raises(SchedulingUnavailableError):
        inventory.load_programme_change_notice_inventory(scope)


def test_outer_transaction_cannot_accumulate_differently_ordered_owner_locks(
    scope, monkeypatch
):
    monkeypatch.setattr(inventory, "connection", SimpleNamespace(in_atomic_block=True))
    candidates = Mock()
    monkeypatch.setattr(inventory, "_identifiers", candidates)
    with pytest.raises(SchedulingUnavailableError):
        inventory.load_programme_change_notice_inventory(scope)
    candidates.assert_not_called()
