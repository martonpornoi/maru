"""Database-free own-request projection and audit/disclosure ordering contracts."""

from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.workforce import programme_starter_boundary as boundary
from maru.workforce import programme_starter_queries as queries
from maru.workforce.models import ProgrammeStarterDecision, ProgrammeStarterRequest
from maru.workforce.programme_starter_inputs import (
    PROGRAMME_STARTER_DEFINITION,
    ProgrammeStarterAction,
    ProgrammeStarterIntent,
    ProgrammeStarterScope,
    programme_starter_decision_digest,
    programme_starter_intent_digest,
)

NOW = datetime(2030, 8, 1, tzinfo=UTC)


@pytest.fixture
def world(monkeypatch):
    actor = Account(
        id=UUID(int=1), account_kind="person", is_active=True, email_verified_at=NOW
    )
    scope = ProgrammeStarterScope(UUID(int=3), UUID(int=4), UUID(int=5))
    intent = ProgrammeStarterIntent(UUID(int=2), "Synthetic staffing.")
    definition = PROGRAMME_STARTER_DEFINITION
    row = ProgrammeStarterRequest(
        id=UUID(int=6),
        organization_id=scope.organization_id,
        series_id=scope.series_id,
        edition_id=scope.edition_id,
        author_id=actor.id,
        approver_id=intent.approver_id,
        reason=intent.reason,
        definition_code=definition.code,
        definition_version=definition.version,
        definition_digest=definition.digest,
        request_digest=programme_starter_intent_digest(scope=scope, details=intent),
        requested_at=NOW - timedelta(hours=1),
        approval_deadline=NOW + timedelta(days=1),
    )
    rows, terminal, trace, audits, mocks = [row], [], [], [], {}
    targets = (object(), object())
    for name in (
        "_require_profile",
        "_require_actor",
        "_lock_scope",
        "_require_integrity",
        "_require_controller",
        "lock_retired_department_authority_boundaries",
    ):
        mock = MagicMock(side_effect=lambda *_a, _name=name, **_kw: trace.append(_name))
        monkeypatch.setattr(queries, name, mock)
        mocks[name] = mock
    monkeypatch.setattr(queries, "_resolve_scope", lambda _: targets)
    monkeypatch.setattr(queries, "_lock_people", lambda _ids: {actor.id: actor})
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(queries.timezone, "now", lambda: NOW)
    manager = MagicMock()
    manager.filter.return_value = manager
    manager.order_by.return_value = manager
    manager.__getitem__.side_effect = lambda _: tuple(rows)
    monkeypatch.setattr(queries.ProgrammeStarterRequest, "objects", manager)
    decisions = MagicMock()
    decisions.filter.side_effect = lambda *_a, **_kw: terminal
    monkeypatch.setattr(queries.ProgrammeStarterDecision, "objects", decisions)
    labels = MagicMock(
        side_effect=lambda _ids: (
            trace.append("labels"),
            {UUID(int=1): "Author", UUID(int=2): "Approver"},
        )[1]
    )
    monkeypatch.setattr(
        queries, "active_verified_person_account_display_labels", labels
    )
    monkeypatch.setattr(
        queries,
        "page_access_scope_label",
        lambda target: (
            "Organization" if target is targets[0] else "Organization / Edition"
        ),
    )
    planning = SimpleNamespace(accepts_private_planning_writes=True)
    monkeypatch.setattr(
        queries, "resolve_private_planning_edition_reference", lambda **_: planning
    )
    monkeypatch.setattr(
        queries,
        "append_audit",
        lambda record: (trace.append("audit"), audits.append(record)),
    )
    return SimpleNamespace(
        actor=actor,
        scope=scope,
        row=row,
        rows=rows,
        terminal=terminal,
        trace=trace,
        audits=audits,
        mocks=mocks,
        manager=manager,
        decisions=decisions,
        labels=labels,
        planning=planning,
    )


def load(world, **changes):
    return queries.load_programme_starter_workspace(
        **(
            {
                "actor": world.actor,
                "scope": world.scope,
                "correlation_id": uuid4(),
                "source_channel": "test",
            }
            | changes
        )
    )


