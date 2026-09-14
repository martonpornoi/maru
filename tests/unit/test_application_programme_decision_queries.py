"""Database-free exact-recipient query scope, bounds and disclosure contracts."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError

from maru.applications import programme_review_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from maru.applications.programme_review_authorization import VIEW_DECISION_SELF


def request(**changes):
    original = queries.ProgrammeReviewReadRequest(
        UUID(int=1),
        UUID(int=2),
        UUID(int=3),
        None,
        VIEW_DECISION_SELF,
        frozenset({"decision_message", "own_acknowledgement"}),
        UUID(int=4),
        "test",
    )
    return replace(original, **changes)


@pytest.fixture
def source(monkeypatch):
    now = datetime(2026, 9, 1, tzinfo=UTC)
    row = SimpleNamespace(
        id=UUID(int=20),
        entry=SimpleNamespace(
            case_id=UUID(int=30),
            case=SimpleNamespace(version=12),
            version=10,
            created_at=now,
        ),
        outcome="accepted",
        message="Exact message",
        acknowledgement_required=True,
    )
    recipients = Mock()
    decisions = Mock()
    query = MagicMock()
    decisions.select_related.return_value.filter.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.__getitem__.side_effect = lambda bounds: [row][bounds]
    receipts = Mock()
    receipts.filter.return_value.values_list.return_value = [(row.id, now)]
    locked = Mock()
    audit = Mock()
    monkeypatch.setattr(
        queries.ProgrammeProposalRevisionContributor, "objects", recipients
    )
    monkeypatch.setattr(queries.ProgrammeReviewDecision, "objects", decisions)
    monkeypatch.setattr(queries.ProgrammeDecisionAcknowledgement, "objects", receipts)
    monkeypatch.setattr(queries, "_locked_scope", locked)
    monkeypatch.setattr(queries, "_audit", audit)
    return SimpleNamespace(
        row=row,
        query=query,
        decisions=decisions,
        recipients=recipients,
        receipts=receipts,
        locked=locked,
        audit=audit,
    )


def read(**changes):
    values = {"request": request(), "decision_id": UUID(int=20)} | changes
    return queries.get_self_programme_decision.__wrapped__(**values)


def test_exact_getter_scopes_before_loading_one_target_and_audits(source):
    result = read()
    assert result.decision_id == UUID(int=20)
    assert result.case_id == UUID(int=30)
    assert result.case_version == 12
    assert result.decision_version == 10
    assert result.message == "Exact message"
    assert result.own_acknowledged
    source.recipients.filter.assert_called_once_with(
        organization_id=UUID(int=2), edition_id=UUID(int=3), account_id=UUID(int=1)
    )
    source.decisions.select_related.return_value.filter.assert_called_once_with(
        revision_id__in=source.recipients.filter.return_value.values.return_value,
        revision__organization_id=UUID(int=2),
        revision__edition_id=UUID(int=3),
        entry__case__proposal__organization_id=UUID(int=2),
        entry__case__proposal__edition_id=UUID(int=3),
    )
    source.query.filter.assert_called_once_with(id=UUID(int=20))
    source.query.__getitem__.assert_called_once_with(slice(None, 2))
    source.receipts.filter.assert_called_once_with(
        decision_id__in=[UUID(int=20)], account_id=UUID(int=1)
    )
    assert source.locked.call_args.args[0] == request()
    assert source.audit.call_args.args[:3] == (request(), "self_decision", UUID(int=20))


@pytest.mark.parametrize(
    "fields", [frozenset({"decision_message"}), frozenset({"own_acknowledgement"})]
)
def test_exact_getter_retains_independent_field_ceiling(source, fields):
    result = read(request=request(requested_fields=fields))
    if "decision_message" in fields:
        assert result.message == "Exact message"
        assert (
            result.own_acknowledged
            is result.acknowledgement_required
            is result.own_acknowledged_at
            is None
        )
    else:
        assert result.message is result.outcome is None
        assert result.own_acknowledged


def test_missing_and_foreign_exact_recipient_getter_is_denied(source):
    source.query.__getitem__.side_effect = lambda _bounds: []
    with pytest.raises(Denied):
        read()


def test_untyped_id_never_loads_recipient_data(source):
    with pytest.raises(ValidationError):
        read(decision_id=str(UUID(int=20)))
    source.locked.assert_not_called()
    source.recipients.filter.assert_not_called()


@pytest.mark.parametrize(
    "capability",
    [
        "applications.manage_programme_review",
        "applications.review_programme",
        "applications.acknowledge_programme_decision_self",
    ],
)
def test_other_purposes_never_inherit_exact_recipient_content(source, capability):
    with pytest.raises(Denied):
        read(request=request(capability_code=capability))
    source.recipients.filter.assert_not_called()


def test_scope_failure_precedes_recipient_loading(source):
    source.locked.side_effect = Denied
    with pytest.raises(Denied):
        read()
    source.recipients.filter.assert_not_called()


def test_late_audit_failure_releases_no_projection(source):
    source.audit.side_effect = RuntimeError("Synthetic read audit failure")
    with pytest.raises(RuntimeError, match="Synthetic read audit failure"):
        read()


def test_refactored_history_keeps_chronological_cursor_and_page_size(source):
    second = SimpleNamespace(**(vars(source.row) | {"id": UUID(int=21)}))
    source.query.__getitem__.side_effect = lambda bounds: [source.row, second][bounds]
    result = queries.list_self_programme_decisions.__wrapped__(
        request=request(), limit=1
    )
    assert len(result.items) == 1
    assert result.next_cursor == source.row.id
    source.query.filter.assert_not_called()
    source.query.order_by.assert_called_once_with("entry__created_at", "id")
    assert source.audit.call_args.args[:3] == (request(), "self_decisions", None)


def test_foreign_history_cursor_is_denied_without_message_disclosure(source):
    source.query.values_list.return_value.first.return_value = None
    with pytest.raises(Denied):
        queries.list_self_programme_decisions.__wrapped__(
            request=request(), after_id=UUID(int=99)
        )
    source.query.__getitem__.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101, True, 1.0, "1"])
def test_history_bounds_stay_strict(source, limit):
    with pytest.raises(Denied):
        queries.list_self_programme_decisions.__wrapped__(
            request=request(), limit=limit
        )
    source.recipients.filter.assert_not_called()
