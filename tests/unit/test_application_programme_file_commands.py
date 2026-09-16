"""Database-free ordering, exact retry and atomic-custody orchestration."""

import hashlib
from contextlib import nullcontext
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from maru.applications import programme_file_commands as files
from maru.applications.programme_file_preparation import PreparedProgrammeFile
from maru.applications.programme_reference_sources import (
    ProgrammeAnswerReferenceIntent,
    ProgrammeAnswerReferenceRequest,
)

PDF = b"%PDF-1.7\nSynthetic unit payload only.\n%%EOF\n"


@pytest.fixture
def request_scope():
    return ProgrammeAnswerReferenceRequest(
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        "test",
    )


@pytest.fixture
def intent():
    return ProgrammeAnswerReferenceIntent(3, 2, 1, uuid4())


@pytest.fixture
def prepared():
    return PreparedProgrammeFile(
        PDF,
        hashlib.sha256(PDF).hexdigest(),
        len(PDF),
        "application/pdf",
        "clamav-instream@1",
        timezone.now(),
    )


@pytest.fixture
def orchestration(monkeypatch, prepared):
    events = []
    result = object()
    monkeypatch.setattr(files, "connection", SimpleNamespace(in_atomic_block=False))
    monkeypatch.setattr(files, "_preflight", lambda *_args: events.append("admit"))
    monkeypatch.setattr(
        files, "_scanner_configuration", lambda: events.append("configured")
    )

    def scan(data):
        assert data == PDF
        events.append("scan")
        return prepared

    def persist(arguments, value, authorizer):
        assert value is prepared
        events.append("persist")
        return result

    monkeypatch.setattr(files.preparation, "prepare_programme_pdf", scan)
    monkeypatch.setattr(files, "_persist", persist)
    audit = Mock()
    monkeypatch.setattr(files, "_append_failure_audit_best_effort", audit)
    return events, result, audit


def test_upload_admits_before_one_body_read_then_scans_before_any_persistence(
    request_scope,
    intent,
    orchestration,
):
    events, result, audit = orchestration

    def read():
        events.append("body")
        return PDF

    assert (
        files.upload_and_use_programme_file(
            request=request_scope,
            intent=intent,
            read_bytes=read,
        )
        is result
    )
    assert events == ["admit", "configured", "body", "scan", "persist"]
    audit.assert_not_called()


@pytest.mark.parametrize("phase", ["admit", "configured", "body", "scan", "persist"])
def test_failure_never_advances_to_later_phase_or_leaks_bytes_into_audit(
    monkeypatch,
    request_scope,
    intent,
    orchestration,
    phase,
):
    events, _, audit = orchestration

    def fail(*args, **kwargs):
        events.append(phase)
        raise files.preparation.ProgrammeFileUnavailableError("Unavailable")

    def reader():
        return events.append("body") or PDF

    targets = {
        "admit": (files, "_preflight"),
        "configured": (files, "_scanner_configuration"),
        "scan": (files.preparation, "prepare_programme_pdf"),
        "persist": (files, "_persist"),
    }
    if phase == "body":
        reader = fail
    else:
        monkeypatch.setattr(*targets[phase], fail)
    with pytest.raises(files.preparation.ProgrammeFileUnavailableError):
        files.upload_and_use_programme_file(
            request=request_scope, intent=intent, read_bytes=reader
        )
    order = ["admit", "configured", "body", "scan", "persist"]
    assert events == order[: order.index(phase) + 1]
    audit.assert_called_once()
    assert PDF.decode() not in repr(audit.call_args)
    assert audit.call_args.kwargs["actor_id"] == request_scope.actor_id
    assert audit.call_args.kwargs["operation"] == "proposal_answer_revised"


