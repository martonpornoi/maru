"""Database-free orchestration checks; not native atomicity or authority acceptance."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from maru.authorization.services import AuthorizationDenied
from maru.identity.models import Account
from maru.workforce import programme_starter_boundary as boundary
from maru.workforce import programme_starter_commands as commands
from maru.workforce.programme_starter_inputs import (
    ProgrammeStarterAction as Action,
)
from maru.workforce.programme_starter_inputs import (
    ProgrammeStarterIntent,
    ProgrammeStarterScope,
    programme_starter_intent_digest,
)
from maru.workforce.programme_starter_writer import _require_programme_starter_writer

NOW = datetime(2030, 8, 1, tzinfo=UTC)


@pytest.fixture
def world(monkeypatch):
    people = {
        UUID(int=i): Account(
            id=UUID(int=i), account_kind="person", is_active=True, email_verified_at=NOW
        )
        for i in (1, 2, 3)
    }
    trace, saved, audits, mocks = [], [], [], {}
    targets = (SimpleNamespace(id=UUID(int=4)), SimpleNamespace(id=UUID(int=6)))
    for name in (
        "_require_profile",
        "_require_actor",
        "lock_retired_department_authority_boundaries",
        "_lock_key",
        "_lock_scope",
        "_require_integrity",
        "_require_controller",
        "_require_planning",
        "_resolve_scope",
    ):
        result = targets if name == "_resolve_scope" else None
        mock = MagicMock(
            side_effect=lambda *_args, _name=name, _result=result, **_kw: (
                trace.append(_name),
                _result,
            )[1]
        )
        monkeypatch.setattr(commands, name, mock)
        mocks[name] = mock
    locks = MagicMock(
        side_effect=lambda ids: (
            trace.append("people"),
            {key: people[key] for key in ids},
        )[1]
    )
    monkeypatch.setattr(commands, "_lock_people", locks)
    requests, decisions = MagicMock(), MagicMock()
    for manager in (requests, decisions):
        manager.select_for_update.return_value = manager
        manager.filter.return_value = manager
        manager.first.return_value = None
        manager.exists.return_value = False
    monkeypatch.setattr(commands.ProgrammeStarterRequest, "objects", requests)
    monkeypatch.setattr(commands.ProgrammeStarterDecision, "objects", decisions)

    def save(record, **kwargs):
        _require_programme_starter_writer()
        assert kwargs == {"force_insert": True}
        trace.append("save")
        saved.append(record)

    for model in (commands.ProgrammeStarterRequest, commands.ProgrammeStarterDecision):
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
    monkeypatch.setattr(
        commands,
        "append_audit",
        lambda record: (
            audits.append(record),
            trace.append("audit"),
            SimpleNamespace(id=uuid4()),
        )[-1],
    )
    output = SimpleNamespace(
        template=SimpleNamespace(id=UUID(int=10)),
        role_bundle=SimpleNamespace(id=UUID(int=11)),
        replayed=False,
    )
    create = MagicMock(side_effect=lambda **_kw: (trace.append("create"), output)[1])
    existing, proof = MagicMock(return_value=None), MagicMock(return_value=True)
    monkeypatch.setattr(commands, "_create_starter_definition", create)
    monkeypatch.setattr(commands, "_existing_starter", existing)
    monkeypatch.setattr(commands, "role_bundle_provenance_is_historical", proof)
    return SimpleNamespace(
        people=people,
        actor=people[UUID(int=1)],
        approver=people[UUID(int=2)],
        stranger=people[UUID(int=3)],
        scope=ProgrammeStarterScope(UUID(int=4), UUID(int=5), UUID(int=6)),
        intent=ProgrammeStarterIntent(UUID(int=2), "Prepare staffing."),
        trace=trace,
        saved=saved,
        audits=audits,
        mocks=mocks,
        locks=locks,
        requests=requests,
        decisions=decisions,
        output=output,
        create=create,
        existing=existing,
        proof=proof,
        targets=targets,
    )


def request(world, **changes):
    return commands.request_programme_starter(
        **(
            {
                "actor": world.actor,
                "scope": world.scope,
                "details": world.intent,
                "idempotency_key": UUID(int=20),
                "correlation_id": UUID(int=21),
                "source_channel": "test",
            }
            | changes
        )
    )


def original(world):
    request(world)
    record = world.saved[-1]
    world.requests.first.return_value = record
    world.trace.clear()
    world.saved.clear()
    world.audits.clear()
    for mock in world.mocks.values():
        mock.reset_mock()
    world.locks.reset_mock()
    return record


def decide(world, record, **changes):
    return commands.decide_programme_starter(
        **(
            {
                "actor": world.approver,
                "scope": world.scope,
                "request_id": record.id,
                "action": Action.APPROVE,
                "reason": "Reviewed.",
                "idempotency_key": UUID(int=22),
                "correlation_id": UUID(int=23),
                "source_channel": "test",
            }
            | changes
        )
    )


@pytest.mark.parametrize("operation", ["request", "decision"])
def test_current_profiles_deny_before_database(world, monkeypatch, operation):
    monkeypatch.setattr(commands, "_require_profile", boundary._require_profile)
    call = (
        (lambda: request(world, details=None))
        if operation == "request"
        else (lambda: decide(world, SimpleNamespace(id=uuid4())))
    )
    with pytest.raises(AuthorizationDenied):
        call()
    assert not world.trace
    world.requests.filter.assert_not_called()


def test_request_retains_own_intent_and_audit_without_output(world):
    result = request(
        world, details=replace(world.intent, reason=" Prepare   staffing. ")
    )
    record = world.saved[0]
    assert result.request_id == record.id
    assert not result.replayed
    assert result.approval_deadline == NOW + timedelta(days=7)
    assert record.reason == world.intent.reason
    assert record.request_digest == programme_starter_intent_digest(
        scope=world.scope, details=world.intent
    )
    assert world.audits[0].principal_id == world.actor.id
    assert world.audits[0].retention_class == "security-extended"
    assert (
        world.trace.index("_lock_scope")
        < world.trace.index("people")
        < world.trace.index("audit")
        < world.trace.index("save")
        < world.trace.index("commit")
    )
    world.create.assert_not_called()


def test_self_approval_rejected_before_transaction(world):
    with pytest.raises(AuthorizationDenied):
        request(world, details=replace(world.intent, approver_id=world.actor.id))
    assert "begin" not in world.trace


def test_request_replay_needs_only_author_and_preserves_deadline(
    world,
):
    record = original(world)
    result = request(world, correlation_id=uuid4())
    assert result.replayed
    assert result.approval_deadline == record.approval_deadline
    world.locks.assert_called_once_with({world.actor.id})
    world.mocks["_require_planning"].assert_not_called()
    assert not world.saved
    assert not world.audits


@pytest.mark.parametrize(
    "change", [{"reason": "Changed"}, {"approver_id": UUID(int=3)}]
)
def test_changed_request_retry_conflicts(world, change):
    original(world)
    with pytest.raises(ValidationError):
        request(world, details=replace(world.intent, **change))
    assert not world.saved


def test_approval_creates_only_exact_meaning_through_factory_and_checks_proof(world):
    record = original(world)
    result = decide(world, record)
    assert result.created_output
    assert not result.replayed
    assert result.template_id == world.output.template.id
    call = world.create.call_args.kwargs
    assert call["actor"] is world.actor
    assert call["approver"] is world.approver
    assert call["reason"] == record.reason
    assert call["organization_target"] is world.targets[0]
    world.proof.assert_called_once_with(bundle=world.output.role_bundle, lock=True)
    assert world.audits[0].principal_id == world.approver.id
    assert (
        world.trace.index("_require_planning")
        < world.trace.index("create")
        < world.trace.index("audit")
        < world.trace.index("save")
    )


def test_queries_keep_all_scope_dimensions_even_for_known_ids(world):
    record = original(world)
    decide(world, record)
    filters = world.requests.filter.call_args.args
    assert dict(filters[0].children) == {
        "organization_id": world.scope.organization_id,
        "series_id": world.scope.series_id,
        "edition_id": world.scope.edition_id,
    }
    assert filters[1].connector == "OR"
    assert set(filters[1].children) == {
        ("author_id", world.approver.id),
        ("approver_id", world.approver.id),
    }
    assert world.requests.filter.call_args.kwargs == {"id": record.id}


@pytest.mark.parametrize(
    "stage", ["_require_integrity", "_require_planning", "_require_controller"]
)
def test_authority_and_readiness_failure_precede_output(world, stage):
    record = original(world)
    world.mocks[stage].side_effect = ValidationError("Unavailable")
    with pytest.raises(ValidationError):
        decide(world, record)
    world.create.assert_not_called()
    assert not world.saved


def test_conflicting_existing_reserved_meaning_is_not_overwritten(world):
    record = original(world)
    world.existing.side_effect = ValidationError("Reserved meaning conflicts")
    with pytest.raises(ValidationError, match="Reserved"):
        decide(world, record)
    world.create.assert_not_called()
    assert not world.saved


def test_existing_definition_reuse_requires_own_approval_and_full_proof(
    world,
):
    record = original(world)
    world.output.replayed = True
    world.existing.return_value = world.output
    result = decide(world, record)
    assert not result.created_output
    world.create.assert_not_called()
    world.proof.assert_called_once_with(bundle=world.output.role_bundle, lock=True)
    assert len(world.saved) == 1


@pytest.mark.parametrize(
    ("action", "actor"), [(Action.DECLINE, "approver"), (Action.CANCEL, "actor")]
)
def test_own_decline_and_cancel_never_need_other_person_planning_or_output(
    world, action, actor
):
    record = original(world)
    record.approval_deadline = NOW - timedelta(days=1)
    person = getattr(world, actor)
    result = decide(world, record, action=action, actor=person)
    assert result.template_id is None
    assert result.role_bundle_id is None
    assert not result.created_output
    world.locks.assert_called_once_with({person.id})
    world.mocks["_require_planning"].assert_not_called()
    world.create.assert_not_called()
    world.existing.assert_not_called()
    world.proof.assert_not_called()


@pytest.mark.parametrize(
    ("action", "actor"),
    [
        (Action.APPROVE, "actor"),
        (Action.DECLINE, "actor"),
        (Action.CANCEL, "approver"),
        (Action.APPROVE, "stranger"),
    ],
)
def test_wrong_actual_person_cannot_decide(world, action, actor):
    record = original(world)
    with pytest.raises(AuthorizationDenied):
        decide(world, record, action=action, actor=getattr(world, actor))
    assert not world.saved
    assert not world.audits
    world.create.assert_not_called()


@pytest.mark.parametrize("remaining", [0, -1])
def test_expired_approval_cannot_create_output(world, remaining):
    record = original(world)
    record.approval_deadline = NOW + timedelta(seconds=remaining)
    with pytest.raises(ValidationError, match="expired"):
        decide(world, record)
    world.create.assert_not_called()


def test_exact_decision_replay_is_historical_and_not_recreated(world):
    record = original(world)
    first = decide(world, record)
    world.decisions.first.return_value = world.saved[-1]
    world.create.reset_mock()
    world.mocks["_require_planning"].reset_mock()
    world.locks.reset_mock()
    world.saved.clear()
    world.audits.clear()
    record.approval_deadline = NOW - timedelta(days=1)
    replay = decide(world, record, correlation_id=uuid4())
    assert replay == replace(first, replayed=True)
    world.locks.assert_called_once_with({world.approver.id})
    world.create.assert_not_called()
    world.mocks["_require_planning"].assert_not_called()
    assert not world.saved
    assert not world.audits


@pytest.mark.parametrize(
    "change",
    [
        {"reason": "Changed"},
        {"action": Action.DECLINE},
        {"idempotency_key": UUID(int=99)},
    ],
)
def test_changed_terminal_retry_never_recreates_output(world, change):
    record = original(world)
    decide(world, record)
    world.decisions.first.return_value = world.saved[-1]
    world.create.reset_mock()
    with pytest.raises(ValidationError):
        decide(world, record, **change)
    world.create.assert_not_called()


@pytest.mark.parametrize("stage", ["factory", "provenance", "audit", "append"])
def test_late_approval_failure_escapes_atomic_boundary_without_terminal_result(
    world, monkeypatch, stage
):
    record = original(world)
    if stage == "factory":
        world.create.side_effect = ValidationError("Unavailable")
    elif stage == "provenance":
        world.proof.return_value = False
    else:
        monkeypatch.setattr(
            commands,
            "append_audit" if stage == "audit" else "_append",
            MagicMock(side_effect=ValidationError("Unavailable")),
        )
    with pytest.raises(ValidationError):
        decide(world, record)
    assert world.trace[-1] == "rollback"
    assert not world.saved
    # This verifies exception propagation, not physical database rollback.


def test_global_key_conflict_is_non_disclosing_and_unrelated_integrity_is_not_hidden():
    error = IntegrityError("private database detail")
    error.__cause__ = Exception()
    error.__cause__.diag = SimpleNamespace(
        constraint_name="wrk_starter_decision_actor_key"
    )
    with pytest.raises(ValidationError, match="different intent"):
        commands._retry_failure(error)
    with pytest.raises(IntegrityError):
        commands._retry_failure(IntegrityError("other"))
