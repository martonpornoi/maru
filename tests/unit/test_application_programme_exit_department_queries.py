"""Compose every admitted case without filtering denials into a partial archive."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_exit_department_queries as archive
from maru.applications.programme_review_authorization import DECIDE, REVIEW_FIELDS
from maru.applications.programme_review_queries import ProgrammeReviewReadRequest
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
    summary = SimpleNamespace(case_id=UUID(int=6), version=3)
    call_id, revision_id, file_id = (UUID(int=i) for i in range(7, 10))
    answer = {"key": "document", "type": "safe_file", "value": str(file_id)}
    review = SimpleNamespace(
        case_id=summary.case_id,
        version=summary.version,
        department_id=request.department_id,
        call_id=call_id,
        revision_id=revision_id,
        evidence_lineage=(1, 2, 3),
        answers_json=json.dumps([answer]),
    )
    attachment = SimpleNamespace(
        case_id=summary.case_id,
        revision_id=revision_id,
        question_key="document",
        file_id=file_id,
        size_bytes=3,
        data=b"PDF",
    )
    configuration = SimpleNamespace(
        department_id=request.department_id,
        calls=(
            SimpleNamespace(
                configuration=SimpleNamespace(summary=SimpleNamespace(call_id=call_id))
            ),
        ),
    )
    page = SimpleNamespace(items=(summary,), next_cursor=None)
    readers = {
        "purpose": ("authorize_programme_archive_scope", Mock()),
        "locked": ("_locked_scope", Mock()),
        "audit": ("_audit", Mock()),
        "configuration": (
            "load_programme_exit_configuration",
            Mock(return_value=configuration),
        ),
        "pages": ("list_programme_review_cases", Mock(return_value=page)),
        "review": ("load_programme_exit_review_case", Mock(return_value=review)),
        "file": ("load_programme_exit_review_file", Mock(return_value=attachment)),
    }
    for name, reader in readers.values():
        monkeypatch.setattr(archive, name, reader)
    return SimpleNamespace(
        read=archive.load_programme_exit_department.__wrapped__,
        args={"request": request},
        request=request,
        summary=summary,
        answer=answer,
        page=page,
        **{name: reader for name, (_, reader) in readers.items()},
    )


def test_complete_department_preserves_source_scopes_and_file_binding(source):
    result = source.read(**source.args)
    assert result.configuration == source.configuration.return_value
    assert result.cases[0].review == source.review.return_value
    assert result.cases[0].files == (source.file.return_value,)
    assert source.pages.call_count == source.purpose.call_count == 2
    assert source.configuration.call_args.kwargs[
        "request"
    ].requested_fields == frozenset({"review_setup"})
    assert source.pages.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_context"}
    )
    assert source.file.call_args.kwargs["request"].requested_fields == frozenset(
        {"review_answers"}
    )
    assert source.review.call_args.kwargs["request"] == source.request
    assert source.audit.call_args.args[1] == "exit_department"
    assert str(source.summary.case_id) not in repr(result)


def test_empty_department_still_requires_source_permissions(source):
    source.pages.return_value = SimpleNamespace(items=(), next_cursor=None)
    assert source.read(**source.args).cases == ()
    source.locked.assert_called_once()
    source.configuration.assert_called_once()
    source.audit.assert_called_once()
    source.review.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"department_id": None},
        {"capability_code": "applications.manage_programme_review"},
        {"requested_fields": frozenset({"review_context"})},
    ],
)
def test_declared_decider_scope_is_required(source, change):
    source.args["request"] = replace(source.request, **change)
    with pytest.raises(archive.ApplicationsProgrammeAuthorizationDeniedError):
        source.read(**source.args)
    source.configuration.assert_not_called()


@pytest.mark.parametrize(
    "boundary", ["configuration", "pages", "review", "file", "audit"]
)
def test_any_required_source_failure_is_not_silently_omitted(source, boundary):
    getattr(source, boundary).side_effect = RuntimeError("synthetic required source")
    with pytest.raises(RuntimeError, match="synthetic required source"):
        source.read(**source.args)


@pytest.mark.parametrize("final", [False, True])
def test_archive_purpose_initial_and_final(source, final):
    source.purpose.side_effect = (
        [None, ProgrammeAuthorizationDeniedError()]
        if final
        else ProgrammeAuthorizationDeniedError
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize(
    "bound",
    ["MAX_EXIT_CASES", "MAX_EXIT_ENTRIES", "MAX_EXIT_FILES", "MAX_EXIT_FILE_BYTES"],
)
def test_composition_resource_limits_refuse_partial_success(source, monkeypatch, bound):
    monkeypatch.setattr(archive, bound, 0)
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"case_id": UUID(int=100)},
        {"version": 99},
        {"department_id": UUID(int=100)},
        {"call_id": UUID(int=100)},
    ],
)
def test_review_must_match_inventory_and_configuration(source, change):
    for key, value in change.items():
        setattr(source.review.return_value, key, value)
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.file.assert_not_called()


@pytest.mark.parametrize(
    "field", ["case_id", "revision_id", "file_id", "question_key", "size_bytes"]
)
def test_file_must_match_exact_selected_case_answer(source, field):
    setattr(
        source.file.return_value, field, 100 if field == "size_bytes" else UUID(int=100)
    )
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)


@pytest.mark.parametrize(
    "answers",
    [
        [],
        [{"type": "text", "value": "private"}],
        [{"type": "safe_file", "value": None}],
    ],
)
def test_nonfile_cleared_and_withheld_answers_do_not_lookup_files(source, answers):
    source.review.return_value.answers_json = json.dumps(answers)
    assert source.read(**source.args).cases[0].files == ()
    source.file.assert_not_called()


def test_configuration_scope_must_match(source):
    source.configuration.return_value.department_id = UUID(int=100)
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.pages.assert_not_called()


def test_changed_final_inventory_fails(source):
    source.pages.side_effect = [
        source.page,
        SimpleNamespace(items=(), next_cursor=None),
    ]
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


def test_inventory_pages_are_complete_and_ordered(source, monkeypatch):
    monkeypatch.setattr(archive, "_PAGE_SIZE", 1)
    second = SimpleNamespace(case_id=UUID(int=20), version=1)
    source.pages.side_effect = [
        SimpleNamespace(items=(source.summary,), next_cursor=source.summary.case_id),
        SimpleNamespace(items=(second,), next_cursor=None),
    ]
    assert archive._inventory(source.request, Mock()) == (source.summary, second)
    assert source.pages.call_args.kwargs["after_id"] == source.summary.case_id


@pytest.mark.parametrize(
    "page",
    [
        SimpleNamespace(items=(), next_cursor=UUID(int=6)),
        SimpleNamespace(
            items=(SimpleNamespace(case_id=UUID(int=6)),), next_cursor=UUID(int=5)
        ),
    ],
)
def test_bad_inventory_cursor_never_becomes_partial_success(source, page):
    source.pages.return_value = page
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)


def test_duplicate_inventory_case_denied(source, monkeypatch):
    monkeypatch.setattr(archive, "_PAGE_SIZE", 1)
    source.pages.return_value = SimpleNamespace(
        items=(source.summary,), next_cursor=source.summary.case_id
    )
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