def test_enclosing_transaction_is_refused_before_authorization_or_body(
    monkeypatch,
    request_scope,
    intent,
    orchestration,
):
    events, _, _ = orchestration
    monkeypatch.setattr(files, "connection", SimpleNamespace(in_atomic_block=True))
    reader = Mock()
    with pytest.raises(files.preparation.ProgrammeFileUnavailableError):
        files.upload_and_use_programme_file(
            request=request_scope, intent=intent, read_bytes=reader
        )
    assert not events
    reader.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_version", 0),
        ("expected_version", True),
        ("expected_version", 2**63 - 1),
        ("expected_call_version", 0),
        ("expected_definition_version", "1"),
        ("retry_key", "wrong"),
    ],
)
def test_invalid_original_intent_is_rejected_before_admission_or_body(
    request_scope,
    intent,
    orchestration,
    field,
    value,
):
    events, _, _ = orchestration
    reader = Mock()
    with pytest.raises(
        (
            files.ApplicationsProgrammeAuthorizationDeniedError,
            files._Unavailable,
            ValueError,
            ValidationError,
        )
    ):
        files.upload_and_use_programme_file(
            request=request_scope,
            intent=replace(intent, **{field: value}),
            read_bytes=reader,
        )
    assert not events
    reader.assert_not_called()


@pytest.fixture
def preflight(monkeypatch, request_scope, intent):
    now = timezone.now()
    context = SimpleNamespace(
        summary=SimpleNamespace(aggregate_version=3, state="draft", call_id=uuid4()),
        call_version=2,
        definition_version=1,
        planning=True,
        call_status="active",
        opens_at=now - timedelta(days=1),
        edit_until=now + timedelta(days=1),
    )
    answer = SimpleNamespace(
        question=SimpleNamespace(
            question_id=request_scope.question_id, field_type="safe_file"
        )
    )
    source = (context, SimpleNamespace(answers=(answer,)))
    replay, question, capacity = Mock(return_value=None), Mock(), Mock()
    monkeypatch.setattr(files, "_replay", replay)
    monkeypatch.setattr(files, "_source", Mock(return_value=source))
    monkeypatch.setattr(files, "_question", question)
    monkeypatch.setattr(files, "_capacity", capacity)
    return source, replay, question, capacity


def test_preflight_repeats_source_and_uses_only_metadata_capacity(
    request_scope, intent, preflight
):
    source, _, question, capacity = preflight
    arguments = files._arguments(request_scope, intent)
    files._preflight.__wrapped__(request_scope, intent, arguments, object())
    assert files._source.call_count == 2
    question.assert_called_once_with(arguments, source[0].summary.call_id, lock=False)
    capacity.assert_called_once_with(arguments, additional_bytes=1)


@pytest.mark.parametrize(
    "change",
    [
        "state",
        "version",
        "call",
        "definition",
        "planning",
        "closed",
        "expired",
        "question",
        "kind",
    ],
)
def test_preflight_rejects_stale_or_inapplicable_source_before_body(
    request_scope, intent, preflight, change
):
    source, _, _, _ = preflight
    context, detail = source
    if change == "state":
        context.summary.state = "sealed"
    elif change == "version":
        context.summary.aggregate_version = 4
    elif change == "call":
        context.call_version = 3
    elif change == "definition":
        context.definition_version = 2
    elif change == "planning":
        context.planning = False
    elif change == "closed":
        context.call_status = "retired"
    elif change == "expired":
        context.edit_until = timezone.now() - timedelta(seconds=1)
    elif change == "question":
        detail.answers = ()
    else:
        detail.answers[0].question.field_type = "short_text"
    with pytest.raises(
        (
            files.commands.ApplicationsProgrammeVersionConflictError,
            files.ApplicationsProgrammeAuthorizationDeniedError,
        )
    ):
        files._preflight.__wrapped__(
            request_scope, intent, files._arguments(request_scope, intent), object()
        )


def test_used_retry_and_changed_source_abort_preflight(
    monkeypatch, request_scope, intent, preflight
):
    _, replay, _, _ = preflight
    arguments = files._arguments(request_scope, intent)
    replay.return_value = object()
    with pytest.raises(files._Conflict):
        files._preflight.__wrapped__(request_scope, intent, arguments, object())
    files._source.assert_not_called()
    replay.return_value = None
    monkeypatch.setattr(files, "_source", Mock(side_effect=[preflight[0], object()]))
    with pytest.raises(files.ApplicationsProgrammeAuthorizationDeniedError):
        files._preflight.__wrapped__(request_scope, intent, arguments, object())


