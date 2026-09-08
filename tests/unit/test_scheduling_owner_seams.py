"""Fast contract tests for minimized owner references used by Scheduling."""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

import maru.events.scheduling_queries as event_queries
import maru.identity.queries as identity_queries
from maru.authorization import policy
from maru.scheduling.catalogs import (
    SchedulingOperation,
    scheduling_choices,
    scheduling_values,
)
from maru.scheduling.writer_boundary import (
    require_scheduling_writer,
    scheduling_writer,
)


def test_resource_policy_preserves_the_complete_exact_target(monkeypatch):
    principal = object()
    principal_loader = MagicMock(return_value=principal)
    target_loader = MagicMock(return_value=object())
    decision = MagicMock(return_value=object())
    monkeypatch.setattr(policy, "_active_verified_person_principal", principal_loader)
    monkeypatch.setattr(policy, "resolve_resource_target", target_loader)
    monkeypatch.setattr(policy, "decide", decision)
    scope = {
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "department_id": uuid4(),
        "resource_binding_id": uuid4(),
    }
    principal_id = uuid4()
    at = datetime(2026, 9, 7, tzinfo=UTC)
    fields = frozenset({"physical_dependencies"})
    result = policy.decide_verified_principal_exact_resource(
        principal_id=principal_id,
        capability_code="venues.view_space_schedule",
        requested_fields=fields,
        at=at,
        **scope,
    )
    assert result is decision.return_value
    principal_loader.assert_called_once_with(principal_id)
    target_loader.assert_called_once_with(**scope)
    decision.assert_called_once_with(
        principal=principal,
        capability_code="venues.view_space_schedule",
        resource=target_loader.return_value,
        requested_fields=fields,
        at=at,
    )


def test_missing_verified_person_does_not_probe_resource(monkeypatch):
    monkeypatch.setattr(policy, "_active_verified_person_principal", lambda _: None)
    target = MagicMock()
    monkeypatch.setattr(policy, "resolve_resource_target", target)
    result = policy.decide_verified_principal_exact_resource(
        principal_id=uuid4(),
        organization_id=uuid4(),
        edition_id=uuid4(),
        department_id=uuid4(),
        resource_binding_id=uuid4(),
        capability_code="venues.view_space_schedule",
    )
    assert not result.allowed
    assert result.fields == frozenset()
    target.assert_not_called()


@pytest.mark.parametrize("lock", [False, True])
def test_person_batch_is_minimized_bounded_and_canonically_locked(monkeypatch, lock):
    first, second = UUID(int=1), UUID(int=2)
    manager = MagicMock()
    query = manager.filter.return_value.order_by.return_value
    locked = query.select_for_update.return_value if lock else query
    locked.values_list.return_value = (first, second)
    monkeypatch.setattr(identity_queries.Account, "objects", manager)
    result = identity_queries.resolve_active_verified_person_references(
        account_ids=(second, first, first), lock=lock
    )
    assert result == (
        identity_queries.ActiveVerifiedPersonReference(first),
        identity_queries.ActiveVerifiedPersonReference(second),
    )
    manager.filter.assert_called_once_with(
        id__in={first, second},
        is_active=True,
        email_verified_at__isnull=False,
        account_kind=identity_queries.Account.Kind.PERSON,
    )
    manager.filter.return_value.order_by.assert_called_once_with("id")
    if lock:
        query.select_for_update.assert_called_once_with(of=("self",))
    else:
        query.select_for_update.assert_not_called()
    locked.values_list.assert_called_once_with("id", flat=True)


@pytest.mark.parametrize("values", [None, "not IDs", ("bad",), (uuid4(),) * 2001])
def test_invalid_person_batch_is_unavailable_before_query(monkeypatch, values):
    manager = MagicMock()
    monkeypatch.setattr(identity_queries.Account, "objects", manager)
    assert (
        identity_queries.resolve_active_verified_person_references(account_ids=values)
        is None
    )
    manager.filter.assert_not_called()


