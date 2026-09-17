"""Database-free query protocol and disclosure ceilings, not native acceptance."""

from contextlib import contextmanager, nullcontext
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError

from maru.authorization import programme_role_queries as queries
from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_inputs import (
    ProgrammeRoleIntent,
    ProgrammeRoleScope,
    programme_role_intent_digest,
)
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account

NOW = datetime(2026, 9, 17, 20, tzinfo=UTC)
RECIPE = PROGRAMME_ROLE_RECIPES[("coverage-reader", 1)]


@pytest.fixture
def world(monkeypatch):
    actor = Account(id=UUID(int=3), is_active=True, email_verified_at=NOW)
    scope = ProgrammeRoleScope(UUID(int=1), UUID(int=2), ScopeLevel.EDITION)
    details = ProgrammeRoleIntent(
        RECIPE.code,
        1,
        UUID(int=5),
        UUID(int=4),
        None,
        None,
        "Synthetic limited coverage review.",
    )
    row = SimpleNamespace(
        id=UUID(int=6),
        author_id=actor.id,
        approver_id=details.approver_id,
        recipient_id=details.recipient_id,
        recipe_code=RECIPE.code,
        recipe_version=1,
        recipe_digest=RECIPE.digest,
        request_digest=programme_role_intent_digest(scope=scope, details=details),
        reason=details.reason,
        requested_at=NOW - timedelta(hours=1),
        approval_deadline=NOW + timedelta(days=6),
        not_before=None,
        expires_at=None,
    )
    query = MagicMock()
    query.filter.return_value = query
    query.order_by.return_value = query
    query.__getitem__.return_value = (row,)
    request_filter = MagicMock(return_value=query)
    decision_filter = MagicMock(return_value=())
    monkeypatch.setattr(queries.ProgrammeRoleRequest.objects, "filter", request_filter)
    monkeypatch.setattr(
        queries.ProgrammeRoleDecisionRecord.objects, "filter", decision_filter
    )
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(queries.timezone, "now", lambda: NOW)
    mocks = {}
    for name, result in {
        "_require_profile": None,
        "_require_actor": None,
        "_require_integrity": None,
        "_resolve_scope": object(),
        "_lock_scope": object(),
        "_lock_people": {actor.id: actor},
        "_require_current_controller": None,
        "lock_retired_department_authority_boundaries": None,
        "resolve_edition_target": object(),
        "page_access_scope_label": "Synthetic convention / Programme edition",
        "active_verified_person_account_display_labels": {
            actor.id: "Author",
            row.approver_id: "Approver",
            row.recipient_id: "Recipient",
        },
        "append_audit": None,
    }.items():
        mocks[name] = MagicMock(return_value=result)
        monkeypatch.setattr(queries, name, mocks[name])
    return SimpleNamespace(
        actor=actor,
        scope=scope,
        row=row,
        query=query,
        request_filter=request_filter,
        decision_filter=decision_filter,
        mocks=mocks,
    )


def load(world, **changes):
    return queries.load_programme_role_workspace(
        actor=world.actor, scope=world.scope, correlation_id=uuid4(), **changes
    )


def test_inventory_pins_complete_scope_person_deadline_and_bounded_order(world):
    result = load(world)
    predicate, person = world.request_filter.call_args.args
    assert dict(predicate.children) == {
        "organization_id": world.scope.organization_id,
        "programme_edition_id": world.scope.programme_edition_id,
        "edition_id": world.scope.programme_edition_id,
        "scope_level": "edition",
        "department_id": None,
        "resource_binding_id": None,
    }
    assert person.connector == "OR"
    assert dict(person.children) == {
        "author_id": world.actor.id,
        "approver_id": world.actor.id,
    }
    assert world.query.filter.call_args.kwargs == {
        "approval_deadline__gt": NOW,
        "decision__isnull": True,
    }
    assert dict(world.query.filter.call_args.args[0].children) == {
        "expires_at__gt": NOW,
        "expires_at__isnull": True,
    }
    world.query.order_by.assert_called_once_with("requested_at", "id")
    world.query.__getitem__.assert_called_once_with(slice(None, 101))
    assert world.decision_filter.call_args.kwargs == {"request_id__in": (world.row.id,)}
    assert (
        dict(world.decision_filter.call_args.args[0].children)[
            "request__organization_id"
        ]
        == world.scope.organization_id
    )
    projected = result.requests[0]
    assert projected.state == "pending"
    assert projected.can_cancel
    assert not projected.can_approve
    assert not projected.can_decline
    assert projected.recipient_name == "Recipient"
    names = {field.name for field in fields(projected)}
    assert not names & {
        "email",
        "idempotency_key",
        "request_digest",
        "source_audit_id",
        "correlation_id",
    }
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.principal_id == world.actor.id
    assert audit.event_edition_id == world.scope.programme_edition_id
    assert audit.safe_metadata == {"target_count": 1}
    assert audit.obligations == ("audit_sensitive_read",)
    assert audit.target_id is None


def test_exact_retained_detail_does_not_depend_on_open_inventory(world):
    world.row.approval_deadline = NOW - timedelta(seconds=1)
    result = load(world, request_id=world.row.id)
    world.query.filter.assert_called_once_with(id=world.row.id)
    assert result.requests[0].state == "expired"
    assert result.requests[0].can_cancel
    assert world.mocks["append_audit"].call_args.args[0].target_id == world.row.id