@pytest.mark.parametrize(
    ("count", "size", "addition", "allowed"),
    [
        (63, 0, 1, True),
        (64, 0, 1, False),
        (0, None, 10, True),
        (1, 64 * 1024 * 1024 - 10, 10, True),
        (1, 64 * 1024 * 1024 - 10, 11, False),
        (1, 64 * 1024 * 1024, 1, False),
    ],
)
def test_exact_retention_quota_boundaries_without_eviction(
    monkeypatch, request_scope, intent, count, size, addition, allowed
):
    manager = Mock()
    manager.filter.return_value.aggregate.return_value = {"count": count, "size": size}
    monkeypatch.setattr(files, "ProgrammeFileIntake", SimpleNamespace(objects=manager))
    arguments = files._arguments(request_scope, intent)
    with nullcontext() if allowed else pytest.raises(files.ProgrammeFileQuotaError):
        files._capacity(arguments, additional_bytes=addition)
    manager.filter.assert_called_once_with(
        organization_id=request_scope.organization_id,
        edition_id=request_scope.edition_id,
        proposal_id=request_scope.proposal_id,
    )
    assert not manager.delete.called


@pytest.fixture
def retained(request_scope, intent, prepared):
    identifier, receipt_id = uuid4(), uuid4()
    return SimpleNamespace(
        id=identifier,
        proposal_id=request_scope.proposal_id,
        question_id=request_scope.question_id,
        source_version=intent.expected_version,
        call_version=intent.expected_call_version,
        definition_version=intent.expected_definition_version,
        file_receipt_id=receipt_id,
        file_receipt=SimpleNamespace(
            id=receipt_id,
            organization_id=request_scope.organization_id,
            edition_id=request_scope.edition_id,
            account_id=request_scope.actor_id,
            status="clean",
            media_type="application/pdf",
            storage_key=f"programme-db/{identifier}",
            scanner_receipt="clamav-instream@1",
            sha256=prepared.sha256,
            size_bytes=prepared.size_bytes,
        ),
    )


@pytest.mark.parametrize(
    "field",
    [
        None,
        "proposal_id",
        "question_id",
        "source_version",
        "call_version",
        "definition_version",
    ],
)
def test_retained_lookup_is_scoped_and_original_intent_cannot_be_substituted(
    monkeypatch, request_scope, intent, retained, field
):
    manager = Mock()
    manager.select_related.return_value.filter.return_value.first.return_value = (
        retained
    )
    monkeypatch.setattr(files, "ProgrammeFileIntake", SimpleNamespace(objects=manager))
    if field:
        setattr(retained, field, 88 if field.endswith("version") else uuid4())
    with pytest.raises(files._Conflict) if field else nullcontext():
        assert files._retained(files._arguments(request_scope, intent)) is retained
    manager.select_related.assert_called_once_with("file_receipt")
    manager.select_related.return_value.filter.assert_called_once_with(
        actor_id=request_scope.actor_id,
        organization_id=request_scope.organization_id,
        edition_id=request_scope.edition_id,
        retry_key=intent.retry_key,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organization_id", None),
        ("edition_id", None),
        ("account_id", None),
        ("status", "rejected"),
        ("media_type", "text/html"),
        ("storage_key", "external/key"),
        ("scanner_receipt", "untrusted"),
    ],
)
def test_retained_receipt_requires_exact_private_custody(
    monkeypatch, request_scope, intent, retained, field, value
):
    manager = Mock()
    manager.select_related.return_value.filter.return_value.first.return_value = (
        retained
    )
    monkeypatch.setattr(files, "ProgrammeFileIntake", SimpleNamespace(objects=manager))
    setattr(retained.file_receipt, field, value)
    with pytest.raises(files._Unavailable):
        files._retained(files._arguments(request_scope, intent))


