"""Exact-self work lineage selection, stale evidence and shared bounded history."""

from contextlib import nullcontext
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from maru.scheduling.command_support import SchedulingUnavailableError
from maru.scheduling.operator_scope import OperatorReadRequest, OperatorScopeKind
from maru.workforce import operator_links as lineage
from maru.workforce import personal_programme_links as links
from maru.workforce.operator_links import OperatorWorkLink
from maru.workforce.shift_commands import (
    ShiftAuthorizationDeniedError,
    ShiftUnavailableError,
)
from tests.unit.test_personal_timetable_rendering import (
    personal as personal,  # noqa: PLC0414
)


@pytest.fixture
def world(monkeypatch, personal):
    work = personal.shifts[0]
    source = OperatorWorkLink(
        UUID(int=40),
        UUID(int=41),
        2,
        work.instructions.demand_id,
        work.instructions.version,
        current=False,
    )
    arguments = {
        "actor_id": personal.actor_id,
        "organization_id": personal.organization_id,
        "edition_id": personal.edition_id,
        "correlation_id": UUID(int=42),
    }
    sources = {
        "_authorize": SimpleNamespace(
            reason_code="self_allowed", obligations=frozenset()
        ),
        "lock_programme_staffing_scope": object(),
        "resolve_active_verified_person_reference": object(),
        "_adopted": True,
        "load_personal_shift_timetable": (work,),
        "_load_lineage": (source,),
        "append_audit": None,
    }
    mocks = {name: Mock(return_value=value) for name, value in sources.items()}
    for name, mock in mocks.items():
        monkeypatch.setattr(links, name, mock)
    monkeypatch.setattr(links.transaction, "atomic", nullcontext)
    return SimpleNamespace(work=work, source=source, arguments=arguments, mocks=mocks)


def test_exact_own_retained_demand_not_successor_is_versioned_audited_and_minimized(
    world,
):
    (result,) = links.load_personal_programme_work_links(**world.arguments)
    assert result.commitment_id == world.work.commitment_id
    assert result.commitment_version == world.work.version
    assert result.status == "confirmed"
    assert result.demand_id == world.work.instructions.demand_id
    assert result.demand_version == world.work.instructions.version
    assert result.binding_id == world.source.binding_id
    assert result.binding_version == world.source.binding_version
    assert not result.current
    assert set(asdict(result)) == {
        "commitment_id",
        "commitment_version",
        "status",
        "demand_id",
        "demand_version",
        "occurrence_id",
        "binding_id",
        "binding_version",
        "current",
    }
    source = world.mocks["_load_lineage"]
    assert source.call_count == 2
    assert source.call_args.kwargs == {
        "organization_id": world.arguments["organization_id"],
        "edition_id": world.arguments["edition_id"],
        "demand_ids": {world.work.instructions.demand_id},
    }
    assert world.mocks["load_personal_shift_timetable"].call_count == 2
    assert world.mocks["_authorize"].call_count == 3
    world.mocks["resolve_active_verified_person_reference"].assert_called_once_with(
        account_id=world.arguments["actor_id"], lock=True
    )
    audit = world.mocks["append_audit"].call_args.args[0]
    assert audit.operation == "workforce.personal_programme_links.read"
    assert audit.principal_id == world.arguments["actor_id"]
    assert audit.retention_class == "workforce-personal"
    assert audit.safe_metadata["access_purpose"] == "own_retained_programme_work_links"


def test_unadopted_layer_is_explicit_without_work_or_lineage_lookup(world):
    world.mocks["_adopted"].return_value = False
    assert links.load_personal_programme_work_links(**world.arguments) is None
    world.mocks["load_personal_shift_timetable"].assert_not_called()
    world.mocks["_load_lineage"].assert_not_called()
    world.mocks["append_audit"].assert_called_once()


