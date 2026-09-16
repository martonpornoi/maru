"""Database-free proof of exact file admission, integrity and disclosure ordering."""

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace as Namespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest

from maru.applications import programme_file_queries as files
from maru.applications import programme_review_file_queries as review
from maru.applications.programme_reference_sources import (
    ProgrammeAnswerReferenceRequest,
)
from maru.applications.programme_review_queries import ProgrammeReviewReadRequest

PDF = b"%PDF-1.7\nSynthetic private bytes\n%%EOF\n"


@pytest.fixture
def request_scope():
    return ProgrammeAnswerReferenceRequest(*(uuid4() for _ in range(6)), "test")


@pytest.fixture
def custody(monkeypatch, request_scope):
    row = Namespace(
        id=uuid4(),
        organization_id=request_scope.organization_id,
        edition_id=request_scope.edition_id,
        proposal_id=request_scope.proposal_id,
        question_id=request_scope.question_id,
        actor_id=uuid4(),
        file_receipt_id=uuid4(),
    )
    row.file_receipt = Namespace(
        organization_id=row.organization_id,
        edition_id=row.edition_id,
        account_id=row.actor_id,
        status="clean",
        media_type="application/pdf",
        storage_key=f"programme-db/{row.id}",
        scanner_receipt="clamav-instream@1",
        size_bytes=len(PDF),
        sha256=hashlib.sha256(PDF).hexdigest(),
    )
    manager = Mock()
    manager.select_related.return_value.filter.return_value.first.return_value = row
    monkeypatch.setattr(files, "ProgrammeFileIntake", Namespace(objects=manager))
    content = Mock()
    content.filter.return_value.values_list.return_value.first.return_value = PDF
    monkeypatch.setattr(files, "ProgrammeFileContent", Namespace(objects=content))
    return Namespace(row=row, manager=manager, content=content)


def metadata_arguments(scope, custody):
    return {
        "organization_id": scope.organization_id,
        "edition_id": scope.edition_id,
        "proposal_id": scope.proposal_id,
        "question_id": scope.question_id,
        "value": str(custody.row.file_receipt_id),
        "answer_version": 8,
    }


def test_metadata_binds_exact_purpose_without_viewer_uploader_equality(
    request_scope, custody
):
    assert custody.row.actor_id != request_scope.actor_id
    assert files._metadata(**metadata_arguments(request_scope, custody)) is custody.row
    custody.manager.select_related.assert_called_once_with("file_receipt")
    custody.manager.select_related.return_value.filter.assert_called_once_with(
        organization_id=request_scope.organization_id,
        edition_id=request_scope.edition_id,
        proposal_id=request_scope.proposal_id,
        question_id=request_scope.question_id,
        file_receipt_id=custody.row.file_receipt_id,
        source_version__lt=8,
    )
    custody.content.filter.assert_not_called()


@pytest.mark.parametrize(
    "value", [None, 4, {}, "invalid", str(UUID(int=0)), uuid4().hex]
)
def test_malformed_reference_is_denied_before_custody_lookup(
    request_scope, custody, value
):
    args = metadata_arguments(request_scope, custody) | {"value": value}
    with pytest.raises(files.Denied):
        files._metadata(**args)
    custody.manager.select_related.assert_not_called()


@pytest.mark.parametrize("version", [None, True, 0, 1, "2"])
def test_invalid_answer_evidence_never_queries_custody(request_scope, custody, version):
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files._metadata(
            **(metadata_arguments(request_scope, custody) | {"answer_version": version})
        )
    custody.manager.select_related.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", uuid4()),
        ("edition_id", uuid4()),
        ("account_id", uuid4()),
        ("status", "pending"),
        ("media_type", "text/html"),
        ("storage_key", "outside/key"),
        ("scanner_receipt", "test-clean"),
        ("size_bytes", 0),
        ("size_bytes", True),
        ("size_bytes", files.MAX_PROGRAMME_FILE_BYTES + 1),
        ("sha256", "A" * 64),
        ("sha256", "a" * 63),
        ("sha256", None),
    ],
)
def test_invalid_metadata_is_unavailable_without_bytes(
    request_scope, custody, field, value
):
    setattr(custody.row.file_receipt, field, value)
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files._metadata(**metadata_arguments(request_scope, custody))
    custody.content.filter.assert_not_called()


