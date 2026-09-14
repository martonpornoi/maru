"""Database-free manager scope, complete roster, owner labels and audit contracts."""

import json
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db.models import F

from maru.applications import programme_review_management_queries as queries
from maru.applications import programme_reviewer_selection as selections
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_rules import ProgrammeReviewUnavailableError
from tests.unit.test_application_programme_review_inputs import review_policy
from tests.unit.test_application_programme_reviewer_selection import request


@pytest.fixture
def world(monkeypatch):
    case = SimpleNamespace(
        id=UUID(int=20),
        proposal=SimpleNamespace(
            call_id=UUID(int=21),
            call=SimpleNamespace(
                owner_department_id=UUID(int=4),
                definition=SimpleNamespace(name="Synthetic call"),
            ),
        ),
        revision_id=UUID(int=22),
        revision=SimpleNamespace(
            sequence=3,
            sealed_at=datetime(2026, 9, 1, tzinfo=UTC),
        ),
        policy=SimpleNamespace(
            version=2, stages=json.loads(json.dumps(asdict(review_policy())))["stages"]
        ),
        version=5,
        stage=0,
        state="open",
    )
    rows = [
        SimpleNamespace(
            id=UUID(int=30 + i), account_id=UUID(int=40 + i), stage=0, state=state
        )
        for i, state in enumerate(("pending", "active", "removed", "recused"))
    ]
    query = MagicMock()
    query.order_by.return_value = query
    query.__getitem__.side_effect = lambda bounds: rows[bounds]
    assignments = Mock()
    assignments.filter.return_value = query
    labels = Mock(return_value={UUID(int=40): "Named reviewer"})
    locked = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    loader = Mock(return_value=case)
    audit = Mock()
    monkeypatch.setattr(queries, "_locked_scope", locked)
    monkeypatch.setattr(queries, "load_review_case", loader)
    monkeypatch.setattr(queries.ProgrammeReviewAssignment, "objects", assignments)
    monkeypatch.setattr(
        queries, "active_verified_person_account_display_labels", labels
    )
    monkeypatch.setattr(queries, "revision_is_current", Mock(return_value=False))
    monkeypatch.setattr(queries, "_audit", audit)
    return SimpleNamespace(
        case=case,
        rows=rows,
        query=query,
        assignments=assignments,
        labels=labels,
        locked=locked,
        loader=loader,
        audit=audit,
    )


def detail(**changes):
    return queries.get_programme_review_management.__wrapped__(
        **({"request": request(), "case_id": UUID(int=20)} | changes)
    )


def test_complete_roster_uses_only_already_owned_person_ids_and_audits(world):
    result = detail()
    assert [row.state for row in result.assignments] == [
        "pending",
        "active",
        "removed",
        "recused",
    ]
    assert [row.display_label for row in result.assignments] == [
        "Named reviewer",
        *["Unavailable person"] * 3,
    ]
    world.labels.assert_called_once_with({row.account_id for row in world.rows})
    world.loader.assert_called_once_with(
        organization_id=UUID(int=2), edition_id=UUID(int=3), case_id=UUID(int=20)
    )
    world.assignments.filter.assert_called_once_with(case_id=UUID(int=20))
    world.query.order_by.assert_called_once_with("stage", "id")
    world.query.__getitem__.assert_called_once_with(slice(None, 129))
    assert result.case.stage_code == "content"
    assert not result.case.current_revision
    assert not hasattr(result, "answers")
    assert world.audit.call_args.args[:3] == (
        request(),
        "management_case",
        UUID(int=20),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"capability_code": "applications.review_programme"},
        {"department_id": None},
        {"requested_fields": frozenset({"review_setup"})},
        {"requested_fields": frozenset({"review_context", "review_answers"})},
    ],
)
def test_exact_manager_field_ceiling_precedes_case_and_identity(world, changes):
    with pytest.raises(Denied):
        detail(request=request(**changes))
    world.locked.assert_not_called()
    world.loader.assert_not_called()
    world.labels.assert_not_called()


def test_source_scope_and_missing_case_precede_identity_labels(world):
    world.case.proposal.call.owner_department_id = UUID(int=99)
    with pytest.raises(Denied):
        detail()
    world.labels.assert_not_called()
    world.loader.side_effect = ProgrammeReviewUnavailableError
    with pytest.raises(Denied):
        detail()
    world.assignments.filter.assert_not_called()


