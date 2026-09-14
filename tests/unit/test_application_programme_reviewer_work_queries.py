"""Own-assignment scope, retained rubric, bounded discovery and audit contracts."""

from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from maru.applications import programme_reviewer_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_rules import ProgrammeReviewUnavailableError
from tests.unit import (
    test_application_programme_review_management_queries as manager_tests,
)
from tests.unit.test_application_programme_reviewer_selection import (
    request as manager_request,
)


def request(**changes):
    return manager_request(**({"capability_code": queries.REVIEW} | changes))


@pytest.fixture
def world(monkeypatch):
    # Real shared case loader/scoping and policy decoder; only database seams mocked.
    base = manager_tests.world.__wrapped__(monkeypatch)
    row = SimpleNamespace(
        id=UUID(int=30),
        account_id=UUID(int=1),
        stage=0,
        state="pending",
        case=base.case,
        case_id=base.case.id,
    )
    base.query.first.return_value = row
    base.query.select_related.return_value = base.query
    base.query.filter.return_value = base.query
    base.rows[:] = [row]
    entries = Mock()
    entry_query = Mock()
    entries.filter.return_value = entry_query
    entry_query.exists.return_value = False
    entry_query.values_list.return_value = []
    cases = MagicMock()
    cases.filter.return_value = cases
    monkeypatch.setattr(queries, "_locked_scope", base.locked)
    monkeypatch.setattr(queries, "_audit", base.audit)
    monkeypatch.setattr(queries, "_cases", Mock(return_value=cases))
    monkeypatch.setattr(queries.ProgrammeReviewEntry, "objects", entries)
    return SimpleNamespace(
        base=base, row=row, entries=entries, entry_query=entry_query, cases=cases
    )


def detail(**changes):
    return queries.get_programme_reviewer_work.__wrapped__(
        **(
            {
                "request": request(),
                "case_id": UUID(int=20),
                "assignment_id": UUID(int=30),
            }
            | changes
        )
    )


def queue(**changes):
    return queries.list_programme_reviewer_work.__wrapped__(
        **({"request": request()} | changes)
    )


@pytest.mark.parametrize("state", ["pending", "active", "removed", "recused"])
def test_retained_own_assignment_loads_only_exact_scope_and_original_rubric(
    world, state
):
    world.row.state = state
    world.base.case.policy.stages.append(
        world.base.case.policy.stages[0] | {"code": "later"}
    )
    world.base.case.stage = 1
    result = detail()
    assert result.stage == 0
    assert result.rubric.code == "content"
    assert result.case.stage_code == "later"
    assert result.state == state
    assert not result.has_scored
    assert not hasattr(result, "answers")
    assert not hasattr(result, "peers")
    world.base.assignments.filter.assert_called_once_with(
        case_id=UUID(int=20), id=UUID(int=30), account_id=UUID(int=1)
    )
    assert world.base.audit.call_args.args[:3] == (
        request(),
        "own_assignment",
        UUID(int=20),
    )
    world.base.labels.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"capability_code": "applications.manage_programme_review"},
        {"department_id": None},
        {"requested_fields": frozenset({"review_answers"})},
        {"requested_fields": frozenset({"review_context", "review_evidence"})},
        {"requested_fields": frozenset()},
    ],
)
def test_exact_reviewer_context_precedes_assignment_loading(world, changes):
    with pytest.raises(Denied):
        detail(request=request(**changes))
    world.base.loader.assert_not_called()
    world.base.assignments.filter.assert_not_called()
    world.entries.filter.assert_not_called()


def test_missing_foreign_assignment_and_department_are_nondisclosing(world):
    world.base.query.first.return_value = None
    with pytest.raises(Denied):
        detail()
    world.base.audit.assert_not_called()
    world.entries.filter.assert_not_called()
    world.base.assignments.reset_mock()
    world.base.case.proposal.call.owner_department_id = UUID(int=99)
    with pytest.raises(Denied):
        detail()
    world.base.assignments.filter.assert_not_called()


@pytest.mark.parametrize("stage", [-1, True, "0", 1])
def test_invalid_retained_assignment_stage_fails_closed(world, stage):
    world.row.stage = stage
    with pytest.raises(ProgrammeReviewUnavailableError):
        detail()
    world.base.audit.assert_not_called()


def test_own_score_flag_is_minimal_scoped_and_audit_failure_discards_result(world):
    world.entry_query.exists.return_value = True
    assert detail().has_scored
    world.entries.filter.assert_called_with(
        case_id=UUID(int=20), assignment_id=UUID(int=30), action="scored"
    )
    world.base.audit.side_effect = Denied
    with pytest.raises(Denied):
        detail()


def test_queue_filters_own_live_relationship_before_limit_and_batches_score_flags(
    world,
):
    world.base.rows.append(SimpleNamespace(**(vars(world.row) | {"id": UUID(int=31)})))
    world.entry_query.values_list.return_value = [UUID(int=30)]
    result = queue(after_id=UUID(int=29), limit=1)
    assert len(result.items) == 1
    assert result.items[0].has_scored
    assert result.next_cursor == UUID(int=30)
    kwargs = world.base.assignments.filter.call_args.kwargs
    assert kwargs["account_id"] == UUID(int=1)
    assert kwargs["state__in"] == ("pending", "active")
    world.base.query.filter.assert_called_once_with(id__gt=UUID(int=29))
    world.base.query.order_by.assert_called_once_with("id")
    world.base.query.__getitem__.assert_called_once_with(slice(None, 2))
    world.entries.filter.assert_called_once_with(
        assignment_id__in=[UUID(int=30)], action="scored", case_id__in=[UUID(int=20)]
    )
    assert world.cases.filter.call_args.kwargs["policy__call__organization_id"] == UUID(
        int=2
    )
    assert world.cases.filter.call_args.kwargs["policy__call__edition_id"] == UUID(
        int=3
    )
    world.base.labels.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101, True, "1"])
def test_queue_bound_precedes_scope_and_discovery(world, limit):
    with pytest.raises(Denied):
        queue(limit=limit)
    world.base.locked.assert_not_called()
    world.base.assignments.filter.assert_not_called()


def test_empty_readonly_discovery_is_complete_and_audited(world):
    world.base.rows.clear()
    world.base.locked.return_value.accepts_private_planning_writes = False
    result = queue()
    assert result.items == ()
    assert result.next_cursor is None
    assert world.base.audit.call_args.args[1] == "own_assignments"
    world.base.query.first.return_value = world.row
    assert not detail().writable
