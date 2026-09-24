"""Bound complete call configuration without substituting archive authority."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.applications import programme_exit_configuration_queries as archive
from maru.applications.programme_review_authorization import MANAGE_REVIEW
from maru.applications.programme_review_queries import ProgrammeReviewReadRequest
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture
def source(monkeypatch):
    request = ProgrammeReviewReadRequest(
        *(UUID(int=i) for i in range(1, 5)),
        MANAGE_REVIEW,
        frozenset({"review_setup"}),
        UUID(int=5),
        "programme-exit",
    )
    summary = SimpleNamespace(call_id=UUID(int=6), aggregate_version=3)
    configuration = SimpleNamespace(summary=summary)
    summaries = Mock(return_value=(summary,))
    config_reader = Mock(return_value=configuration)
    versions = [(UUID(int=7), 1), (UUID(int=8), 2)]
    query = Mock()
    query.return_value.order_by.return_value.values_list.side_effect = lambda *_: (
        versions
    )
    policy_reader = Mock(
        side_effect=lambda **args: SimpleNamespace(
            policy_id=versions[args["version"] - 1][0], version=args["version"]
        )
    )
    purpose, locked, audit = Mock(), Mock(), Mock()
    monkeypatch.setattr(archive, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(archive, "_locked_scope", locked)
    monkeypatch.setattr(archive, "_audit", audit)
    monkeypatch.setattr(archive, "list_managed_programme_calls", summaries)
    monkeypatch.setattr(
        archive, "get_managed_programme_call_configuration", config_reader
    )
    monkeypatch.setattr(archive, "get_programme_review_setup_policy", policy_reader)
    monkeypatch.setattr(archive.ProgrammeReviewPolicy.objects, "filter", query)
    return SimpleNamespace(
        read=archive.load_programme_exit_configuration.__wrapped__,
        args={"request": request},
        request=request,
        summary=summary,
        configuration=configuration,
        summaries=summaries,
        config_reader=config_reader,
        versions=versions,
        query=query,
        policy_reader=policy_reader,
        purpose=purpose,
        locked=locked,
        audit=audit,
    )


def test_complete_configuration_and_policy_history_remain_separately_authorized(source):
    result = source.read(**source.args)
    assert result.department_id == source.request.department_id
    assert result.calls[0].configuration == source.configuration
    assert [
        (row.policy_id, row.version) for row in result.calls[0].policies
    ] == source.versions
    assert source.purpose.call_count == source.summaries.call_count == 2
    assert source.config_reader.call_count == 2
    source.locked.assert_called_once()
    assert source.audit.call_args.args[1] == "exit_configuration"
    assert source.query.call_args.kwargs == {
        "call_id": source.summary.call_id,
        "call__organization_id": source.request.organization_id,
        "call__edition_id": source.request.edition_id,
        "call__owner_department_id": source.request.department_id,
    }
    assert str(source.summary.call_id) not in repr(result)


def test_empty_configuration_still_requires_both_sources_and_audit(source):
    source.summaries.return_value = ()
    result = source.read(**source.args)
    assert result.calls == ()
    assert source.summaries.call_count == source.purpose.call_count == 2
    source.locked.assert_called_once()
    source.audit.assert_called_once()
    source.policy_reader.assert_not_called()


def test_call_without_policy_is_honestly_empty(source):
    source.versions.clear()
    assert source.read(**source.args).calls[0].policies == ()
    source.policy_reader.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"capability_code": "applications.decide_programme"},
        {"requested_fields": frozenset({"review_context"})},
        {"department_id": None},
    ],
)
def test_incorrect_scope_is_denied_before_discovery(source, change):
    source.args["request"] = replace(source.request, **change)
    with pytest.raises(archive.ApplicationsProgrammeAuthorizationDeniedError):
        source.read(**source.args)
    source.summaries.assert_not_called()


@pytest.mark.parametrize("final", [False, True])
def test_archive_purpose_is_required_initially_and_finally(source, final):
    source.purpose.side_effect = (
        [None, ProgrammeAuthorizationDeniedError()]
        if final
        else ProgrammeAuthorizationDeniedError
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        source.read(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize(
    "boundary", ["locked", "summaries", "config_reader", "policy_reader", "audit"]
)
def test_mandatory_source_or_audit_failure_propagates(source, boundary):
    getattr(source, boundary).side_effect = RuntimeError("synthetic boundary failure")
    with pytest.raises(RuntimeError, match="synthetic boundary failure"):
        source.read(**source.args)


@pytest.mark.parametrize("versions", [[2], [1, 3], [1, 1]])
def test_incomplete_policy_sequence_refuses_partial_success(source, versions):
    source.versions[:] = [
        (UUID(int=7 + i), version) for i, version in enumerate(versions)
    ]
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.policy_reader.assert_not_called()


@pytest.mark.parametrize(
    "bound", ["MAX_EXIT_POLICIES_PER_CALL", "MAX_EXIT_POLICIES_PER_DEPARTMENT"]
)
def test_overflow_refuses_without_truncation(source, monkeypatch, bound):
    monkeypatch.setattr(archive, bound, 1)
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.policy_reader.assert_not_called()


def test_policy_identity_must_match_exact_inventory(source):
    source.policy_reader.side_effect = lambda **args: SimpleNamespace(
        policy_id=UUID(int=900), version=args["version"]
    )
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)


def test_changed_call_inventory_denied_before_final_audit(source):
    source.summaries.side_effect = [(source.summary,), ()]
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
    source.audit.assert_not_called()


def test_changed_full_configuration_denied(source):
    source.config_reader.side_effect = [
        source.configuration,
        SimpleNamespace(summary=source.summary, extra="changed"),
    ]
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)


def test_changed_policy_inventory_denied(source):
    source.query.return_value.order_by.return_value.values_list.side_effect = [
        source.versions,
        [],
    ]
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)


def test_summary_configuration_mismatch_denied(source):
    source.config_reader.return_value = SimpleNamespace(summary=None)
    with pytest.raises(archive.ProgrammeReviewUnavailableError):
        source.read(**source.args)
