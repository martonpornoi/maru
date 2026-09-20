"""Check complete inventory and person-before-audit lock ordering."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.programme import exit_owner_queries as owner
from maru.programme import queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.exit_lineage_queries import (
    ProgrammeExitLineage,
    ProgrammeExitLineageCollection,
)


@pytest.fixture
def source(monkeypatch):
    args = dict(
        zip(
            ("actor_id", "organization_id", "edition_id", "correlation_id"),
            (UUID(int=i) for i in range(10, 14)),
            strict=True,
        )
    )
    args["reason"] = "Synthetic complete owner evidence"
    items, people, order = [UUID(int=20), UUID(int=21)], [UUID(int=1), UUID(int=30)], []
    inventory, hosts = Mock(), Mock()
    inventory.return_value.order_by.return_value.values_list.side_effect = (
        lambda *_a, **_k: items
    )
    host_ids = hosts.return_value.order_by.return_value.values_list.return_value
    host_ids.distinct.side_effect = lambda: people
    monkeypatch.setattr(owner.ProgrammeItem.objects, "filter", inventory)
    monkeypatch.setattr(owner.ProgrammeHostRelationship.objects, "filter", hosts)
    locks = Mock(
        side_effect=lambda **kw: (order.append("people"), kw["account_ids"])[1]
    )
    monkeypatch.setattr(owner, "lock_account_references_for_evidence", locks)
    monkeypatch.setattr(
        owner, "lock_programme_staffing_scope", lambda **_: order.append("parent")
    )
    admit, audit = Mock(), Mock(side_effect=lambda **_: order.append("audit"))
    monkeypatch.setattr(owner, "_admit_lineage", admit)
    monkeypatch.setattr(
        queries, "authorize_programme_scope", Mock(return_value=SimpleNamespace())
    )
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    monkeypatch.setattr(queries, "_append_query_audit", audit)
    monkeypatch.setattr(queries, "_append_query_denial_audit", Mock())

    def lineage(**kw):
        order.append("lineage-audit")
        return ProgrammeExitLineage(
            kw["item_id"],
            5,
            (ProgrammeExitLineageCollection("working", ("id",), ((UUID(int=40),),)),),
        )

    def content(**kw):
        order.append("content")
        return SimpleNamespace(
            core=SimpleNamespace(
                private=SimpleNamespace(
                    item=SimpleNamespace(id=kw["item_id"], aggregate_version=5),
                )
            )
        )

    lineage_read, content_read, placements = (
        Mock(side_effect=lineage),
        Mock(side_effect=content),
        Mock(return_value=()),
    )
    monkeypatch.setattr(owner, "load_programme_exit_lineage", lineage_read)
    monkeypatch.setattr(owner, "load_programme_exit_item", content_read)
    monkeypatch.setattr(owner, "load_programme_exit_placement_histories", placements)
    return SimpleNamespace(
        args=args,
        items=items,
        people=people,
        order=order,
        inventory=inventory,
        hosts=hosts,
        locks=locks,
        admit=admit,
        audit=audit,
        lineage=lineage_read,
        content=content_read,
        placements=placements,
    )


def test_all_people_are_locked_before_first_audited_child(source):
    result = owner.load_programme_exit_owner(**source.args)
    assert tuple(item.lineage.item_id for item in result.items) == tuple(source.items)
    assert source.order[:3] == ["parent", "people", "lineage-audit"]
    assert source.order[-1] == "audit"
    source.locks.assert_called_once_with(
        account_ids=(UUID(int=1), UUID(int=10), UUID(int=30))
    )
    assert source.admit.call_count == 3
    assert source.audit.call_args.kwargs["target_count"] == 2
    scope = {key: source.args[key] for key in ("organization_id", "edition_id")}
    source.inventory.assert_called_once_with(**scope)
    source.hosts.assert_called_once_with(**scope, item_id__in=tuple(source.items))
    assert "00000000" not in repr(result)


def test_empty_owner_still_locks_actor_reauthorizes_and_audits(source):
    source.items.clear()
    source.people.clear()
    assert owner.load_programme_exit_owner(**source.args).items == ()
    source.locks.assert_called_once_with(account_ids=(source.args["actor_id"],))
    source.lineage.assert_not_called()
    assert source.admit.call_count == 3
    assert source.audit.call_args.kwargs["target_count"] == 0


@pytest.mark.parametrize(
    "guard",
    [
        "MAX_PROGRAMME_ITEMS_PER_EDITION",
        "MAX_PERSON_REFERENCE_BATCH",
        "MAX_OWNER_LINEAGE_ROWS",
    ],
)
def test_supported_bounds_refuse_whole_owner(source, monkeypatch, guard):
    monkeypatch.setattr(owner, guard, 1)
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        owner.load_programme_exit_owner(**source.args)
    source.audit.assert_not_called()
    if guard != "MAX_OWNER_LINEAGE_ROWS":
        source.lineage.assert_not_called()


@pytest.mark.parametrize("answer", [None, (), (UUID(int=10),)])
def test_missing_or_incomplete_identity_lock_set_refuses(source, answer):
    source.locks.side_effect = None
    source.locks.return_value = answer
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        owner.load_programme_exit_owner(**source.args)
    source.lineage.assert_not_called()
    source.audit.assert_not_called()


@pytest.mark.parametrize("field", ["item_id", "item_version"])
def test_lineage_content_mismatch_refuses(source, field):
    original = source.lineage.side_effect
    source.lineage.side_effect = lambda **kw: replace(
        original(**kw),
        **{
            field: UUID(int=99) if field == "item_id" else 9,
        },
    )
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        owner.load_programme_exit_owner(**source.args)
    source.audit.assert_not_called()


@pytest.mark.parametrize("initial", [True, False])
def test_initial_or_final_denial_refuses_owner(source, initial):
    source.admit.side_effect = ([None, None] if not initial else []) + [
        ProgrammeAuthorizationDeniedError()
    ]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        owner.load_programme_exit_owner(**source.args)
    source.audit.assert_not_called()
    if initial:
        source.inventory.assert_not_called()
        source.locks.assert_not_called()


@pytest.mark.parametrize("failure", ["lineage", "content", "placements", "audit"])
def test_any_child_or_final_audit_failure_withholds_whole_result(source, failure):
    getattr(source, failure).side_effect = RuntimeError("synthetic dependency failure")
    with pytest.raises(RuntimeError, match="synthetic dependency failure"):
        owner.load_programme_exit_owner(**source.args)
    if failure != "audit":
        source.audit.assert_not_called()
