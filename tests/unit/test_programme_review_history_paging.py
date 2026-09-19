"""Check real protected-query composition with fake storage, never native proof."""

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import UUID

import pytest

from maru.authorization.policy import PolicyDecision
from maru.programme import queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError


@pytest.fixture
def boundary(monkeypatch):
    actor, organization, edition, item = (UUID(int=i) for i in range(1, 5))
    scope = SimpleNamespace(
        actor_id=actor,
        organization_id=organization,
        edition_id=edition,
        decision=PolicyDecision(
            allowed=True,
            fields=frozenset(),
            obligations=frozenset({"audit_sensitive_read"}),
            reason_code="synthetic",
        ),
    )
    events = []
    auth = Mock(side_effect=lambda **_kwargs: (events.append("authorize"), scope)[1])
    audit = Mock(side_effect=lambda _record: events.append("audit"))
    monkeypatch.setattr(queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries, "append_audit", audit)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    return SimpleNamespace(
        args={
            "actor_id": actor,
            "organization_id": organization,
            "edition_id": edition,
            "item_id": item,
            "reason": "Inspect private history",
        },
        actor=actor,
        organization=organization,
        edition=edition,
        item=item,
        scope=scope,
        auth=auth,
        audit=audit,
        events=events,
    )


@pytest.fixture
def readiness(boundary, monkeypatch):
    instant = datetime(2026, 9, 19, tzinfo=UTC)
    # The compound position, not the aggregate version alone, is unique.
    positions = [
        (7, "public_copy", "requirement_revision", 2),
        (7, "public_copy", "evidence", 3),
        (7, "public_copy", "evidence", 2),
        (7, "host_confirmation", "evidence", 1),
        (6, "public_copy", "evidence", 1),
    ]
    rows = [
        (
            concern,
            kind,
            sequence,
            version,
            1,
            1,
            None,
            "satisfied",
            "working",
            1,
            "Private rationale",
            boundary.actor,
            "Private decision",
            instant,
        )
        for version, concern, kind, sequence in positions
    ]
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor

    def execute(sql, params):
        boundary.events.append("select")
        assert params[:7] == [
            boundary.item,
            boundary.organization,
            boundary.edition,
            boundary.organization,
            boundary.edition,
            boundary.organization,
            boundary.edition,
        ]
        normalized = " ".join(sql.split())
        assert (
            "( combined.item_version, combined.concern, combined.kind, "
            "combined.sequence ) < (%s::bigint, %s::varchar, %s::varchar, %s::bigint)"
            in normalized
        )
        assert (
            "ORDER BY history.item_version DESC, history.concern DESC, "
            "history.kind DESC, history.sequence DESC" in normalized
        )
        selected = [
            row
            for row in rows
            if params[7] or (row[3], row[0], row[1], row[2]) < tuple(params[8:12])
        ][: params[12]]
        cursor.fetchall.return_value = selected or [(None,) * 14]

    cursor.execute.side_effect = execute
    monkeypatch.setattr(queries.connection, "cursor", Mock(return_value=cursor))
    boundary.cursor = cursor
    boundary.positions = positions
    return boundary


def test_compound_cursor_traverses_ties_and_audits_every_page(readiness):
    before = None
    seen = []
    while True:
        page = queries.list_programme_readiness_history(
            **readiness.args, limit=1, before=before
        )
        if not page:
            break
        row = page[-1]
        before = queries.ProgrammeReadinessHistoryCursor(
            row.item_version, row.concern, row.kind, row.sequence
        )
        seen.append((before.item_version, before.concern, before.kind, before.sequence))
        assert len(seen) <= len(readiness.positions)
    assert seen == readiness.positions
    assert readiness.events == ["authorize", "select", "authorize", "audit"] * 6
    assert all(
        call.kwargs["requested_fields"] == frozenset({"readiness_history"})
        for call in readiness.auth.call_args_list
    )
    assert "Private rationale" not in repr(readiness.audit.call_args_list)
    assert readiness.audit.call_args.args[0].safe_metadata["target_count"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("item_version", None),
        ("item_version", 0),
        ("item_version", True),
        ("item_version", 2**63),
        ("sequence", None),
        ("sequence", -1),
        ("sequence", "1"),
        ("sequence", 2**63),
        ("concern", []),
        ("concern", "unknown"),
        ("kind", "unknown"),
        ("kind", []),
    ],
)
def test_invalid_compound_cursor_reads_nothing(readiness, field, value):
    valid = queries.ProgrammeReadinessHistoryCursor(7, "public_copy", "evidence", 1)
    with pytest.raises(ValueError, match="cursor"):
        queries.list_programme_readiness_history(
            **readiness.args, before=replace(valid, **{field: value})
        )
    readiness.cursor.execute.assert_not_called()