@pytest.mark.parametrize("reason", ["no_work", "unlinked"])
def test_adopted_empty_is_complete_not_unadopted(world, reason):
    if reason == "no_work":
        world.mocks["load_personal_shift_timetable"].return_value = ()
    else:
        world.mocks["_load_lineage"].return_value = ()
    assert links.load_personal_programme_work_links(**world.arguments) == ()
    if reason == "no_work":
        world.mocks["_load_lineage"].assert_not_called()


@pytest.mark.parametrize("status", ["claimed", "confirmed", "removed", "completed"])
def test_binding_lineage_does_not_reinterpret_work_status(world, status):
    world.mocks["load_personal_shift_timetable"].return_value = (
        replace(world.work, status=status),
    )
    (result,) = links.load_personal_programme_work_links(**world.arguments)
    assert result.status == status
    assert not result.current


@pytest.mark.parametrize(
    "source",
    [
        "_authorize",
        "resolve_active_verified_person_reference",
        "load_personal_shift_timetable",
    ],
)
def test_denied_or_deactivated_person_never_reaches_lineage(world, source):
    mock = world.mocks[source]
    if source == "resolve_active_verified_person_reference":
        mock.return_value = None
    else:
        mock.side_effect = ShiftAuthorizationDeniedError
    with pytest.raises(ShiftAuthorizationDeniedError):
        links.load_personal_programme_work_links(**world.arguments)
    world.mocks["_load_lineage"].assert_not_called()
    world.mocks["append_audit"].assert_not_called()


@pytest.mark.parametrize(
    "source", ["work", "lineage", "adoption", "final_policy", "audit"]
)
def test_late_failure_prevents_a_successful_result(world, source):
    expected = ShiftUnavailableError
    if source == "work":
        world.mocks["load_personal_shift_timetable"].side_effect = [(world.work,), ()]
    elif source == "lineage":
        world.mocks["_load_lineage"].side_effect = [(world.source,), ()]
    elif source == "adoption":
        world.mocks["_adopted"].side_effect = [True, False]
    elif source == "final_policy":
        mock = world.mocks["_authorize"]
        mock.side_effect = [
            mock.return_value,
            mock.return_value,
            ShiftAuthorizationDeniedError,
        ]
        expected = ShiftAuthorizationDeniedError
    else:
        world.mocks["append_audit"].side_effect = RuntimeError("audit unavailable")
        expected = RuntimeError
    with pytest.raises(expected):
        links.load_personal_programme_work_links(**world.arguments)


@pytest.mark.parametrize("error", [DatabaseError, SchedulingUnavailableError])
def test_native_source_failure_keeps_owner_unavailable_semantics(world, error):
    world.mocks["_load_lineage"].side_effect = error
    with pytest.raises(ShiftUnavailableError):
        links.load_personal_programme_work_links(**world.arguments)


@pytest.mark.parametrize(
    "fault",
    ["version", "duplicate_work", "duplicate_demand", "foreign_demand", "oversized"],
)
def test_inconsistent_or_oversized_sources_cannot_return_partial_links(
    world, monkeypatch, fault
):
    if fault == "version":
        world.mocks["_load_lineage"].return_value = (
            replace(world.source, demand_version=99),
        )
    elif fault == "duplicate_work":
        world.mocks["load_personal_shift_timetable"].return_value = (
            world.work,
            world.work,
        )
    elif fault == "duplicate_demand":
        world.mocks["_load_lineage"].return_value = (world.source, world.source)
    elif fault == "foreign_demand":
        world.mocks["_load_lineage"].return_value = (
            replace(world.source, demand_id=UUID(int=999)),
        )
    else:
        monkeypatch.setattr(links, "MAX_SHIFT_COMMITMENTS", 0)
    with pytest.raises(ShiftUnavailableError):
        links.load_personal_programme_work_links(**world.arguments)


@pytest.mark.parametrize(
    "field", ["actor_id", "organization_id", "edition_id", "correlation_id"]
)
@pytest.mark.parametrize("value", [None, UUID(int=0), "not-a-uuid"])
def test_malformed_attribution_precedes_any_owner_read(world, field, value):
    with pytest.raises(ValidationError):
        links.load_personal_programme_work_links(**(world.arguments | {field: value}))
    world.mocks["_authorize"].assert_not_called()