def test_inventory_is_own_exact_scope_bounded_and_audited_before_return(world):
    result = load(world)
    assert result.organization_label == "Organization"
    assert result.edition_label == "Organization / Edition"
    assert result.definition == PROGRAMME_STARTER_DEFINITION
    row = result.requests[0]
    assert row.can_cancel
    assert not row.can_approve
    assert not row.can_decline
    assert row.state_label == "Pending"
    scope, own = world.manager.filter.call_args_list[0].args
    assert dict(scope.children) == {
        "organization_id": world.scope.organization_id,
        "series_id": world.scope.series_id,
        "edition_id": world.scope.edition_id,
    }
    assert own.connector == "OR"
    assert set(own.children) == {
        ("author_id", world.actor.id),
        ("approver_id", world.actor.id),
    }
    assert world.manager.filter.call_args_list[1].kwargs == {
        "approval_deadline__gt": NOW,
        "decision__isnull": True,
    }
    world.manager.__getitem__.assert_called_once_with(slice(None, 101))
    assert (
        world.trace.index("_require_controller")
        < world.trace.index("labels")
        < world.trace.index("audit")
    )
    assert world.trace[-2:] == ["_require_controller", "audit"]
    assert world.audits[0].safe_metadata == {"target_count": 1}
    assert world.audits[0].principal_id == world.actor.id


def test_empty_inventory_still_audited_without_person_lookup(world):
    world.rows.clear()
    assert load(world).requests == ()
    world.labels.assert_not_called()
    assert world.audits[0].safe_metadata == {"target_count": 0}


def test_overflow_is_never_truncated_or_disclosed(world):
    world.rows.extend([world.row] * 100)
    with pytest.raises(ValidationError, match="Too many"):
        load(world)
    world.labels.assert_not_called()
    assert not world.audits


def test_unknown_or_foreign_known_request_releases_nothing(world):
    world.rows.clear()
    with pytest.raises(AuthorizationDenied):
        load(world, request_id=uuid4())
    world.labels.assert_not_called()
    assert not world.audits


@pytest.mark.parametrize("defect", ["authority", "integrity", "definition", "intent"])
def test_changed_authority_integrity_or_retained_meaning_stops_before_labels(
    world, defect
):
    if defect in {"authority", "integrity"}:
        world.mocks[
            "_require_controller" if defect == "authority" else "_require_integrity"
        ].side_effect = ValidationError("Unavailable")
    elif defect == "definition":
        world.row.definition_digest = "0" * 64
    else:
        world.row.reason = "Changed without original digest"
    with pytest.raises(ValidationError):
        load(world)
    world.labels.assert_not_called()
    assert not world.audits


def test_final_authority_loss_and_audit_failure_prevent_projection(world, monkeypatch):
    world.mocks["_require_controller"].side_effect = [
        None,
        AuthorizationDenied("Unavailable", reason_code="test"),
    ]
    with pytest.raises(AuthorizationDenied):
        load(world)
    assert not world.audits
    world.mocks["_require_controller"].side_effect = None
    monkeypatch.setattr(
        queries,
        "append_audit",
        MagicMock(side_effect=ValidationError("Audit unavailable")),
    )
    with pytest.raises(ValidationError, match="Audit"):
        load(world)


@pytest.mark.parametrize("expired", [True, False])
@pytest.mark.parametrize("planning", [True, False])
def test_approver_controls_do_not_offer_expired_or_later_phase_approval(
    world, expired, planning
):
    world.actor.id = UUID(int=2)
    world.planning.accepts_private_planning_writes = planning
    if expired:
        world.row.approval_deadline = NOW
    result = load(world, request_id=world.row.id).requests[0]
    assert result.can_approve is (planning and not expired)
    assert result.can_decline
    assert not result.can_cancel


def test_missing_other_person_label_is_neutral_and_cannot_offer_approval(world):
    world.actor.id = UUID(int=2)
    world.labels.side_effect = None
    world.labels.return_value = {world.actor.id: "Approver"}
    result = load(world).requests[0]
    assert result.author_name == "Unavailable person"
    assert not result.can_approve
    assert result.can_decline


def test_terminal_history_has_no_new_controls_or_effective_access_claim(world):
    world.terminal.append(
        ProgrammeStarterDecision(
            request_id=world.row.id,
            actor_id=world.row.approver_id,
            action="approve",
            reason="Reviewed",
            decided_at=NOW,
            template_id=UUID(int=10),
            role_bundle_id=UUID(int=11),
            created_output=True,
            request_digest=programme_starter_decision_digest(
                scope=world.scope,
                request_id=world.row.id,
                action=ProgrammeStarterAction.APPROVE,
                reason="Reviewed",
            ),
        )
    )
    result = load(world, request_id=world.row.id).requests[0]
    assert result.state_label == "Approved"
    assert result.template_id == UUID(int=10)
    assert not result.can_approve
    assert not result.can_decline
    assert not result.can_cancel
    world.terminal[0].actor_id = world.row.author_id
    with pytest.raises(AuthorizationDenied):
        load(world, request_id=world.row.id)


def test_current_profiles_fail_before_lookup(world, monkeypatch):
    monkeypatch.setattr(queries, "_require_profile", boundary._require_profile)
    with pytest.raises(AuthorizationDenied):
        load(world)
    world.manager.filter.assert_not_called()
