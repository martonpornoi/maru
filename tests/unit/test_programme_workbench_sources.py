"""Exercise source-selection queries with real audit composition and fake storage."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.programme import queries
from maru.programme import workbench_sources as sources
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.workbench_queries import ProgrammeWorkbenchRequest


@pytest.fixture
def source_query(monkeypatch):
    scope = ProgrammeWorkbenchRequest(*(UUID(int=i) for i in range(1, 5)))
    item_id = UUID(int=5)
    events = []
    admitted = SimpleNamespace(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        decision=PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset(),
            reason_code="synthetic",
        ),
    )

    def authorize(**kwargs):
        events.append("lock" if kwargs.get("lock") else "authorize")
        return admitted

    auth = Mock(side_effect=authorize)
    monkeypatch.setattr(sources, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    audit = Mock(side_effect=lambda _record: events.append("audit"))
    monkeypatch.setattr(queries, "append_audit", audit)
    storage = {}
    for model, row in (
        (sources.ProgrammeItem, None),
        (
            sources.ProgrammeWorkingRevision,
            {"id": UUID(int=10), "sequence": 2, "item_version": 6},
        ),
        (
            sources.ProgrammeDeliveryRevision,
            {"id": UUID(int=11), "sequence": 3, "item_version": 7},
        ),
        (
            sources.ProgrammePublicRendition,
            {
                "id": UUID(int=12),
                "rendition_number": 4,
                "source_item_version": 6,
                "public_title": "Historical public title",
                "withdrawn": False,
            },
        ),
        (sources.ProgrammePublicRenditionWithdrawal, None),
    ):
        chain = MagicMock()
        chain.first.return_value = row
        chain.exists.return_value = model is sources.ProgrammeItem
        chain.order_by.return_value = chain
        chain.values.return_value = chain
        chain.annotate.return_value = chain
        chain.__getitem__.side_effect = lambda selection, row=row: [row][selection]

        def select(*, chain=chain, **kwargs):
            events.append("select")
            assert kwargs["organization_id"] == scope.organization_id
            assert kwargs["edition_id"] == scope.edition_id
            return chain

        selector = Mock(side_effect=select)
        monkeypatch.setattr(model.objects, "filter", selector)
        storage[model.__name__] = (selector, chain)
    return SimpleNamespace(
        scope=scope,
        item_id=item_id,
        events=events,
        auth=auth,
        admitted=admitted,
        audit=audit,
        storage=storage,
    )


@pytest.mark.parametrize(
    ("layer", "model", "columns"),
    [
        ("working", "ProgrammeWorkingRevision", ("id", "sequence", "item_version")),
        ("delivery", "ProgrammeDeliveryRevision", ("id", "sequence", "item_version")),
        (
            "public-copy",
            "ProgrammePublicRendition",
            ("id", "rendition_number", "source_item_version"),
        ),
    ],
)
def test_exact_source_uses_only_independent_fields_and_audits_before_disclosure(
    source_query, layer, model, columns
):
    query = source_query
    result = sources.load_programme_evidence_source(
        query.scope, item_id=query.item_id, layer=layer
    )
    assert result is not None
    assert str(result.object_id) in result.key
    assert "Historical public title" not in repr(result)
    query.storage[model][1].values.assert_called_once_with(*columns)
    assert query.storage[model][0].call_args.kwargs["item_id"] == query.item_id
    assert query.events[:2] == ["authorize", "lock"]
    assert query.events[-2:] == ["authorize", "audit"]
    capability, fields = sources.SOURCE_READS[layer]
    for call in query.auth.call_args_list:
        assert call.kwargs["capability_code"] == capability
        assert call.kwargs["requested_fields"] == fields
    record = query.audit.call_args.args[0]
    assert record.operation == "programme.query.workbench_evidence_source"
    assert record.safe_metadata["target_count"] == 1


def test_withdrawn_latest_public_source_never_falls_back(source_query):
    query = source_query
    query.storage["ProgrammePublicRenditionWithdrawal"][1].exists.return_value = True
    assert (
        sources.load_programme_evidence_source(
            query.scope, item_id=query.item_id, layer="public-copy"
        )
        is None
    )
    query.storage["ProgrammePublicRendition"][1].first.assert_called_once_with()
    assert query.audit.call_args.args[0].safe_metadata["target_count"] == 0


@pytest.mark.parametrize(
    ("layer", "model"),
    [
        ("delivery", "ProgrammeDeliveryRevision"),
        ("public-copy", "ProgrammePublicRendition"),
    ],
)
def test_optional_absent_source_is_audited_absence_not_an_attestation(
    source_query, layer, model
):
    query = source_query
    query.storage[model][1].first.return_value = None
    assert (
        sources.load_programme_evidence_source(
            query.scope, item_id=query.item_id, layer=layer
        )
        is None
    )
    assert query.audit.call_args.args[0].safe_metadata["target_count"] == 0


def test_missing_required_working_source_is_unavailable(source_query):
    query = source_query
    query.storage["ProgrammeWorkingRevision"][1].first.return_value = None
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        sources.load_programme_evidence_source(
            query.scope, item_id=query.item_id, layer="working"
        )
    query.audit.assert_not_called()


def read_selection(query, kind):
    if kind == "withdrawal":
        return sources.list_programme_withdrawal_choices(
            query.scope, item_id=query.item_id
        )
    return sources.load_programme_evidence_source(
        query.scope, item_id=query.item_id, layer="delivery"
    )


@pytest.mark.parametrize("kind", ["withdrawal", "evidence"])
@pytest.mark.parametrize("denial_at", [1, 2, 3])
def test_denial_at_initial_lock_or_final_boundary_releases_no_source(
    source_query, kind, denial_at
):
    query = source_query
    count = 0

    def authorize(**_kwargs):
        nonlocal count
        count += 1
        if count == denial_at:
            raise ProgrammeAuthorizationDeniedError
        return query.admitted

    query.auth.side_effect = authorize
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        read_selection(query, kind)
    assert all(call.args[0].outcome == "deny" for call in query.audit.call_args_list)
    if denial_at <= 2:
        assert "select" not in query.events


@pytest.mark.parametrize("kind", ["withdrawal", "evidence"])
def test_required_audit_failure_releases_no_source_selection(source_query, kind):
    source_query.audit.side_effect = DatabaseError("Synthetic audit failure")
    with pytest.raises(DatabaseError):
        read_selection(source_query, kind)


@pytest.mark.parametrize("kind", ["withdrawal", "evidence"])
def test_missing_or_foreign_item_stops_before_source_query(source_query, kind):
    query = source_query
    query.storage["ProgrammeItem"][1].exists.return_value = False
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        read_selection(query, kind)
    query.storage["ProgrammePublicRendition"][0].assert_not_called()
    query.storage["ProgrammeDeliveryRevision"][0].assert_not_called()
    query.audit.assert_not_called()


def test_complete_withdrawal_choices_exclude_already_withdrawn_but_retain_older_copy(
    source_query,
):
    query = source_query
    rows = [
        {
            "id": UUID(int=30),
            "rendition_number": 3,
            "public_title": "Already withdrawn",
            "withdrawn": True,
        },
        {
            "id": UUID(int=31),
            "rendition_number": 2,
            "public_title": "Retained older copy",
            "withdrawn": False,
        },
    ]
    chain = query.storage["ProgrammePublicRendition"][1]
    chain.__getitem__.side_effect = lambda selection: rows[selection]
    result = read_selection(query, "withdrawal")
    assert result == (
        sources.ProgrammeWithdrawalChoice(UUID(int=31), 2, "Retained older copy"),
    )
    chain.values.assert_called_once_with(
        "id", "rendition_number", "public_title", "withdrawn"
    )
    assert query.events[:2] == ["authorize", "lock"]
    assert query.events[-2:] == ["authorize", "audit"]
    for call in query.auth.call_args_list:
        assert call.kwargs["requested_fields"] == frozenset(
            {"public_copy_review_history"}
        )
    assert (
        query.audit.call_args.args[0].operation
        == "programme.query.workbench_withdrawal_choices"
    )


def test_withdrawal_overflow_refuses_partial_targets(source_query, monkeypatch):
    monkeypatch.setattr(sources, "MAX_PROGRAMME_PUBLIC_RENDITIONS", 0)
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        read_selection(source_query, "withdrawal")
    source_query.audit.assert_not_called()


def test_unknown_layer_never_reaches_storage_or_policy(source_query):
    with pytest.raises(ValueError, match="registered Programme source layer"):
        sources.load_programme_evidence_source(
            source_query.scope, item_id=source_query.item_id, layer="private-contact"
        )
    assert source_query.events == []
