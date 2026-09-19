"""Bounded placement inventory and collection feedback without native proof."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from maru.authorization.policy import PolicyDecision
from maru.programme import exit_placement_queries as exit_queries
from maru.programme import placement_queries as placements
from maru.programme import queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.commands import ProgrammeUnavailableError
from maru.programme.release_inputs import ProgrammePlacementDecisionKind as Kind


@pytest.fixture
def boundary(monkeypatch):
    request = placements.ProgrammePlacementReadRequest(
        *(UUID(int=i) for i in range(1, 5))
    )
    scope = SimpleNamespace(
        actor_id=request.actor_id,
        organization_id=request.organization_id,
        edition_id=request.edition_id,
        decision=PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="synthetic",
        ),
    )
    auth = Mock(return_value=scope)
    audit = Mock()
    monkeypatch.setattr(queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries, "append_audit", audit)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    admit = Mock()
    lock = Mock()
    monkeypatch.setattr(placements, "_admit", admit)
    monkeypatch.setattr(exit_queries, "_admit", admit)
    monkeypatch.setattr(placements, "lock_programme_staffing_scope", lock)
    monkeypatch.setattr(exit_queries, "lock_programme_staffing_scope", lock)
    return SimpleNamespace(
        request=request,
        item_id=UUID(int=5),
        scope=scope,
        auth=auth,
        audit=audit,
        admit=admit,
        lock=lock,
    )


@pytest.fixture
def inventory(boundary, monkeypatch):
    item_manager = Mock()
    item_manager.filter.return_value.exists.return_value = True
    monkeypatch.setattr(placements.ProgrammeItem, "objects", item_manager)
    rows = [{"placement_id": UUID(int=i), "through_sequence": i} for i in range(10, 13)]
    queryset = MagicMock()
    for method in ("filter", "values", "annotate", "order_by"):
        getattr(queryset, method).return_value = queryset
    queryset.__getitem__.side_effect = lambda limit: rows[limit]
    manager = Mock()
    manager.filter.return_value = queryset
    monkeypatch.setattr(placements.ProgrammePlacementDecision, "objects", manager)
    monkeypatch.setattr(placements, "PLACEMENT_HISTORY_PAGE_SIZE", 2)
    return SimpleNamespace(
        boundary=boundary,
        rows=rows,
        manager=manager,
        queryset=queryset,
        item_manager=item_manager,
    )


def _heads(boundary, **kwargs):
    return placements.list_programme_placement_history_heads(
        boundary.request,
        item_id=boundary.item_id,
        kind=Kind.ACCESSIBILITY_FIT,
        **kwargs,
    )


def test_inventory_groups_scoped_streams_and_uses_exclusive_keyset(inventory):
    b = inventory.boundary
    result = _heads(b, after_placement_id=UUID(int=9))
    assert [row.placement_id for row in result.entries] == [UUID(int=10), UUID(int=11)]
    assert result.next_after_placement_id == UUID(int=11)
    inventory.manager.filter.assert_called_once_with(
        organization_id=b.request.organization_id,
        edition_id=b.request.edition_id,
        item_id=b.item_id,
        kind=Kind.ACCESSIBILITY_FIT,
    )
    inventory.queryset.filter.assert_called_once_with(placement_id__gt=UUID(int=9))
    inventory.queryset.values.assert_called_once_with("placement_id")
    aggregate = inventory.queryset.annotate.call_args.kwargs["through_sequence"]
    assert aggregate.source_expressions[0].name == "sequence"
    inventory.queryset.order_by.assert_called_once_with("placement_id")
    inventory.queryset.__getitem__.assert_called_once_with(slice(None, 3))
    assert all(call.kwargs["history"] for call in b.admit.call_args_list)
    assert b.auth.call_args.kwargs["requested_fields"] == frozenset(
        {"placement_decisions", "delivery_history"}
    )
    assert b.audit.call_args.args[0].safe_metadata["target_count"] == 2


def test_existing_item_exhaustion_is_audited_but_unknown_item_is_unavailable(inventory):
    inventory.rows.clear()
    assert _heads(inventory.boundary).entries == ()
    assert inventory.boundary.audit.call_count == 1
    inventory.item_manager.filter.return_value.exists.return_value = False
    with pytest.raises(ProgrammeUnavailableError):
        _heads(inventory.boundary)
    assert inventory.boundary.audit.call_count == 1


@pytest.mark.parametrize("ceiling", [None, 0, True, 1002])
def test_corrupt_head_ceiling_is_not_a_partial_inventory(inventory, ceiling):
    inventory.rows[0]["through_sequence"] = ceiling
    with pytest.raises(ProgrammeUnavailableError):
        _heads(inventory.boundary)
    inventory.boundary.audit.assert_not_called()


@pytest.mark.parametrize("denial_call", [0, 1, 2])
def test_head_admission_failure_releases_no_inventory(inventory, denial_call):
    b = inventory.boundary
    b.admit.side_effect = [None] * denial_call + [ProgrammeAuthorizationDeniedError]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        _heads(b)
    if denial_call == 0:
        inventory.manager.filter.assert_not_called()


@pytest.fixture
def collector(boundary, monkeypatch):
    b = boundary
    monkeypatch.setattr(placements, "PLACEMENT_HISTORY_PAGE_SIZE", 1)
    streams = {
        Kind.ACCESSIBILITY_FIT: [(10, 2), (11, 1)],
        Kind.STAFFING_NOT_REQUIRED: [(20, 2)],
    }
    calls = []

    def heads(request, *, item_id, kind, after_placement_id, **_kwargs):
        assert request == b.request
        assert item_id == b.item_id
        calls.append(("heads", kind, after_placement_id))
        choices = [
            pair
            for pair in streams[kind]
            if after_placement_id is None or UUID(int=pair[0]) > after_placement_id
        ]
        entries = tuple(
            placements.ProgrammePlacementHistoryHead(UUID(int=identifier), through)
            for identifier, through in choices[:1]
        )
        return placements.ProgrammePlacementHistoryHeadsPage(
            entries, entries[-1].placement_id if len(choices) > 1 else None
        )

    def history(
        request,
        *,
        item_id,
        kind,
        placement_id,
        through_sequence,
        after_sequence,
        **_kwargs,
    ):
        assert request == b.request
        assert item_id == b.item_id
        assert (placement_id.int, through_sequence) in streams[kind]
        calls.append(("history", kind, placement_id, through_sequence, after_sequence))
        entry = placements.ProgrammePlacementHistoryEntry(
            UUID(int=100 + after_sequence),
            after_sequence + 1,
            "withdrawn",
            UUID(int=50),
            1,
            "a" * 64,
            request.actor_id,
            "Restricted rationale",
            datetime(2026, 9, 19, tzinfo=UTC),
        )
        return placements.ProgrammePlacementHistoryPage(
            through_sequence,
            (entry,),
            entry.sequence if entry.sequence < through_sequence else None,
        )

    head_reader, history_reader = Mock(side_effect=heads), Mock(side_effect=history)
    monkeypatch.setattr(
        placements, "list_programme_placement_history_heads", head_reader
    )
    monkeypatch.setattr(
        placements, "load_programme_placement_decision_history", history_reader
    )
    return SimpleNamespace(
        boundary=b,
        streams=streams,
        calls=calls,
        head_reader=head_reader,
        history_reader=history_reader,
    )


def _collect(collector):
    b = collector.boundary
    return exit_queries.load_programme_exit_placement_histories(
        b.request, item_id=b.item_id, reason="Retain placement evidence"
    )


def test_collection_keeps_both_independent_stream_kinds_and_complete_pages(collector):
    result = _collect(collector)
    assert len(result) == 3
    assert sum(len(stream.entries) for stream in result) == 5
    assert [stream.head.through_sequence for stream in result] == [2, 1, 2]
    assert all(row.item_version == 1 for stream in result for row in stream.entries)
    assert all(row.state == "withdrawn" for stream in result for row in stream.entries)
    assert "Restricted" not in repr(result)
    assert len([call for call in collector.calls if call[0] == "heads"]) == 3
    b = collector.boundary
    assert [call.args[1] for call in b.admit.call_args_list] == list(Kind) * 2
    b.lock.assert_called_once_with(
        organization_id=b.request.organization_id, edition_id=b.request.edition_id
    )
    record = b.audit.call_args.args[0]
    assert record.operation == "programme.query.exit_placement_histories"
    assert record.safe_metadata["target_count"] == 3


@pytest.mark.parametrize("denial_call", range(4))
def test_each_initial_or_final_kind_denial_refuses_collection(collector, denial_call):
    b = collector.boundary
    b.admit.side_effect = [None] * denial_call + [ProgrammeAuthorizationDeniedError]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        _collect(collector)
    assert b.audit.call_args.args[0].outcome == "deny"
    if denial_call < 2:
        collector.head_reader.assert_not_called()


@pytest.mark.parametrize(
    "bound", ["MAX_EXIT_PLACEMENT_STREAMS", "MAX_EXIT_PLACEMENT_RECORDS"]
)
def test_collection_bounds_refuse_instead_of_truncating(collector, monkeypatch, bound):
    monkeypatch.setattr(exit_queries, bound, 1)
    with pytest.raises(ProgrammeUnavailableError):
        _collect(collector)
    collector.boundary.audit.assert_not_called()


def test_final_audit_failure_returns_no_decisions(collector):
    collector.boundary.audit.side_effect = RuntimeError("synthetic audit failure")
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        _collect(collector)


@pytest.mark.parametrize(
    "shape",
    [
        "empty_continuation",
        "bad_cursor",
        "repeated_head",
        "overfull",
        "invalid_sequence",
    ],
)
def test_head_pages_cannot_loop_or_invent_history(collector, shape):
    head = placements.ProgrammePlacementHistoryHead(UUID(int=10), 2)
    pages = {
        "empty_continuation": [
            placements.ProgrammePlacementHistoryHeadsPage((), UUID(int=10))
        ],
        "bad_cursor": [
            placements.ProgrammePlacementHistoryHeadsPage((head,), UUID(int=11))
        ],
        "repeated_head": [
            placements.ProgrammePlacementHistoryHeadsPage((head,), head.placement_id)
        ]
        * 2,
        "overfull": [placements.ProgrammePlacementHistoryHeadsPage((head, head), None)],
        "invalid_sequence": [
            placements.ProgrammePlacementHistoryHeadsPage(
                (
                    placements.ProgrammePlacementHistoryHead(
                        UUID(int=10), through_sequence=True
                    ),
                ),
                None,
            )
        ],
    }
    collector.head_reader.side_effect = pages[shape]
    with pytest.raises(ProgrammeUnavailableError):
        _collect(collector)


@pytest.mark.parametrize("shape", ["gap", "empty", "wrong_ceiling", "wrong_cursor"])
def test_fixed_history_cannot_gap_truncate_or_change_ceiling(collector, shape):
    row = placements.ProgrammePlacementHistoryEntry(
        UUID(int=100),
        2 if shape == "gap" else 1,
        "withdrawn",
        UUID(int=50),
        1,
        "a" * 64,
        UUID(int=1),
        "Private",
        datetime(2026, 9, 19, tzinfo=UTC),
    )
    collector.history_reader.side_effect = None
    collector.history_reader.return_value = placements.ProgrammePlacementHistoryPage(
        3 if shape == "wrong_ceiling" else 2,
        () if shape == "empty" else (row,),
        None if shape == "wrong_cursor" else 1,
    )
    with pytest.raises(ProgrammeUnavailableError):
        _collect(collector)


def test_no_retained_decisions_is_an_audited_empty_collection(collector):
    collector.streams[Kind.ACCESSIBILITY_FIT] = []
    collector.streams[Kind.STAFFING_NOT_REQUIRED] = []
    assert _collect(collector) == ()
    assert collector.boundary.audit.call_args.args[0].safe_metadata["target_count"] == 0
    collector.history_reader.assert_not_called()


@pytest.mark.parametrize("call", [0, 1])
def test_initial_and_final_primary_policy_denial_returns_no_heads(inventory, call):
    b = inventory.boundary
    b.auth.side_effect = [b.scope] * call + [ProgrammeAuthorizationDeniedError]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        _heads(b)
    assert b.audit.call_args.args[0].outcome == "deny"


def test_head_audit_failure_withholds_inventory(inventory):
    inventory.boundary.audit.side_effect = RuntimeError("synthetic audit failure")
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        _heads(inventory.boundary)
