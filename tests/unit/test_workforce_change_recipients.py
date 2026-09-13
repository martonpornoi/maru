"""Sender work-field authority, exact recipients and mandatory minimized audit."""

from contextlib import nullcontext
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.scheduling.command_support import SchedulingUnavailableError
from maru.workforce import change_recipient_queries as queries
from maru.workforce.operator_links import OperatorWorkLink
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)


@pytest.fixture
def world(monkeypatch):
    request = queries.ProgrammeWorkRecipientRequest(
        *(UUID(int=n) for n in range(10, 16))
    )
    recipient = UUID(int=1)
    work = (request.commitment_id, recipient, 3, "confirmed", UUID(int=16), 4)
    source = OperatorWorkLink(
        request.occurrence_id, UUID(int=17), 2, work[4], work[5], current=False
    )
    decision = PolicyDecision(
        allowed=True,
        fields=queries._FIELDS,
        obligations=frozenset(),
        reason_code="sender_scope",
    )
    real_work = queries._work
    values = {
        "decide_verified_principal_exact_edition": decision,
        "edition_adoption_profile_reference": SimpleNamespace(
            code="synthetic", version=1
        ),
        "profile_allows_adapter": True,
        "lock_programme_staffing_scope": None,
        "_work": work,
        "_load_lineage": (source,),
        "resolve_active_verified_person_reference": object(),
        "active_verified_person_account_display_labels": {
            recipient: "Selected volunteer"
        },
        "append_audit": None,
    }
    mocks = {name: Mock(return_value=value) for name, value in values.items()}
    for name, mock in mocks.items():
        monkeypatch.setattr(queries, name, mock)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        request=request,
        recipient=recipient,
        work=work,
        source=source,
        decision=decision,
        mocks=mocks,
        real_work=real_work,
    )


def test_exact_sender_authority_and_recipient_identity_have_distinct_roles(world):
    result = queries.load_work_change_recipient(world.request)
    assert result.account_id == world.recipient != world.request.actor_id
    assert result.work.commitment_id == world.request.commitment_id
    assert result.work.occurrence_id == world.request.occurrence_id
    assert result.work.status == "confirmed"
    assert result.work.demand_id == world.work[4]
    assert not result.work.current
    assert set(asdict(result)) == {"account_id", "display_label", "work"}
    for call in world.mocks["decide_verified_principal_exact_edition"].call_args_list:
        assert call.kwargs["principal_id"] == world.request.actor_id
        assert call.kwargs["requested_fields"] == frozenset(
            {"coverage_states", "holder_display_labels"}
        )
    people = world.mocks["resolve_active_verified_person_reference"].call_args_list
    assert [call.kwargs["account_id"] for call in people] == [
        world.recipient,
        world.request.actor_id,
    ]
    assert all(call.kwargs["lock"] for call in people)
    world.mocks[
        "active_verified_person_account_display_labels"
    ].assert_called_once_with({world.recipient})
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.principal_id == world.request.actor_id
    assert audit.target_id == world.request.commitment_id
    assert audit.operation == "workforce.programme_change_recipient.read"
    assert "Selected volunteer" not in repr(audit)
    assert (
        world.mocks["_work"].call_count == world.mocks["_load_lineage"].call_count == 2
    )
    assert world.mocks["_load_lineage"].call_args.kwargs == {
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
        "demand_ids": {world.work[4]},
    }


@pytest.mark.parametrize(
    "fault", ["permission", "coverage_fields", "label_fields", "profile", "adapter"]
)
def test_owner_admission_failure_precedes_personnel_lookup(world, fault):
    if fault in {"permission", "coverage_fields", "label_fields"}:
        world.mocks["decide_verified_principal_exact_edition"].return_value = replace(
            world.decision,
            allowed=fault != "permission",
            fields=frozenset({"coverage_states"})
            if fault == "label_fields"
            else frozenset({"holder_display_labels"}),
        )
    elif fault == "profile":
        world.mocks["edition_adoption_profile_reference"].return_value = None
    else:
        world.mocks["profile_allows_adapter"].return_value = False
    with pytest.raises(ProgrammeStaffingDeniedError):
        queries.load_work_change_recipient(world.request)
    world.mocks["_work"].assert_not_called()


