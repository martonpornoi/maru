"""Exact sealed choice metadata inside existing audited review read boundaries."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from maru.applications import programme_review_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_authorization import DECIDE, MODERATE, REVIEW
from maru.applications.programme_review_rules import ProgrammeReviewUnavailableError
from tests.unit.test_application_programme_answer_display import OPTIONS


@pytest.fixture
def source(monkeypatch):
    request = queries.ProgrammeReviewReadRequest(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        UUID(int=4),
        REVIEW,
        frozenset({"review_answers"}),
        UUID(int=5),
        "test",
    )
    question = SimpleNamespace(
        label="Exact original question", field_type="single_choice", options=OPTIONS
    )
    row = SimpleNamespace(
        question_key="topic",
        question_type="single_choice",
        classification="C2",
        question=question,
        answer_revision=SimpleNamespace(value="workshop"),
    )
    case = SimpleNamespace(
        id=UUID(int=20),
        version=5,
        revision_id=UUID(int=30),
        stage=0,
        policy=SimpleNamespace(
            stages=({"question_keys": ["topic"], "anonymous": False},)
        ),
    )
    query = MagicMock()
    query.filter.return_value = query
    query.exclude.return_value = query
    query.order_by.return_value = query
    query.__getitem__.side_effect = lambda bounds: [row][bounds]
    manager = Mock()
    manager.select_related.return_value = query
    locked = Mock(
        return_value=SimpleNamespace(
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            edition_id=request.edition_id,
            department_id=request.department_id,
        )
    )
    assignment = Mock(return_value=None)
    sensitive = Mock()
    extra_sensitive = Mock()
    audit = Mock()
    monkeypatch.setattr(queries.ProgrammeProposalRevisionAnswer, "objects", manager)
    monkeypatch.setattr(queries, "_locked_scope", locked)
    monkeypatch.setattr(queries, "load_review_case", Mock(return_value=case))
    monkeypatch.setattr(queries, "_detail_assignment", assignment)
    monkeypatch.setattr(
        queries, "require_sensitive_programme_review_authority", sensitive
    )
    monkeypatch.setattr(queries, "authorize_programme_review_scope", extra_sensitive)
    monkeypatch.setattr(queries, "_audit", audit)
    monkeypatch.setattr(queries, "_context", Mock(return_value="{}"))
    return SimpleNamespace(
        request=request,
        row=row,
        question=question,
        case=case,
        query=query,
        manager=manager,
        locked=locked,
        assignment=assignment,
        sensitive=sensitive,
        extra_sensitive=extra_sensitive,
        audit=audit,
    )


def read(source, **changes):
    return queries.get_programme_review_detail.__wrapped__(
        request=replace(source.request, **changes),
        case_id=source.case.id,
    )


@pytest.mark.parametrize("capability", [REVIEW, MODERATE, DECIDE])
def test_every_content_role_gets_only_exact_selected_metadata_before_required_audit(
    source, capability
):
    detail = read(source, capability_code=capability)
    rows = json.loads(detail.answers_json)
    assert rows == [
        {
            "key": "topic",
            "label": "Exact original question",
            "type": "single_choice",
            "classification": "C2",
            "value": "workshop",
            "selected_options": [OPTIONS[1]],
        }
    ]
    assert "Unselected private option" not in detail.answers_json
    source.manager.select_related.assert_called_once_with("question", "answer_revision")
    source.query.filter.assert_called_once_with(
        revision_id=UUID(int=30),
        organization_id=UUID(int=2),
        edition_id=UUID(int=3),
        question_key__in=["topic"],
    )
    source.query.__getitem__.assert_called_once_with(slice(None, 501))
    source.audit.assert_called_once()
    source.sensitive.assert_called_once()
    source.assignment.assert_called_once()


def test_anonymous_query_keeps_structured_identifiers_and_source_bindings_excluded(
    source,
):
    source.case.policy.stages[0]["anonymous"] = True
    assert json.loads(read(source).answers_json)[0]["selected_options"] == [OPTIONS[1]]
    source.query.exclude.assert_called_once_with(
        question_type__in=queries._ANONYMOUS_OMISSIONS
    )
    assert "address" in queries._ANONYMOUS_OMISSIONS
    assert "safe_file" in queries._ANONYMOUS_OMISSIONS
    source.query.filter.assert_any_call(question__source_binding="")


@pytest.mark.parametrize("guard", ["locked", "assignment", "sensitive"])
def test_current_admission_failure_precedes_answer_loading(source, guard):
    getattr(source, guard).side_effect = Denied
    with pytest.raises(Denied):
        read(source)
    source.manager.select_related.assert_not_called()


def test_restricted_answer_labels_still_require_the_extra_sensitive_purpose(source):
    source.row.classification = "C3"
    source.extra_sensitive.side_effect = Denied
    with pytest.raises(Denied):
        read(source)
    source.extra_sensitive.assert_called_once()
    source.audit.assert_not_called()


def test_audit_failure_releases_no_formatted_projection(source):
    source.audit.side_effect = RuntimeError("Synthetic required audit failure")
    with pytest.raises(RuntimeError, match="required audit failure"):
        read(source)


@pytest.mark.parametrize("change", ["type", "missing_code", "malformed_options"])
def test_incoherent_original_question_metadata_is_unavailable(source, change):
    if change == "type":
        source.question.field_type = "short_text"
    elif change == "missing_code":
        source.row.answer_revision.value = "unknown"
    else:
        source.question.options = []
    with pytest.raises(ProgrammeReviewUnavailableError):
        read(source)
    source.audit.assert_not_called()


def test_absent_answer_does_not_load_choice_labels(source):
    source.row.answer_revision = None
    del source.question.options
    row = json.loads(read(source).answers_json)[0]
    assert row["value"] is None
    assert "selected_options" not in row


def test_non_answer_field_ceiling_never_loads_choice_metadata(source):
    result = read(source, requested_fields=frozenset({"review_context"}))
    assert result.answers_json is None
    source.manager.select_related.assert_not_called()


def test_complete_answer_bound_is_not_silently_truncated(source):
    source.query.__getitem__.side_effect = lambda _bounds: [source.row] * 501
    with pytest.raises(ProgrammeReviewUnavailableError):
        read(source)
