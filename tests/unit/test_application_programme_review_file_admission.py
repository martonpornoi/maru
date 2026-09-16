"""Actual review projection and sensitive admission precede every custody lookup."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.applications import programme_file_queries as files
from maru.applications import programme_review_file_queries as review
from maru.applications import programme_review_queries as queries
from tests.unit import test_application_programme_review_answer_queries as answer_tests

source = answer_tests.source


@pytest.fixture
def world(source, monkeypatch):
    source.question.field_type = source.row.question_type = "safe_file"
    source.row.answer_revision.value = str(UUID(int=40))
    source.case.policy_id = UUID(int=31)
    source.case.proposal_id = UUID(int=32)
    source.assignment.return_value = SimpleNamespace(id=UUID(int=50))
    source.current = Mock(return_value=True)
    source.binding = Mock(return_value=(UUID(int=60), 8))
    source.projection = Mock(return_value="private projection")
    for name, target in (
        (
            "get_programme_review_detail",
            queries.get_programme_review_detail.__wrapped__,
        ),
        ("_locked_scope", source.locked),
        ("load_review_case", Mock(return_value=source.case)),
        ("_detail_assignment", source.assignment),
        ("revision_is_current", source.current),
        ("_audit", source.audit),
        ("_answer_binding", source.binding),
        ("_projection", source.projection),
    ):
        monkeypatch.setattr(review, name, target)
    return source


def read(world, **changes):
    args = {
        "request": world.request,
        "case_id": world.case.id,
        "question_key": "topic",
        "assignment_id": UUID(int=50),
        "include_bytes": True,
    }
    return review.get_programme_review_file.__wrapped__(**(args | changes))


@pytest.mark.parametrize("role", [review.REVIEW, review.MODERATE, review.DECIDE])
def test_real_projection_and_sensitive_authority_precede_download(world, role):
    world.row.classification = "C3"
    assert (
        read(
            world,
            request=replace(world.request, capability_code=role),
            assignment_id=UUID(int=50) if role == review.REVIEW else None,
        )
        == "private projection"
    )
    assert world.sensitive.call_count == 2
    assert world.extra_sensitive.call_count == 2
    world.query.filter.assert_any_call(
        revision_id=world.case.revision_id,
        organization_id=world.request.organization_id,
        edition_id=world.request.edition_id,
        question_key__in=["topic"],
    )
    assert world.projection.call_args.kwargs["proposal_id"] == world.case.proposal_id
    assert world.projection.call_args.kwargs["value"] == str(UUID(int=40))
    assert world.audit.call_args.args[1] == "file_download"


@pytest.mark.parametrize("role", [review.REVIEW, review.MODERATE, review.DECIDE])
def test_anonymous_exclusion_and_direct_reader_refuse_before_file_binding(world, role):
    world.case.policy.stages[0]["anonymous"] = True
    with pytest.raises(files.Denied):
        read(
            world,
            request=replace(world.request, capability_code=role),
            assignment_id=UUID(int=50) if role == review.REVIEW else None,
        )
    world.query.exclude.assert_called_once_with(
        question_type__in=queries._ANONYMOUS_OMISSIONS
    )
    assert "safe_file" in queries._ANONYMOUS_OMISSIONS
    world.binding.assert_not_called()
    world.projection.assert_not_called()


@pytest.mark.parametrize(
    "guard", ["locked", "assignment", "sensitive", "extra_sensitive"]
)
def test_actual_admission_failure_precedes_any_file_lookup(world, guard):
    world.row.classification = "C3"
    getattr(world, guard).side_effect = files.Denied
    with pytest.raises(files.Denied):
        read(world)
    world.binding.assert_not_called()
    world.projection.assert_not_called()


@pytest.mark.parametrize(
    "fault",
    ["old_seal", "wrong_assignment", "wrong_case", "wrong_version", "source_audit"],
)
def test_actual_source_fences_precede_custody(monkeypatch, world, fault):
    if fault == "old_seal":
        world.current.return_value = False
    elif fault == "wrong_assignment":
        world.assignment.return_value = SimpleNamespace(id=UUID(int=99))
    elif fault in {"wrong_case", "wrong_version"}:
        detail = queries.ProgrammeReviewDetail(
            UUID(int=99) if fault == "wrong_case" else world.case.id,
            4 if fault == "wrong_version" else world.case.version,
            None,
            "[]",
            None,
            None,
        )
        monkeypatch.setattr(
            review, "get_programme_review_detail", Mock(return_value=detail)
        )
    else:
        world.audit.side_effect = DatabaseError
    with pytest.raises((files.Denied, DatabaseError)):
        read(world, case_id=UUID(int=20))
    world.binding.assert_not_called()
    world.projection.assert_not_called()


def test_anonymity_change_after_preparation_withholds_bytes(world):
    def prepared(**_kwargs):
        world.case.policy.stages[0]["anonymous"] = True
        return "must not release"

    world.projection.side_effect = prepared
    with pytest.raises(files.Denied):
        read(world)
    world.projection.assert_called_once()
