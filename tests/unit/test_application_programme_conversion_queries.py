"""Scoped acceptance labels, canonical eligibility and independent owner authority."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db.models import F

from maru.applications import programme_conversion_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_conversion_sources import (
    ProgrammeConversionConflictError,
    ProgrammeConversionUnavailableError,
)
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


def request():
    return queries.ProgrammeConversionReadRequest(*(UUID(int=i) for i in range(1, 6)))


@pytest.fixture
def world(monkeypatch):
    case = SimpleNamespace(
        id=UUID(int=20),
        version=5,
        revision_id=UUID(int=22),
        proposal=SimpleNamespace(
            call=SimpleNamespace(
                owner_department_id=UUID(int=4),
                definition=SimpleNamespace(name="Synthetic accepted call"),
            )
        ),
    )
    decision = SimpleNamespace(
        id=UUID(int=30),
        revision_id=UUID(int=22),
        revision=SimpleNamespace(sequence=3),
        entry=SimpleNamespace(
            case=case,
            case_id=case.id,
            version=4,
            created_at=datetime(2026, 9, 14, tzinfo=UTC),
        ),
    )
    scope = SimpleNamespace(
        accepts_private_planning_writes=True,
        decision=SimpleNamespace(reason_code="synthetic", obligations=frozenset()),
    )
    auth, programme, lock, audit, effective = (
        Mock(return_value=scope),
        Mock(),
        Mock(),
        Mock(),
        Mock(),
    )
    loader = Mock(return_value=case)
    storage = MagicMock()
    for name in ("select_related", "filter", "order_by"):
        getattr(storage, name).return_value = storage
    storage.__getitem__.side_effect = lambda bounds: [decision, decision][bounds]
    storage.first.return_value = decision
    transition = Mock()
    transition.filter.return_value.exists.return_value = False
    for name, value in (
        ("authorize_programme_conversion_scope", auth),
        ("authorize_programme_scope", programme),
        ("lock_programme_edition_write_scope", lock),
        ("append_audit", audit),
        ("load_review_case", loader),
        ("_current_accepted_decision", effective),
    ):
        monkeypatch.setattr(queries, name, value)
    monkeypatch.setattr(queries.ProgrammeReviewDecision, "objects", storage)
    monkeypatch.setattr(queries.ProgrammeAcceptedTransition, "objects", transition)
    return SimpleNamespace(
        case=case,
        decision=decision,
        scope=scope,
        auth=auth,
        programme=programme,
        lock=lock,
        audit=audit,
        effective=effective,
        loader=loader,
        storage=storage,
        transition=transition,
    )


def source(**changes):
    return queries.get_programme_conversion_source.__wrapped__(
        **({"request": request(), "decision_id": UUID(int=30)} | changes)
    )


def test_discovery_is_exact_scoped_before_bounded_exclusive_paging(world):
    result = queries.list_programme_conversion_choices.__wrapped__(
        request=request(), after_id=UUID(int=29), limit=1
    )
    assert len(result.items) == 1
    assert result.next_cursor == UUID(int=30)
    assert result.items[0].call_name == "Synthetic accepted call"
    assert result.items[0].decision_version == 4
    assert result.items[0].review_version == 5
    first = world.storage.filter.call_args_list[0].kwargs
    assert (
        first["revision__organization_id"]
        == first["entry__case__proposal__organization_id"]
        == UUID(int=2)
    )
    assert (
        first["revision__edition_id"]
        == first["entry__case__proposal__edition_id"]
        == UUID(int=3)
    )
    assert first["entry__case__proposal__call__owner_department_id"] == UUID(int=4)
    assert first["entry__case__revision_id"] == F("revision_id")
    assert first["revision__proposal_id"] == F("entry__case__proposal_id")
    assert first["entry__case__policy__call_id"] == F("entry__case__proposal__call_id")
    assert first["outcome"] == "accepted"
    assert first["entry__action"] == "decided"
    assert world.storage.filter.call_args_list[1].kwargs == {"id__gt": UUID(int=29)}
    world.storage.__getitem__.assert_called_once_with(slice(None, 2))
    world.effective.assert_not_called()
    world.audit.assert_called_once()
    assert not hasattr(result.items[0], "message")
    assert not hasattr(result.items[0], "contributors")


def test_selected_source_reuses_canonical_eligibility_without_private_copy(world):
    result = source()
    assert result.eligible
    assert result.writable
    assert not result.consumed
    world.effective.assert_called_once_with(
        scope=world.scope,
        decision_id=UUID(int=30),
        revision_id=UUID(int=22),
        expected_review_version=5,
    )
    world.transition.filter.assert_called_once_with(
        organization_id=UUID(int=2), edition_id=UUID(int=3), revision_id=UUID(int=22)
    )
    assert all(
        entry.kwargs["capability_code"] == "programme.manage_items"
        and entry.kwargs["requested_fields"] == frozenset()
        for entry in world.programme.call_args_list
    )
    world.lock.assert_called_once_with(
        actor_id=UUID(int=1),
        organization_id=UUID(int=2),
        edition_id=UUID(int=3),
        department_ids=(UUID(int=4),),
    )
    record = world.audit.call_args.args[0]
    assert record.capability_code == "applications.convert_programme_acceptance"
    assert "audit_sensitive_read" in record.obligations
    assert record.target_id == UUID(int=30)


def test_navigation_checks_both_owners_without_source_or_private_read(world):
    assert queries.can_use_programme_conversion(request())
    world.storage.select_related.assert_not_called()
    world.audit.assert_not_called()
    world.programme.side_effect = ProgrammeAuthorizationDeniedError
    assert not queries.can_use_programme_conversion(request())
    world.programme.side_effect = None
    world.auth.side_effect = Denied
    assert not queries.can_use_programme_conversion(request())


def test_historical_ineffective_and_consumed_facts_are_separate(world):
    world.effective.side_effect = ProgrammeConversionConflictError
    world.transition.filter.return_value.exists.return_value = True
    world.scope.accepts_private_planning_writes = False
    result = source()
    assert not result.eligible
    assert not result.writable
    assert result.consumed
    assert result.choice.decision_id == UUID(int=30)


@pytest.mark.parametrize(
    ("boundary", "error"),
    [("auth", Denied), ("programme", ProgrammeAuthorizationDeniedError)],
)
def test_both_owner_admissions_precede_source_read(world, boundary, error):
    getattr(world, boundary).side_effect = error
    with pytest.raises(error):
        source()
    world.storage.select_related.assert_not_called()
    world.lock.assert_not_called()


def test_missing_or_wrong_department_source_is_generic(world):
    world.storage.first.return_value = None
    with pytest.raises(Denied):
        source()
    world.storage.first.return_value = world.decision
    world.case.proposal.call.owner_department_id = UUID(int=99)
    with pytest.raises(Denied):
        source()
    world.effective.assert_not_called()
    world.audit.assert_not_called()


def test_unavailable_canonical_dependency_is_not_false_eligibility(world):
    world.effective.side_effect = ProgrammeConversionUnavailableError
    with pytest.raises(ProgrammeConversionUnavailableError):
        source()
    world.audit.assert_not_called()


def test_release_boundary_reauthorizes_and_requires_audit(world):
    world.auth.side_effect = [world.scope, world.scope, Denied]
    with pytest.raises(Denied):
        source()
    world.audit.assert_not_called()
    world.auth.side_effect = None
    world.audit.side_effect = Denied
    with pytest.raises(Denied):
        source()


@pytest.mark.parametrize("limit", [0, 101, True, "1"])
def test_closed_page_bounds_precede_authority(world, limit):
    with pytest.raises(Denied):
        queries.list_programme_conversion_choices.__wrapped__(
            request=request(), limit=limit
        )
    world.auth.assert_not_called()
