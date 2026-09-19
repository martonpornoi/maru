"""Exercise audited history paging with fake storage, not PostgreSQL acceptance."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from maru.authorization.policy import PolicyDecision
from maru.programme import queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture(params=["working", "delivery"])
def history(request, monkeypatch):
    kind = request.param
    actor, organization, edition, item = (UUID(int=i) for i in range(1, 5))
    events = []
    rows = [
        SimpleNamespace(
            sequence=i,
            internal_title=f"Private title {i}",
            working_summary="Private summary",
            technical_requirements="Private technical notes",
            accessibility_delivery="Private delivery notes",
            media_consent_notes="Private consent notes",
            actor_id=actor,
            reason="Retained synthetic rationale",
            occurred_at=datetime(2026, 9, 19, tzinfo=UTC),
            item_version=i,
        )
        for i in range(1, 206)
    ]
    scope = SimpleNamespace(
        actor_id=actor,
        organization_id=organization,
        edition_id=edition,
        decision=PolicyDecision(
            allowed=True,
            fields=frozenset({f"{kind}_history"}),
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="synthetic",
        ),
    )
    auth = Mock(side_effect=lambda **_kwargs: (events.append("authorize"), scope)[1])
    audit = Mock(side_effect=lambda _record: events.append("audit"))
    monkeypatch.setattr(queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries, "append_audit", audit)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)

    def item_filter(**kwargs):
        events.append("item")
        assert kwargs == {
            "id": item,
            "organization_id": organization,
            "edition_id": edition,
        }
        return SimpleNamespace(exists=lambda: True)

    item_select = Mock(side_effect=item_filter)
    monkeypatch.setattr(queries.ProgrammeItem.objects, "filter", item_select)

    def chain(selected):
        result = MagicMock()

        def order(*fields):
            assert fields == ("-sequence", "-id")
            return sorted(selected, key=lambda row: row.sequence, reverse=True)

        def filter_older(**kwargs):
            assert set(kwargs) == {"sequence__lt"}
            return chain(
                [row for row in selected if row.sequence < kwargs["sequence__lt"]]
            )

        result.order_by.side_effect = order
        result.filter.side_effect = filter_older
        return result

    def revisions_filter(**kwargs):
        events.append("revisions")
        assert kwargs == {
            "item_id": item,
            "organization_id": organization,
            "edition_id": edition,
        }
        return chain(rows)

    revision_select = Mock(side_effect=revisions_filter)
    model = (
        queries.ProgrammeWorkingRevision
        if kind == "working"
        else queries.ProgrammeDeliveryRevision
    )
    monkeypatch.setattr(model.objects, "filter", revision_select)
    return SimpleNamespace(
        kind=kind,
        query=getattr(queries, f"list_programme_{kind}_history"),
        args={
            "actor_id": actor,
            "organization_id": organization,
            "edition_id": edition,
            "item_id": item,
            "reason": "Inspect authorized retained history",
        },
        events=events,
        auth=auth,
        audit=audit,
        scope=scope,
        item_select=item_select,
        revision_select=revision_select,
    )


def test_all_history_is_reachable_beyond_default_ceiling(history):
    first = history.query(**history.args, limit=200)
    second = history.query(
        **history.args, limit=200, before_sequence=first[-1].sequence
    )
    end = history.query(**history.args, limit=200, before_sequence=second[-1].sequence)
    assert [row.sequence for row in (*first, *second)] == list(range(205, 0, -1))
    assert end == ()
    assert (
        history.events == ["authorize", "item", "revisions", "authorize", "audit"] * 3
    )
    assert [
        call.args[0].safe_metadata["target_count"]
        for call in history.audit.call_args_list
    ] == [200, 5, 0]
    for call in history.auth.call_args_list:
        assert call.kwargs["requested_fields"] == frozenset({f"{history.kind}_history"})
        assert call.kwargs["capability_code"] == (
            "programme.view_private"
            if history.kind == "working"
            else "programme.view_delivery"
        )
    assert "Private" not in repr(history.audit.call_args_list)


def test_default_page_and_exclusive_cursor_preserve_order(history):
    assert len(history.query(**history.args)) == 100
    assert [
        row.sequence
        for row in history.query(**history.args, limit=2, before_sequence=204)
    ] == [203, 202]
    assert (
        len(
            history.query(
                **history.args, limit=1, before_sequence=9_223_372_036_854_775_807
            )
        )
        == 1
    )


@pytest.mark.parametrize(
    "cursor", [0, -1, True, False, "2", 2.0, 9_223_372_036_854_775_808]
)
def test_invalid_cursor_never_reaches_storage(history, cursor):
    with pytest.raises(ValueError, match="positive bigint"):
        history.query(**history.args, before_sequence=cursor)
    history.item_select.assert_not_called()
    history.revision_select.assert_not_called()


@pytest.mark.parametrize("stage", ["before", "after"])
def test_cursor_does_not_bypass_initial_or_final_denial(history, stage):
    history.auth.side_effect = (
        ProgrammeAuthorizationDeniedError
        if stage == "before"
        else [history.scope, ProgrammeAuthorizationDeniedError]
    )
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        history.query(**history.args, before_sequence=204)
    assert history.revision_select.call_count == (0 if stage == "before" else 1)
    assert history.audit.call_count == 1
    assert history.audit.call_args.args[0].outcome == "deny"
    assert "Private" not in repr(history.audit.call_args)


def test_audit_failure_releases_no_page(history):
    history.audit.side_effect = RuntimeError("synthetic audit outage")
    with pytest.raises(RuntimeError, match="synthetic audit outage"):
        history.query(**history.args, before_sequence=204)


def test_wrong_scoped_item_never_reads_revisions(history):
    history.item_select.side_effect = None
    history.item_select.return_value = SimpleNamespace(exists=lambda: False)
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        history.query(**history.args, before_sequence=204)
    history.revision_select.assert_not_called()
    history.audit.assert_not_called()
