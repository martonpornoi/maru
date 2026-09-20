"""Exercise the real composed read boundary with isolated owner storage doubles."""

from contextlib import nullcontext
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.programme import exit_lineage_queries as lineage
from maru.programme import queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.release_inputs import ProgrammePlacementDecisionKind


@pytest.fixture
def archive(monkeypatch):
    args = {
        key: UUID(int=index)
        for index, key in enumerate(
            ("actor_id", "organization_id", "edition_id", "item_id", "correlation_id"),
            1,
        )
    }
    args["reason"] = "Inspect synthetic archive lineage"
    calls = []
    purpose = Mock(side_effect=lambda **_: calls.append("purpose"))
    source = Mock(side_effect=lambda **_: calls.append("source"))
    placement = Mock(side_effect=lambda *_args, **_: calls.append("placement"))
    lock = Mock(side_effect=lambda **_: calls.append("lock"))
    audit = Mock(side_effect=lambda **_: calls.append("audit"))
    outer = Mock(return_value=SimpleNamespace())
    monkeypatch.setattr(lineage, "authorize_programme_archive_scope", purpose)
    monkeypatch.setattr(lineage, "authorize_programme_scope", source)
    monkeypatch.setattr(lineage, "_admit", placement)
    monkeypatch.setattr(lineage, "lock_programme_staffing_scope", lock)
    monkeypatch.setattr(queries, "authorize_programme_scope", outer)
    monkeypatch.setattr(queries, "_append_query_audit", audit)
    denial = Mock()
    monkeypatch.setattr(queries, "_append_query_denial_audit", denial)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    item = Mock()
    item.only.return_value.first.return_value = SimpleNamespace(aggregate_version=7)
    item_filter = Mock(side_effect=lambda **_: (calls.append("item"), item)[1])
    monkeypatch.setattr(lineage.models.ProgrammeItem.objects, "filter", item_filter)
    records = {}
    storage = {}
    for name, model, columns in lineage._COLLECTIONS:
        records[name] = []
        if name == "source_bindings":
            records[name] = [(UUID(int=21), "organizer-core@1", None, None)]
        elif name == "working":
            records[name] = [(UUID(int=22), 1, 1)]
        query = Mock()
        query.order_by.return_value.values_list.side_effect = (
            lambda *_columns, name=name: records[name]
        )
        select = Mock(return_value=query)
        monkeypatch.setattr(model._default_manager, "filter", select)
        storage[name] = (select, query, columns)
    return SimpleNamespace(
        args=args,
        calls=calls,
        purpose=purpose,
        source=source,
        placement=placement,
        lock=lock,
        audit=audit,
        outer=outer,
        denial=denial,
        item=item,
        item_filter=item_filter,
        records=records,
        storage=storage,
    )


def test_exact_scoped_declared_columns_and_required_audit(archive):
    result = lineage.load_programme_exit_lineage(**archive.args)
    assert result.item_id == archive.args["item_id"]
    assert result.item_version == 7
    assert len(result.collections) == 14
    expected_scope = {
        key: archive.args[key] for key in ("item_id", "organization_id", "edition_id")
    }
    archive.item_filter.assert_called_once_with(
        id=expected_scope["item_id"],
        organization_id=expected_scope["organization_id"],
        edition_id=expected_scope["edition_id"],
    )
    for collection in result.collections:
        select, query, columns = archive.storage[collection.name]
        select.assert_called_once_with(**expected_scope)
        query.order_by.assert_called_once_with("id")
        query.order_by.return_value.values_list.assert_called_once_with(*columns)
        assert collection.columns == columns
        assert collection.rows == tuple(archive.records[collection.name])
    assert archive.calls.index("lock") < archive.calls.index("item")
    assert archive.calls[-1] == "audit"
    assert archive.purpose.call_count == 3
    assert archive.source.call_count == 3 * len(lineage._FIELDS)
    assert archive.placement.call_count == 3 * len(ProgrammePlacementDecisionKind)
    assert archive.audit.call_args.kwargs["target_count"] == 2
    assert archive.audit.call_args.kwargs["operation"] == "programme.query.exit_lineage"
    assert all(
        call.kwargs["requested_fields"] == frozenset({"source_lineage"})
        for call in archive.purpose.call_args_list
    )
    for index, call in enumerate(archive.source.call_args_list):
        capability, fields = lineage._FIELDS[index % len(lineage._FIELDS)]
        assert call.kwargs["capability_code"] == capability
        assert call.kwargs["requested_fields"] == fields
    assert str(result.item_id) not in repr(result)
    assert "organizer-core" not in repr(result.collections[0])
    with pytest.raises(FrozenInstanceError):
        result.item_version = 8


