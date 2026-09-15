"""Real operator selection/signatures with minimized substituted owner boundaries."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.core import signing
from django.db import DatabaseError

from maru.identity.queries import ActiveVerifiedPersonReference
from maru.scheduling import operator_notice_choices as choices
from maru.scheduling import operator_notice_person_selection as people
from maru.scheduling import planning_queries
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.change_notice_selection import (
    NoticeOccurrenceChoice,
    NoticeSourceSelection,
)
from maru.scheduling.change_recipient_queries import (
    OperatorChangeRecipient,
    OperatorChangeRecipientIneligibleError,
)
from maru.scheduling.command_support import (
    SchedulingUnavailableError,
    SchedulingVersionConflictError,
)
from maru.scheduling.operator_scope import OperatorScopeKind
from maru.scheduling.planning_queries import PlanningOccurrence, SchedulingReadRequest
from maru.venues.timetable_queries import VenueTimetableSpace
from maru.workforce.queries import CurrentDepartmentChoiceReference


@pytest.fixture
def operator_world(monkeypatch, settings):
    settings.SECRET_KEY = "isolated-synthetic-operator-signatures"
    request = SchedulingReadRequest(*(UUID(int=n) for n in range(10, 14)))
    occurrence = PlanningOccurrence(uuid4(), uuid4(), 1, uuid4(), "active", None, None)
    source = NoticeSourceSelection(
        uuid4(), 2, (NoticeOccurrenceChoice(occurrence, "Opening <ceremony>", 1, 1),)
    )
    room = VenueTimetableSpace(
        uuid4(),
        1,
        "Stage <one>",
        "Standing",
        "active",
        uuid4(),
        1,
        "Synthetic hotel",
        "active",
    )
    department = CurrentDepartmentChoiceReference(uuid4(), "PROG", "Programme <team>")
    values = {
        "authorize_scheduling_scope": None,
        "load_notice_source_selection": source,
        "list_venue_timetable_spaces": (room,),
        "list_programme_operator_department_choices": (department,),
    }
    mocks = {name: Mock(return_value=value) for name, value in values.items()}
    for name, mock in mocks.items():
        monkeypatch.setattr(choices, name, mock)
    monkeypatch.setattr(choices, "connection", SimpleNamespace(in_atomic_block=False))
    person = ActiveVerifiedPersonReference(UUID(int=1))
    intent = people.OperatorNoticeIntent(
        source.release_id, occurrence.id, 2, OperatorScopeKind.ROOM, room.id, uuid4()
    )
    recipient = OperatorChangeRecipient(
        person.account_id,
        "Synthetic <operator>",
        intent.kind,
        intent.target_id,
        staffing_adopted=False,
        policy_version="synthetic",
    )
    lookup = Mock(return_value=person)
    locks = Mock(side_effect=lambda *, account_ids: tuple(sorted(account_ids)))
    loader = Mock(return_value=recipient)
    reads = []

    def read(scope, **kwargs):
        reads.append((scope, kwargs))
        return kwargs["loader"](None)

    monkeypatch.setattr(people, "_read", read)
    monkeypatch.setattr(
        people, "resolve_active_verified_person_reference_by_email", lookup
    )
    monkeypatch.setattr(people, "lock_account_references_for_evidence", locks)
    monkeypatch.setattr(people, "load_operator_change_recipient", loader)
    return SimpleNamespace(
        request=request,
        source=source,
        room=room,
        department=department,
        mocks=mocks,
        person=person,
        intent=intent,
        recipient=recipient,
        lookup=lookup,
        locks=locks,
        loader=loader,
        reads=reads,
    )


def prepare(world):
    return people.prepare_operator_notice_person_selection(
        world.request, intent=world.intent, email="known@example.invalid"
    )


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
def test_complete_labelled_targets_use_only_independent_relevant_owner(
    operator_world, kind
):
    w = operator_world
    result = choices.load_notice_operator_choices(
        w.request, occurrence_id=w.intent.occurrence_id, kind=kind
    )
    expected = {
        OperatorScopeKind.ROOM: w.room.id,
        OperatorScopeKind.DEPARTMENT: w.department.department_id,
        OperatorScopeKind.EDITION: w.request.edition_id,
    }[kind]
    assert result.targets[0].id == expected
    assert w.mocks["list_venue_timetable_spaces"].call_count == (
        kind is OperatorScopeKind.ROOM
    )
    assert w.mocks["list_programme_operator_department_choices"].call_count == (
        kind is OperatorScopeKind.DEPARTMENT
    )
    for call in w.mocks["authorize_scheduling_scope"].call_args_list:
        assert call.kwargs["requested_fields"] == frozenset({"operator_recipients"})
        assert call.kwargs["actor_id"] == w.request.actor_id
    w.lookup.assert_not_called()


def test_no_source_or_target_discovery_before_sender_field_admission(operator_world):
    w = operator_world
    w.mocks[
        "authorize_scheduling_scope"
    ].side_effect = SchedulingAuthorizationDeniedError
    with pytest.raises(SchedulingAuthorizationDeniedError):
        prepare(w)
    w.mocks["load_notice_source_selection"].assert_not_called()
    w.lookup.assert_not_called()


@pytest.mark.parametrize(
    "field", ["occurrence_id", "target_id", "release_id", "pointer_version"]
)
def test_unknown_or_moved_original_source_fails_before_identity(operator_world, field):
    w = operator_world
    w.intent = replace(
        w.intent, **{field: 3 if field == "pointer_version" else uuid4()}
    )
    with pytest.raises(SchedulingVersionConflictError):
        prepare(w)
    w.lookup.assert_not_called()


def test_retired_room_not_offered_and_outer_transaction_rejected(
    operator_world, monkeypatch
):
    w = operator_world
    w.mocks["list_venue_timetable_spaces"].return_value = (
        replace(w.room, venue_lifecycle="retired"),
    )
    with pytest.raises(SchedulingVersionConflictError):
        prepare(w)
    monkeypatch.setattr(choices, "connection", SimpleNamespace(in_atomic_block=True))
    with pytest.raises(SchedulingUnavailableError):
        prepare(w)
    w.lookup.assert_not_called()


def test_known_person_signature_binds_original_scope_and_uses_complete_locks(
    operator_world,
):
    w = operator_world
    result = prepare(w)
    assert result.recipient == w.recipient
    assert w.locks.call_args.kwargs == {
        "account_ids": tuple(sorted((w.request.actor_id, w.person.account_id)))
    }
    assert w.lookup.call_count == 2
    assert all(
        call.kwargs == {"email": "known@example.invalid"}
        for call in w.lookup.call_args_list
    )
    payload = signing.loads(result.token, salt=people._SALT)
    assert payload == people._payload(w.request, w.intent, w.person.account_id)
    assert "email" not in payload
    assert "label" not in payload
    assert not result.token.startswith(".")
    assert len(result.token) <= 2048
    assert w.reads[0][0] == w.request
    assert w.reads[0][1]["purpose"] == "operator_notice_known_person"


@pytest.mark.parametrize("empty", ["unknown", "ineligible"])
def test_unknown_and_ineligible_share_audited_empty_result(operator_world, empty):
    w = operator_world
    if empty == "unknown":
        w.lookup.return_value = None
    else:
        w.loader.side_effect = OperatorChangeRecipientIneligibleError
    assert prepare(w) is None
    assert len(w.reads) == 1
    assert w.reads[0][1]["fields"] == frozenset({"operator_recipients"})


@pytest.mark.parametrize("failure", ["lock", "email_move", "dependency", "source_move"])
def test_unavailable_is_never_advertised_as_empty(operator_world, failure):
    w = operator_world
    if failure == "lock":
        w.locks.return_value = None
        w.locks.side_effect = None
    elif failure == "email_move":
        w.lookup.side_effect = [w.person, ActiveVerifiedPersonReference(uuid4())]
    elif failure == "dependency":
        w.loader.side_effect = SchedulingUnavailableError
    else:
        w.mocks["load_notice_source_selection"].side_effect = [
            w.source,
            replace(w.source, pointer_version=3),
        ]
    with pytest.raises((SchedulingUnavailableError, SchedulingVersionConflictError)):
        prepare(w)


def test_signed_retry_never_resolves_email_or_retargets_person(operator_world):
    w = operator_world
    result = prepare(w)
    w.lookup.reset_mock()
    w.lookup.side_effect = AssertionError("Email must never be revisited")
    assert (
        people.load_operator_notice_person_selection(w.request, token=result.token)
        == result
    )
    w.lookup.assert_not_called()
    assert w.loader.call_args.args[0].account_id == w.person.account_id
    w.loader.side_effect = OperatorChangeRecipientIneligibleError
    with pytest.raises(SchedulingUnavailableError):
        people.load_operator_notice_person_selection(w.request, token=result.token)


@pytest.mark.parametrize(
    "mutation",
    [
        "actor",
        "organization",
        "edition",
        "person",
        "pointer",
        "extra",
        "kind",
        "compressed",
        "oversized",
        "tamper",
    ],
)
def test_signed_selection_rejects_wrong_context_and_noncanonical_shape(
    operator_world, mutation
):
    w = operator_world
    result = prepare(w)
    payload = signing.loads(result.token, salt=people._SALT)
    if mutation in {"actor", "organization", "edition"}:
        payload[mutation] = str(uuid4())
    elif mutation == "person":
        payload[mutation] = str(UUID(int=0))
    elif mutation == "pointer":
        payload[mutation] = True
    elif mutation == "extra":
        payload[mutation] = "unexpected"
    elif mutation == "kind":
        payload[mutation] = "host"
    token = signing.dumps(payload, salt=people._SALT, compress=mutation == "compressed")
    if mutation == "oversized":
        token = "a" * 2049
    elif mutation == "tamper":
        token += "x"
    w.loader.reset_mock()
    with pytest.raises(SchedulingAuthorizationDeniedError):
        people.load_operator_notice_person_selection(w.request, token=token)
    w.loader.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("audit_failure", [False, True])
def test_real_read_requires_actual_sender_positive_empty_audit(
    operator_world, monkeypatch, empty, audit_failure
):
    w = operator_world
    if empty:
        w.lookup.return_value = None
    audit = Mock(side_effect=DatabaseError if audit_failure else None)
    authorize = Mock(return_value=object())
    monkeypatch.setattr(people, "_read", planning_queries._read)
    monkeypatch.setattr(planning_queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(planning_queries, "_lock_edition", Mock())
    monkeypatch.setattr(planning_queries, "_authorize", authorize)
    monkeypatch.setattr(planning_queries, "_audit", audit)
    if audit_failure:
        with pytest.raises(SchedulingUnavailableError):
            prepare(w)
    else:
        assert (prepare(w) is None) is empty
    assert audit.call_args.args == (
        w.request,
        people.VIEW_CHANGE_RECIPIENTS,
        "operator_notice_known_person",
    )
    assert authorize.call_args.kwargs == {"lock": True}
    assert "known@example.invalid" not in repr(audit.call_args)
