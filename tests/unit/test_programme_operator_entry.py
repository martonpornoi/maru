"""Complete operator choice admission, minimal labels and source/audit failures."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.events.queries import EditionAdoptionProfileReference
from maru.events.scheduling_queries import SchedulingEditionReference
from maru.identity.queries import ActiveVerifiedPersonReference
from maru.scheduling import operator_entry_queries as entry
from maru.scheduling import operator_scope
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.venues.operator_entry_references import (
    OperatorRoomCandidate,
    OperatorRoomChoiceReference,
    OperatorRoomSetReference,
)
from maru.workforce.queries import (
    CurrentDepartmentChoiceReference,
    CurrentDepartmentSetReference,
)

DENIED = PolicyDecision(
    allowed=False,
    fields=frozenset(),
    obligations=frozenset(),
    reason_code="permission_absent",
)


@pytest.fixture
def world(monkeypatch):
    scope = SchedulingReadRequest(*(UUID(int=value) for value in range(1, 5)))
    departments = (UUID(int=10), UUID(int=20))
    rooms = tuple(
        OperatorRoomCandidate(UUID(int=value), 1, UUID(int=40), 1, department)
        for value, department in zip((30, 31), departments, strict=True)
    )
    actor = Mock(return_value=ActiveVerifiedPersonReference(scope.actor_id))
    edition = Mock(
        return_value=SchedulingEditionReference(
            scope.organization_id,
            scope.edition_id,
            1,
            accepts_scheduling_writes=True,
            zone_name="Europe/Budapest",
        )
    )
    profile = Mock(
        return_value=EditionAdoptionProfileReference("programme_operations", 1)
    )
    staffing = {"adopted": False}
    adapters = Mock(
        side_effect=lambda _code, _version, code: (
            code == entry.SCHEDULING_OPERATOR_RELEASE_ADAPTER or staffing["adopted"]
        )
    )
    room_set = Mock(
        return_value=OperatorRoomSetReference(
            scope.organization_id, scope.edition_id, rooms
        )
    )
    department_set = Mock(
        return_value=CurrentDepartmentSetReference(
            scope.organization_id, scope.edition_id, departments
        )
    )
    trace, grants = [], {}

    def decide(request, *, capability, fields):
        trace.append(("policy", request.kind, request.target_id, capability))
        assert (
            request.actor_id,
            request.organization_id,
            request.edition_id,
            request.correlation_id,
        ) == (
            scope.actor_id,
            scope.organization_id,
            scope.edition_id,
            scope.correlation_id,
        )
        return grants.get((request.kind, request.target_id, capability), DENIED)

    policies = Mock(side_effect=decide)
    room_labels = {
        row.space_id: OperatorRoomChoiceReference(
            row, f"Room {index}", "Convention Hotel"
        )
        for index, row in enumerate(rooms, start=1)
    }
    department_labels = {
        value: CurrentDepartmentChoiceReference(value, f"dept-{index}", "Programme")
        for index, value in enumerate(departments, start=1)
    }

    def room_label(**values):
        trace.append(("room_label", values["space_id"]))
        assert values["organization_id"] == scope.organization_id
        assert values["edition_id"] == scope.edition_id
        return room_labels[values["space_id"]]

    def department_label(**values):
        trace.append(("department_label", values["department_id"]))
        return department_labels[values["department_id"]]

    room_lookup, department_lookup = (
        Mock(side_effect=room_label),
        Mock(side_effect=department_label),
    )
    audit = Mock(side_effect=lambda record: trace.append(("audit", record.target_id)))
    monkeypatch.setattr(entry.transaction, "atomic", nullcontext)
    monkeypatch.setattr(entry, "resolve_active_verified_person_reference", actor)
    monkeypatch.setattr(entry, "resolve_scheduling_edition_reference", edition)
    monkeypatch.setattr(entry, "edition_adoption_profile_reference", profile)
    monkeypatch.setattr(entry, "profile_allows_adapter", adapters)
    monkeypatch.setattr(entry, "resolve_operator_room_set_reference", room_set)
    monkeypatch.setattr(
        entry, "resolve_current_department_set_reference", department_set
    )
    monkeypatch.setattr(entry, "resolve_operator_room_choice_reference", room_lookup)
    monkeypatch.setattr(
        entry, "resolve_current_department_choice_reference", department_lookup
    )
    monkeypatch.setattr(entry, "append_audit", audit)
    monkeypatch.setattr(operator_scope, "_operator_scope_decision", policies)
    return SimpleNamespace(**locals())


def allow(world, kind=operator_scope.OperatorScopeKind.ROOM, target_id=None):
    target_id = (
        target_id
        or {
            operator_scope.OperatorScopeKind.ROOM: world.rooms[0].space_id,
            operator_scope.OperatorScopeKind.DEPARTMENT: world.departments[0],
            operator_scope.OperatorScopeKind.EDITION: world.scope.edition_id,
        }[kind]
    )
    for capability, fields in entry._owners(kind, staffing=world.staffing["adopted"]):
        world.grants[(kind, target_id, capability)] = PolicyDecision(
            allowed=True,
            fields=fields,
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="direct_grant",
        )
    return kind, target_id


@pytest.mark.parametrize("kind", list(operator_scope.OperatorScopeKind))
def test_only_complete_independent_purpose_is_named_after_all_policy(world, kind):
    kind, target = allow(world, kind)
    result = entry.load_operator_entry(world.scope)
    assert [(choice.kind, choice.target_id) for choice in result.choices] == [
        (kind, target)
    ]
    assert len(result.source_fingerprint) == 64
    first_label = next(
        (index for index, item in enumerate(world.trace) if item[0].endswith("label")),
        None,
    )
    if first_label is not None:
        assert all(item[0] == "policy" for item in world.trace[:first_label])
        assert first_label == 15
    for call in world.room_lookup.call_args_list:
        assert kind is operator_scope.OperatorScopeKind.ROOM
        assert call.kwargs["space_id"] == target
    for call in world.department_lookup.call_args_list:
        assert kind is operator_scope.OperatorScopeKind.DEPARTMENT
        assert call.kwargs["department_id"] == target
    assert world.audit.call_count == 3
    assert {call.args[0].capability_code for call in world.audit.call_args_list} == {
        code for code, _ in entry._OWNERS
    }
    assert all(call.args[0].target_id == target for call in world.audit.call_args_list)


def test_authorized_empty_observation_has_no_labels_or_hidden_target_audit(world):
    assert entry.load_operator_entry(world.scope).choices == ()
    world.room_lookup.assert_not_called()
    world.department_lookup.assert_not_called()
    record = world.audit.call_args.args[0]
    assert record.target_id is None
    assert record.reason_code == "permission_absent"
    assert record.safe_metadata == {"policy_version": entry.POLICY_VERSION}


@pytest.mark.parametrize("kind", list(operator_scope.OperatorScopeKind))
@pytest.mark.parametrize("missing", [code for code, _fields in entry._OWNERS])
@pytest.mark.parametrize("partial", [False, True])
def test_missing_or_partial_owner_never_names_the_purpose(
    world, kind, missing, partial
):
    key = (*allow(world, kind), missing)
    world.grants[key] = (
        replace(world.grants[key], fields=frozenset()) if partial else DENIED
    )
    assert entry.load_operator_entry(world.scope).choices == ()
    world.room_lookup.assert_not_called()
    world.department_lookup.assert_not_called()


def test_adopted_department_work_needs_only_explicit_membership_not_details(world):
    world.staffing["adopted"] = True
    kind, target = allow(world, operator_scope.OperatorScopeKind.DEPARTMENT)
    key = (kind, target, entry._WORK[0])
    grant = world.grants.pop(key)
    assert entry.load_operator_entry(world.scope).choices == ()
    world.department_lookup.assert_not_called()
    world.grants[key] = grant
    assert len(entry.load_operator_entry(world.scope).choices) == 1
    assert grant.fields == frozenset({"scope_links"})
    assert all(
        call.kwargs["capability"] != "programme.view_operator_delivery"
        for call in world.policies.call_args_list
    )


@pytest.mark.parametrize(
    "change", ["actor", "edition", "profile", "room_set", "department_set"]
)
def test_missing_owner_withholds_entire_catalog_before_labels(world, change):
    allow(world)
    getattr(world, change).return_value = None
    with pytest.raises((entry.Denied, entry.Unavailable)):
        entry.load_operator_entry(world.scope)
    world.room_lookup.assert_not_called()
    world.audit.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        "foreign_room",
        "foreign_department",
        "duplicate_room",
        "duplicate_department",
        "bad_room",
        "zero_version",
        "oversized_room",
        "oversized_department",
    ],
)
def test_bad_complete_membership_is_never_silently_filtered(world, change):
    allow(world)
    rooms, departments = world.room_set.return_value, world.department_set.return_value
    if change == "foreign_room":
        rooms = replace(rooms, organization_id=UUID(int=99))
    elif change == "foreign_department":
        departments = replace(departments, edition_id=UUID(int=99))
    elif change == "duplicate_room":
        rooms = replace(rooms, rooms=(*rooms.rooms, rooms.rooms[0]))
    elif change == "duplicate_department":
        departments = replace(
            departments,
            department_ids=(*departments.department_ids, departments.department_ids[0]),
        )
    elif change == "bad_room":
        rooms = replace(rooms, rooms=(object(),))
    elif change == "zero_version":
        rooms = replace(rooms, rooms=(replace(rooms.rooms[0], version=0),))
    elif change == "oversized_room":
        rooms = replace(rooms, rooms=rooms.rooms[:1] * 257)
    else:
        departments = replace(
            departments, department_ids=departments.department_ids[:1] * 257
        )
    world.room_set.return_value, world.department_set.return_value = rooms, departments
    with pytest.raises(entry.Unavailable):
        entry.load_operator_entry(world.scope)
    world.room_lookup.assert_not_called()
    world.audit.assert_not_called()


@pytest.mark.parametrize(
    "bad",
    [
        object(),
        replace(DENIED, allowed=1),
        replace(DENIED, reason_code="scope_denied"),
        replace(DENIED, policy_version="old"),
        replace(DENIED, fields=set()),
        replace(DENIED, obligations=frozenset({"audit_sensitive_read"})),
    ],
)
def test_malformed_or_nonordinary_policy_withholds_catalog(world, bad):
    allow(world)
    world.grants[
        (
            operator_scope.OperatorScopeKind.ROOM,
            world.rooms[1].space_id,
            entry._OWNERS[0][0],
        )
    ] = bad
    with pytest.raises(entry.Denied):
        entry.load_operator_entry(world.scope)
    world.room_lookup.assert_not_called()
    world.audit.assert_not_called()


@pytest.mark.parametrize(
    "change", ["label", "version", "policy", "department", "adapter"]
)
def test_second_observation_movement_never_commits_success_audit(world, change):
    kind, target = allow(world)
    original = world.room_lookup.side_effect

    def moved(**values):
        value = original(**values)
        if change == "label":
            world.room_labels[target] = replace(value, label="Moved room")
        elif change == "version":
            world.room_set.return_value = replace(
                world.room_set.return_value,
                rooms=(replace(world.rooms[0], version=2), world.rooms[1]),
            )
        elif change == "policy":
            world.grants[(kind, target, entry._OWNERS[0][0])] = DENIED
        elif change == "department":
            world.department_set.return_value = replace(
                world.department_set.return_value, department_ids=world.departments[:1]
            )
        else:
            world.adapters.side_effect = None
            world.adapters.return_value = False
        return value

    world.room_lookup.side_effect = moved
    with pytest.raises((entry.Unavailable, entry.Denied)):
        entry.load_operator_entry(world.scope)
    world.audit.assert_not_called()


def test_indistinguishable_permitted_rooms_fail_without_deduplication(world):
    allow(world)
    allow(world, target_id=world.rooms[1].space_id)
    world.room_labels[world.rooms[1].space_id] = replace(
        world.room_labels[world.rooms[1].space_id], label="Room 1"
    )
    with pytest.raises(entry.Unavailable):
        entry.load_operator_entry(world.scope)
    world.audit.assert_not_called()


@pytest.mark.parametrize(
    "source", ["room_set", "room_lookup", "department_set", "policies", "audit"]
)
def test_database_failure_never_releases_apparently_complete_choices(world, source):
    allow(world)
    getattr(world, source).side_effect = DatabaseError("synthetic failure")
    with pytest.raises(entry.Unavailable):
        entry.load_operator_entry(world.scope)


def test_metadata_offers_no_names_or_sensitive_read_audit(world):
    assert entry.can_enter_operator_tasks(world.scope) is False
    allow(world)
    assert entry.can_enter_operator_tasks(world.scope) is True
    world.room_lookup.assert_not_called()
    world.department_lookup.assert_not_called()
    world.audit.assert_not_called()
    world.room_set.side_effect = DatabaseError
    assert entry.can_enter_operator_tasks(world.scope) is False


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "correlation_id"]
)
def test_zero_identifiers_are_rejected_before_owner_dispatch(world, field):
    scope = replace(world.scope, **{field: UUID(int=0)})
    assert entry.can_enter_operator_tasks(scope) is False
    with pytest.raises(entry.Denied):
        entry.load_operator_entry(scope)
    world.actor.assert_not_called()
