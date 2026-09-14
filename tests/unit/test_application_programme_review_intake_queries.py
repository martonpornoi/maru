"""Fast intake scope, complete pagination, retained selection and audit contracts."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.core.exceptions import ValidationError
from django.db.models import F

from maru.applications import programme_review_intake_queries as queries
from maru.applications.programme_authorization import (
    ApplicationsProgrammeAuthorizationDeniedError as Denied,
)
from tests.unit.test_application_programme_review_setup_queries import request


@pytest.fixture
def source(monkeypatch):
    proposal = SimpleNamespace(
        id=UUID(int=41),
        state="submitted",
        submitted_revision_id=UUID(int=40),
        sealed_revision_id=UUID(int=40),
    )
    row = SimpleNamespace(
        id=UUID(int=40),
        proposal_id=proposal.id,
        proposal=proposal,
        sequence=3,
        sealed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    query = MagicMock()
    query.filter.return_value = query
    query.exclude.return_value = query
    query.order_by.return_value = query
    query.first.return_value = row
    query.__getitem__.side_effect = lambda bounds: [row][bounds]
    seals = Mock(return_value=query)
    scope = Mock(return_value=SimpleNamespace(accepts_private_planning_writes=True))
    audit = Mock()
    contributor = Mock(return_value=False)
    cases = Mock()
    cases.filter.return_value.exists.return_value = False
    collaborators = Mock()
    monkeypatch.setattr(queries, "_seals", seals)
    monkeypatch.setattr(queries, "_scope", scope)
    monkeypatch.setattr(queries, "_audit", audit)
    monkeypatch.setattr(queries, "is_proposal_contributor", contributor)
    monkeypatch.setattr(queries.ProgrammeReviewCase, "objects", cases)
    monkeypatch.setattr(queries.ProgrammeProposalCollaborator, "objects", collaborators)
    return SimpleNamespace(
        row=row,
        query=query,
        seals=seals,
        scope=scope,
        audit=audit,
        contributor=contributor,
        cases=cases,
        collaborators=collaborators,
    )


def page(**changes):
    return queries.list_programme_review_intake_seals.__wrapped__(
        **({"request": request(), "call_id": UUID(int=20)} | changes)
    )


def selected(**changes):
    return queries.get_programme_review_intake_seal.__wrapped__(
        **(
            {"request": request(), "call_id": UUID(int=20), "revision_id": UUID(int=40)}
            | changes
        )
    )


def test_source_relation_scopes_both_seal_and_proposal_via_owned_call():
    sql, params = queries._seals(request(), UUID(int=20)).query.sql_with_params()
    assert '"applications_programmeproposalrevision"."organization_id"' in sql
    assert '"applications_programmeproposalrevision"."edition_id"' in sql
    assert '"applications_programmeproposal"."organization_id"' in sql
    assert '"applications_programmeproposal"."edition_id"' in sql
    assert '"owner_department_id"' in sql
    assert set(params) >= {UUID(int=2), UUID(int=3), UUID(int=4), UUID(int=20)}


def test_discovery_excludes_noncurrent_contributors_and_cases_before_lookahead(source):
    second = SimpleNamespace(**(vars(source.row) | {"id": UUID(int=42)}))
    source.query.__getitem__.side_effect = lambda bounds: [source.row, second][bounds]
    result = page(after_id=UUID(int=39), limit=1)
    assert result.next_cursor == UUID(int=40)
    assert len(result.items) == 1
    assert result.items[0].sealed_at == source.row.sealed_at
    assert source.query.filter.call_args_list[0].kwargs == {
        "proposal__state": "submitted",
        "id": F("proposal__submitted_revision_id"),
        "proposal__sealed_revision_id": F("id"),
    }
    assert source.query.exclude.call_args_list[0].kwargs == {
        "proposal__submission__account_id": UUID(int=1)
    }
    assert source.query.exclude.call_args_list[1].kwargs == {
        "proposal_id__in": source.collaborators.filter.return_value.values.return_value
    }
    source.collaborators.filter.assert_called_once_with(
        organization_id=UUID(int=2), edition_id=UUID(int=3), account_id=UUID(int=1)
    )
    assert source.query.exclude.call_args_list[2].kwargs == {
        "id__in": source.cases.filter.return_value.values.return_value
    }
    assert source.query.filter.call_args_list[1].kwargs == {"id__gt": UUID(int=39)}
    calls = [call[0] for call in source.query.mock_calls]
    assert max(
        index for index, name in enumerate(calls) if name == "exclude"
    ) < calls.index("__getitem__")
    source.query.__getitem__.assert_called_once_with(slice(None, 2))
    assert source.audit.call_args.args[:3] == (request(), "intake_seals", UUID(int=20))


def test_exact_selection_loads_original_seal_and_audits_before_metadata_release(source):
    result = selected()
    assert result.eligible
    assert result.writable
    assert not result.opened
    assert result.seal.proposal_id == UUID(int=41)
    source.query.filter.assert_called_once_with(id=UUID(int=40))
    source.seals.assert_called_once_with(request(), UUID(int=20))
    source.contributor.assert_called_once_with(source.row.proposal, UUID(int=1))
    assert source.audit.call_args.args[:3] == (request(), "intake_seal", UUID(int=40))
    assert not hasattr(result, "answers")
    assert not hasattr(result, "case_id")


@pytest.mark.parametrize("state", ["draft", "sealed", "withdrawn"])
def test_retained_source_metadata_survives_lifecycle_changes_without_fresh_eligibility(
    source, state
):
    source.row.proposal.state = state
    assert selected().eligible is False
    source.audit.assert_called_once()


@pytest.mark.parametrize("field", ["submitted_revision_id", "sealed_revision_id"])
def test_exact_selection_never_rebases_to_newer_revision(source, field):
    setattr(source.row.proposal, field, UUID(int=90))
    result = selected()
    assert result.seal.revision_id == UUID(int=40)
    assert not result.eligible


def test_existing_case_and_retained_contributor_conflict_do_not_hide_retry_metadata(
    source,
):
    source.cases.filter.return_value.exists.return_value = True
    assert selected().opened
    assert not selected().eligible
    source.cases.filter.return_value.exists.return_value = False
    source.contributor.return_value = True
    assert not selected().eligible
    source.scope.return_value.accepts_private_planning_writes = False
    assert not selected().writable


def test_scope_failure_precedes_all_model_access_and_audit_failure_prevents_release(
    source,
):
    source.scope.side_effect = Denied
    with pytest.raises(Denied):
        page()
    source.seals.assert_not_called()
    source.collaborators.filter.assert_not_called()
    source.scope.side_effect = None
    source.audit.side_effect = Denied
    with pytest.raises(Denied):
        selected()


def test_missing_or_foreign_exact_selection_is_non_disclosing(source):
    source.query.first.return_value = None
    with pytest.raises(Denied):
        selected()
    source.cases.filter.assert_not_called()
    source.audit.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101, True, "50"])
def test_invalid_limit_never_loads_source(source, limit):
    with pytest.raises(Denied):
        page(limit=limit)
    source.seals.assert_not_called()


@pytest.mark.parametrize("field", ["call_id", "revision_id"])
def test_identifiers_remain_typed_nonzero_references(source, field):
    with pytest.raises(ValidationError):
        selected(**{field: str(UUID(int=1))})
    source.scope.assert_not_called()


@pytest.mark.parametrize(
    "fields",
    [
        frozenset(),
        frozenset({"review_context"}),
        frozenset({"review_setup", "review_answers"}),
    ],
)
def test_intake_reuses_exact_setup_ceiling_not_manager_content_authority(
    monkeypatch, fields
):
    locked = Mock()
    monkeypatch.setattr(
        "maru.applications.programme_review_setup_queries._locked_scope", locked
    )
    with pytest.raises(Denied):
        queries._scope(replace(request(), requested_fields=fields), Mock())
    locked.assert_not_called()
