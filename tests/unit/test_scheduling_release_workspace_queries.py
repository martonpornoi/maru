"""Owner read envelopes, minimized projections and completeness without PostgreSQL."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from django.db import DatabaseError

from maru.scheduling import planning_queries
from maru.scheduling import release_workspace_queries as queries
from maru.scheduling.authorization import SchedulingAuthorizationDeniedError
from maru.scheduling.catalogs import SchedulingOperation as Op
from maru.scheduling.command_support import (
    SchedulingLimitError,
    SchedulingUnavailableError,
)
from maru.scheduling.models import SchedulingCommandReceipt
from maru.scheduling.planning_queries import SchedulingReadRequest
from maru.scheduling.release_inputs import ReleaseCandidateSelection


def queryset(rows):
    query = MagicMock()
    for method in ("filter", "only", "select_related", "order_by"):
        getattr(query, method).return_value = query
    query.__getitem__.side_effect = lambda key: rows[key]
    query.__iter__.side_effect = lambda: iter(rows)
    query.first.side_effect = lambda: rows[0] if rows else None
    query.count.side_effect = lambda: len(rows)
    query.exists.side_effect = lambda: bool(rows)
    return query


@pytest.fixture
def release_query_world(monkeypatch):
    request = SchedulingReadRequest(uuid4(), uuid4(), uuid4(), uuid4())
    scope = SimpleNamespace(accepts_writes=True)
    authorize = Mock(return_value=scope)
    audit = Mock()
    monkeypatch.setattr(planning_queries, "_authorize", authorize)
    monkeypatch.setattr(planning_queries, "_audit", audit)
    monkeypatch.setattr(planning_queries, "_lock_edition", Mock())
    monkeypatch.setattr(planning_queries.transaction, "atomic", nullcontext)
    tables = {}
    managers = {}
    for model in (
        queries.SchedulingCandidate,
        queries.SchedulingCandidateRevision,
        queries.SchedulingReleaseApproval,
        queries.SchedulingReleaseWarningAcknowledgement,
        queries.SchedulingRelease,
        queries.SchedulingReleaseWithdrawal,
        queries.SchedulingReleasePointer,
    ):
        tables[model] = []
        managers[model] = queryset(tables[model])
        monkeypatch.setattr(model, "objects", managers[model])
    revision = queries.SchedulingCandidateRevision(
        id=uuid4(),
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        candidate=queries.SchedulingCandidate(id=uuid4(), lifecycle="draft"),
        sequence=3,
        label="Original private candidate",
        placement_count=1,
    )
    return SimpleNamespace(
        request=request,
        scope=scope,
        authorize=authorize,
        audit=audit,
        tables=tables,
        managers=managers,
        revision=revision,
    )


def evidence(world, model, operation, *, version=1, **values):
    identifier = uuid4()
    attributed = {
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
        "actor_id": world.request.actor_id,
        "reason": "Retained <private> rationale",
        "occurred_at": datetime(2030, 8, 1, 10, tzinfo=UTC),
    }
    receipt = SchedulingCommandReceipt(
        id=uuid4(),
        **attributed,
        operation=operation,
        result_object_id=identifier,
        resulting_version=version,
    )
    return model(id=identifier, **attributed, command_receipt=receipt, **values)


def install_candidate(world):
    world.tables[queries.SchedulingCandidateRevision].append(world.revision)
    world.tables[queries.SchedulingCandidate].append(world.revision.candidate)


def approval(world):
    row = evidence(
        world,
        queries.SchedulingReleaseApproval,
        Op.RELEASE_APPROVE,
        candidate_revision=world.revision,
        source_snapshot_digest="a" * 64,
    )
    world.tables[queries.SchedulingReleaseApproval].append(row)
    return row


def selection(world):
    return ReleaseCandidateSelection(
        world.revision.candidate_id, world.revision.id, 3, "a" * 64
    )


def test_candidate_discovery_is_complete_minimized_scoped_and_audited(
    release_query_world,
):
    world = release_query_world
    install_candidate(world)
    rows = queries.list_release_candidates(world.request)
    assert len(rows) == 1
    assert rows[0].label == world.revision.label
    assert rows[0].version == 3
    assert not hasattr(rows[0], "reason")
    assert not hasattr(rows[0], "actor_id")
    filters = world.managers[
        queries.SchedulingCandidateRevision
    ].filter.call_args.kwargs
    assert (
        filters["organization_id"]
        == filters["candidate__organization_id"]
        == world.request.organization_id
    )
    assert (
        filters["edition_id"]
        == filters["candidate__edition_id"]
        == world.request.edition_id
    )
    assert filters["sequence"].name == "candidate__aggregate_version"
    assert world.authorize.call_count == 2
    assert world.authorize.call_args.args[1:3] == (
        "scheduling.view_planning",
        frozenset({"candidates"}),
    )
    assert world.authorize.call_args.kwargs["lock"] is True
    assert world.audit.call_args.args[2] == "release_candidates"
    world.tables[queries.SchedulingCandidateRevision].clear()
    with pytest.raises(SchedulingUnavailableError):
        queries.list_release_candidates(world.request)


def test_candidate_overflow_never_returns_a_partial_inventory(
    release_query_world, monkeypatch
):
    world = release_query_world
    install_candidate(world)
    monkeypatch.setattr(queries, "MAX_CANDIDATES", 0)
    with pytest.raises(SchedulingLimitError):
        queries.list_release_candidates(world.request)
    world.audit.assert_not_called()


@pytest.mark.parametrize("final", [False, True])
def test_denial_before_or_after_loading_never_discloses_evidence(
    release_query_world, final
):
    world = release_query_world
    approval(world)
    world.authorize.side_effect = ([world.scope] if final else []) + [
        SchedulingAuthorizationDeniedError()
    ]
    with pytest.raises(SchedulingAuthorizationDeniedError):
        queries.list_release_approvals(world.request)
    if not final:
        world.managers[queries.SchedulingReleaseApproval].filter.assert_not_called()
    assert all(call.kwargs["scope"] is None for call in world.audit.call_args_list)


def test_required_audit_failure_discards_already_loaded_data(release_query_world):
    world = release_query_world
    approval(world)
    world.audit.side_effect = DatabaseError("synthetic required audit unavailable")
    with pytest.raises(SchedulingUnavailableError):
        queries.list_release_approvals(world.request)


def test_warning_query_binds_exact_source_and_receipt_not_planner_acknowledgements(
    release_query_world,
):
    world = release_query_world
    install_candidate(world)
    row = evidence(
        world,
        queries.SchedulingReleaseWarningAcknowledgement,
        Op.RELEASE_WARNING_ACKNOWLEDGE,
        candidate_revision=world.revision,
        source_snapshot_digest="a" * 64,
        finding_fingerprint="b" * 64,
        check_code="hosts",
        finding_code="host_outside_preference",
    )
    world.tables[queries.SchedulingReleaseWarningAcknowledgement].append(row)
    result = queries.list_release_warning_evidence(
        world.request, selection=selection(world)
    )
    assert result[0].reason == row.reason
    filters = world.managers[
        queries.SchedulingReleaseWarningAcknowledgement
    ].filter.call_args.kwargs
    assert filters == {
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
        "candidate_revision_id": world.revision.id,
        "source_snapshot_digest": "a" * 64,
    }
    assert world.authorize.call_args.args[1:3] == (
        "scheduling.view_history",
        frozenset({"planning_history"}),
    )
    row.command_receipt.operation = Op.WARNING_ACKNOWLEDGE
    with pytest.raises(SchedulingUnavailableError):
        queries.list_release_warning_evidence(world.request, selection=selection(world))


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "edition_id",
        "operation",
        "result_object_id",
        "resulting_version",
        "actor_id",
        "reason",
        "occurred_at",
    ],
)
def test_approval_receipt_incoherence_is_unavailable_not_omitted(
    release_query_world, field
):
    world = release_query_world
    row = approval(world)
    setattr(row.command_receipt, field, None)
    with pytest.raises(SchedulingUnavailableError):
        queries.list_release_approvals(world.request)
    world.audit.assert_not_called()


def test_approval_keeps_original_revision_and_explicit_page_anchor(
    release_query_world, monkeypatch
):
    world = release_query_world
    row = approval(world)
    second = approval(world)
    monkeypatch.setattr(queries, "RELEASE_HISTORY_PAGE_SIZE", 1)
    page = queries.list_release_approvals(world.request)
    assert len(page.entries) == 1
    assert page.next_before_id == row.id
    assert page.entries[0].candidate.label == "Original private candidate"
    assert page.entries[0].snapshot_digest == "a" * 64
    assert not hasattr(page.entries[0], "eligible")
    query = world.managers[queries.SchedulingReleaseApproval]
    query.first.side_effect = None
    query.first.return_value = row
    queries.list_release_approvals(world.request, before_id=row.id)
    cursor = next(call.args[0] for call in query.filter.call_args_list if call.args)
    assert cursor.connector == "OR"
    assert cursor.children[0] == ("occurred_at__lt", row.occurred_at)
    assert ("id__lt", row.id) in cursor.children[1].children
    query.first.return_value = None
    with pytest.raises(SchedulingUnavailableError):
        queries.list_release_approvals(world.request, before_id=second.id)


def test_exact_approval_selection_is_tenant_scoped_and_missing_is_unavailable(
    release_query_world,
):
    world = release_query_world
    row = approval(world)
    result = queries.load_release_approval(world.request, approval_id=row.id)
    assert result.id == row.id
    assert world.managers[
        queries.SchedulingReleaseApproval
    ].filter.call_args.kwargs == {
        "organization_id": world.request.organization_id,
        "edition_id": world.request.edition_id,
        "id": row.id,
    }
    world.tables[queries.SchedulingReleaseApproval].clear()
    with pytest.raises(SchedulingUnavailableError):
        queries.load_release_approval(world.request, approval_id=row.id)


def test_pointer_observation_distinguishes_absence_active_and_withdrawn_without_content(
    release_query_world,
):
    world = release_query_world
    assert queries.load_release_pointer(
        world.request
    ) == queries.ReleasePointerObservation(None, 0)
    published = evidence(
        world, queries.SchedulingRelease, Op.RELEASE_PUBLISH, pointer_version=1
    )
    world.tables[queries.SchedulingRelease].append(published)
    with pytest.raises(SchedulingUnavailableError):
        queries.load_release_pointer(world.request)
    pointer = queries.SchedulingReleasePointer(
        version=1,
        active_release_id=published.id,
        command_receipt_id=published.command_receipt_id,
    )
    world.tables[queries.SchedulingReleasePointer].append(pointer)
    assert queries.load_release_pointer(
        world.request
    ) == queries.ReleasePointerObservation(published.id, 1)
    withdrawn = evidence(
        world,
        queries.SchedulingReleaseWithdrawal,
        Op.RELEASE_WITHDRAW,
        version=2,
        pointer_version=2,
        release_id=published.id,
    )
    world.tables[queries.SchedulingReleaseWithdrawal].append(withdrawn)
    pointer.version, pointer.active_release_id, pointer.command_receipt_id = (
        2,
        None,
        withdrawn.command_receipt_id,
    )
    assert queries.load_release_pointer(
        world.request
    ) == queries.ReleasePointerObservation(None, 2)
    assert world.authorize.call_args.args[1:3] == (
        "scheduling.view_planning",
        frozenset({"release_manifest"}),
    )


def test_history_is_contiguous_and_independently_ceilinged(release_query_world):
    world = release_query_world
    published = evidence(
        world, queries.SchedulingRelease, Op.RELEASE_PUBLISH, pointer_version=1
    )
    withdrawn = evidence(
        world,
        queries.SchedulingReleaseWithdrawal,
        Op.RELEASE_WITHDRAW,
        version=2,
        pointer_version=2,
        release_id=published.id,
    )
    world.tables[queries.SchedulingRelease].append(published)
    world.tables[queries.SchedulingReleaseWithdrawal].append(withdrawn)
    world.tables[queries.SchedulingReleasePointer].append(
        queries.SchedulingReleasePointer(version=2)
    )
    page = queries.list_release_history(world.request)
    assert [row.version for row in page.entries] == [2, 1]
    assert [row.operation for row in page.entries] == [
        Op.RELEASE_WITHDRAW,
        Op.RELEASE_PUBLISH,
    ]
    assert page.entries[0].release_id == published.id
    assert world.authorize.call_args.args[1:3] == (
        "scheduling.view_history",
        frozenset({"planning_history", "release_manifest"}),
    )
    world.tables[queries.SchedulingRelease].clear()
    with pytest.raises(SchedulingUnavailableError):
        queries.list_release_history(world.request)
    with pytest.raises(SchedulingUnavailableError):
        queries.list_release_history(world.request, before_version=9)