def test_missing_intake_is_unavailable(request_scope, custody):
    query = custody.manager.select_related.return_value.filter.return_value
    query.first.return_value = None
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files._metadata(**metadata_arguments(request_scope, custody))


@pytest.mark.parametrize("payload", [PDF, memoryview(PDF)])
def test_bytes_are_exact_and_scoped(custody, payload):
    custody.content.filter.return_value.values_list.return_value.first.return_value = (
        payload
    )
    assert files._bytes(custody.row) == PDF
    row = custody.row
    custody.content.filter.assert_called_once_with(
        intake_id=row.id,
        intake__organization_id=row.organization_id,
        intake__edition_id=row.edition_id,
        intake__proposal_id=row.proposal_id,
        intake__question_id=row.question_id,
        intake__file_receipt_id=row.file_receipt_id,
    )
    custody.content.filter.return_value.values_list.assert_called_once_with(
        "payload", flat=True
    )


@pytest.mark.parametrize(
    "payload", [None, "private text", bytearray(PDF), b"", PDF[:-1], b"X" * len(PDF)]
)
def test_missing_changed_or_wrongly_typed_bytes_never_release(custody, payload):
    custody.content.filter.return_value.values_list.return_value.first.return_value = (
        payload
    )
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files._bytes(custody.row)


def test_empty_metadata_and_empty_download_do_not_look_up_files(request_scope, custody):
    args = metadata_arguments(request_scope, custody) | {"value": None}
    result = files._projection(
        source="source", label="Supporting document", include_bytes=False, **args
    )
    assert not result.present
    assert result.size_bytes is None
    assert result.data is None
    with pytest.raises(files.ProgrammeFileUnavailableError):
        files._projection(
            source="source", label="Supporting document", include_bytes=True, **args
        )
    custody.manager.select_related.assert_not_called()
    custody.content.filter.assert_not_called()


@pytest.mark.parametrize("include_bytes", [False, True])
def test_projection_minimizes_private_data_and_only_explicitly_loads_bytes(
    request_scope, custody, include_bytes
):
    result = files._projection(
        source="sensitive source",
        label="Document",
        include_bytes=include_bytes,
        **metadata_arguments(request_scope, custody),
    )
    assert result.present
    assert result.size_bytes == len(PDF)
    assert result.data == (PDF if include_bytes else None)
    assert custody.content.filter.call_count == int(include_bytes)
    assert "sensitive source" not in repr(result)
    assert "Synthetic private bytes" not in repr(result)
    assert not hasattr(result, "storage_key")
    assert not hasattr(result, "sha256")
    assert not hasattr(result, "receipt_id")


@pytest.fixture
def self_query(monkeypatch, request_scope, custody):
    answer = Namespace(
        question=Namespace(
            question_id=request_scope.question_id,
            field_type="safe_file",
            label="Document",
        ),
        value=str(custody.row.file_receipt_id),
        resulting_version=8,
    )
    source = Namespace(answers=(answer,))
    admitted = Mock(return_value=source)
    scope = Mock(return_value="scope")
    audit = Mock()
    monkeypatch.setattr(files, "_self_source", admitted)
    monkeypatch.setattr(files, "_scope", scope)
    monkeypatch.setattr(
        files,
        "_audit_inputs",
        Mock(return_value=(request_scope.correlation_id, "test")),
    )
    monkeypatch.setattr(files, "_append_sensitive_read", audit)
    return Namespace(
        source=source, answer=answer, admitted=admitted, scope=scope, audit=audit
    )


@pytest.mark.parametrize("sealed", [False, True])
@pytest.mark.parametrize("include_bytes", [False, True])
def test_self_reader_repeats_source_and_audits_exact_purpose(
    request_scope, custody, self_query, sealed, include_bytes
):
    revision_id = uuid4() if sealed else None
    result = files.get_self_programme_file.__wrapped__(
        request=request_scope, revision_id=revision_id, include_bytes=include_bytes
    )
    assert result.source is self_query.source
    assert result.data == (PDF if include_bytes else None)
    assert self_query.admitted.call_count == 2
    assert self_query.admitted.call_args.kwargs == {}
    assert self_query.admitted.call_args.args[:2] == (request_scope, revision_id)
    assert self_query.scope.call_args.kwargs["fields"] == (
        files._FROZEN_FIELDS if sealed else files._FIELDS
    )
    audit = self_query.audit.call_args.kwargs
    assert audit["operation"].endswith(
        "file_download" if include_bytes else "file_reference"
    )
    assert audit["target_id"] == request_scope.proposal_id
    assert "data" not in audit
    assert "sha256" not in audit


