"""Minimal Department label owner admission, scope, bounds and audited disclosure."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.workforce import operator_target_choices as choices
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)


@pytest.fixture
def departments(monkeypatch):
    scope = dict(
        zip(
            ("actor_id", "organization_id", "edition_id", "correlation_id"),
            (UUID(int=n) for n in range(1, 5)),
            strict=True,
        )
    )
    records = [(UUID(int=5), "PROG", "Synthetic <Programme>")]
    manager = MagicMock()
    manager.filter.return_value = manager
    manager.order_by.return_value = manager
    manager.values_list.return_value = manager
    manager.__getitem__.side_effect = lambda key: records[key]
    monkeypatch.setattr(choices.Department, "objects", manager)
    monkeypatch.setattr(choices.transaction, "atomic", nullcontext)
    decision = PolicyDecision(
        allowed=True,
        fields=frozenset({"departments"}),
        obligations=frozenset(),
        reason_code="synthetic",
    )
    policy = Mock(return_value=decision)
    actor = Mock(return_value=object())
    locks = Mock()
    audit = Mock()
    for name, mock in {
        "decide_verified_principal_exact_edition": policy,
        "resolve_active_verified_person_reference": actor,
        "lock_programme_staffing_scope": locks,
        "append_audit": audit,
    }.items():
        monkeypatch.setattr(choices, name, mock)
    return SimpleNamespace(
        scope=scope,
        records=records,
        manager=manager,
        policy=policy,
        actor=actor,
        locks=locks,
        audit=audit,
        decision=decision,
    )


@pytest.mark.parametrize("empty", [False, True])
def test_minimal_current_scope_labels_have_actual_sender_positive_empty_audit(
    departments, empty
):
    w = departments
    if empty:
        w.records.clear()
    result = choices.list_programme_operator_department_choices(**w.scope)
    assert len(result) == len(w.records)
    assert w.manager.filter.call_args.kwargs == {
        "organization_id": w.scope["organization_id"],
        "edition_id": w.scope["edition_id"],
        "retired_at__isnull": True,
    }
    assert w.manager.values_list.call_args.args == ("id", "code", "name")
    assert w.manager.__getitem__.call_args.args == (
        slice(None, choices.MAX_STRUCTURE_DEPARTMENTS + 1),
    )
    assert w.manager.values_list.call_count == 2
    assert all(
        call.kwargs["requested_fields"] == frozenset({"departments"})
        for call in w.policy.call_args_list
    )
    audit = w.audit.call_args.args[0]
    assert audit.principal_id == w.scope["actor_id"]
    assert audit.target_id == w.scope["edition_id"]
    assert audit.operation == "workforce.programme_operator_department_choices.read"
    assert audit.retention_class == "workforce-restricted"
    assert "Synthetic" not in repr(audit)


def test_field_denial_precedes_scope_identity_and_tables(departments):
    w = departments
    w.policy.return_value = replace(w.decision, fields=frozenset())
    with pytest.raises(ProgrammeStaffingDeniedError):
        choices.list_programme_operator_department_choices(**w.scope)
    w.manager.filter.assert_not_called()
    w.actor.assert_not_called()
    w.locks.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    ["missing_actor", "moved_labels", "final_denial", "overflow", "database", "audit"],
)
def test_no_partial_or_unauditable_department_choices(departments, failure):
    w = departments
    if failure == "missing_actor":
        w.actor.return_value = None
    elif failure == "moved_labels":
        w.manager.__getitem__.side_effect = [w.records, []]
    elif failure == "final_denial":
        w.policy.side_effect = [
            w.decision,
            w.decision,
            replace(w.decision, allowed=False),
        ]
    elif failure == "overflow":
        w.records *= choices.MAX_STRUCTURE_DEPARTMENTS + 1
    elif failure == "database":
        w.manager.filter.side_effect = DatabaseError
    else:
        w.audit.side_effect = DatabaseError
    with pytest.raises(
        (ProgrammeStaffingDeniedError, ProgrammeStaffingUnavailableError)
    ):
        choices.list_programme_operator_department_choices(**w.scope)


def test_canonical_scope_precedes_actor_lock_and_label_read(departments):
    w = departments
    events = []
    w.locks.side_effect = lambda **_kwargs: events.append("scope")
    w.actor.side_effect = lambda **kwargs: (
        events.append(("actor", kwargs["lock"])) or object()
    )
    w.manager.__getitem__.side_effect = lambda key: (
        events.append("labels") or w.records[key]
    )
    choices.list_programme_operator_department_choices(**w.scope)
    assert events[:3] == ["scope", ("actor", True), "labels"]