def test_body_free_result_check_uses_only_original_canonical_receipt(
    monkeypatch, request_scope, intent, retained
):
    events = []
    result = object()
    monkeypatch.setattr(files, "_lock_retry", lambda *_args: events.append("lock"))
    monkeypatch.setattr(
        files, "_retained", lambda *_args: events.append("metadata") or retained
    )
    replay = Mock(return_value=result)
    monkeypatch.setattr(files, "_replay", replay)
    assert (
        files.get_programme_file_upload_result.__wrapped__(
            request=request_scope, intent=intent
        )
        is result
    )
    assert events == ["lock", "metadata"]
    assert replay.call_args.args[1] == retained.file_receipt_id
    replay.return_value = None
    with pytest.raises(files._Unavailable):
        files.get_programme_file_upload_result.__wrapped__(
            request=request_scope, intent=intent
        )


def test_unused_result_check_does_not_create_an_answer(
    monkeypatch, request_scope, intent
):
    monkeypatch.setattr(files, "_lock_retry", Mock())
    monkeypatch.setattr(files, "_retained", Mock(return_value=None))
    monkeypatch.setattr(files, "_replay", Mock(return_value=None))
    answer = Mock()
    monkeypatch.setattr(files.commands, "append_programme_proposal_answer", answer)
    assert (
        files.get_programme_file_upload_result.__wrapped__(
            request=request_scope, intent=intent
        )
        is None
    )
    answer.assert_not_called()


@pytest.mark.parametrize("mismatch", [None, "sha256", "size_bytes"])
def test_concurrent_winner_replay_compares_exact_bytes_before_any_new_custody(
    monkeypatch, request_scope, intent, retained, prepared, mismatch
):
    events = []
    monkeypatch.setattr(files, "_lock_retry", lambda *_args: events.append("lock"))
    monkeypatch.setattr(
        files, "_retained", lambda *_args: events.append("metadata") or retained
    )
    completed = Mock(return_value=object())
    monkeypatch.setattr(files, "_completed", completed)
    manager = Mock()
    monkeypatch.setattr(
        files, "ApplicationFileReceipt", SimpleNamespace(objects=manager)
    )
    if mismatch:
        setattr(
            retained.file_receipt, mismatch, "0" * 64 if mismatch == "sha256" else 1
        )
    with pytest.raises(files._Conflict) if mismatch else nullcontext():
        assert (
            files._persist.__wrapped__(
                files._arguments(request_scope, intent), prepared, object()
            )
            is completed.return_value
        )
    assert events == ["lock", "metadata"]
    assert completed.call_count == (0 if mismatch else 1)
    manager.create.assert_not_called()


def test_digest_is_exactly_the_existing_answer_command_contract(request_scope, intent):
    arguments, receipt_id = files._arguments(request_scope, intent), uuid4()
    assert files._digest(arguments, receipt_id) == files.commands._request_digest(
        action="proposal_answer_revised",
        actor_id=request_scope.actor_id,
        organization_id=request_scope.organization_id,
        edition_id=request_scope.edition_id,
        target_id=request_scope.proposal_id,
        expected_version=3,
        reason="Upload and use this supporting file.",
        source_channel="test",
        values={
            "question_id": request_scope.question_id,
            "value": str(receipt_id),
            "expected_call_version": 2,
            "expected_definition_version": 1,
        },
    )


