"""Database-free moderator purpose, independence, paging and evidence contracts."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db.models import F

from maru.applications import programme_moderation_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_authorization import MODERATE
from maru.applications.programme_review_queries import ProgrammeReviewDetail
from maru.applications.programme_review_rules import (
    ProgrammeReviewConflictError,
    ProgrammeReviewUnavailableError,
)
from tests.unit import test_application_programme_review_management_queries as manager
from tests.unit.test_application_programme_reviewer_selection import (
    request as manager_request,
)


def request(**changes):
    return replace(manager_request(), capability_code=MODERATE, **changes)


@pytest.fixture
def world(monkeypatch):
    base = manager.world.__wrapped__(monkeypatch)
    locked = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    audit = Mock()
    independent = Mock()
    monkeypatch.setattr(queries, "_locked_scope", locked)
    monkeypatch.setattr(queries, "_audit", audit)
    monkeypatch.setattr(queries, "require_independent_actor", independent)
    return SimpleNamespace(
        base=base, locked=locked, audit=audit, independent=independent
    )


def detail(**changes):
    return queries.get_programme_moderation_case.__wrapped__(
        **({"request": request(), "case_id": UUID(int=20)} | changes)
    )


def test_exact_retained_metadata_checks_independence_before_disclosure(world):
    result = detail()
    assert result.case.call_name == "Synthetic call"
    assert result.stages[0].code == "content"
    assert result.writable
    assert not result.case.current_revision
    world.independent.assert_called_once_with(world.base.case, UUID(int=1))
    world.base.labels.assert_not_called()
    world.audit.assert_called_once()


@pytest.mark.parametrize(
    "capability",
    [
        "applications.manage_programme_review",
        "applications.review_programme",
        "applications.decide_programme",
    ],
)
def test_other_roles_never_inherit_moderator_metadata(world, capability):
    with pytest.raises(Denied):
        detail(request=replace(request(), capability_code=capability))
    world.locked.assert_not_called()
    world.base.loader.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"department_id": None},
        {"requested_fields": frozenset()},
        {"requested_fields": frozenset({"review_evidence"})},
        {"requested_fields": frozenset({"review_context", "review_answers"})},
    ],
)
def test_metadata_ceiling_is_exact_and_precedes_object_reads(world, changes):
    with pytest.raises(Denied):
        detail(request=request(**changes))
    world.base.loader.assert_not_called()


def test_independence_denial_is_generic_without_audit_or_labels(world):
    world.independent.side_effect = ProgrammeReviewConflictError
    with pytest.raises(Denied):
        detail()
    world.audit.assert_not_called()
    world.base.labels.assert_not_called()


def test_wrong_department_and_audit_failure_release_no_metadata(world):
    world.base.case.proposal.call.owner_department_id = UUID(int=99)
    with pytest.raises(Denied):
        detail()
    world.independent.assert_not_called()
    world.base.case.proposal.call.owner_department_id = UUID(int=4)
    world.audit.side_effect = Denied
    with pytest.raises(Denied):
        detail()


def test_all_retained_conflicts_are_excluded_before_exclusive_paging(
    world, monkeypatch
):
    query = MagicMock()
    for name in ("select_related", "filter", "exclude", "order_by"):
        getattr(query, name).return_value = query
    query.__getitem__.side_effect = lambda bounds: [world.base.case, world.base.case][
        bounds
    ]
    monkeypatch.setattr(queries, "_cases", Mock(return_value=query))
    collaborators = Mock()
    assignments = Mock()
    monkeypatch.setattr(queries.ProgrammeProposalCollaborator, "objects", collaborators)
    monkeypatch.setattr(queries.ProgrammeReviewAssignment, "objects", assignments)
    result = queries.list_programme_moderation_cases.__wrapped__(
        request=request(),
        limit=1,
        after_id=UUID(int=19),
    )
    assert len(result.items) == 1
    assert result.next_cursor == UUID(int=20)
    assert query.filter.call_args_list[0].kwargs == {
        "policy__call__organization_id": UUID(int=2),
        "policy__call__edition_id": UUID(int=3),
        "policy__call_id": F("proposal__call_id"),
        "revision__proposal_id": F("proposal_id"),
    }
    assert query.filter.call_args_list[1].kwargs == {"id__gt": UUID(int=19)}
    assert [call.kwargs for call in query.exclude.call_args_list] == [
        {"proposal__submission__account_id": UUID(int=1)},
        {"proposal_id__in": collaborators.filter.return_value.values.return_value},
        {"id__in": assignments.filter.return_value.values.return_value},
    ]
    collaborators.filter.assert_called_once_with(
        organization_id=UUID(int=2), edition_id=UUID(int=3), account_id=UUID(int=1)
    )
    assignments.filter.assert_called_once_with(
        case__proposal__organization_id=UUID(int=2),
        case__proposal__edition_id=UUID(int=3),
        account_id=UUID(int=1),
    )
    query.__getitem__.assert_called_once_with(slice(None, 2))
    names = [call[0] for call in query.mock_calls]
    assert max(i for i, name in enumerate(names) if name == "exclude") < names.index(
        "__getitem__"
    )


@pytest.mark.parametrize("limit", [0, 101, True, "1"])
def test_invalid_page_bounds_precede_scope(world, limit):
    with pytest.raises(Denied):
        queries.list_programme_moderation_cases.__wrapped__(
            request=request(), limit=limit
        )
    world.locked.assert_not_called()


@pytest.fixture
def evidence(world, monkeypatch):
    protected = Mock(
        return_value=ProgrammeReviewDetail(UUID(int=20), 5, None, None, "[]", None)
    )
    scores = Mock(return_value=(object(),))
    ready = Mock(return_value=False)
    monkeypatch.setattr(queries, "get_programme_review_detail", protected)
    monkeypatch.setattr(queries, "latest_stage_scores", scores)
    monkeypatch.setattr(queries, "stage_is_ready", ready)
    return SimpleNamespace(protected=protected, scores=scores, ready=ready)


def read_evidence(**changes):
    return queries.get_programme_moderation_evidence.__wrapped__(
        **(
            {
                "request": request(requested_fields=frozenset({"review_evidence"})),
                "case_id": UUID(int=20),
            }
            | changes
        )
    )


def test_evidence_uses_protected_owner_and_existing_readiness_not_averages(
    world, evidence
):
    result = read_evidence(after_version=3)
    assert result.valid_scores == 1
    assert result.required_reviews == 2
    assert not result.ready
    assert evidence.protected.call_args.kwargs["after_version"] == 3
    evidence.ready.assert_called_once_with(world.base.case, 0)
    world.audit.assert_called_once()


def test_content_authority_failure_precedes_score_counts_and_extra_reads(
    world, evidence
):
    evidence.protected.side_effect = Denied
    with pytest.raises(Denied):
        read_evidence()
    evidence.scores.assert_not_called()
    world.base.loader.assert_not_called()


def test_evidence_cannot_be_requested_using_metadata_authority(world, evidence):
    with pytest.raises(Denied):
        read_evidence(request=request())
    evidence.protected.assert_not_called()


@pytest.mark.parametrize("mismatch", [True, False])
def test_moved_version_and_excess_scores_fail_closed(world, evidence, mismatch):
    if mismatch:
        world.base.case.version = 6
    else:
        evidence.scores.return_value = (object(),) * 17
    with pytest.raises(ProgrammeReviewUnavailableError):
        read_evidence()
    world.audit.assert_not_called()
