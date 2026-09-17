"""Database-free command orchestration, never native transaction acceptance."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models

from maru.authorization import programme_role_boundary as boundary
from maru.authorization import programme_role_commands as commands
from maru.authorization.catalog import ScopeLevel
from maru.authorization.programme_role_inputs import (
    ProgrammeRoleDecision,
    ProgrammeRoleIntent,
    ProgrammeRoleScope,
    programme_role_decision_digest,
    programme_role_intent_digest,
)
from maru.authorization.programme_role_recipes import PROGRAMME_ROLE_RECIPES
from maru.authorization.programme_role_writer import (
    _programme_role_writer,
    _require_programme_role_writer,
)
from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account

NOW = datetime(2030, 8, 1, tzinfo=UTC)
RECIPE = PROGRAMME_ROLE_RECIPES[("coverage-reader", 1)]


@pytest.fixture
def world(monkeypatch):
    people = {
        UUID(int=value): Account(
            id=UUID(int=value),
            account_kind="person",
            is_active=True,
            email_verified_at=NOW,
            email=f"person{value}@example.invalid",
        )
        for value in (1, 2, 3)
    }
    scope = ProgrammeRoleScope(UUID(int=4), UUID(int=5), ScopeLevel.EDITION)
    intent = ProgrammeRoleIntent(
        RECIPE.code, 1, UUID(int=3), UUID(int=2), None, None, "Synthetic access."
    )
    trace, saved, audits = [], [], []
    mocks = {}
    target = SimpleNamespace(id="target")
    values = {
        "_require_profile": None,
        "_require_actor": None,
        "lock_retired_department_authority_boundaries": None,
        "_lock_key": None,
        "_resolve_scope": target,
        "_lock_scope": target,
        "_require_integrity": None,
        "_require_current_controller": None,
        "_require_horizons": None,
        "_exact_bundle": SimpleNamespace(id=UUID(int=10)),
    }
    for name, result in values.items():
        mock = MagicMock(
            side_effect=lambda *_args, _name=name, _result=result, **_kwargs: (
                trace.append(_name),
                _result,
            )[1]
        )
        monkeypatch.setattr(commands, name, mock)
        mocks[name] = mock
    monkeypatch.setattr(
        commands,
        "_lock_people",
        lambda ids: (trace.append("people"), {key: people[key] for key in ids})[1],
    )
    requests, decisions = MagicMock(), MagicMock()
    for manager in (requests, decisions):
        manager.select_for_update.return_value = manager
        manager.filter.return_value = manager
        manager.first.return_value = None
        manager.exists.return_value = False
    monkeypatch.setattr(commands.ProgrammeRoleRequest, "objects", requests)
    monkeypatch.setattr(commands.ProgrammeRoleDecisionRecord, "objects", decisions)

    def save(record, **kwargs):
        _require_programme_role_writer()
        assert kwargs == {"force_insert": True}
        trace.append("save")
        saved.append(record)

    for model in (commands.ProgrammeRoleRequest, commands.ProgrammeRoleDecisionRecord):
        monkeypatch.setattr(model, "save", save)

    @contextmanager
    def atomic():
        trace.append("begin")
        try:
            yield
        except Exception:
            trace.append("rollback")
            raise
        else:
            trace.append("commit")

    monkeypatch.setattr(commands.transaction, "atomic", atomic)
    monkeypatch.setattr(commands.timezone, "now", lambda: NOW)

    def audit(record):
        audits.append(record)
        trace.append("audit")
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(commands, "append_audit", audit)
    assign = MagicMock(
        side_effect=lambda **_kwargs: (
            trace.append("assign"),
            SimpleNamespace(id=UUID(int=11)),
        )[1]
    )
    monkeypatch.setattr(commands.authority, "assign_role", assign)
    return SimpleNamespace(
        people=people,
        actor=people[UUID(int=1)],
        approver=people[UUID(int=2)],
        recipient=people[UUID(int=3)],
        scope=scope,
        intent=intent,
        trace=trace,
        saved=saved,
        audits=audits,
        mocks=mocks,
        requests=requests,
        decisions=decisions,
        assign=assign,
        target=target,
    )


def request(world, **changes):
    return commands.request_programme_role(
        **{
            "actor": world.actor,
            "scope": world.scope,
            "details": world.intent,
            "idempotency_key": UUID(int=20),
            "correlation_id": UUID(int=21),
            "source_channel": "test",
            **changes,
        }
    )


def original_request(world):
    request(world)
    original = world.saved[-1]
    world.requests.first.return_value = original
    world.trace.clear()
    world.saved.clear()
    world.audits.clear()
    return original


def decision(world, original, **changes):
    return commands.decide_programme_role(
        **{
            "actor": world.approver,
            "scope": world.scope,
            "request_id": original.id,
            "action": ProgrammeRoleDecision.APPROVE,
            "reason": "Reviewed exact intent.",
            "idempotency_key": UUID(int=22),
            "correlation_id": UUID(int=23),
            "source_channel": "test",
            **changes,
        }
    )


@pytest.mark.parametrize("operation", ["request", "decision"])
def test_current_profiles_deny_before_database_or_input_processing(
    world, monkeypatch, operation
):
    monkeypatch.setattr(commands, "_require_profile", boundary._require_profile)
    call = (
        (lambda: request(world, details=None))
        if operation == "request"
        else (lambda: decision(world, SimpleNamespace(id=uuid4())))
    )
    with pytest.raises(AuthorizationDenied):
        call()
    assert world.trace == []
    world.requests.filter.assert_not_called()
    world.decisions.filter.assert_not_called()


def test_request_retains_normalized_intent_without_grant(world):
    result = request(
        world, details=replace(world.intent, reason=" Synthetic   access. ")
    )
    stored = world.saved[0]
    assert result.request_id == stored.id
    assert result.approval_deadline == NOW + timedelta(days=7)
    assert not result.replayed
    assert stored.reason == world.intent.reason
    assert stored.request_digest == programme_role_intent_digest(
        scope=world.scope, details=world.intent
    )
    assert (
        world.trace.index("lock_retired_department_authority_boundaries")
        < world.trace.index("_lock_scope")
        < world.trace.index("people")
        < world.trace.index("_require_horizons")
        < world.trace.index("audit")
        < world.trace.index("save")
    )
    assert world.trace[-1] == "commit"
    world.assign.assert_not_called()
    world.mocks["_exact_bundle"].assert_not_called()
    assert world.audits[0].principal_id == world.actor.id
    assert world.audits[0].target_id == stored.id
    assert world.audits[0].retention_class == "security-extended"


@pytest.mark.parametrize("field", ["idempotency_key", "correlation_id"])
@pytest.mark.parametrize("value", [None, False, "uuid", UUID(int=0)])
def test_request_context_rejects_invalid_ids_before_lookup(world, field, value):
    with pytest.raises(ValidationError):
        request(world, **{field: value})
    world.requests.filter.assert_not_called()


@pytest.mark.parametrize("value", ["", "a" * 33, "Test", "test\n", None])
def test_request_channel_is_closed_before_lookup(world, value):
    with pytest.raises(ValidationError):
        request(world, source_channel=value)
    world.requests.filter.assert_not_called()


def test_author_cannot_name_self_as_approver(world):
    with pytest.raises(AuthorizationDenied):
        request(world, details=replace(world.intent, approver_id=world.actor.id))
    assert "begin" not in world.trace


@pytest.mark.parametrize(
    "stage",
    ["_require_actor", "_lock_scope", "_require_integrity", "_require_horizons"],
)
def test_request_denial_never_leaves_success_evidence(world, stage):
    world.mocks[stage].side_effect = boundary._unavailable()
    with pytest.raises(AuthorizationDenied):
        request(world)
    assert not world.saved
    assert not world.audits
    world.assign.assert_not_called()


def test_exact_request_retry_reauthorizes_without_renewing_deadline(world):
    original = original_request(world)
    original.approval_deadline = NOW - timedelta(days=1)
    result = request(world, correlation_id=uuid4())
    assert result.replayed
    assert result.request_id == original.id
    assert result.approval_deadline == original.approval_deadline
    assert "_require_current_controller" in world.trace
    assert "_require_horizons" not in world.trace
    assert not world.saved
    assert not world.audits


def test_changed_request_retry_conflicts(world):
    original_request(world)
    with pytest.raises(ValidationError, match="different access intent"):
        request(world, details=replace(world.intent, reason="Different reason."))
    assert not world.saved


def test_approval_passes_exact_intent_to_existing_owner_and_retains_own_action(world):
    original = original_request(world)
    result = decision(world, original)
    assert result.role_assignment_id == UUID(int=11)
    assert not result.replayed
    args = world.assign.call_args.kwargs
    assert args["actor"] is world.actor
    assert args["approver"] is world.approver
    assert args["recipient"] is world.recipient
    assert args["reason"] == original.reason
    assert args["effective_from"] == NOW
    assert args["expires_at"] is None
    assert args["correlation_id"] == UUID(int=23)
    assert world.saved[0].actor_id == world.approver.id
    assert world.saved[0].reason == "Reviewed exact intent."
    assert world.audits[0].operation == "authorization.programme_role.approve"
    assert (
        world.trace.index("people")
        < world.trace.index("_require_horizons")
        < world.trace.index("assign")
        < world.trace.index("audit")
        < world.trace.index("save")
    )
    assert world.trace[-1] == "commit"


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_approval_never_backdates_and_preserves_requested_end(world, offset):
    world.intent = replace(
        world.intent,
        not_before=NOW + timedelta(hours=offset),
        expires_at=NOW + timedelta(days=3),
    )
    original = original_request(world)
    decision(world, original)
    assert world.assign.call_args.kwargs["effective_from"] == max(
        NOW, world.intent.not_before
    )
    assert world.assign.call_args.kwargs["expires_at"] == world.intent.expires_at


@pytest.mark.parametrize(
    "action", [ProgrammeRoleDecision.DECLINE, ProgrammeRoleDecision.CANCEL]
)
def test_nonapproval_requires_actual_person_and_never_creates_a_role(world, action):
    original = original_request(world)
    actor = world.actor if action is ProgrammeRoleDecision.CANCEL else world.approver
    result = decision(world, original, action=action, actor=actor)
    assert result.role_assignment_id is None
    assert result.action is action
    assert world.saved[0].actor_id == actor.id
    world.assign.assert_not_called()
    world.mocks["_exact_bundle"].assert_not_called()
    assert "_require_horizons" not in world.trace


@pytest.mark.parametrize("action", list(ProgrammeRoleDecision))
def test_unrelated_person_cannot_act_on_known_request(world, action):
    original = original_request(world)
    with pytest.raises(AuthorizationDenied):
        decision(world, original, action=action, actor=world.recipient)
    assert not world.saved
    assert not world.audits
    world.assign.assert_not_called()


def test_unknown_or_foreign_request_has_same_denial(world):
    original = original_request(world)
    world.requests.first.return_value = None
    with pytest.raises(AuthorizationDenied):
        decision(world, original)
    filters = world.requests.filter.call_args_list[0].kwargs
    assert filters["author_id"] == world.actor.id  # first call was request creation
    decision_filters = dict(world.requests.filter.call_args.args[0].children)
    assert decision_filters["organization_id"] == world.scope.organization_id
    assert decision_filters["programme_edition_id"] == world.scope.programme_edition_id
    assert decision_filters["department_id"] is None
    assert decision_filters["resource_binding_id"] is None
    assert world.requests.filter.call_args.kwargs == {"id": original.id}


@pytest.mark.parametrize("level", list(ScopeLevel))
@pytest.mark.parametrize("prefix", ["", "request__"])
def test_every_retained_lookup_pins_tenant_context_and_full_target(level, prefix):
    scoped = ProgrammeRoleScope(
        uuid4(),
        uuid4(),
        level,
        uuid4() if level in {ScopeLevel.DEPARTMENT, ScopeLevel.RESOURCE} else None,
        uuid4() if level is ScopeLevel.RESOURCE else None,
        "venue.edition_space" if level is ScopeLevel.RESOURCE else "",
    )
    values = dict(commands._scope_filter(scoped, prefix=prefix).children)
    assert values == {
        prefix + "organization_id": scoped.organization_id,
        prefix + "programme_edition_id": scoped.programme_edition_id,
        prefix + "edition_id": None
        if level is ScopeLevel.ORGANIZATION
        else scoped.programme_edition_id,
        prefix + "scope_level": level.value,
        prefix + "department_id": scoped.department_id,
        prefix + "resource_binding_id": scoped.resource_binding_id,
    }


@pytest.mark.parametrize(
    "constraint",
    ["programme_role_request_author_key", "programme_role_decision_actor_key"],
)
def test_cross_scope_global_key_conflict_is_classified_without_foreign_row_read(
    constraint,
):
    cause = Exception("Synthetic unique violation")
    cause.sqlstate = "23505"
    cause.diag = SimpleNamespace(constraint_name=constraint)
    error = IntegrityError("Synthetic global key collision")
    error.__cause__ = cause
    record = MagicMock()
    record.save.side_effect = error
    with pytest.raises(ValidationError, match="different intent") as caught:
        commands._append_evidence(record)
    assert caught.value.code == "programme_role_retry_conflict"
    with pytest.raises(ValidationError):
        _require_programme_role_writer()


@pytest.mark.parametrize(
    ("state", "constraint"),
    [
        ("23514", "programme_role_request_author_key"),
        ("23505", "unexpected_constraint"),
        (None, None),
    ],
)
def test_unrelated_native_failure_is_not_misreported_as_retry_conflict(
    state, constraint
):
    cause = Exception("Synthetic native failure")
    cause.sqlstate = state
    cause.diag = SimpleNamespace(constraint_name=constraint)
    error = IntegrityError("Unrelated invariant failed")
    error.__cause__ = cause
    record = MagicMock()
    record.save.side_effect = error
    with pytest.raises(IntegrityError, match="Unrelated invariant"):
        commands._append_evidence(record)


def test_expired_approval_does_not_create_role_or_audit(world):
    original = original_request(world)
    original.approval_deadline = NOW
    with pytest.raises(ValidationError, match="expired"):
        decision(world, original)
    world.mocks["_exact_bundle"].assert_not_called()
    world.assign.assert_not_called()
    assert not world.audits


@pytest.mark.parametrize("fault", ["recipe", "digest"])
def test_stale_retained_intent_is_not_approved(world, fault):
    original = original_request(world)
    if fault == "recipe":
        original.recipe_digest = "b" * 64
    else:
        original.request_digest = "b" * 64
    with pytest.raises(AuthorizationDenied):
        decision(world, original)
    world.assign.assert_not_called()


def test_failed_assignment_escapes_outer_transaction_without_decision(world):
    original = original_request(world)
    world.assign.side_effect = ValidationError("Assignment failed.")
    with pytest.raises(ValidationError, match="Assignment failed"):
        decision(world, original)
    assert world.trace[-1] == "rollback"
    assert not world.saved
    assert not world.audits


@pytest.mark.parametrize("action", list(ProgrammeRoleDecision))
def test_terminal_retry_only_returns_original_and_never_regrants(world, action):
    original = original_request(world)
    actor = world.actor if action is ProgrammeRoleDecision.CANCEL else world.approver
    terminal = commands.ProgrammeRoleDecisionRecord(
        request_id=original.id,
        actor_id=actor.id,
        action=action.value,
        idempotency_key=UUID(int=22),
        request_digest=programme_role_decision_digest(
            request_id=original.id, decision=action, reason="Reviewed exact intent."
        ),
        role_assignment_id=UUID(int=11)
        if action is ProgrammeRoleDecision.APPROVE
        else None,
    )
    world.decisions.first.return_value = terminal
    original.approval_deadline = NOW - timedelta(days=1)
    result = decision(world, original, action=action, actor=actor)
    assert result.replayed
    assert result.decision_id == terminal.id
    assert result.role_assignment_id == terminal.role_assignment_id
    world.assign.assert_not_called()
    assert "_require_current_controller" in world.trace
    assert not world.saved
    assert not world.audits


def test_terminal_changed_retry_and_revoked_actor_do_not_replay(world):
    original = original_request(world)
    world.decisions.first.return_value = commands.ProgrammeRoleDecisionRecord(
        request_id=original.id,
        actor_id=world.approver.id,
        idempotency_key=uuid4(),
        request_digest="a" * 64,
    )
    with pytest.raises(ValidationError, match="terminal decision"):
        decision(world, original)
    world.mocks["_require_current_controller"].side_effect = boundary._unavailable()
    with pytest.raises(AuthorizationDenied):
        decision(world, original)
    world.assign.assert_not_called()


def test_decision_key_cannot_be_reused_on_other_request(world):
    original = original_request(world)
    world.decisions.exists.return_value = True
    with pytest.raises(ValidationError, match="another decision"):
        decision(world, original)
    world.assign.assert_not_called()


@pytest.mark.parametrize(
    "model", [commands.ProgrammeRoleRequest, commands.ProgrammeRoleDecisionRecord]
)
def test_private_writer_only_appends_and_unwinds_on_error(model, monkeypatch):
    save, clean = MagicMock(), MagicMock()
    monkeypatch.setattr(models.Model, "save", save)
    monkeypatch.setattr(model, "full_clean", clean)
    with pytest.raises(ValidationError):
        model().save()
    with _programme_role_writer():
        model().save(force_insert=True)
        retained = model()
        retained._state.adding = False
        with pytest.raises(ValidationError, match="retained"):
            retained.save()
    save.assert_called_once_with(force_insert=True)
    clean.assert_called_once_with()
    with pytest.raises(RuntimeError), _programme_role_writer():
        raise RuntimeError("rollback")
    with pytest.raises(ValidationError):
        model().save()
