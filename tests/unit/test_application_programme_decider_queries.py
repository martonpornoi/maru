"""Decider-only discovery, all-stage readiness and non-recipient history scope."""

import json
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db.models import F

from maru.applications import programme_decider_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_authorization import (
    DECIDE,
    MANAGE_REVIEW,
    MODERATE,
    REVIEW,
)
from maru.applications.programme_review_queries import ProgrammeReviewDetail
from maru.applications.programme_review_rules import (
    ProgrammeReviewConflictError,
    ProgrammeReviewUnavailableError,
)
from tests.unit import test_application_programme_review_management_queries as manager
from tests.unit.test_application_programme_decider_preview import request
from tests.unit.test_application_programme_review_inputs import review_policy


@pytest.fixture
def world(monkeypatch):
    base = manager.world.__wrapped__(monkeypatch)
    policy = review_policy()
    policy = replace(
        policy, stages=(*policy.stages, replace(policy.stages[0], code="quality"))
    )
    document = json.loads(json.dumps(asdict(policy)))
    base.case.policy.stages = document["stages"]
    base.case.policy.templates = document["templates"]
    locked = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    audit, independent, sensitive = Mock(), Mock(), Mock()
    protected = Mock(
        return_value=ProgrammeReviewDetail(UUID(int=20), 5, "{}", None, None, None)
    )
    scores, ready = Mock(return_value=(object(), object())), Mock(return_value=True)
    for name, value in (
        ("_locked_scope", locked),
        ("_audit", audit),
        ("require_independent_actor", independent),
        ("require_sensitive_programme_review_authority", sensitive),
        ("get_programme_review_detail", protected),
        ("latest_stage_scores", scores),
        ("stage_is_ready", ready),
    ):
        monkeypatch.setattr(queries, name, value)
    return SimpleNamespace(
        base=base,
        locked=locked,
        audit=audit,
        independent=independent,
        sensitive=sensitive,
        protected=protected,
        scores=scores,
        ready=ready,
    )


def call(name="work", **changes):
    functions = {
        "work": queries.get_programme_decision_work,
        "evidence": queries.get_programme_decision_evidence,
        "messages": queries.list_programme_decision_messages,
    }
    field = "review_context" if name == "work" else "review_evidence"
    return functions[name].__wrapped__(
        **(
            {
                "request": request(requested_fields=frozenset({field})),
                "case_id": UUID(int=20),
            }
            | changes
        )
    )


def test_templates_are_pinned_only_after_existing_protected_context_and_independence(
    world,
):
    result = call()
    assert result.policy.stages[1].code == "quality"
    assert len(result.policy.templates) == 4
    assert result.detail == world.protected.return_value
    world.independent.assert_called_once_with(
        world.base.case, UUID(int=1), decision=True
    )
    assert world.protected.call_args.kwargs["request"].capability_code == DECIDE
    world.base.labels.assert_not_called()
    world.audit.assert_called_once()


@pytest.mark.parametrize("capability", [MANAGE_REVIEW, MODERATE, REVIEW])
@pytest.mark.parametrize("name", ["work", "evidence", "messages"])
def test_other_review_roles_cannot_inherit_decider_queries(world, capability, name):
    field = "review_context" if name == "work" else "review_evidence"
    with pytest.raises(Denied):
        call(
            name,
            request=request(
                capability_code=capability, requested_fields=frozenset({field})
            ),
        )
    world.locked.assert_not_called()
    world.protected.assert_not_called()
    world.base.loader.assert_not_called()


@pytest.mark.parametrize("name", ["work", "evidence", "messages"])
@pytest.mark.parametrize(
    "change",
    [
        {"department_id": None},
        {"requested_fields": frozenset()},
        {"requested_fields": frozenset({"review_context", "review_evidence"})},
    ],
)
def test_closed_purpose_precedes_any_private_read(world, name, change):
    with pytest.raises(Denied):
        call(name, request=request(**change))
    world.protected.assert_not_called()
    world.base.loader.assert_not_called()


def test_protected_context_sensitive_denial_and_failed_independence_release_nothing(
    world,
):
    world.protected.side_effect = Denied
    with pytest.raises(Denied):
        call()
    world.independent.assert_not_called()
    world.protected.side_effect = None
    world.independent.side_effect = ProgrammeReviewConflictError
    with pytest.raises(Denied):
        call()
    world.audit.assert_not_called()


@pytest.mark.parametrize("name", ["work", "evidence", "messages"])
def test_wrong_department_is_denied_before_independence_and_history(world, name):
    world.base.case.proposal.call.owner_department_id = UUID(int=99)
    with pytest.raises(Denied):
        call(name)
    world.independent.assert_not_called()
    world.audit.assert_not_called()


@pytest.mark.parametrize("name", ["work", "evidence"])
def test_inconsistent_case_version_releases_no_projection(world, name):
    world.protected.return_value = replace(world.protected.return_value, version=6)
    with pytest.raises(ProgrammeReviewUnavailableError):
        call(name)
    world.audit.assert_not_called()


