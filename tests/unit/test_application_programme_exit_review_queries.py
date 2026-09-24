"""Keep archive review paging complete without changing source rights."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_exit_review_queries as archive
from maru.applications.programme_decider_queries import (
    DecisionMessage,
    DecisionMessages,
)
from maru.applications.programme_review_authorization import DECIDE, REVIEW_FIELDS
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
        REVIEW_FIELDS,
        UUID(int=5),
        "programme-exit",
    )
    case_id = UUID(int=6)
    rows = [
        (UUID(int=20 + i), i, datetime(2030, 1, 1, tzinfo=UTC)) for i in range(1, 6)
    ]
    context, answers = (
        '{"stage":0}',
        '[{"key":"title","classification":"C2","value":"PRIVATE"}]',
    )
    pages = [
        ProgrammeReviewDetail(
            case_id,
            5,
            context,
            answers,
            json.dumps(
                [
                    {"version": i, "payload": "PRIVATE"}
                    for i in range(after + 1, min(after + 2, 5) + 1)
                ]
            ),
            after + 2 if after + 2 < 5 else None,
        )
        for after in (0, 2, 4)
    ]
    pages.append(ProgrammeReviewDetail(case_id, 5, context, answers, "[]", None))
    reader = Mock(side_effect=pages)
    monkeypatch.setattr(archive, "get_programme_review_detail", reader)
    messages = Mock(return_value=DecisionMessages(5, (), None))
    monkeypatch.setattr(archive, "list_programme_decision_messages", messages)
    purpose, locked, audit = Mock(), Mock(), Mock()
    monkeypatch.setattr(archive, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(archive, "_locked_scope", locked)
    monkeypatch.setattr(archive, "_audit", audit)
    monkeypatch.setattr(archive, "_PAGE_SIZE", 2)
    case = SimpleNamespace(
        version=5,
        proposal_id=UUID(int=7),
        revision_id=UUID(int=8),
        policy_id=UUID(int=9),
        proposal=SimpleNamespace(call_id=UUID(int=10)),
    )
    monkeypatch.setattr(archive, "load_review_case", Mock(return_value=case))
    query = Mock()
    query.return_value.order_by.return_value.values_list.side_effect = lambda *_: rows
    monkeypatch.setattr(archive.ProgrammeReviewEntry.objects, "filter", query)
    # Native tests below exercise the transaction decorator with real PostgreSQL.
    return SimpleNamespace(
        read=archive.load_programme_exit_review_case.__wrapped__,
        args={"request": request, "case_id": case_id},
        request=request,
        rows=rows,
        pages=pages,
        reader=reader,
        purpose=purpose,
        locked=locked,
        audit=audit,
        case=case,
        query=query,
        messages=messages,
    )


def test_complete_pages_stable_lineage_and_existing_field_ceilings(source):
    result = source.read(**source.args)
    assert result.case_id == source.args["case_id"]
    assert result.version == 5
    assert result.proposal_id == source.case.proposal_id
    assert [entry["version"] for entry in json.loads(result.evidence_json)] == [
        1,
        2,
        3,
        4,
        5,
    ]
    assert result.evidence_lineage == tuple(source.rows)
    assert source.purpose.call_count == 2
    calls = source.reader.call_args_list
    assert [call.kwargs.get("after_version", 0) for call in calls] == [0, 2, 4, 5]
    assert calls[0].kwargs["request"].requested_fields == REVIEW_FIELDS
    assert calls[1].kwargs["request"].requested_fields == frozenset({"review_evidence"})
    assert calls[-1].kwargs["request"].requested_fields == REVIEW_FIELDS
    source.query.assert_called_once_with(
        case_id=source.args["case_id"],
        case__proposal__organization_id=source.request.organization_id,
        case__proposal__edition_id=source.request.edition_id,
        case__revision__organization_id=source.request.organization_id,
        case__revision__edition_id=source.request.edition_id,
    )
    assert source.audit.call_args.args[1] == "exit_case"
    assert "PRIVATE" not in repr(result)


def message(version, *, identifier=None):
    return DecisionMessage(
        UUID(int=identifier or 100 + version),
        version,
        datetime(2030, 1, 1, tzinfo=UTC),
        "waitlisted",
        "Retained message",
        acknowledgement_required=True,
    )


def test_outgoing_messages_are_complete_across_pages_without_recipient_discovery(
    source,
):
    source.messages.side_effect = [
        DecisionMessages(5, (message(1), message(3)), 3),
        DecisionMessages(5, (message(5),), None),
    ]
    result = source.read(**source.args)
    assert [item.version for item in result.decisions] == [1, 3, 5]
    assert [
        call.kwargs["after_version"] for call in source.messages.call_args_list
    ] == [0, 3]
    assert all(
        call.kwargs["request"].requested_fields == frozenset({"review_evidence"})
        for call in source.messages.call_args_list
    )


@pytest.mark.parametrize(
    "page",
    [
        DecisionMessages(6, (), None),
        DecisionMessages(5, (message(1), message(2), message(3)), None),
        DecisionMessages(5, (message(0),), None),
        DecisionMessages(5, (message(6),), None),
        DecisionMessages(5, (message(2), message(1)), None),
        DecisionMessages(5, (message(1), message(2, identifier=101)), None),
        DecisionMessages(5, (message(1),), 1),
        DecisionMessages(5, (message(1), message(2)), 3),
    ],
)
def test_bad_or_changed_message_pages_refuse_whole_case(source, page):
    source.messages.return_value = page
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"capability_code": "applications.manage_programme_review"},
        {"capability_code": "applications.review_programme"},
        {"requested_fields": frozenset({"review_context"})},
        {"department_id": None},
    ],
)
def test_incomplete_source_purpose_never_loads_archive(source, change):
    with pytest.raises(archive.Denied):
        source.read(**{**source.args, "request": replace(source.request, **change)})
    source.reader.assert_not_called()


@pytest.mark.parametrize(
    ("index", "change"),
    [
        (0, {"version": 0}),
        (0, {"version": True}),
        (0, {"version": 20001}),
        (0, {"context_json": None}),
        (0, {"answers_json": None}),
        (0, {"answers_json": "not-json"}),
        (0, {"answers_json": "{}"}),
        (0, {"answers_json": '[ {"classification":"C4"} ]'}),
        (0, {"answers_json": '[ {"classification":"unknown"} ]'}),
        (0, {"evidence_json": None}),
        (0, {"evidence_json": "not-json"}),
        (0, {"evidence_json": "{}"}),
        (0, {"evidence_json": "[]"}),
        (0, {"evidence_json": '[{"version":2},{"version":1}]'}),
        (0, {"evidence_json": '[{"version":true},{"version":2}]'}),
        (0, {"next_evidence_version": None}),
        (1, {"version": 6}),
        (1, {"case_id": UUID(int=99)}),
        (2, {"next_evidence_version": 5}),
        (3, {"version": 6}),
        (3, {"case_id": UUID(int=99)}),
        (3, {"answers_json": "[]"}),
        (3, {"context_json": "{}"}),
        (3, {"evidence_json": '[ {"version":6} ]'}),
        (3, {"next_evidence_version": 6}),
    ],
)
def test_missing_changed_gapped_or_overflow_source_refuses_whole_case(
    source, index, change
):
    source.pages[index] = replace(source.pages[index], **change)
    source.reader.side_effect = source.pages
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "reordered", "version"])
def test_lineage_must_match_complete_case_evidence(source, failure):
    if failure == "missing":
        source.rows.pop()
    elif failure == "reordered":
        source.rows.reverse()
    else:
        source.case.version = 6
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize("final", [False, True])
def test_archive_purpose_must_be_current_before_collection_and_return(source, final):
    source.purpose.side_effect = ([None] if final else []) + [
        ProgrammeAuthorizationDeniedError()
    ]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        source.read(**source.args)
    source.audit.assert_not_called()
    if not final:
        source.reader.assert_not_called()


def test_audit_failure_does_not_return_retained_evidence(source):
    source.audit.side_effect = RuntimeError("synthetic audit outage")
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        source.read(**source.args)
