"""Fast setup query bounds, scope-before-load and audit-before-disclosure contracts."""

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_review_setup_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_rules import ProgrammeReviewUnavailableError
from tests.unit.test_application_programme_review_inputs import review_policy


def request(**changes):
    return replace(
        queries.ProgrammeReviewReadRequest(
            UUID(int=1),
            UUID(int=2),
            UUID(int=3),
            UUID(int=4),
            queries.MANAGE_REVIEW,
            frozenset({"review_setup"}),
            UUID(int=5),
            "test",
        ),
        **changes,
    )


@pytest.fixture
def source(monkeypatch):
    call = SimpleNamespace(
        id=UUID(int=20),
        definition_id=UUID(int=21),
        definition=SimpleNamespace(
            name="Call", code="programme", version=1, status="active"
        ),
    )
    calls = MagicMock()
    calls.filter.return_value = calls
    calls.first.return_value = call
    calls.order_by.return_value = calls
    calls.__getitem__.side_effect = lambda bounds: [call][bounds]
    call_query = Mock(return_value=calls)
    questions = MagicMock()
    question_query = questions.filter.return_value.order_by.return_value
    question_query.__getitem__.return_value = [
        SimpleNamespace(
            key="title", label="Title", field_type="short_text", classification="C2"
        )
    ]
    policies = Mock()
    document = json.loads(json.dumps(asdict(review_policy())))
    policy = SimpleNamespace(
        id=UUID(int=30),
        version=2,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        reason="Explicit policy",
        **document,
    )
    policies.filter.return_value.first.return_value = policy
    policies.filter.return_value.aggregate.return_value = {"value": 2}
    locked = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    audit = Mock()
    monkeypatch.setattr(queries, "_call_query", call_query)
    monkeypatch.setattr(queries.ApplicationQuestion, "objects", questions)
    monkeypatch.setattr(queries.ProgrammeReviewPolicy, "objects", policies)
    monkeypatch.setattr(queries, "_locked_scope", locked)
    monkeypatch.setattr(queries, "_audit", audit)
    return SimpleNamespace(
        call=call,
        calls=calls,
        call_query=call_query,
        questions=questions,
        question_query=question_query,
        policies=policies,
        policy=policy,
        locked=locked,
        audit=audit,
    )


def context(**changes):
    return queries.get_programme_review_setup.__wrapped__(
        **({"request": request(), "call_id": UUID(int=20)} | changes)
    )


def policy(**changes):
    return queries.get_programme_review_setup_policy.__wrapped__(
        **({"request": request(), "call_id": UUID(int=20), "version": 2} | changes)
    )


def test_setup_context_scopes_call_and_questions_before_complete_audited_projection(
    source,
):
    result = context()
    assert result.call.call_id == UUID(int=20)
    assert result.policy_version == 2
    assert result.questions == (
        queries.ReviewSetupQuestion("title", "Title", "short_text", "C2"),
    )
    source.call_query.assert_called_once_with(
        organization_id=UUID(int=2), edition_id=UUID(int=3), department_id=UUID(int=4)
    )
    source.calls.filter.assert_called_once_with(id=UUID(int=20))
    source.questions.filter.assert_called_once_with(
        definition_id=UUID(int=21),
        definition__organization_id=UUID(int=2),
        definition__edition_id=UUID(int=3),
    )
    source.question_query.__getitem__.assert_called_once_with(slice(None, 501))
    source.audit.assert_called_once()
    assert source.audit.call_args.args[:3] == (
        request(),
        "setup_configuration",
        UUID(int=20),
    )
    assert not hasattr(result, "answers")


@pytest.mark.parametrize(
    "change",
    [
        {"department_id": None},
        {"capability_code": "applications.manage_programme_call"},
        {"capability_code": "applications.review_programme"},
        {"requested_fields": frozenset()},
        {"requested_fields": frozenset({"review_context"})},
        {"requested_fields": frozenset({"review_setup", "review_answers"})},
    ],
)
def test_wrong_purpose_or_fields_are_denied_before_configuration_load(source, change):
    with pytest.raises(Denied):
        context(request=request(**change))
    source.locked.assert_not_called()
    source.call_query.assert_not_called()
    source.questions.filter.assert_not_called()


def test_authorization_failure_precedes_call_load(source):
    source.locked.side_effect = Denied
    with pytest.raises(Denied):
        context()
    source.call_query.assert_not_called()


def test_unknown_foreign_call_and_overflow_never_disclose_partial_question_data(source):
    source.calls.first.return_value = None
    with pytest.raises(Denied):
        context()
    source.questions.filter.assert_not_called()
    source.calls.first.return_value = source.call
    source.question_query.__getitem__.return_value *= 501
    with pytest.raises(ProgrammeReviewUnavailableError):
        context()
    source.audit.assert_not_called()


def test_audit_failure_prevents_configuration_release(source):
    source.audit.side_effect = Denied
    with pytest.raises(Denied):
        context()


def test_closed_planning_remains_readable_without_writability_claim(source):
    source.locked.return_value.accepts_private_planning_writes = False
    assert context().writable is False


def test_call_page_uses_exclusive_uuid_cursor_and_one_lookahead(source):
    second = SimpleNamespace(**(vars(source.call) | {"id": UUID(int=22)}))
    source.calls.__getitem__.side_effect = lambda bounds: [source.call, second][bounds]
    page = queries.list_programme_review_setup_calls.__wrapped__(
        request=request(), after_id=UUID(int=19), limit=1
    )
    assert page.next_cursor == source.call.id
    assert len(page.items) == 1
    source.calls.filter.assert_called_once_with(id__gt=UUID(int=19))
    source.calls.__getitem__.assert_called_once_with(slice(None, 2))
    source.audit.assert_called_once()


@pytest.mark.parametrize("limit", [0, 101, True, "1"])
def test_bad_page_limit_never_loads_calls(source, limit):
    with pytest.raises(Denied):
        queries.list_programme_review_setup_calls.__wrapped__(
            request=request(), limit=limit
        )
    source.call_query.assert_not_called()


def test_exact_policy_is_scoped_via_call_before_normalized_projection_and_audit(source):
    result = policy()
    assert result.policy == review_policy().normalized()
    assert result.reason == "Explicit policy"
    source.policies.filter.assert_called_once_with(
        call_id__in=source.calls.values.return_value, version=2
    )
    source.calls.filter.assert_called_once_with(id=UUID(int=20))
    assert source.audit.call_args.args[:3] == (request(), "setup_policy", UUID(int=30))


@pytest.mark.parametrize("version", [0, -1, True, "2", 2**63])
def test_policy_version_rejects_aliases_before_loading(source, version):
    with pytest.raises(Denied):
        policy(version=version)
    source.policies.filter.assert_not_called()


def test_unknown_policy_corrupt_document_and_audit_failures_are_closed(source):
    source.policies.filter.return_value.first.return_value = None
    with pytest.raises(Denied):
        policy()
    source.policies.filter.return_value.first.return_value = source.policy
    source.policy.stages = []
    with pytest.raises(ProgrammeReviewUnavailableError):
        policy()
    source.audit.assert_not_called()


def test_untyped_call_identifier_is_rejected_before_scope_and_queries(source):
    with pytest.raises(ValidationError):
        context(call_id=str(UUID(int=20)))
    source.locked.assert_not_called()
    source.call_query.assert_not_called()
