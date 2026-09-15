"""Complete minimized work choices with real composition and substituted owners."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.workforce import notice_recipient_choices as choices
from maru.workforce.operator_links import OperatorWorkLink
from maru.workforce.programme_staffing_queries import (
    ProgrammeStaffingDeniedError,
    ProgrammeStaffingUnavailableError,
)


@pytest.fixture
def work_choices(monkeypatch):
    request = choices.ProgrammeWorkNoticeRequest(*(UUID(int=n) for n in range(10, 15)))
    person = UUID(int=1)
    start = datetime(2026, 10, 1, 12, tzinfo=UTC)
    end = start + timedelta(hours=1)
    link = OperatorWorkLink(
        request.occurrence_id, UUID(int=20), 3, UUID(int=21), 4, current=False
    )
    row = choices._WorkRow(
        UUID(int=22),
        person,
        2,
        "confirmed",
        link.demand_id,
        4,
        "Synthetic <stage> shift",
        start,
        end,
        start,
        end,
    )
    records = [row]
    manager = MagicMock()
    manager.filter.return_value = manager
    manager.order_by.return_value = manager
    manager.values_list.return_value = manager
    manager.__getitem__.side_effect = lambda key: records[key]
    manager.count.side_effect = lambda: len(records)
    monkeypatch.setattr(choices.ShiftCommitment, "objects", manager)
    decision = PolicyDecision(
        allowed=True,
        fields=choices.NOTICE_WORK_CHOICE_FIELDS,
        obligations=frozenset(),
        reason_code="sender_scope",
    )
    values = {
        "decide_verified_principal_exact_edition": decision,
        "edition_adoption_profile_reference": SimpleNamespace(
            code="synthetic", version=1
        ),
        "profile_allows_adapter": True,
        "lock_programme_staffing_scope": None,
        "_load_lineage": (link,),
        "lock_account_references_for_evidence": tuple(
            sorted((request.actor_id, person))
        ),
        "resolve_active_verified_person_reference": object(),
        "active_verified_person_account_display_labels": {
            request.actor_id: "Sender",
            person: "Synthetic <holder>",
        },
        "append_audit": None,
    }
    mocks = {name: Mock(return_value=value) for name, value in values.items()}
    for name, mock in mocks.items():
        monkeypatch.setattr(choices, name, mock)
    monkeypatch.setattr(choices.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        request=request,
        person=person,
        link=link,
        row=row,
        records=records,
        manager=manager,
        mocks=mocks,
        decision=decision,
    )


@pytest.mark.parametrize(
    ("current", "status"), [(False, "confirmed"), (True, "claimed")]
)
def test_exact_operative_work_labels_preserve_lineage_and_sender_audit(
    work_choices, current, status
):
    world = work_choices
    world.mocks["_load_lineage"].return_value = (replace(world.link, current=current),)
    world.records[0] = world.row._replace(status=status)
    result = choices.list_programme_work_notice_choices(world.request)
    assert len(result) == 1
    assert result[0].title == world.row.title
    assert result[0].starts_at == world.row.starts_at
    recipient = result[0].recipient
    assert recipient.account_id == world.person
    assert recipient.work.current == current
    assert recipient.work.status == status
    assert recipient.work.commitment_id == world.row.id
    assert recipient.work.demand_version == 4
    assert recipient.work.binding_version == 3
    assert recipient.work.occurrence_id == world.request.occurrence_id
    for call in world.mocks["decide_verified_principal_exact_edition"].call_args_list:
        assert call.kwargs["principal_id"] == world.request.actor_id
        assert call.kwargs["requested_fields"] == choices.NOTICE_WORK_CHOICE_FIELDS
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.principal_id == world.request.actor_id
    assert audit.target_id == world.request.edition_id
    assert audit.operation == "workforce.programme_change_recipient_choices.read"
    assert "Synthetic" not in repr(audit)
    assert world.mocks["_load_lineage"].call_count == 4
    assert world.manager.values_list.call_count == 2


def test_real_queries_are_bounded_scoped_and_do_not_load_other_personnel_fields(
    work_choices,
):
    world = work_choices
    choices.list_programme_work_notice_choices(world.request)
    scope = world.manager.filter.call_args_list[0].kwargs
    assert scope["organization_id"] == world.request.organization_id
    assert scope["edition_id"] == world.request.edition_id
    assert scope["status__in"] == ("claimed", "confirmed")
    assert set(scope["demand_id__in"]) == {world.link.demand_id}
    for parent in ("demand", "demand__position", "demand__position__department"):
        assert scope[parent + "__organization_id"] == world.request.organization_id
        assert scope[parent + "__edition_id"] == world.request.edition_id
    assert world.manager.values_list.call_args.args == (
        "id",
        "account_id",
        "command_version",
        "status",
        "demand_id",
        "demand__command_version",
        "demand__title",
        "starts_at",
        "ends_at",
        "demand__starts_at",
        "demand__ends_at",
    )
    assert world.manager.__getitem__.call_args.args == (slice(None, 1025),)


def test_complete_people_lock_follows_scope_and_precedes_identity_labels(work_choices):
    world = work_choices
    timeline = Mock()
    for name in (
        "lock_programme_staffing_scope",
        "lock_account_references_for_evidence",
        "resolve_active_verified_person_reference",
        "active_verified_person_account_display_labels",
    ):
        timeline.attach_mock(world.mocks[name], name)
    choices.list_programme_work_notice_choices(world.request)
    assert [row[0] for row in timeline.mock_calls[:4]] == [
        "lock_programme_staffing_scope",
        "lock_account_references_for_evidence",
        "resolve_active_verified_person_reference",
        "active_verified_person_account_display_labels",
    ]
    assert timeline.mock_calls[1].kwargs == {
        "account_ids": tuple(sorted((world.person, world.request.actor_id))),
    }


@pytest.mark.parametrize("field", sorted(choices.NOTICE_WORK_CHOICE_FIELDS))
def test_each_choice_field_denial_precedes_profile_and_work_discovery(
    work_choices, field
):
    world = work_choices
    world.mocks["decide_verified_principal_exact_edition"].return_value = replace(
        world.decision,
        fields=world.decision.fields - {field},
    )
    with pytest.raises(ProgrammeStaffingDeniedError):
        choices.list_programme_work_notice_choices(world.request)
    world.mocks["edition_adoption_profile_reference"].assert_not_called()
    world.manager.filter.assert_not_called()


@pytest.mark.parametrize("boundary", ["profile", "adapter", "policy"])
def test_unadopted_or_denied_work_does_not_discover_people(work_choices, boundary):
    world = work_choices
    name, value = {
        "profile": ("edition_adoption_profile_reference", None),
        "adapter": ("profile_allows_adapter", False),
        "policy": (
            "decide_verified_principal_exact_edition",
            replace(world.decision, allowed=False),
        ),
    }[boundary]
    world.mocks[name].return_value = value
    with pytest.raises(ProgrammeStaffingDeniedError):
        choices.list_programme_work_notice_choices(world.request)
    world.mocks["_load_lineage"].assert_not_called()
    world.mocks["lock_account_references_for_evidence"].assert_not_called()


@pytest.mark.parametrize("empty", ["work", "eligible_people", "lineage"])
def test_empty_choices_are_still_sender_audited_without_hidden_recipient_counts(
    work_choices, empty
):
    world = work_choices
    if empty != "eligible_people":
        world.records.clear()
        world.mocks["lock_account_references_for_evidence"].return_value = (
            world.request.actor_id,
        )
    if empty == "lineage":
        world.mocks["_load_lineage"].return_value = ()
    world.mocks["active_verified_person_account_display_labels"].return_value = {
        world.request.actor_id: "Sender"
    }
    assert choices.list_programme_work_notice_choices(world.request) == ()
    world.mocks["append_audit"].assert_called_once()


@pytest.mark.parametrize(
    "fault", ["duplicate", "foreign_occurrence", "ambiguous_demand"]
)
def test_complete_lineage_is_required_before_person_discovery(work_choices, fault):
    world = work_choices
    loader = world.mocks["_load_lineage"]
    if fault == "duplicate":
        loader.return_value = (world.link, world.link)
    elif fault == "foreign_occurrence":
        loader.return_value = (replace(world.link, occurrence_id=UUID(int=99)),)
    else:
        loader.side_effect = [(world.link,), (world.link, world.link)]
    with pytest.raises(ProgrammeStaffingUnavailableError):
        choices.list_programme_work_notice_choices(world.request)
    world.mocks["lock_account_references_for_evidence"].assert_not_called()


@pytest.mark.parametrize(
    "fault", ["version", "interval", "empty_interval", "parent_scope", "overflow"]
)
def test_incoherent_or_overflow_work_is_not_a_partial_selection(
    work_choices, monkeypatch, fault
):
    world = work_choices
    if fault == "version":
        world.records[0] = world.row._replace(demand_version=9)
    elif fault == "interval":
        world.records[0] = world.row._replace(
            starts_at=world.row.starts_at + timedelta(minutes=1)
        )
    elif fault == "empty_interval":
        world.records[0] = world.row._replace(
            ends_at=world.row.starts_at, demand_ends_at=world.row.starts_at
        )
    elif fault == "parent_scope":
        world.manager.count.side_effect = None
        world.manager.count.return_value = 2
    else:
        monkeypatch.setattr(choices, "MAX_NOTICE_WORK_CHOICES", 0)
    with pytest.raises(
        choices.ProgrammeWorkNoticeLimitError
        if fault == "overflow"
        else ProgrammeStaffingUnavailableError
    ):
        choices.list_programme_work_notice_choices(world.request)
    world.mocks["active_verified_person_account_display_labels"].assert_not_called()


@pytest.mark.parametrize(
    "fault",
    [
        "missing_person",
        "sender",
        "sender_label",
        "moved_work",
        "moved_lineage",
        "moved_label",
        "final_policy",
        "audit",
        "database",
    ],
)
def test_late_changes_and_dependency_failure_withhold_all_choices(work_choices, fault):
    world = work_choices
    expected = ProgrammeStaffingUnavailableError
    if fault == "missing_person":
        world.mocks["lock_account_references_for_evidence"].return_value = (
            world.request.actor_id,
        )
    elif fault == "sender":
        world.mocks["resolve_active_verified_person_reference"].return_value = None
        expected = ProgrammeStaffingDeniedError
    elif fault == "sender_label":
        world.mocks["active_verified_person_account_display_labels"].return_value = {
            world.person: "Holder"
        }
        expected = ProgrammeStaffingDeniedError
    elif fault == "moved_work":
        world.manager.__getitem__.side_effect = [
            [world.row],
            [world.row._replace(version=3)],
        ]
    elif fault == "moved_lineage":
        world.mocks["_load_lineage"].side_effect = [(world.link,), (world.link,), ()]
    elif fault == "moved_label":
        labels = world.mocks[
            "active_verified_person_account_display_labels"
        ].return_value
        world.mocks["active_verified_person_account_display_labels"].side_effect = [
            labels,
            {**labels, world.person: "Changed"},
        ]
    elif fault == "final_policy":
        world.mocks["decide_verified_principal_exact_edition"].side_effect = [
            world.decision,
            world.decision,
            replace(world.decision, allowed=False),
        ]
        expected = ProgrammeStaffingDeniedError
    elif fault == "audit":
        world.mocks["append_audit"].side_effect = RuntimeError("audit unavailable")
        expected = RuntimeError
    else:
        world.mocks["_load_lineage"].side_effect = DatabaseError
    with pytest.raises(expected):
        choices.list_programme_work_notice_choices(world.request)


@pytest.mark.parametrize(
    "field", list(choices.ProgrammeWorkNoticeRequest.__dataclass_fields__)
)
def test_invalid_scope_fails_before_owner_admission(work_choices, field):
    with pytest.raises(ProgrammeStaffingDeniedError):
        choices.list_programme_work_notice_choices(
            replace(work_choices.request, **{field: UUID(int=0)})
        )
    work_choices.mocks["decide_verified_principal_exact_edition"].assert_not_called()