@pytest.mark.parametrize("fault", ["denied", "missing", "duplicate", "wrong_type"])
def test_self_denial_precedes_identifying_lookup(
    request_scope, custody, self_query, fault
):
    if fault == "denied":
        self_query.admitted.side_effect = files.Denied
    elif fault == "missing":
        self_query.source.answers = ()
    elif fault == "duplicate":
        self_query.source.answers *= 2
    else:
        self_query.answer.question.field_type = "person_reference"
    with pytest.raises(files.Denied):
        files.get_self_programme_file.__wrapped__(
            request=request_scope, include_bytes=True
        )
    custody.manager.select_related.assert_not_called()
    custody.content.filter.assert_not_called()
    self_query.audit.assert_not_called()


@pytest.mark.parametrize("fault", ["source", "authority", "audit"])
def test_self_late_failures_never_return_prepared_bytes(
    request_scope, custody, self_query, fault
):
    if fault == "source":
        self_query.admitted.side_effect = [self_query.source, Namespace(answers=())]
    elif fault == "authority":
        self_query.scope.side_effect = files.Denied
    else:
        self_query.audit.side_effect = files.Denied
    with pytest.raises(files.Denied):
        files.get_self_programme_file.__wrapped__(
            request=request_scope, include_bytes=True
        )
    custody.content.filter.assert_called_once()


@pytest.mark.parametrize("bad", [None, object(), "request"])
def test_self_request_shape_is_closed(self_query, bad):
    with pytest.raises(files.Denied):
        files.get_self_programme_file.__wrapped__(request=bad)
    self_query.admitted.assert_not_called()


@pytest.mark.parametrize("bad", [1, None, "true"])
def test_byte_flag_is_exact_boolean(request_scope, self_query, bad):
    with pytest.raises(files.Denied):
        files.get_self_programme_file.__wrapped__(
            request=request_scope, include_bytes=bad
        )
    self_query.admitted.assert_not_called()


@pytest.fixture
def review_query(monkeypatch, request_scope, custody):
    request = ProgrammeReviewReadRequest(
        request_scope.actor_id,
        request_scope.organization_id,
        request_scope.edition_id,
        uuid4(),
        review.REVIEW,
        frozenset({"review_answers"}),
        uuid4(),
        "test",
    )
    case_id, assignment_id = uuid4(), uuid4()
    answer = {
        "key": "supporting-document",
        "label": "Document",
        "type": "safe_file",
        "value": str(custody.row.file_receipt_id),
    }
    detail = review.ProgrammeReviewDetail(
        case_id, 5, None, json.dumps([answer]), None, None
    )
    source = review._ReviewSource(
        detail, uuid4(), uuid4(), 0, assignment_id, request_scope.proposal_id
    )
    admitted = Mock(return_value=source)
    binding = Mock(return_value=(request_scope.question_id, 8))
    audit = Mock()
    monkeypatch.setattr(review, "_source", admitted)
    monkeypatch.setattr(review, "_answer_binding", binding)
    monkeypatch.setattr(review, "_audit", audit)
    return Namespace(
        request=request,
        case_id=case_id,
        assignment_id=assignment_id,
        source=source,
        admitted=admitted,
        binding=binding,
        audit=audit,
        answer=answer,
    )


def review_args(query):
    return {
        "request": query.request,
        "case_id": query.case_id,
        "question_key": "supporting-document",
        "assignment_id": query.assignment_id,
    }