@pytest.mark.parametrize("boundary", ["purpose", "source", "placement", "outer"])
@pytest.mark.parametrize("final", [False, True])
def test_initial_and_final_denial_withhold_everything(archive, boundary, final):
    guard = getattr(archive, boundary)
    counts = {
        "purpose": 3,
        "source": 3 * len(lineage._FIELDS),
        "placement": 3 * len(ProgrammePlacementDecisionKind),
        "outer": 2,
    }
    guard.side_effect = [None] * (counts[boundary] - 1 if final else 0) + [
        ProgrammeAuthorizationDeniedError()
    ]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        lineage.load_programme_exit_lineage(**archive.args)
    archive.audit.assert_not_called()
    archive.denial.assert_called_once()
    if not final:
        archive.item_filter.assert_not_called()


def test_missing_or_wrong_scope_item_is_unavailable_without_child_reads(archive):
    archive.item.only.return_value.first.return_value = None
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        lineage.load_programme_exit_lineage(**archive.args)
    for select, _query, _columns in archive.storage.values():
        select.assert_not_called()
    archive.audit.assert_not_called()


@pytest.mark.parametrize("bad", ["missing-binding", "duplicate-binding", "working"])
def test_required_evidence_is_never_silently_omitted(archive, bad):
    if bad == "missing-binding":
        archive.records["source_bindings"] = []
    elif bad == "duplicate-binding":
        archive.records["source_bindings"] *= 2
    else:
        archive.records["working"] = []
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        lineage.load_programme_exit_lineage(**archive.args)
    archive.audit.assert_not_called()


@pytest.mark.parametrize(
    "bound", ["MAX_LINEAGE_COLLECTION_ROWS", "MAX_LINEAGE_ITEM_ROWS"]
)
def test_exact_limit_passes_and_one_more_refuses_without_truncation(
    archive,
    monkeypatch,
    bound,
):
    monkeypatch.setattr(lineage, bound, 3)
    if bound == "MAX_LINEAGE_COLLECTION_ROWS":
        archive.records["working"] *= 3
    else:
        archive.records["working"] *= 2
    lineage.load_programme_exit_lineage(**archive.args)
    archive.audit.reset_mock()
    archive.records["working"].append((UUID(int=33), 4, 4))
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        lineage.load_programme_exit_lineage(**archive.args)
    archive.audit.assert_not_called()


def test_audit_failure_never_returns_lineage(archive):
    archive.audit.side_effect = RuntimeError("synthetic audit outage")
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        lineage.load_programme_exit_lineage(**archive.args)


def test_no_secret_or_private_body_fields_in_closed_schema():
    forbidden = {
        "title",
        "briefing",
        "body",
        "periods_digest",
        "request_digest",
        "idempotency_key",
        "reason",
        "email",
        "starts_at",
        "ends_at",
    }
    for _name, model, columns in lineage._COLLECTIONS:
        assert not forbidden.intersection(columns)
        # Metadata is inspected by tests only, never used to select exported fields.
        assert set(columns) <= {field.attname for field in model._meta.fields}
        assert columns[0] == "id"
    assert lineage.LINEAGE_CONTRACT == "programme.exit-lineage@1"
