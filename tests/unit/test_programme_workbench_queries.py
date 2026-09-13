"""Exercise real query composition with fake storage, not database certification."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest
from django.db import DatabaseError

from maru.authorization.policy import PolicyDecision
from maru.programme import queries
from maru.programme import workbench_queries as workbench
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture
def query(monkeypatch):
    scope = workbench.ProgrammeWorkbenchRequest(*(UUID(int=i) for i in range(1, 5)))
    item = SimpleNamespace(
        id=UUID(int=5),
        kind="ceremony",
        provenance_kind="organizer_core",
        lifecycle="active",
        aggregate_version=7,
    )
    revision = SimpleNamespace(
        id=UUID(int=6),
        item_id=item.id,
        internal_title="Private label",
        working_summary="Private summary",
        item_version=6,
    )
    events = []
    admitted = SimpleNamespace(
        actor_id=scope.actor_id,
        organization_id=scope.organization_id,
        edition_id=scope.edition_id,
        decision=PolicyDecision(
            allowed=True,
            fields=frozenset({"item_summaries", "working_information"}),
            obligations=frozenset(),
            reason_code="synthetic",
        ),
    )

    def authorize(**kwargs):
        events.append("lock" if kwargs.get("lock") else "authorize")
        return admitted

    auth = Mock(side_effect=authorize)
    monkeypatch.setattr(queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(workbench, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    audit = Mock(side_effect=lambda _record: events.append("audit"))
    monkeypatch.setattr(queries, "append_audit", audit)
    storage = {}
    for model, result, listing in [
        (workbench.ProgrammeEditionControl, SimpleNamespace(aggregate_version=3), []),
        (workbench.ProgrammeItem, item, [item]),
        (workbench.ProgrammeWorkingRevision, revision, [revision]),
    ]:
        chain = MagicMock()
        chain.first.return_value = result
        chain.order_by.return_value = chain
        chain.distinct.return_value = chain
        chain.only.return_value = chain
        chain.__getitem__.side_effect = lambda selection, rows=listing: rows[selection]
        chain.__iter__.side_effect = lambda rows=listing: iter(rows)

        def select(*, chain=chain, **kwargs):
            events.append("select")
            assert kwargs["organization_id"] == scope.organization_id
            assert kwargs["edition_id"] == scope.edition_id
            return chain

        select_mock = Mock(side_effect=select)
        monkeypatch.setattr(model.objects, "filter", select_mock)
        storage[model.__name__] = (select_mock, chain)
    return SimpleNamespace(
        scope=scope,
        item=item,
        revision=revision,
        events=events,
        auth=auth,
        admitted=admitted,
        audit=audit,
        storage=storage,
    )


def test_inventory_uses_complete_bounded_title_only_storage_and_audits_first(query):
    result = workbench.load_programme_workbench_inventory(query.scope)
    assert result.control_version == 3
    assert result.items[0].internal_title == "Private label"
    assert "Private summary" not in repr(result)
    assert query.events[:2] == ["authorize", "lock"]
    assert query.events[-2:] == ["authorize", "audit"]
    record = query.audit.call_args.args[0]
    assert record.operation == "programme.query.workbench_inventory"
    assert record.safe_metadata["target_count"] == 1
    chain = query.storage["ProgrammeWorkingRevision"][1]
    chain.only.assert_called_once_with(
        "id", "item_id", "internal_title", "item_version"
    )
    assert "working_summary" not in chain.only.call_args.args


def test_item_query_binds_exact_version_working_source_and_audit(query):
    result = workbench.load_programme_workbench_item(query.scope, item_id=query.item.id)
    assert result.working_revision_id == query.revision.id
    assert result.private.item.aggregate_version == 7
    assert result.private.working.item_version == 6
    assert result.private.working.working_summary == "Private summary"
    assert query.events[:2] == ["authorize", "lock"]
    assert query.events[-2:] == ["authorize", "audit"]
    assert query.audit.call_args.args[0].target_id == query.item.id


@pytest.mark.parametrize("item_read", [False, True])
def test_initial_denial_never_reaches_storage(query, item_read):
    query.auth.side_effect = ProgrammeAuthorizationDeniedError
    loader = (
        (
            lambda: workbench.load_programme_workbench_item(
                query.scope, item_id=query.item.id
            )
        )
        if item_read
        else lambda: workbench.load_programme_workbench_inventory(query.scope)
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        loader()
    assert "select" not in query.events
    assert query.audit.call_args.args[0].outcome == "deny"


@pytest.mark.parametrize("denial_at", [2, 3])
def test_locked_or_final_reauthorization_denial_returns_no_projection(query, denial_at):
    count = 0

    def authorize(**_kwargs):
        nonlocal count
        count += 1
        if count == denial_at:
            raise ProgrammeAuthorizationDeniedError
        return query.admitted

    query.auth.side_effect = authorize
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        workbench.load_programme_workbench_item(query.scope, item_id=query.item.id)
    assert all(call.args[0].outcome == "deny" for call in query.audit.call_args_list)
    if denial_at == 2:
        assert "select" not in query.events


@pytest.mark.parametrize("item_read", [False, True])
def test_required_audit_failure_prevents_return(query, item_read):
    query.audit.side_effect = DatabaseError("Synthetic audit unavailable")
    loader = (
        (
            lambda: workbench.load_programme_workbench_item(
                query.scope, item_id=query.item.id
            )
        )
        if item_read
        else lambda: workbench.load_programme_workbench_inventory(query.scope)
    )
    with pytest.raises(DatabaseError):
        loader()


def test_overflow_refuses_partial_inventory_before_loading_revisions(
    query, monkeypatch
):
    monkeypatch.setattr(workbench, "MAX_PROGRAMME_ITEMS_PER_EDITION", 0)
    with pytest.raises(queries.ProgrammeTimetableInventoryLimitError):
        workbench.load_programme_workbench_inventory(query.scope)
    query.storage["ProgrammeWorkingRevision"][0].assert_not_called()
    query.audit.assert_not_called()


def test_empty_scope_has_zero_creation_version_not_a_fabricated_control(query):
    query.storage["ProgrammeEditionControl"][1].first.return_value = None
    query.storage["ProgrammeItem"][1].__getitem__.side_effect = lambda _selection: []
    query.storage["ProgrammeWorkingRevision"][1].__iter__.side_effect = lambda: iter(())
    result = workbench.load_programme_workbench_inventory(query.scope)
    assert result == workbench.ProgrammeWorkbenchInventory(0, ())


@pytest.mark.parametrize("missing", ["control", "working"])
def test_incomplete_inventory_is_unavailable_not_empty_or_partial(query, missing):
    if missing == "control":
        query.storage["ProgrammeEditionControl"][1].first.return_value = None
    else:
        query.storage["ProgrammeWorkingRevision"][1].__iter__.side_effect = lambda: (
            iter(())
        )
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        workbench.load_programme_workbench_inventory(query.scope)
    query.audit.assert_not_called()


@pytest.mark.parametrize("missing", ["ProgrammeItem", "ProgrammeWorkingRevision"])
def test_missing_or_foreign_item_reference_has_no_partial_item(query, missing):
    query.storage[missing][1].first.return_value = None
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        workbench.load_programme_workbench_item(query.scope, item_id=query.item.id)
    query.audit.assert_not_called()