@pytest.mark.parametrize("role", [review.REVIEW, review.MODERATE, review.DECIDE])
@pytest.mark.parametrize("include_bytes", [False, True])
def test_review_roles_repeat_exact_source_before_file_audit(
    custody, review_query, role, include_bytes
):
    args = review_args(review_query)
    args["request"] = replace(review_query.request, capability_code=role)
    if role != review.REVIEW:
        args["assignment_id"] = None
    result = review.get_programme_review_file.__wrapped__(
        **args, include_bytes=include_bytes
    )
    assert result.data == (PDF if include_bytes else None)
    assert review_query.admitted.call_count == 2
    assert review_query.binding.call_args.args[3] == review_query.answer["value"]
    assert review_query.audit.call_args.args[1] == (
        "file_download" if include_bytes else "file_reference"
    )


@pytest.mark.parametrize(
    "fault",
    ["role", "fields", "missing_assignment", "extra_assignment", "key", "long_key"],
)
def test_invalid_review_purpose_precedes_source_and_file_lookup(
    custody, review_query, fault
):
    args = review_args(review_query)
    if fault == "role":
        args["request"] = replace(
            review_query.request, capability_code="applications.manage_review"
        )
    elif fault == "fields":
        args["request"] = replace(
            review_query.request, requested_fields=frozenset({"review_context"})
        )
    elif fault == "missing_assignment":
        args["assignment_id"] = None
    elif fault == "extra_assignment":
        args["request"] = replace(review_query.request, capability_code=review.MODERATE)
    else:
        args["question_key"] = "bad key" if fault == "key" else "a" * 81
    with pytest.raises(files.Denied):
        review.get_programme_review_file.__wrapped__(**args)
    review_query.admitted.assert_not_called()
    review_query.binding.assert_not_called()
    custody.manager.select_related.assert_not_called()


@pytest.mark.parametrize("fault", ["denied", "missing", "duplicate", "wrong_type"])
def test_review_admission_or_omission_precedes_file_lookup(
    custody, review_query, fault
):
    if fault == "denied":
        review_query.admitted.side_effect = files.Denied
    else:
        answer = review_query.answer.copy()
        rows = (
            []
            if fault == "missing"
            else [answer, answer]
            if fault == "duplicate"
            else [answer | {"type": "text"}]
        )
        detail = replace(review_query.source.detail, answers_json=json.dumps(rows))
        review_query.admitted.return_value = replace(review_query.source, detail=detail)
    with pytest.raises(files.Denied):
        review.get_programme_review_file.__wrapped__(
            **review_args(review_query), include_bytes=True
        )
    review_query.binding.assert_not_called()
    custody.manager.select_related.assert_not_called()


@pytest.mark.parametrize("include_bytes", [False, True])
def test_empty_review_answer_never_loads_custody(custody, review_query, include_bytes):
    detail = replace(
        review_query.source.detail,
        answers_json=json.dumps([review_query.answer | {"value": None}]),
    )
    review_query.admitted.return_value = replace(review_query.source, detail=detail)
    if include_bytes:
        with pytest.raises(files.ProgrammeFileUnavailableError):
            review.get_programme_review_file.__wrapped__(
                **review_args(review_query), include_bytes=True
            )
    else:
        assert not review.get_programme_review_file.__wrapped__(
            **review_args(review_query)
        ).present
        review_query.audit.assert_called_once()
    review_query.binding.assert_not_called()
    custody.manager.select_related.assert_not_called()


@pytest.mark.parametrize("fault", ["source", "audit"])
def test_review_late_denial_never_returns_bytes(custody, review_query, fault):
    if fault == "source":
        review_query.admitted.side_effect = [
            review_query.source,
            replace(review_query.source, policy_id=uuid4()),
        ]
    else:
        review_query.audit.side_effect = files.Denied
    with pytest.raises(files.Denied):
        review.get_programme_review_file.__wrapped__(
            **review_args(review_query), include_bytes=True
        )
    custody.content.filter.assert_called_once()