def test_overflow_never_returns_partial_roster_or_resolves_people(world):
    world.rows[:] = [world.rows[0]] * 129
    with pytest.raises(ProgrammeReviewUnavailableError):
        detail()
    world.labels.assert_not_called()
    world.audit.assert_not_called()


def test_readonly_and_empty_roster_remain_audited_but_audit_failure_discards_result(
    world,
):
    world.rows.clear()
    world.locked.return_value.accepts_private_planning_writes = False
    result = detail()
    assert not result.writable
    assert not result.assignments
    world.audit.side_effect = Denied
    with pytest.raises(Denied):
        detail()


@pytest.mark.parametrize("stage", [-1, True, 1, "0"])
def test_invalid_case_stage_fails_closed(world, stage):
    world.case.stage = stage
    with pytest.raises(ProgrammeReviewUnavailableError):
        detail()


def test_unavailable_retained_stage_cannot_silently_drop_assignment(world):
    world.rows[1].stage = 1
    with pytest.raises(ProgrammeReviewUnavailableError):
        detail()


def test_queue_filters_source_relations_before_exclusive_pagination_and_lookahead(
    world, monkeypatch
):
    query = MagicMock()
    query.select_related.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    second = SimpleNamespace(**(vars(world.case) | {"id": UUID(int=23)}))
    query.__getitem__.side_effect = lambda bounds: [world.case, second][bounds]
    cases = Mock(return_value=query)
    monkeypatch.setattr(queries, "_cases", cases)
    result = queries.list_programme_review_management_cases.__wrapped__(
        request=request(), after_id=UUID(int=19), limit=1
    )
    assert result.next_cursor == UUID(int=20)
    assert [case.case_id for case in result.items] == [UUID(int=20)]
    assert query.filter.call_args_list[0].kwargs == {
        "policy__call__organization_id": UUID(int=2),
        "policy__call__edition_id": UUID(int=3),
        "policy__call_id": F("proposal__call_id"),
        "revision__proposal_id": F("proposal_id"),
    }
    assert query.filter.call_args_list[1].kwargs == {"id__gt": UUID(int=19)}
    query.__getitem__.assert_called_once_with(slice(None, 2))
    assert world.audit.call_args.args[:3] == (request(), "management_cases", None)


@pytest.mark.parametrize("limit", [0, 101, True, "50"])
def test_queue_limits_are_closed_before_admission(world, limit):
    with pytest.raises(Denied):
        queries.list_programme_review_management_cases.__wrapped__(
            request=request(), limit=limit
        )
    world.locked.assert_not_called()


def test_case_relation_scopes_both_proposal_and_revision_before_projection():
    sql, params = queries._cases(request()).query.sql_with_params()
    for column in ("organization_id", "edition_id", "owner_department_id"):
        assert column in sql
    assert set(params) >= {UUID(int=2), UUID(int=3), UUID(int=4)}


@pytest.mark.parametrize(
    "excluded", ["opener", "contributor", "moderator", "duplicate", "full", None]
)
def test_candidate_exclusions_use_retained_rows_and_exact_current_stage(
    monkeypatch, excluded
):
    account_id = UUID(int=40)
    case = SimpleNamespace(
        id=UUID(int=20),
        stage=1,
        created_by_id=account_id if excluded == "opener" else UUID(int=99),
        proposal=object(),
    )
    contributor = Mock(return_value=excluded == "contributor")
    entries = Mock()
    entries.filter.return_value.exists.return_value = excluded == "moderator"
    assignments = Mock()
    assignments.filter.return_value.exists.return_value = excluded == "duplicate"
    assignments.filter.return_value.count.return_value = (
        16 if excluded == "full" else 15
    )
    monkeypatch.setattr(selections, "is_proposal_contributor", contributor)
    monkeypatch.setattr(selections.ProgrammeReviewEntry, "objects", entries)
    monkeypatch.setattr(selections.ProgrammeReviewAssignment, "objects", assignments)
    assert selections._suitable(case, account_id) is (excluded is None)
    if excluded is None:
        assert entries.filter.call_args.kwargs == {
            "case_id": case.id,
            "actor_id": account_id,
            "action__in": (
                selections.ProgrammeReviewAction.MODERATED,
                selections.ProgrammeReviewAction.DECIDED,
            ),
        }
        assert assignments.filter.call_args_list[0].kwargs == {
            "case_id": case.id,
            "stage": 1,
            "account_id": account_id,
        }
        assert assignments.filter.call_args_list[1].kwargs == {
            "case_id": case.id,
            "stage": 1,
        }
