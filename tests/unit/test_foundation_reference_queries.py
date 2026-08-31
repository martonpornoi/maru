from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.events.models import EventEdition
from maru.events.queries import (
    PrivatePlanningEditionReference,
    resolve_private_planning_edition_reference,
)
from maru.identity.queries import (
    ActiveVerifiedAccountReference,
    resolve_active_verified_account_reference,
)


def _values_list_query(row):
    manager = MagicMock()
    base_query = manager.all.return_value
    values_query = base_query.filter.return_value.values_list.return_value
    values_query.first.return_value = row
    return manager, base_query


def test_active_verified_account_reference_is_identifier_only(monkeypatch) -> None:
    account_id = uuid4()
    manager, base_query = _values_list_query(account_id)
    monkeypatch.setattr(
        "maru.identity.queries.Account",
        SimpleNamespace(objects=manager),
    )

    reference = resolve_active_verified_account_reference(account_id=account_id)

    assert reference == ActiveVerifiedAccountReference(account_id=account_id)
    assert tuple(reference.__dataclass_fields__) == ("account_id",)
    base_query.filter.assert_called_once_with(
        id=account_id,
        is_active=True,
        email_verified_at__isnull=False,
    )
    base_query.filter.return_value.values_list.assert_called_once_with(
        "id",
        flat=True,
    )
    base_query.select_for_update.assert_not_called()


@pytest.mark.parametrize("account_state", ["inactive", "unverified"])
def test_active_verified_account_reference_hides_unavailable_state(
    monkeypatch,
    account_state,
) -> None:
    account_id = uuid4()
    manager, base_query = _values_list_query(None)
    monkeypatch.setattr(
        "maru.identity.queries.Account",
        SimpleNamespace(objects=manager),
    )

    assert resolve_active_verified_account_reference(account_id=account_id) is None, (
        account_state
    )
    base_query.filter.assert_called_once_with(
        id=account_id,
        is_active=True,
        email_verified_at__isnull=False,
    )


def test_active_verified_account_reference_can_lock_exact_row(monkeypatch) -> None:
    account_id = uuid4()
    manager = MagicMock()
    base_query = manager.all.return_value
    locked_query = base_query.select_for_update.return_value
    locked_query.filter.return_value.values_list.return_value.first.return_value = (
        account_id
    )
    monkeypatch.setattr(
        "maru.identity.queries.Account",
        SimpleNamespace(objects=manager),
    )

    reference = resolve_active_verified_account_reference(
        account_id=account_id,
        lock=True,
    )

    assert reference == ActiveVerifiedAccountReference(account_id=account_id)
    base_query.select_for_update.assert_called_once_with(of=("self",))
    locked_query.filter.assert_called_once_with(
        id=account_id,
        is_active=True,
        email_verified_at__isnull=False,
    )


@pytest.mark.parametrize(
    ("lifecycle", "expected_writable"),
    [
        (EventEdition.Lifecycle.DRAFT, True),
        (EventEdition.Lifecycle.PREPARING, True),
        (EventEdition.Lifecycle.READY, False),
        (EventEdition.Lifecycle.ARCHIVED, False),
        (EventEdition.Lifecycle.CANCELLED, False),
    ],
)
def test_private_planning_edition_reference_projects_owned_lifecycle_rule(
    monkeypatch,
    lifecycle,
    expected_writable,
) -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    manager, base_query = _values_list_query((edition_id, organization_id, lifecycle))
    monkeypatch.setattr(
        "maru.events.queries.EventEdition",
        SimpleNamespace(objects=manager),
    )

    reference = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
    )

    assert reference == PrivatePlanningEditionReference(
        edition_id=edition_id,
        organization_id=organization_id,
        accepts_private_planning_writes=expected_writable,
    )
    assert tuple(reference.__dataclass_fields__) == (
        "edition_id",
        "organization_id",
        "accepts_private_planning_writes",
    )
    base_query.filter.assert_called_once_with(
        id=edition_id,
        organization_id=organization_id,
        series__organization_id=organization_id,
    )
    base_query.filter.return_value.values_list.assert_called_once_with(
        "id",
        "organization_id",
        "lifecycle",
    )


def test_private_planning_edition_reference_hides_foreign_scope(monkeypatch) -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    manager, base_query = _values_list_query(None)
    monkeypatch.setattr(
        "maru.events.queries.EventEdition",
        SimpleNamespace(objects=manager),
    )

    assert (
        resolve_private_planning_edition_reference(
            organization_id=organization_id,
            edition_id=edition_id,
        )
        is None
    )
    base_query.filter.assert_called_once_with(
        id=edition_id,
        organization_id=organization_id,
        series__organization_id=organization_id,
    )


def test_private_planning_edition_reference_can_lock_exact_row(monkeypatch) -> None:
    organization_id = uuid4()
    edition_id = uuid4()
    manager = MagicMock()
    base_query = manager.all.return_value
    locked_query = base_query.select_for_update.return_value
    locked_query.filter.return_value.values_list.return_value.first.return_value = (
        edition_id,
        organization_id,
        EventEdition.Lifecycle.DRAFT,
    )
    monkeypatch.setattr(
        "maru.events.queries.EventEdition",
        SimpleNamespace(objects=manager),
    )

    reference = resolve_private_planning_edition_reference(
        organization_id=organization_id,
        edition_id=edition_id,
        lock=True,
    )

    assert reference is not None
    assert reference.accepts_private_planning_writes is True
    base_query.select_for_update.assert_called_once_with(of=("self",))
    locked_query.filter.assert_called_once_with(
        id=edition_id,
        organization_id=organization_id,
        series__organization_id=organization_id,
    )