def test_wrong_cursor_type_and_foreign_item_remain_unavailable(readiness):
    with pytest.raises(ValueError, match="cursor"):
        queries.list_programme_readiness_history(
            **readiness.args, before=(7, "public_copy", "evidence", 1)
        )
    readiness.cursor.execute.side_effect = None
    readiness.cursor.fetchall.return_value = []
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        queries.list_programme_readiness_history(**readiness.args)
    readiness.audit.assert_not_called()


@pytest.fixture
def reviews(boundary, monkeypatch):
    instant = datetime(2026, 9, 19, tzinfo=UTC)
    rows = [
        {
            "rendition_number": number,
            "source_item_version": number,
            "public_title": f"Retained private review {number}",
            "public_summary": "Private review",
            "public_content_note": "",
            "reviewed_by_id": boundary.actor,
            "review_reason": "Private review reason",
            "reviewed_at": instant,
            "withdrawal__occurred_at": instant if number == 1 else None,
            "withdrawal__actor_id": boundary.actor if number == 1 else None,
            "withdrawal__reason": "Private withdrawal reason" if number == 1 else None,
        }
        for number in (3, 2, 1)
    ]

    def chain(selected):
        result = MagicMock()
        result.order_by.side_effect = lambda *fields: (
            result if fields == ("-rendition_number", "-id") else None
        )

        def values(*fields):
            assert set(fields) == set(rows[0])
            return selected

        def older(**kwargs):
            assert set(kwargs) == {"rendition_number__lt"}
            return chain(
                [
                    row
                    for row in selected
                    if row["rendition_number"] < kwargs["rendition_number__lt"]
                ]
            )

        result.values.side_effect = values
        result.filter.side_effect = older
        return result

    def select(**kwargs):
        boundary.events.append("select")
        assert kwargs == {
            "item_id": boundary.item,
            "organization_id": boundary.organization,
            "edition_id": boundary.edition,
        }
        return chain(rows)

    storage = Mock(side_effect=select)
    monkeypatch.setattr(queries.ProgrammePublicRendition.objects, "filter", storage)
    monkeypatch.setattr(
        queries.ProgrammeItem.objects,
        "filter",
        Mock(return_value=SimpleNamespace(exists=lambda: True)),
    )
    boundary.storage = storage
    return boundary


def test_private_copy_history_keeps_withdrawal_evidence_on_older_pages(reviews):
    first = queries.list_programme_public_copy_review_history(**reviews.args, limit=2)
    second = queries.list_programme_public_copy_review_history(
        **reviews.args, limit=2, before_rendition_number=first[-1].rendition_number
    )
    assert [row.rendition_number for row in (*first, *second)] == [3, 2, 1]
    assert second[0].withdrawal_reason == "Private withdrawal reason"
    assert second[0].public_title == "Retained private review 1"
    assert (
        queries.list_programme_public_copy_review_history(
            **reviews.args, before_rendition_number=1
        )
        == ()
    )
    assert reviews.events == ["authorize", "select", "authorize", "audit"] * 3
    assert all(
        call.kwargs["requested_fields"] == frozenset({"public_copy_review_history"})
        and call.kwargs["capability_code"] == "programme.view_private"
        for call in reviews.auth.call_args_list
    )
    assert "Private withdrawal" not in repr(reviews.audit.call_args_list)


@pytest.mark.parametrize("cursor", [0, -1, True, "2", 2**63])
def test_invalid_review_cursor_reads_nothing(reviews, cursor):
    with pytest.raises(ValueError, match="cursor"):
        queries.list_programme_public_copy_review_history(
            **reviews.args, before_rendition_number=cursor
        )
    reviews.storage.assert_not_called()


@pytest.mark.parametrize("kind", ["readiness", "reviews"])
@pytest.mark.parametrize("stage", ["initial", "final", "audit"])
def test_each_history_page_refuses_denial_or_failed_audit(request, kind, stage):
    boundary = request.getfixturevalue(kind)
    read = (
        queries.list_programme_readiness_history
        if kind == "readiness"
        else queries.list_programme_public_copy_review_history
    )
    if stage == "initial":
        boundary.auth.side_effect = ProgrammeAuthorizationDeniedError
    elif stage == "final":
        boundary.auth.side_effect = [boundary.scope, ProgrammeAuthorizationDeniedError]
    else:
        boundary.audit.side_effect = RuntimeError("synthetic audit failure")
    with pytest.raises(RuntimeError):
        read(**boundary.args)
    if stage == "initial":
        assert "select" not in boundary.events
    if stage != "audit":
        assert boundary.audit.call_args.args[0].outcome == "deny"