@pytest.mark.parametrize("sealed", [False, True])
def test_real_self_source_uses_exact_fields_and_relationship(
    monkeypatch, request_scope, sealed
):
    revision_id = uuid4() if sealed else None
    fields = files._FROZEN_FIELDS if sealed else files._FIELDS
    summary = object()
    projection = Namespace(
        summary=summary,
        requested_fields=fields,
        revision=Namespace(revision_id=revision_id),
    )
    scope = Mock(return_value="independent view scope")
    same = Mock()
    current = Mock(return_value=projection)
    frozen = Mock(return_value=projection)
    monkeypatch.setattr(files, "_scope", scope)
    monkeypatch.setattr(files, "_same_scope", same)
    monkeypatch.setattr(files.queries, "get_self_programme_proposal_detail", current)
    monkeypatch.setattr(files.personal, "get_self_programme_frozen_revision", frozen)
    assert files._self_source(request_scope, revision_id, files._DEFAULT) is projection
    scope.assert_called_once_with(request_scope, files._DEFAULT, fields=fields)
    same.assert_called_once_with(summary, "independent view scope")
    assert current.call_count == int(not sealed)
    assert frozen.call_count == int(sealed)
    call = (frozen if sealed else current).call_args.kwargs
    assert call["actor_id"] == request_scope.actor_id
    assert call["organization_id"] == request_scope.organization_id
    assert call["edition_id"] == request_scope.edition_id
    assert call["proposal_id"] == request_scope.proposal_id
    assert "question_id" not in call
    if sealed:
        assert call["revision_id"] == revision_id
    else:
        assert call["requested_fields"] == fields


@pytest.mark.parametrize("fault", ["fields", "summary", "seal", "relationship"])
def test_actual_self_source_rejects_incoherent_owner_projection(
    monkeypatch, request_scope, fault
):
    projection = Namespace(
        summary=object(),
        requested_fields=files._FIELDS,
        revision=Namespace(revision_id=uuid4()),
    )
    if fault == "fields":
        projection.requested_fields = frozenset({"proposal_summary"})
    if fault == "summary":
        projection.summary = None
    monkeypatch.setattr(files, "_scope", Mock())
    monkeypatch.setattr(
        files,
        "_same_scope",
        Mock(side_effect=files.Denied if fault == "relationship" else None),
    )
    monkeypatch.setattr(
        files.queries,
        "get_self_programme_proposal_detail",
        Mock(return_value=projection),
    )
    monkeypatch.setattr(
        files.personal,
        "get_self_programme_frozen_revision",
        Mock(return_value=projection),
    )
    with pytest.raises(files.Denied):
        files._self_source(
            request_scope, uuid4() if fault == "seal" else None, files._DEFAULT
        )


@pytest.mark.parametrize("row", [None, (uuid4(), None), (uuid4(), True)])
def test_review_binding_requires_real_version(monkeypatch, review_query, row):
    manager = Mock()
    manager.filter.return_value.values_list.return_value.first.return_value = row
    monkeypatch.setattr(
        review, "ProgrammeProposalRevisionAnswer", Namespace(objects=manager)
    )
    # Call the original helper; the orchestration fixture replaces its module name.
    with pytest.raises(files.ProgrammeFileUnavailableError):
        ORIGINAL_BINDING(
            review_query.request,
            review_query.source,
            "supporting-document",
            review_query.answer["value"],
        )


def test_review_binding_selects_only_exact_seal_question_and_answer(
    monkeypatch, review_query
):
    manager = Mock()
    question_id = uuid4()
    manager.filter.return_value.values_list.return_value.first.return_value = (
        question_id,
        8,
    )
    monkeypatch.setattr(
        review, "ProgrammeProposalRevisionAnswer", Namespace(objects=manager)
    )
    assert ORIGINAL_BINDING(
        review_query.request,
        review_query.source,
        "supporting-document",
        review_query.answer["value"],
    ) == (question_id, 8)
    filters = manager.filter.call_args.kwargs
    assert filters["organization_id"] == review_query.request.organization_id
    assert filters["edition_id"] == review_query.request.edition_id
    assert filters["revision_id"] == review_query.source.revision_id
    assert filters["revision__proposal_id"] == review_query.source.proposal_id
    assert filters["question_type"] == "safe_file"
    assert filters["question__field_type"] == "safe_file"
    assert filters["question_key"] == "supporting-document"
    assert filters["question__key"] == "supporting-document"
    assert filters["answer_revision__value"] == review_query.answer["value"]
    assert (
        filters["answer_revision__submission__programme_proposal__id"]
        == review_query.source.proposal_id
    )


ORIGINAL_BINDING = review._answer_binding