def test_every_configured_stage_uses_canonical_quorum_and_fresh_moderation(world):
    world.ready.side_effect = [True, False]
    result = call("evidence", after_version=3)
    assert [
        (stage.code, stage.valid_scores, stage.required_reviews, stage.ready)
        for stage in result.stages
    ] == [("content", 2, 2, True), ("quality", 2, 2, False)]
    assert [entry.args for entry in world.scores.call_args_list] == [
        (world.base.case, 0),
        (world.base.case, 1),
    ]
    assert world.protected.call_args.kwargs["after_version"] == 3
    assert world.protected.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_evidence"}
    )
    world.audit.assert_called_once()


def test_overfull_stage_is_unavailable_not_truncated(world):
    world.scores.return_value = (object(),) * 17
    with pytest.raises(ProgrammeReviewUnavailableError):
        call("evidence")
    world.audit.assert_not_called()


def test_discovery_filters_all_conflicts_including_prior_moderator_before_paging(
    world, monkeypatch
):
    query = MagicMock()
    for name in ("select_related", "filter", "exclude", "order_by"):
        getattr(query, name).return_value = query
    query.__getitem__.side_effect = lambda bounds: [world.base.case, world.base.case][
        bounds
    ]
    monkeypatch.setattr(queries, "_cases", Mock(return_value=query))
    collaborators, assignments, entries = Mock(), Mock(), Mock()
    for model, objects in (
        (queries.ProgrammeProposalCollaborator, collaborators),
        (queries.ProgrammeReviewAssignment, assignments),
        (queries.ProgrammeReviewEntry, entries),
    ):
        monkeypatch.setattr(model, "objects", objects)
    result = queries.list_programme_decision_cases.__wrapped__(
        request=request(), limit=1, after_id=UUID(int=19)
    )
    assert len(result.items) == 1
    assert result.next_cursor == UUID(int=20)
    assert query.filter.call_args_list[0].kwargs == {
        "policy__call__organization_id": UUID(int=2),
        "policy__call__edition_id": UUID(int=3),
        "policy__call_id": F("proposal__call_id"),
        "revision__proposal_id": F("proposal_id"),
    }
    assert [entry.kwargs for entry in query.exclude.call_args_list] == [
        {"proposal__submission__account_id": UUID(int=1)},
        {"proposal_id__in": collaborators.filter.return_value.values.return_value},
        {"id__in": assignments.filter.return_value.values.return_value},
        {"id__in": entries.filter.return_value.values.return_value},
    ]
    entries.filter.assert_called_once_with(
        case__proposal__organization_id=UUID(int=2),
        case__proposal__edition_id=UUID(int=3),
        actor_id=UUID(int=1),
        action="moderated",
    )
    assert query.filter.call_args_list[1].kwargs == {"id__gt": UUID(int=19)}
    query.__getitem__.assert_called_once_with(slice(None, 2))
    names = [entry[0] for entry in query.mock_calls]
    assert max(i for i, name in enumerate(names) if name == "exclude") < names.index(
        "__getitem__"
    )
    world.base.labels.assert_not_called()
    world.protected.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101, True, "1"])
def test_bad_page_bounds_precede_scope(world, limit):
    with pytest.raises(Denied):
        queries.list_programme_decision_cases.__wrapped__(
            request=request(), limit=limit
        )
    world.locked.assert_not_called()


@pytest.fixture
def history(world, monkeypatch):
    row = SimpleNamespace(
        id=UUID(int=80),
        entry=SimpleNamespace(version=4, created_at=world.base.case.revision.sealed_at),
        outcome="waitlisted",
        message="Exact stored recipient text",
        acknowledgement_required=True,
    )
    query = MagicMock()
    for name in ("select_related", "filter", "order_by"):
        getattr(query, name).return_value = query
    query.__getitem__.side_effect = lambda bounds: [row, row][bounds]
    monkeypatch.setattr(queries.ProgrammeReviewDecision, "objects", query)
    return query


def test_message_history_is_exact_source_audited_and_sensitive_without_recipients(
    world, history
):
    result = call("messages", after_version=2, limit=1)
    assert result.version == 5
    assert result.next_version == 4
    assert result.items[0].message == "Exact stored recipient text"
    assert not hasattr(result.items[0], "recipients")
    assert not hasattr(result.items[0], "acknowledged")
    history.filter.assert_called_once_with(
        entry__case=world.base.case,
        revision_id=UUID(int=22),
        revision__organization_id=UUID(int=2),
        revision__edition_id=UUID(int=3),
        entry__version__gt=2,
        entry__version__lte=5,
    )
    history.order_by.assert_called_once_with("entry__version")
    history.__getitem__.assert_called_once_with(slice(None, 2))
    assert world.sensitive.call_args.kwargs["requested_fields"] == frozenset(
        {"review_evidence"}
    )
    world.base.labels.assert_not_called()
    world.audit.assert_called_once()


def test_sensitive_message_denial_and_audit_failure_release_no_history(world, history):
    world.sensitive.side_effect = Denied
    with pytest.raises(Denied):
        call("messages")
    history.select_related.assert_not_called()
    world.sensitive.side_effect = None
    world.audit.side_effect = Denied
    with pytest.raises(Denied):
        call("messages")


@pytest.mark.parametrize("cursor", [-1, True, "2", 2**63])
def test_message_cursor_is_closed_before_scope(world, cursor):
    with pytest.raises(Denied):
        call("messages", after_version=cursor)
    world.locked.assert_not_called()
