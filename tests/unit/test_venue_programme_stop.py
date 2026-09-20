"""Venue stop admission under parent locks, without weakening correction policy."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from maru.events.programme_stop_queries import ProgrammeStopReference
from maru.venues import scheduling_reservations, services


@pytest.mark.parametrize(
    "reference",
    [None, ProgrammeStopReference(applies=True, is_stopped=True, version=2)],
)
def test_missing_or_stopped_scope_cannot_admit_new_venue_work(monkeypatch, reference):
    monkeypatch.setattr(
        services, "resolve_programme_stop_reference", lambda **_: reference
    )
    with pytest.raises(
        (services.VenueAuthorizationDeniedError, services.VenueStateConflictError)
    ):
        services._require_programme_operation_open(
            organization_id=uuid4(), edition_id=uuid4()
        )


@pytest.mark.parametrize("applies", [False, True])
def test_non_stopped_reference_does_not_replace_other_owner_checks(
    monkeypatch, applies
):
    resolver = MagicMock(
        return_value=ProgrammeStopReference(
            applies=applies, is_stopped=False, version=2
        )
    )
    monkeypatch.setattr(services, "resolve_programme_stop_reference", resolver)
    organization_id, edition_id = uuid4(), uuid4()
    services._require_programme_operation_open(
        organization_id=organization_id, edition_id=edition_id
    )
    resolver.assert_called_once_with(
        organization_id=organization_id, edition_id=edition_id
    )


def test_edition_admission_checks_stop_after_lock_and_before_final_policy(monkeypatch):
    calls = []
    monkeypatch.setattr(services, "resolve_edition_target", lambda **_: object())
    monkeypatch.setattr(
        services, "_require_decision", lambda **_: calls.append("policy")
    )
    monkeypatch.setattr(services, "_lock_owner_scope", lambda **_: calls.append("lock"))

    def stopped(**_):
        calls.append("stop")
        raise services.VenueStateConflictError

    monkeypatch.setattr(services, "_require_programme_operation_open", stopped)
    with pytest.raises(services.VenueStateConflictError):
        services._edition_decision(
            actor=SimpleNamespace(id=uuid4()),
            organization_id=uuid4(),
            edition_id=uuid4(),
            capability_code=services.EDITION_SELECT_CAPABILITY,
            at=datetime.now(UTC),
        )
    assert calls == ["policy", "lock", "stop"]


@pytest.mark.parametrize("retained_correction", [False, True])
def test_space_correction_preserves_two_policy_checks_and_parent_lock(
    monkeypatch, retained_correction
):
    query = MagicMock()
    query.order_by.return_value = query
    query.values.return_value = query
    query.first.return_value = {"id": uuid4(), "responsible_department_id": uuid4()}
    monkeypatch.setattr(
        services.EditionSpaceSelection.objects, "filter", lambda **_: query
    )
    target = SimpleNamespace(
        department_id=query.first.return_value["responsible_department_id"]
    )
    monkeypatch.setattr(services, "resolve_edition_space_target", lambda **_: target)
    decision = MagicMock()
    monkeypatch.setattr(services, "_require_decision", decision)
    lock = MagicMock()
    monkeypatch.setattr(services, "_lock_owner_scope", lock)
    stopped = MagicMock(side_effect=services.VenueStateConflictError)
    monkeypatch.setattr(services, "_require_programme_operation_open", stopped)
    args = {
        "actor": SimpleNamespace(id=uuid4()),
        "organization_id": uuid4(),
        "edition_id": uuid4(),
        "space_selection_id": query.first.return_value["id"],
        "capability_code": services.SPACE_MANAGE_CAPABILITY,
        "at": datetime.now(UTC),
        "retained_correction": retained_correction,
    }
    if retained_correction:
        services._space_decision(**args)
        stopped.assert_not_called()
        assert decision.call_count == 2
    else:
        with pytest.raises(services.VenueStateConflictError):
            services._space_decision(**args)
        stopped.assert_called_once()
        assert decision.call_count == 1
    lock.assert_called_once()


def test_direct_reservation_adapter_denies_before_loading_mutable_intent(monkeypatch):
    monkeypatch.setattr(scheduling_reservations, "_require_adapter", lambda *_: None)
    monkeypatch.setattr(
        scheduling_reservations, "lock_edition_ownership", lambda **_: True
    )
    monkeypatch.setattr(
        scheduling_reservations,
        "_require_programme_operation_open",
        MagicMock(side_effect=services.VenueStateConflictError),
    )
    source = MagicMock()
    monkeypatch.setattr(
        scheduling_reservations, "resolve_scheduling_reservation_source", source
    )
    # Exercise the function body without pretending a database-free test proves
    # PostgreSQL transaction/locking behavior.
    with pytest.raises(services.VenueStateConflictError):
        scheduling_reservations.apply_scheduling_reservation.__wrapped__(
            actor_id=uuid4(),
            organization_id=uuid4(),
            edition_id=uuid4(),
            intent_id=uuid4(),
            correlation_id=uuid4(),
            source_channel="test",
        )
    source.assert_not_called()
