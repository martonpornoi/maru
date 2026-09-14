"""Database-free exact-self context and late-disclosure regression checks."""

from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_personal_queries as queries
from maru.applications import programme_queries as projections
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError,
)
from tests.unit.test_application_programme_proposal_views import source


@pytest.fixture
def context(monkeypatch):
    available = source()
    definition = SimpleNamespace(**asdict(available.summary))
    call = SimpleNamespace(
        definition=definition,
        max_collaborators=4,
        tracks=Mock(),
        formats=Mock(),
    )
    call.tracks.order_by.return_value = [
        SimpleNamespace(
            id=row.track_id,
            code=row.code,
            label=row.label,
            description=row.description,
            position=row.position,
        )
        for row in available.tracks
    ]
    call.formats.order_by.return_value = [
        SimpleNamespace(
            id=row.format_id,
            code=row.code,
            label=row.label,
            description=row.description,
            position=row.position,
            min_duration_minutes=row.minimum_duration_minutes,
            default_duration_minutes=row.default_duration_minutes,
            max_duration_minutes=row.maximum_duration_minutes,
        )
        for row in available.formats
    ]
    proposal = SimpleNamespace(
        id=UUID(int=40),
        submission_id=UUID(int=41),
        call_id=available.summary.call_id,
        submission=SimpleNamespace(aggregate_version=7),
        call=call,
        state="draft",
        sealed_revision_id=None,
        submitted_revision_id=None,
    )
    summary = projections._proposal_summary(proposal=proposal, relationship="lead")
    scope = SimpleNamespace(**asdict(summary), accepts_private_planning_writes=True)
    authorize = Mock(return_value=scope)
    monkeypatch.setattr(queries, "authorize_programme_proposal_scope", authorize)
    source_query = Mock()
    query = source_query.return_value.filter.return_value
    query.first.return_value = proposal
    monkeypatch.setattr(queries, "_proposal_query", source_query)
    audit = Mock()
    monkeypatch.setattr(queries, "_append_sensitive_read", audit)
    return SimpleNamespace(
        available=available,
        proposal=proposal,
        scope=scope,
        authorize=authorize,
        source_query=source_query,
        query=query,
        audit=audit,
    )


def read(**overrides):
    values = {
        "actor_id": UUID(int=1),
        "organization_id": UUID(int=2),
        "edition_id": UUID(int=3),
        "proposal_id": UUID(int=40),
        "correlation_id": UUID(int=5),
        "source_channel": "programme-proposal-workspace",
    }
    return queries.get_self_programme_workflow.__wrapped__(**(values | overrides))


def test_lead_context_is_minimized_scoped_audited_and_complete(context):
    result = read()
    assert result.tracks == context.available.tracks
    assert result.formats == context.available.formats
    assert result.maximum_collaborators == 4
    assert result.summary.aggregate_version == 7
    assert result.planning
    assert not hasattr(result, "questions")
    assert not hasattr(result, "owner_department_id")
    context.source_query.assert_called_once_with(
        organization_id=UUID(int=2), edition_id=UUID(int=3)
    )
    context.source_query.return_value.filter.assert_called_once_with(id=UUID(int=40))
    assert context.query.first.call_count == 2
    assert context.authorize.call_count == 2
    for invocation in context.authorize.call_args_list:
        assert invocation.kwargs["requested_fields"] == frozenset(
            {"proposal_summary", "workflow_context"}
        )
        assert invocation.kwargs["actor_id"] == UUID(int=1)
    context.audit.assert_called_once()
    assert context.audit.call_args.kwargs["target_id"] == UUID(int=40)


@pytest.mark.parametrize("relationship", ["invited", "collaborator"])
def test_nonlead_context_does_not_load_catalog_or_roster(context, relationship):
    context.scope.relationship = relationship
    result = read()
    assert result.summary.relationship == relationship
    assert result.tracks == result.formats == ()
    assert result.maximum_collaborators is None
    context.proposal.call.tracks.order_by.assert_not_called()
    context.proposal.call.formats.order_by.assert_not_called()


def test_unavailable_new_call_and_closed_planning_do_not_erase_history(
    context, monkeypatch
):
    context.scope.accepts_private_planning_writes = False
    context.proposal.call.definition.status = "retired"
    monkeypatch.setattr(
        projections,
        "available_programme_calls",
        Mock(side_effect=AssertionError),
    )
    result = read()
    assert not result.planning
    assert result.call_status == "retired"
    assert result.summary.aggregate_version == 7


def test_denial_precedes_source_load(context):
    context.authorize.side_effect = ApplicationsProgrammeAuthorizationDeniedError
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read()
    context.source_query.assert_not_called()
    context.audit.assert_not_called()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("aggregate_version", 8),
        ("state", "sealed"),
        ("relationship", "collaborator"),
        ("proposal_id", UUID(int=99)),
        ("call_id", UUID(int=99)),
        ("submission_id", UUID(int=99)),
        ("accepts_private_planning_writes", False),
    ],
)
def test_changed_self_scope_discards_prepared_context(context, key, value):
    fresh = SimpleNamespace(**(vars(context.scope) | {key: value}))
    context.authorize.side_effect = [context.scope, fresh]
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read()
    context.audit.assert_not_called()


@pytest.mark.parametrize(
    ("key", "value"), [("aggregate_version", 9), ("status", "retired")]
)
def test_changed_call_source_discards_context(context, key, value):
    definition = SimpleNamespace(
        **(vars(context.proposal.call.definition) | {key: value})
    )
    current = SimpleNamespace(call=SimpleNamespace(definition=definition))
    context.query.first.side_effect = [context.proposal, current]
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read()
    context.audit.assert_not_called()


@pytest.mark.parametrize("catalog", ["tracks", "formats"])
def test_catalog_overflow_is_not_a_partial_chooser(context, catalog):
    manager = getattr(context.proposal.call, catalog)
    manager.order_by.return_value *= 101
    with pytest.raises(projections.ApplicationsProgrammeProjectionOverflowError):
        read()
    context.audit.assert_not_called()


def test_audit_failure_never_returns_prepared_context(context):
    context.audit.side_effect = RuntimeError("audit unavailable")
    with pytest.raises(RuntimeError, match="audit unavailable"):
        read()


def test_naive_instant_is_refused_before_authority(context):
    with pytest.raises(ApplicationsProgrammeAuthorizationDeniedError):
        read(now=datetime(2026, 9, 14, tzinfo=UTC).replace(tzinfo=None))
    context.authorize.assert_not_called()