@pytest.fixture
def history(monkeypatch):
    org, edition, binding, occurrence, old, new, department = [
        UUID(int=n) for n in range(101, 108)
    ]
    manager = Mock()
    query = manager.filter.return_value
    query.filter.return_value = query
    query.order_by.return_value.values_list.return_value.distinct.return_value = [
        (binding, 2, occurrence, new)
    ]
    monkeypatch.setattr(lineage.ProgrammeShiftBinding, "objects", manager)
    revisions_manager = Mock()
    revisions = revisions_manager.filter.return_value.order_by.return_value
    aggregate = {"binding_id": binding, "count": 2, "first": 1, "last": 2}
    revisions.values.return_value.annotate.return_value = [aggregate]
    revisions.filter.return_value.values_list.return_value = [(binding, new)]
    revisions.values_list.return_value.union.return_value.order_by.return_value = [
        (binding, old),
        (binding, new),
    ]
    monkeypatch.setattr(
        lineage.ProgrammeShiftBindingRevision, "objects", revisions_manager
    )
    demands = Mock()
    demands.filter.return_value.values_list.return_value = [
        (old, 3, department),
        (new, 1, department),
    ]
    monkeypatch.setattr(lineage.ShiftDemand, "objects", demands)
    return SimpleNamespace(
        org=org,
        edition=edition,
        binding=binding,
        occurrence=occurrence,
        old=old,
        new=new,
        department=department,
        manager=manager,
        query=query,
        revisions=revisions,
        revisions_manager=revisions_manager,
        aggregate=aggregate,
        demands=demands,
    )


def test_shared_real_lineage_loader_retains_old_own_demand_without_disclosing_successor(
    history,
):
    h = history
    (result,) = lineage._load_lineage(
        organization_id=h.org, edition_id=h.edition, demand_ids={h.old}
    )
    assert result.demand_id == h.old
    assert result.binding_version == 2
    assert not result.current
    condition = h.query.filter.call_args.args[0]
    assert condition.connector == "OR"
    assert {name for name, _ in condition.children} == {
        "demand_id__in",
        "revisions__demand_id__in",
        "revisions__predecessor_id__in",
    }
    assert all(values == {h.old} for _, values in condition.children)
    for manager in (h.manager, h.revisions_manager, h.demands):
        assert manager.filter.call_args.kwargs["organization_id"] == h.org
        assert manager.filter.call_args.kwargs["edition_id"] == h.edition


@pytest.mark.parametrize("kind", list(OperatorScopeKind))
def test_existing_operator_wrapper_preserves_original_filter_contract(history, kind):
    h = history
    request = OperatorReadRequest(
        UUID(int=90), h.org, h.edition, UUID(int=91), kind, h.department
    )
    result = lineage._load_links(request, occurrence_ids={h.occurrence})
    assert {row.demand_id for row in result} == {h.old, h.new}
    assert h.query.filter.call_args_list[0].kwargs == {
        "occurrence_id__in": {h.occurrence}
    }
    if kind is OperatorScopeKind.DEPARTMENT:
        assert all(
            value == h.department
            for _, value in h.query.filter.call_args.args[0].children
        )


@pytest.mark.parametrize("fault", ["first", "count", "last", "head", "missing_demand"])
def test_shared_lineage_rejects_incomplete_history_even_for_minimized_self_result(
    history, fault
):
    h = history
    if fault in {"first", "count", "last"}:
        h.aggregate[fault] = 99
    elif fault == "head":
        h.revisions.filter.return_value.values_list.return_value = []
    else:
        h.demands.filter.return_value.values_list.return_value = [
            (h.old, 3, h.department)
        ]
    with pytest.raises(SchedulingUnavailableError):
        lineage._load_lineage(
            organization_id=h.org, edition_id=h.edition, demand_ids={h.old}
        )