@pytest.fixture
def fresh_write(monkeypatch, request_scope, intent, prepared):
    events = []
    now = timezone.now()
    definition = SimpleNamespace(
        aggregate_version=2,
        version=1,
        status="active",
        opens_at=now - timedelta(days=1),
        applicant_edit_until=now + timedelta(days=1),
    )
    proposal = SimpleNamespace(
        id=request_scope.proposal_id,
        submission_id=uuid4(),
        call_id=uuid4(),
        state="draft",
        submission=SimpleNamespace(aggregate_version=3),
        call=SimpleNamespace(definition=definition),
    )
    scope = SimpleNamespace(
        proposal_id=proposal.id,
        submission_id=proposal.submission_id,
        call_id=proposal.call_id,
        relationship="lead",
        accepts_private_planning_writes=True,
    )
    monkeypatch.setattr(
        files, "_lock_retry", lambda *_args: events.append("retry-lock")
    )
    monkeypatch.setattr(files, "_retained", Mock(return_value=None))
    monkeypatch.setattr(files, "_replay", Mock(return_value=None))

    def authorize(**kwargs):
        assert kwargs["lock"] is True
        if kwargs["capability_code"] == files.APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF:
            assert kwargs["requested_fields"] == frozenset(
                {"proposal_summary", "answers"}
            )
            events.append("read-authority")
        else:
            assert (
                kwargs["capability_code"]
                == files.APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
            )
            events.append("write-authority")
        return scope

    monkeypatch.setattr(files, "authorize_programme_proposal_scope", authorize)
    monkeypatch.setattr(files, "_locked_proposal", Mock(return_value=proposal))
    monkeypatch.setattr(files, "_question", Mock(return_value=object()))
    monkeypatch.setattr(files, "_latest_answer_map", Mock(return_value={}))
    monkeypatch.setattr(files, "_question_is_applicable", Mock(return_value=True))
    monkeypatch.setattr(
        files, "_capacity", lambda *_args, **_kwargs: events.append("quota")
    )
    monkeypatch.setattr(files, "programme_application_database_writer", nullcontext)
    receipt, intake, content = Mock(), Mock(), Mock()
    receipt.create.side_effect = lambda **kwargs: (
        events.append("receipt") or SimpleNamespace(**kwargs)
    )
    intake.create.side_effect = lambda **kwargs: (
        events.append("intake") or SimpleNamespace(**kwargs)
    )
    content.create.side_effect = lambda **_kwargs: events.append("content")
    monkeypatch.setattr(
        files, "ApplicationFileReceipt", SimpleNamespace(objects=receipt)
    )
    monkeypatch.setattr(files, "ProgrammeFileIntake", SimpleNamespace(objects=intake))
    monkeypatch.setattr(files, "ProgrammeFileContent", SimpleNamespace(objects=content))
    result = object()
    answer = Mock(side_effect=lambda **_kwargs: events.append("answer") or result)
    monkeypatch.setattr(files.commands, "append_programme_proposal_answer", answer)
    return SimpleNamespace(
        events=events,
        proposal=proposal,
        scope=scope,
        receipt=receipt,
        intake=intake,
        content=content,
        answer=answer,
        result=result,
    )


def test_fresh_write_rechecks_both_authorities_and_commits_through_one_answer(
    request_scope,
    intent,
    prepared,
    fresh_write,
):
    arguments, authorizer = files._arguments(request_scope, intent), object()
    assert (
        files._persist.__wrapped__(arguments, prepared, authorizer)
        is fresh_write.result
    )
    assert fresh_write.events == [
        "retry-lock",
        "read-authority",
        "write-authority",
        "quota",
        "receipt",
        "intake",
        "content",
        "answer",
    ]
    receipt = fresh_write.receipt.create.call_args.kwargs
    intake = fresh_write.intake.create.call_args.kwargs
    assert receipt["sha256"] == prepared.sha256
    assert receipt["size_bytes"] == len(PDF)
    assert receipt["storage_key"] == f"programme-db/{intake['id']}"
    assert receipt["account_id"] == request_scope.actor_id
    assert intake["source_version"] == 3
    assert intake["call_version"] == 2
    assert intake["definition_version"] == 1
    assert intake["retry_key"] == intent.retry_key
    assert fresh_write.content.create.call_args.kwargs["payload"] is PDF
    fresh_write.answer.assert_called_once_with(
        **arguments, value=str(receipt["id"]), authorizer=authorizer
    )


