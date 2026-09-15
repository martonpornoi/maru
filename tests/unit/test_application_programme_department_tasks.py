"""Complete entry authority, source changes and no hidden Department disclosure."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.applications import programme_call_departments as departments
from maru.applications import programme_department_tasks as tasks
from maru.authorization.policy import PolicyDecision
from maru.events.queries import (
    EditionAdoptionProfileReference,
    PrivatePlanningEditionReference,
)
from maru.identity.queries import ActiveVerifiedPersonReference
from maru.workforce.queries import (
    CurrentDepartmentChoiceReference,
    CurrentDepartmentSetReference,
)

_DENY = PolicyDecision(
    allowed=False,
    fields=frozenset(),
    obligations=frozenset(),
    reason_code="permission_absent",
)


@pytest.fixture
def entry(monkeypatch):
    values = {
        key: UUID(int=index)
        for index, key in enumerate(
            ("actor_id", "organization_id", "edition_id", "correlation_id"), start=1
        )
    }
    values["source_channel"] = "test"
    ids = (UUID(int=10), UUID(int=20), UUID(int=30))
    trace = []
    policies = {}

    def policy(**kw):
        trace.append(("policy", kw["department_id"]))
        return policies.get(
            (kw["department_id"], kw["capability_code"], kw["requested_fields"]), _DENY
        )

    authorizer = SimpleNamespace(authorize_department=Mock(side_effect=policy))
    values["authorizer"] = authorizer
    guard = Mock(side_effect=lambda value: trace.append(("guard", value)))
    actor = Mock(return_value=ActiveVerifiedPersonReference(values["actor_id"]))
    edition = Mock(
        return_value=PrivatePlanningEditionReference(
            values["edition_id"],
            values["organization_id"],
            accepts_private_planning_writes=True,
        )
    )
    profile = Mock(
        return_value=EditionAdoptionProfileReference("programme_operations", 1)
    )
    adopted = Mock(return_value=True)
    members = CurrentDepartmentSetReference(
        values["organization_id"], values["edition_id"], ids
    )
    listing = Mock(return_value=members)
    labels = {
        identifier: CurrentDepartmentChoiceReference(identifier, code, label)
        for identifier, code, label in zip(
            ids,
            ("programme", "stage", "private"),
            ("Programme", "Programme", "Hidden department"),
            strict=True,
        )
    }

    def label(**kw):
        trace.append(("label", kw["department_id"]))
        return labels[kw["department_id"]]

    lookup = Mock(side_effect=label)
    audit = Mock(
        side_effect=lambda record, **_kw: trace.append(("audit", record.target_id))
    )
    monkeypatch.setattr(tasks, "_require_test_authorizer", guard)
    monkeypatch.setattr(tasks, "resolve_active_verified_person_reference", actor)
    monkeypatch.setattr(tasks, "resolve_private_planning_edition_reference", edition)
    monkeypatch.setattr(tasks, "edition_adoption_profile_reference", profile)
    monkeypatch.setattr(tasks, "profile_allows_application_target", adopted)
    monkeypatch.setattr(tasks, "resolve_current_department_set_reference", listing)
    monkeypatch.setattr(
        departments, "resolve_current_department_choice_reference", lookup
    )
    monkeypatch.setattr(tasks, "append_audit", audit)
    monkeypatch.setattr(tasks.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        values=values,
        ids=ids,
        policies=policies,
        trace=trace,
        guard=guard,
        actor=actor,
        edition=edition,
        profile=profile,
        adopted=adopted,
        members=members,
        listing=listing,
        labels=labels,
        lookup=lookup,
        audit=audit,
        authorizer=authorizer,
    )


def _allow(entry, task, index=0, **changes):
    decision = PolicyDecision(
        allowed=True,
        fields=task.fields,
        obligations=task.obligations,
        reason_code="direct_grant",
    )
    entry.policies[(entry.ids[index], task.capability, task.fields or None)] = replace(
        decision, **changes
    )


@pytest.mark.parametrize("task", tasks._TASKS, ids=lambda task: task.code)
def test_each_purpose_has_only_its_exact_destination_fields_and_audit(entry, task):
    _allow(entry, task)
    result = tasks.list_programme_department_tasks(**entry.values)
    assert len(result.tasks) == 1
    choice = result.tasks[0]
    assert choice.task_code == task.code
    assert choice.department_id == entry.ids[0]
    assert choice.department_label == "Programme"
    assert choice.policy_label == "Direct permission"
    assert choice.url.endswith(f"/{entry.ids[0]}/{task.suffix}")
    assert len(result.source_fingerprint) == 64
    assert result.source_fingerprint not in repr(result)
    assert "Hidden department" not in repr(result)
    assert entry.trace[0][0] == "guard"
    assert entry.trace.index(("policy", entry.ids[-1])) < entry.trace.index(
        ("label", entry.ids[0])
    )
    assert {call.kwargs["department_id"] for call in entry.lookup.call_args_list} == {
        entry.ids[0]
    }
    records = [call.args[0] for call in entry.audit.call_args_list]
    allowed = [record for record in records if record.outcome == "allow"]
    assert len(allowed) == 1
    assert allowed[0].capability_code == task.capability
    assert allowed[0].target_id == entry.ids[0]
    assert "audit_sensitive_read" in allowed[0].obligations
    assert all(record.safe_metadata is None for record in records)
    assert all(record.principal_id == entry.values["actor_id"] for record in records)
    assert all("Hidden department" not in repr(record) for record in records)


def test_mixed_departments_and_partial_fields_preserve_independent_tasks(entry):
    _allow(entry, tasks._TASKS[0])
    _allow(entry, tasks._TASKS[1], fields=frozenset())
    _allow(entry, tasks._TASKS[2])
    _allow(entry, tasks._TASKS[3], index=1, reason_code="role_assignment")
    result = tasks.list_programme_department_tasks(**entry.values)
    assert [(item.department_code, item.task_code) for item in result.tasks] == [
        ("programme", "calls"),
        ("programme", "reviewers"),
        ("stage", "mine"),
    ]
    assert result.tasks[-1].policy_label == "Assigned role"
    assert all(
        not call.kwargs["capability_code"].startswith("workforce.")
        for call in entry.authorizer.authorize_department.call_args_list
    )
    assert tasks.list_programme_department_tasks(**entry.values) == result


@pytest.mark.parametrize("empty_members", [False, True])
def test_empty_does_not_claim_a_grant_or_load_hidden_names(entry, empty_members):
    if empty_members:
        entry.listing.return_value = replace(entry.members, department_ids=())
    result = tasks.list_programme_department_tasks(**entry.values)
    assert result.tasks == ()
    entry.lookup.assert_not_called()
    assert len(entry.audit.call_args_list) == len(tasks._TASKS)
    for call in entry.audit.call_args_list:
        assert call.args[0].outcome == "deny"
        assert call.args[0].target_id is None
        assert call.args[0].reason_code == "task_unavailable"


def test_readonly_keeps_admitted_inspection(entry):
    _allow(entry, tasks._TASKS[0])
    entry.edition.return_value = replace(
        entry.edition.return_value, accepts_private_planning_writes=False
    )
    result = tasks.list_programme_department_tasks(**entry.values)
    assert not result.accepts_private_planning_writes
    assert len(result.tasks) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed": 1},
        {"fields": frozenset({"review_answers"})},
        {"fields": set()},
        {"obligations": frozenset()},
        {"obligations": frozenset({"unknown"})},
        {"reason_code": "unknown"},
        {"reason_code": []},
        {"policy_version": "old"},
        {"allowed": False, "reason_code": "account_inactive"},
    ],
)
def test_incoherent_policy_withholds_whole_catalog_before_names(entry, changes):
    _allow(entry, tasks._TASKS[0])
    _allow(entry, tasks._TASKS[3], index=1, **changes)
    with pytest.raises(tasks.Denied):
        tasks.list_programme_department_tasks(**entry.values)
    entry.lookup.assert_not_called()


@pytest.mark.parametrize("dependency", ["actor", "edition", "profile"])
def test_unknown_owner_or_profile_cannot_enumerate(entry, dependency):
    getattr(entry, dependency).return_value = None
    with pytest.raises(tasks.Denied):
        tasks.list_programme_department_tasks(**entry.values)
    entry.listing.assert_not_called()
    entry.lookup.assert_not_called()


def test_inactive_profile_is_denied_even_when_edition_has_no_departments(entry):
    entry.adopted.return_value = False
    entry.listing.return_value = replace(entry.members, department_ids=())
    with pytest.raises(tasks.Denied):
        tasks.list_programme_department_tasks(**entry.values)
    entry.listing.assert_not_called()


@pytest.mark.parametrize(
    "change", ["foreign", "duplicate", "zero", "overflow", "missing"]
)
def test_incoherent_or_oversized_department_set_has_no_partial_names(entry, change):
    source = {
        "foreign": replace(entry.members, organization_id=UUID(int=90)),
        "duplicate": replace(
            entry.members, department_ids=(entry.ids[0], entry.ids[0])
        ),
        "zero": replace(entry.members, department_ids=(UUID(int=0),)),
        "overflow": replace(
            entry.members, department_ids=tuple(UUID(int=i + 1) for i in range(257))
        ),
        "missing": None,
    }[change]
    entry.listing.return_value = source
    with pytest.raises(tasks.Denied):
        tasks.list_programme_department_tasks(**entry.values)
    entry.lookup.assert_not_called()


@pytest.mark.parametrize(
    "change", ["permission", "label", "hidden_set", "lifecycle", "identity", "profile"]
)
def test_changed_source_during_audit_discards_visible_catalog(entry, change):
    _allow(entry, tasks._TASKS[0])

    def alter(record, **kw):
        if change == "permission":
            entry.policies.clear()
        elif change == "label":
            entry.labels[entry.ids[0]] = replace(
                entry.labels[entry.ids[0]], label="Changed"
            )
        elif change == "hidden_set":
            entry.listing.return_value = replace(
                entry.members, department_ids=entry.ids[:2]
            )
        elif change == "lifecycle":
            entry.edition.return_value = replace(
                entry.edition.return_value, accepts_private_planning_writes=False
            )
        elif change == "profile":
            entry.profile.return_value = replace(entry.profile.return_value, version=2)
        else:
            entry.actor.return_value = None

    entry.audit.side_effect = alter
    with pytest.raises(tasks.Denied):
        tasks.list_programme_department_tasks(**entry.values)


@pytest.mark.parametrize("dependency", ["lookup", "listing", "audit"])
def test_dependency_failure_never_returns_partial_choices(entry, dependency):
    _allow(entry, tasks._TASKS[0])
    getattr(entry, dependency).side_effect = DatabaseError("synthetic unavailable")
    with pytest.raises(DatabaseError):
        tasks.list_programme_department_tasks(**entry.values)


def test_substitute_authorizer_must_pass_existing_guard(entry):
    entry.guard.side_effect = tasks.Denied
    with pytest.raises(tasks.Denied):
        tasks.list_programme_department_tasks(**entry.values)
    entry.actor.assert_not_called()
    entry.listing.assert_not_called()


@pytest.mark.parametrize("owner", ["actor", "organization", "edition"])
def test_foreign_owner_reference_never_reaches_department_discovery(entry, owner):
    if owner == "actor":
        entry.actor.return_value = ActiveVerifiedPersonReference(UUID(int=99))
    else:
        entry.edition.return_value = replace(
            entry.edition.return_value, **{owner + "_id": UUID(int=99)}
        )
    with pytest.raises(tasks.Denied):
        tasks.list_programme_department_tasks(**entry.values)
    entry.listing.assert_not_called()
    assert all(call.args[0].outcome == "deny" for call in entry.audit.call_args_list)
    assert all(call.args[0].target_id is None for call in entry.audit.call_args_list)


def test_complete_maximum_department_catalog_is_not_silently_truncated(entry):
    entry.ids = tuple(UUID(int=index + 100) for index in range(256))
    entry.listing.return_value = replace(entry.members, department_ids=entry.ids)
    entry.labels.clear()
    for index, identifier in enumerate(entry.ids):
        entry.labels[identifier] = CurrentDepartmentChoiceReference(
            identifier, f"department-{index}", f"Synthetic Department {index}"
        )
        _allow(entry, tasks._TASKS[0], index=index)
    result = tasks.list_programme_department_tasks(**entry.values)
    assert len(result.tasks) == 256
    assert {item.department_id for item in result.tasks} == set(entry.ids)