def test_empty_inventory_is_audited_without_person_lookup(world):
    world.query.__getitem__.return_value = ()
    assert load(world).requests == ()
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()
    assert world.mocks["append_audit"].call_args.args[0].safe_metadata == {
        "target_count": 0
    }


@pytest.mark.parametrize("request_id", [UUID(int=0), "known-id", 3])
def test_malformed_exact_request_is_denied_before_lookup(world, request_id):
    with pytest.raises(AuthorizationDenied):
        load(world, request_id=request_id)
    world.request_filter.assert_not_called()


def test_missing_or_foreign_exact_record_has_same_denial_without_labels(world):
    world.query.__getitem__.return_value = ()
    with pytest.raises(AuthorizationDenied):
        load(world, request_id=uuid4())
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


def test_overflow_releases_no_partial_inventory_or_labels(world):
    world.query.__getitem__.return_value = (world.row,) * 101
    with pytest.raises(ValidationError) as error:
        load(world)
    assert error.value.code == "programme_role_inventory_overflow"
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


@pytest.mark.parametrize(
    "name",
    [
        "_require_profile",
        "_require_actor",
        "_resolve_scope",
        "_lock_scope",
        "_require_integrity",
        "_lock_people",
    ],
)
def test_boundary_failure_precedes_all_request_and_label_reads(world, name):
    world.mocks[name].side_effect = AuthorizationDenied(
        "Unavailable", reason_code="unavailable"
    )
    with pytest.raises(AuthorizationDenied):
        load(world)
    world.request_filter.assert_not_called()
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()


@pytest.mark.parametrize("check", [0, 1])
def test_locked_and_final_current_controller_checks_all_gate_release(world, check):
    world.mocks["_require_current_controller"].side_effect = [None] * check + [
        AuthorizationDenied("Unavailable", reason_code="unavailable")
    ]
    with pytest.raises(AuthorizationDenied):
        load(world)
    world.mocks["append_audit"].assert_not_called()
    if check == 0:
        world.request_filter.assert_not_called()


def test_source_selector_is_never_called_outside_the_canonical_transaction(
    world, monkeypatch
):
    active = False
    calls = []

    @contextmanager
    def atomic():
        nonlocal active
        active = True
        try:
            yield
        finally:
            active = False

    def source(*_args):
        assert active, "Persistent source selection requires the owning transaction"
        calls.append("source")

    monkeypatch.setattr(queries.transaction, "atomic", atomic)
    world.mocks["_require_current_controller"].side_effect = source
    load(world)
    assert calls == ["source", "source"]
    assert not active


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recipe_code", "unknown"),
        ("recipe_digest", "0" * 64),
        ("reason", "Changed retained reason"),
        ("request_digest", "0" * 64),
    ],
)
def test_incoherent_immutable_intent_cannot_release_people(world, field, value):
    setattr(world.row, field, value)
    with pytest.raises(AuthorizationDenied):
        load(world)
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()


@pytest.mark.parametrize("state", ["approve", "decline", "cancel"])
def test_terminal_state_is_historical_without_new_action_or_grant(world, state):
    terminal = SimpleNamespace(
        request_id=world.row.id,
        action=state,
        reason="Original terminal reason",
        decided_at=NOW - timedelta(minutes=5),
        role_assignment_id=uuid4() if state == "approve" else None,
    )
    world.decision_filter.return_value = (terminal,)
    detail = load(world, request_id=world.row.id).requests[0]
    assert detail.state == state
    assert detail.role_assignment_id == terminal.role_assignment_id
    assert not any((detail.can_approve, detail.can_decline, detail.can_cancel))


@pytest.mark.parametrize("expired", ["no", "deadline", "interval"])
@pytest.mark.parametrize("labels_available", [True, False])
def test_approver_controls_and_unavailable_person_labels(
    world, expired, labels_available
):
    if expired == "deadline":
        world.row.approval_deadline = NOW
    if expired == "interval":
        world.row.expires_at = NOW
    labels = (
        {
            world.row.author_id: "Author",
            world.row.approver_id: "Approver",
            world.row.recipient_id: "Recipient",
        }
        if labels_available
        else {}
    )
    detail = queries._project(
        world.row, None, RECIPE, labels, world.row.approver_id, NOW
    )
    assert detail.can_approve == (expired == "no" and labels_available)
    assert detail.can_decline
    assert not detail.can_cancel
    assert detail.recipient_name == (
        "Recipient" if labels_available else "Unavailable person"
    )


def test_audit_failure_returns_no_projection(world):
    world.mocks["append_audit"].side_effect = RuntimeError("Synthetic audit failure")
    with pytest.raises(RuntimeError, match="audit failure"):
        load(world)


def test_plain_recipient_is_not_part_of_authorized_own_request_filter(world):
    load(world)
    assert "recipient_id" not in dict(world.request_filter.call_args.args[1].children)


def test_changed_context_or_no_context_is_not_substituted(world):
    world.mocks["resolve_edition_target"].return_value = None
    with pytest.raises(AuthorizationDenied):
        load(world)
    world.mocks["append_audit"].assert_not_called()