@pytest.mark.parametrize("person", ["sender", "recipient"])
def test_current_verified_person_is_required_in_canonical_order(world, person):
    identifier = world.request.actor_id if person == "sender" else world.recipient
    world.mocks["resolve_active_verified_person_reference"].side_effect = (
        lambda *, account_id, lock: (
            None if account_id == identifier or not lock else object()
        )
    )
    with pytest.raises(
        ProgrammeStaffingDeniedError
        if person == "sender"
        else ProgrammeStaffingUnavailableError
    ):
        queries.load_work_change_recipient(world.request)
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "occurrence", "demand", "version"]
)
def test_lineage_must_prove_the_exact_requested_work_purpose(world, fault):
    if fault == "missing":
        sources = ()
    elif fault == "duplicate":
        sources = (world.source, world.source)
    else:
        name = {
            "occurrence": "occurrence_id",
            "demand": "demand_id",
            "version": "demand_version",
        }[fault]
        sources = (
            replace(world.source, **{name: 99 if fault == "version" else UUID(int=99)}),
        )
    world.mocks["_load_lineage"].return_value = sources
    with pytest.raises(ProgrammeStaffingUnavailableError):
        queries.load_work_change_recipient(world.request)
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()


@pytest.mark.parametrize(
    "source", ["work", "lineage", "labels", "final_authority", "audit"]
)
def test_late_owner_or_audit_failure_withholds_the_selected_recipient(world, source):
    expected = ProgrammeStaffingUnavailableError
    if source == "work":
        world.mocks["_work"].side_effect = [
            world.work,
            (*world.work[:2], 4, *world.work[3:]),
        ]
    elif source == "lineage":
        world.mocks["_load_lineage"].side_effect = [(world.source,), ()]
    elif source == "labels":
        world.mocks["active_verified_person_account_display_labels"].return_value = {}
    elif source == "final_authority":
        world.mocks["decide_verified_principal_exact_edition"].side_effect = [
            world.decision,
            world.decision,
            replace(world.decision, allowed=False),
        ]
        expected = ProgrammeStaffingDeniedError
    else:
        world.mocks["append_audit"].side_effect = RuntimeError("audit unavailable")
        expected = RuntimeError
    with pytest.raises(expected):
        queries.load_work_change_recipient(world.request)


@pytest.mark.parametrize("error", [DatabaseError, SchedulingUnavailableError])
def test_native_failure_retains_owner_unavailable_semantics(world, error):
    world.mocks["_load_lineage"].side_effect = error
    with pytest.raises(ProgrammeStaffingUnavailableError):
        queries.load_work_change_recipient(world.request)


@pytest.mark.parametrize(
    "field", list(queries.ProgrammeWorkRecipientRequest.__dataclass_fields__)
)
def test_malformed_exact_scope_cannot_reach_owner_policy(world, field):
    with pytest.raises(ProgrammeStaffingDeniedError):
        queries.load_work_change_recipient(
            replace(world.request, **{field: UUID(int=0)})
        )
    world.mocks["decide_verified_principal_exact_edition"].assert_not_called()


@pytest.mark.parametrize(
    "status", [None, "claimed", "confirmed", "removed", "completed"]
)
def test_real_work_lookup_is_exact_scoped_minimized_and_operative(
    world, monkeypatch, status
):
    manager = Mock()
    manager.filter.return_value.values_list.return_value.first.return_value = (
        None if status is None else (*world.work[:3], status, *world.work[4:])
    )
    monkeypatch.setattr(queries.ShiftCommitment, "objects", manager)
    if status in {"claimed", "confirmed"}:
        assert world.real_work(world.request)[3] == status
    else:
        with pytest.raises(ProgrammeStaffingUnavailableError):
            world.real_work(world.request)
    scope = manager.filter.call_args.kwargs
    assert scope["id"] == world.request.commitment_id
    assert scope["organization_id"] == world.request.organization_id
    assert scope["edition_id"] == world.request.edition_id
    assert (
        scope["demand__position__department__organization_id"]
        == world.request.organization_id
    )
    assert scope["demand__position__department__edition_id"] == world.request.edition_id
    assert manager.filter.return_value.values_list.call_args.args == (
        "id",
        "account_id",
        "command_version",
        "status",
        "demand_id",
        "demand__command_version",
    )