def test_empty_person_batch_is_complete_without_discovery(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(identity_queries.Account, "objects", manager)
    assert (
        identity_queries.resolve_active_verified_person_references(account_ids=()) == ()
    )
    manager.filter.assert_not_called()


@pytest.mark.parametrize("complete", [False, True])
def test_evidence_lock_preserves_legacy_eligibility_and_returns_only_sorted_ids(
    monkeypatch, complete
):
    first, second = UUID(int=1), UUID(int=2)
    manager = MagicMock()
    query = (
        manager.select_for_update.return_value.filter.return_value.order_by.return_value
    )
    query.values_list.return_value = (first, second) if complete else (first,)
    monkeypatch.setattr(identity_queries.Account, "objects", manager)
    result = identity_queries.lock_account_references_for_evidence(
        account_ids=(second, first, first)
    )
    assert result == ((first, second) if complete else None)
    manager.select_for_update.assert_called_once_with(of=("self",))
    manager.select_for_update.return_value.filter.assert_called_once_with(
        id__in=(first, second)
    )
    manager.select_for_update.return_value.filter.return_value.order_by.assert_called_once_with(
        "id"
    )
    query.values_list.assert_called_once_with("id", flat=True)


@pytest.mark.parametrize("values", [None, "not IDs", ("bad",), (uuid4(),) * 2001])
def test_evidence_lock_rejects_invalid_batch_before_query(monkeypatch, values):
    manager = MagicMock()
    monkeypatch.setattr(identity_queries.Account, "objects", manager)
    assert (
        identity_queries.lock_account_references_for_evidence(account_ids=values)
        is None
    )
    manager.select_for_update.assert_not_called()


def test_conflict_person_keys_are_edition_bounded_not_directory_lookups(monkeypatch):
    manager = MagicMock()
    monkeypatch.setattr(identity_queries.Account, "objects", manager)
    edition_id, account_id = uuid4(), uuid4()
    key = identity_queries.edition_person_conflict_key(
        edition_id=edition_id, account_id=account_id
    )
    assert key == identity_queries.edition_person_conflict_key(
        edition_id=edition_id, account_id=account_id
    )
    assert key != identity_queries.edition_person_conflict_key(
        edition_id=uuid4(), account_id=account_id
    )
    assert key != identity_queries.edition_person_conflict_key(
        edition_id=edition_id, account_id=uuid4()
    )
    manager.filter.assert_not_called()


@pytest.mark.parametrize(
    ("edition_id", "account_id"), [("bad", uuid4()), (uuid4(), "bad")]
)
def test_conflict_key_rejects_untyped_scope(edition_id, account_id):
    with pytest.raises(ValidationError):
        identity_queries.edition_person_conflict_key(
            edition_id=edition_id, account_id=account_id
        )


@pytest.mark.parametrize(
    ("lifecycle", "writable"),
    [
        ("draft", True),
        ("preparing", True),
        ("ready", True),
        ("live", True),
        ("closing", False),
        ("archived", False),
        ("cancelled", False),
        ("future", False),
    ],
)
def test_events_owns_live_scheduling_without_reopening_private_content(
    monkeypatch, lifecycle, writable
):
    organization_id, edition_id = uuid4(), uuid4()
    manager = MagicMock()
    query = manager.all.return_value.select_for_update.return_value
    query.filter.return_value.values_list.return_value.first.return_value = (
        edition_id,
        organization_id,
        7,
        lifecycle,
        "Europe/Budapest",
    )
    monkeypatch.setattr(event_queries.EventEdition, "objects", manager)
    result = event_queries.resolve_scheduling_edition_reference(
        organization_id=organization_id, edition_id=edition_id, lock=True
    )
    assert result == event_queries.SchedulingEditionReference(
        organization_id, edition_id, 7, writable, "Europe/Budapest"
    )
    manager.all.return_value.select_for_update.assert_called_once_with(of=("self",))
    query.filter.assert_called_once_with(
        id=edition_id,
        organization_id=organization_id,
        series__organization_id=organization_id,
    )
    query.filter.return_value.values_list.assert_called_once_with(
        "id", "organization_id", "aggregate_version", "lifecycle", "time_zone"
    )


@pytest.mark.parametrize(
    "error", [None, ValueError(), TypeError(), ValidationError("invalid")]
)
def test_unavailable_edition_scope_has_one_empty_shape(monkeypatch, error):
    manager = MagicMock()
    first = manager.all.return_value.filter.return_value.values_list.return_value.first
    first.return_value = None
    first.side_effect = error
    monkeypatch.setattr(event_queries.EventEdition, "objects", manager)
    assert (
        event_queries.resolve_scheduling_edition_reference(
            organization_id=uuid4(), edition_id=uuid4()
        )
        is None
    )
    manager.all.return_value.select_for_update.assert_not_called()


def test_historical_constraint_values_do_not_refer_to_current_enum_classes():
    values = scheduling_values(SchedulingOperation)
    assert all(type(value) is str for value in values)
    assert values == tuple(
        value for value, _ in scheduling_choices(SchedulingOperation)
    )
    assert len(values) == len(set(values))


def test_writer_scope_is_nested_and_resets_after_failure():
    def failing_nested_command():
        with scheduling_writer():
            require_scheduling_writer()
            raise RuntimeError("synthetic rollback")

    with pytest.raises(ValidationError):
        require_scheduling_writer()
    with scheduling_writer():
        require_scheduling_writer()
        with pytest.raises(RuntimeError):
            failing_nested_command()
        require_scheduling_writer()
    with pytest.raises(ValidationError):
        require_scheduling_writer()
