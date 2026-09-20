"""Keep archive file authority separate from current source and byte custody."""

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_exit_file_queries as archive
from maru.applications.programme_file_queries import ProgrammeFileProjection
from maru.applications.programme_review_authorization import DECIDE
from maru.applications.programme_review_queries import (
    ProgrammeReviewDetail,
    ProgrammeReviewReadRequest,
)
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture
def source(monkeypatch):
    request = ProgrammeReviewReadRequest(
        *(UUID(int=i) for i in range(1, 5)),
        DECIDE,
        frozenset({"review_answers"}),
        UUID(int=5),
        "programme-exit",
    )
    case_id, file_id, question_id = (UUID(int=i) for i in range(6, 9))
    answer = {
        "key": "supporting-file",
        "type": "safe_file",
        "classification": "C3",
        "label": "Restricted supporting file",
        "value": str(file_id),
    }
    detail = ProgrammeReviewDetail(case_id, 3, None, json.dumps([answer]), None, None)
    case = SimpleNamespace(
        version=3,
        revision_id=UUID(int=9),
        policy_id=UUID(int=10),
        stage=0,
        proposal_id=UUID(int=11),
        policy=SimpleNamespace(stages=[{"anonymous": False}]),
    )
    reader, loader = Mock(return_value=detail), Mock(return_value=case)
    monkeypatch.setattr(archive, "get_programme_review_detail", reader)
    monkeypatch.setattr(archive, "load_review_case", loader)
    purpose, audit = Mock(), Mock()
    monkeypatch.setattr(archive, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(archive, "_audit", audit)
    binding = Mock(return_value=(question_id, 2))
    monkeypatch.setattr(archive, "_answer_binding", binding)
    data = b"%PDF-1.7\nSynthetic private document\n%%EOF\n"
    projection = Mock(
        return_value=ProgrammeFileProjection(
            None, answer["label"], present=True, size_bytes=len(data), data=data
        )
    )
    receipt = SimpleNamespace(
        size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest()
    )
    metadata = Mock(return_value=SimpleNamespace(file_receipt=receipt))
    monkeypatch.setattr(archive, "_projection", projection)
    monkeypatch.setattr(archive, "_metadata", metadata)
    return SimpleNamespace(
        read=archive.load_programme_exit_review_file.__wrapped__,
        args={"request": request, "case_id": case_id, "question_key": answer["key"]},
        answer=answer,
        detail=detail,
        case=case,
        data=data,
        file_id=file_id,
        question_id=question_id,
        reader=reader,
        loader=loader,
        purpose=purpose,
        audit=audit,
        binding=binding,
        projection=projection,
        metadata=metadata,
        receipt=receipt,
    )


def test_exact_file_lineage_repeated_authority_and_integrity(source):
    result = source.read(**source.args)
    assert result.file_id == source.file_id
    assert result.case_id == source.args["case_id"]
    assert result.revision_id == source.case.revision_id
    assert result.question_id == source.question_id
    assert result.answer_version == 2
    assert result.data == source.data
    assert result.sha256 == hashlib.sha256(source.data).hexdigest()
    assert source.reader.call_count == source.purpose.call_count == 2
    source.metadata.assert_called_once_with(
        organization_id=source.args["request"].organization_id,
        edition_id=source.args["request"].edition_id,
        proposal_id=source.case.proposal_id,
        question_id=source.question_id,
        value=str(source.file_id),
        answer_version=2,
    )
    assert source.projection.call_args.kwargs["include_bytes"] is True
    assert source.audit.call_args.args[1] == "exit_file"
    assert str(source.file_id) not in repr(result)
    assert "Synthetic private" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.data = b"changed"


@pytest.mark.parametrize("key", ["", "A", "a/b", "a--b", "a" * 81, None, 3])
def test_bad_question_key_denied_before_source(source, key):
    source.args["question_key"] = key
    with pytest.raises(archive.Denied):
        source.read(**source.args)
    source.reader.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"capability_code": "applications.review_programme"},
        {"department_id": None},
        {"requested_fields": frozenset()},
        {"requested_fields": frozenset({"review_answers", "review_context"})},
    ],
)
def test_exact_decider_field_scope_required(source, change):
    source.args["request"] = replace(source.args["request"], **change)
    with pytest.raises(archive.Denied):
        source.read(**source.args)
    source.reader.assert_not_called()


@pytest.mark.parametrize("value", ["{", "null", "{}", "[null]", "[]"])
def test_malformed_or_withheld_answers_never_lookup_custody(source, value):
    source.reader.return_value = replace(source.detail, answers_json=value)
    with pytest.raises(archive.Denied):
        source.read(**source.args)
    source.binding.assert_not_called()
    source.projection.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"type": "text"},
        {"classification": "C4"},
        {"label": None},
        {"key": "another-question"},
    ],
)
def test_unavailable_answer_ceiling_never_lookup_custody(source, change):
    source.reader.return_value = replace(
        source.detail, answers_json=json.dumps([{**source.answer, **change}])
    )
    with pytest.raises(archive.Denied):
        source.read(**source.args)
    source.binding.assert_not_called()


def test_duplicate_answer_is_not_arbitrarily_selected(source):
    source.reader.return_value = replace(
        source.detail, answers_json=json.dumps([source.answer, source.answer])
    )
    with pytest.raises(archive.Denied):
        source.read(**source.args)
    source.binding.assert_not_called()


def test_cleared_answer_is_unavailable_without_custody_lookup(source):
    source.reader.return_value = replace(
        source.detail, answers_json=json.dumps([{**source.answer, "value": None}])
    )
    with pytest.raises(archive.ProgrammeFileUnavailableError):
        source.read(**source.args)
    source.binding.assert_not_called()


def test_anonymity_denies_before_answer_binding_or_custody(source):
    source.case.policy.stages[0]["anonymous"] = True
    with pytest.raises(archive.Denied):
        source.read(**source.args)
    source.binding.assert_not_called()
    source.projection.assert_not_called()


@pytest.mark.parametrize("final", [False, True])
def test_archive_authority_revocation_never_returns_bytes(source, final):
    source.purpose.side_effect = (
        [None, ProgrammeAuthorizationDeniedError()]
        if final
        else ProgrammeAuthorizationDeniedError
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        source.read(**source.args)
    source.audit.assert_not_called()


def test_source_change_after_read_fails_closed(source):
    source.reader.side_effect = [source.detail, replace(source.detail, version=4)]
    with pytest.raises(archive.Denied):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize("change", [{"sha256": "0" * 64}, {"size_bytes": 1}])
def test_final_custody_integrity_must_still_agree(source, change):
    for name, value in change.items():
        setattr(source.receipt, name, value)
    with pytest.raises(archive.ProgrammeFileUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize("data", [None, b"short"])
def test_unavailable_or_inconsistent_projection_fails(source, data):
    source.projection.return_value = replace(source.projection.return_value, data=data)
    with pytest.raises(archive.ProgrammeFileUnavailableError):
        source.read(**source.args)


@pytest.mark.parametrize(
    "boundary", ["reader", "binding", "projection", "metadata", "audit"]
)
def test_failure_at_any_mandatory_boundary_does_not_return_data(source, boundary):
    getattr(source, boundary).side_effect = RuntimeError("synthetic boundary failure")
    with pytest.raises(RuntimeError, match="synthetic boundary failure"):
        source.read(**source.args)