@pytest.mark.parametrize(
    "change",
    [
        "relationship",
        "planning",
        "proposal",
        "version",
        "call",
        "definition",
        "state",
        "window",
        "question",
        "quota",
        "read_authority",
        "write_authority",
    ],
)
def test_post_scan_changes_refuse_before_any_custody(
    monkeypatch,
    request_scope,
    intent,
    prepared,
    fresh_write,
    change,
):
    proposal, scope = fresh_write.proposal, fresh_write.scope
    if change == "relationship":
        scope.relationship = "invited"
    elif change == "planning":
        scope.accepts_private_planning_writes = False
    elif change == "proposal":
        scope.proposal_id = uuid4()
    elif change == "version":
        proposal.submission.aggregate_version = 4
    elif change == "call":
        proposal.call.definition.aggregate_version = 3
    elif change == "definition":
        proposal.call.definition.version = 2
    elif change == "state":
        proposal.state = "sealed"
    elif change == "window":
        proposal.call.definition.applicant_edit_until = timezone.now() - timedelta(
            seconds=1
        )
    elif change == "question":
        monkeypatch.setattr(files, "_question_is_applicable", Mock(return_value=False))
    elif change == "quota":
        monkeypatch.setattr(
            files, "_capacity", Mock(side_effect=files.ProgrammeFileQuotaError)
        )
    else:
        original = files.authorize_programme_proposal_scope

        def deny(**kwargs):
            denied = (
                files.APPLICATIONS_VIEW_PROGRAMME_PROPOSAL_SELF
                if change == "read_authority"
                else files.APPLICATIONS_EDIT_PROGRAMME_PROPOSAL_SELF
            )
            if kwargs["capability_code"] == denied:
                raise files.ApplicationsProgrammeAuthorizationDeniedError
            return original(**kwargs)

        monkeypatch.setattr(files, "authorize_programme_proposal_scope", deny)
    with pytest.raises(
        (
            files.ApplicationsProgrammeAuthorizationDeniedError,
            files.commands.ApplicationsProgrammeCommandError,
        )
    ):
        files._persist.__wrapped__(
            files._arguments(request_scope, intent), prepared, object()
        )
    fresh_write.receipt.create.assert_not_called()
    fresh_write.intake.create.assert_not_called()
    fresh_write.content.create.assert_not_called()
    fresh_write.answer.assert_not_called()


@pytest.mark.parametrize("malformed", [None, object(), {}, "PRIVATE-NOT-A-SCOPE"])
def test_untyped_scope_rejected_without_body_or_raw_error_disclosure(
    intent, orchestration, malformed
):
    reader = Mock()
    with pytest.raises(files.ApplicationsProgrammeAuthorizationDeniedError):
        files.upload_and_use_programme_file(
            request=malformed, intent=intent, read_bytes=reader
        )
    reader.assert_not_called()
    assert "PRIVATE-NOT-A-SCOPE" not in repr(orchestration[2].call_args)


def test_transport_cannot_open_a_transaction_around_scanning(
    monkeypatch,
    request_scope,
    intent,
    orchestration,
):
    def reader():
        monkeypatch.setattr(files, "connection", SimpleNamespace(in_atomic_block=True))
        return PDF

    with pytest.raises(files.preparation.ProgrammeFileUnavailableError):
        files.upload_and_use_programme_file(
            request=request_scope, intent=intent, read_bytes=reader
        )
    assert orchestration[0] == ["admit", "configured"]


@pytest.mark.parametrize(
    ("value", "exists"), [(None, False), (uuid4(), True), (uuid4(), False)]
)
def test_canonical_answer_validates_exact_intake_but_clear_needs_no_file_lookup(
    monkeypatch,
    request_scope,
    value,
    exists,
):
    manager = Mock()
    manager.filter.return_value.exists.return_value = exists
    monkeypatch.setattr(
        files.commands, "ProgrammeFileIntake", SimpleNamespace(objects=manager)
    )
    with pytest.raises(files._Unavailable) if value and not exists else nullcontext():
        files.commands._require_registered_reference(
            question=SimpleNamespace(
                id=request_scope.question_id, field_type="safe_file"
            ),
            proposal=SimpleNamespace(id=request_scope.proposal_id),
            organization_id=request_scope.organization_id,
            edition_id=request_scope.edition_id,
            value=None if value is None else str(value),
        )
    if value:
        manager.filter.assert_called_once_with(
            organization_id=request_scope.organization_id,
            edition_id=request_scope.edition_id,
            proposal_id=request_scope.proposal_id,
            question_id=request_scope.question_id,
            file_receipt_id=value,
        )
    else:
        manager.filter.assert_not_called()
