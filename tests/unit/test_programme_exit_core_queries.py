"""Verify owner-core orchestration and completeness without database acceptance."""

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

from maru.authorization.policy import PolicyDecision
from maru.programme import exit_core_queries as core
from maru.programme import queries
from maru.programme.authorization import ProgrammeAuthorizationDeniedError
from maru.programme.exit_core_queries import _readiness_history, _sequence_history


@pytest.fixture
def owner(monkeypatch):
    actor, organization, edition, item, correlation = (UUID(int=i) for i in range(1, 6))
    args = {
        "actor_id": actor,
        "organization_id": organization,
        "edition_id": edition,
        "item_id": item,
        "correlation_id": correlation,
        "reason": "Inspect retained core",
    }
    events = []
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
    auth = Mock(
        side_effect=lambda **kwargs: (
            events.append("lock" if kwargs.get("lock") else "authorize"),
            scope,
        )[1]
    )
    monkeypatch.setattr(queries, "authorize_programme_scope", auth)
    monkeypatch.setattr(core, "authorize_programme_scope", auth)
    monkeypatch.setattr(queries.transaction, "atomic", nullcontext)
    audit = Mock(side_effect=lambda _record: events.append("audit"))
    monkeypatch.setattr(queries, "append_audit", audit)
    working = queries.ProgrammeWorkingHistoryEntryProjection(
        1,
        "Private title",
        "Private summary",
        actor,
        "Private reason",
        datetime(2026, 9, 19, tzinfo=UTC),
        1,
    )
    private = queries.ProgrammePrivateItemProjection(
        queries.ProgrammeItemProjection(
            item, "ceremony", "organizer_core", "active", 1
        ),
        queries.ProgrammeWorkingProjection("Private title", "Private summary", 1),
    )
    readers = {}
    for name, result in {
        "load_programme_private_item": private,
        "list_programme_working_history": (working,),
        "list_programme_delivery_history": (),
        "list_programme_discussion": (),
        "list_programme_readiness_history": (),
        "list_programme_public_copy_review_history": (),
    }.items():

        def read(*, result=result, name=name, **kwargs):
            events.append(name)
            for key, value in args.items():
                assert kwargs[key] == value
            assert kwargs["source_channel"] == "programme-exit"
            return result

        readers[name] = Mock(side_effect=read)
        monkeypatch.setattr(queries, name, readers[name])
    return SimpleNamespace(
        args=args,
        events=events,
        auth=auth,
        audit=audit,
        scope=scope,
        readers=readers,
        private=private,
        working=working,
    )


def test_core_preserves_private_layers_and_all_current_authority_checks(owner):
    result = core.load_programme_exit_core(**owner.args)
    assert result.private == owner.private
    assert result.working == (owner.working,)
    assert (
        result.delivery
        == result.discussion
        == result.readiness
        == result.copy_reviews
        == ()
    )
    assert "Private" not in repr(result)
    assert owner.events[:5] == ["authorize", "lock", "lock", "lock", "lock"]
    assert owner.events[-6:] == ["authorize"] * 5 + ["audit"]
    locks = [
        call.kwargs for call in owner.auth.call_args_list if call.kwargs.get("lock")
    ]
    assert [call["capability_code"] for call in locks] == [
        "programme.view_private",
        "programme.view_delivery",
        "programme.view_discussion",
        "programme.view_readiness",
    ]
    assert locks[2]["requested_fields"] == frozenset({"discussion_entries"})
    assert "public_copy_review_history" in locks[0]["requested_fields"]
    record = owner.audit.call_args.args[0]
    assert record.operation == "programme.query.exit_core"
    assert record.target_id == owner.args["item_id"]
    assert record.safe_metadata["target_count"] == 1
    assert "Private" not in repr(record.safe_metadata)


@pytest.mark.parametrize("call", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
def test_any_initial_locked_or_final_denial_releases_nothing(owner, call):
    owner.auth.side_effect = [owner.scope] * call + [ProgrammeAuthorizationDeniedError]
    with pytest.raises(ProgrammeAuthorizationDeniedError):
        core.load_programme_exit_core(**owner.args)
    assert owner.audit.call_args.args[0].outcome == "deny"
    if call <= 4:
        assert all(reader.call_count == 0 for reader in owner.readers.values())


@pytest.mark.parametrize("missing", [True, False])
def test_missing_or_mismatched_working_history_is_not_complete(owner, missing):
    reader = owner.readers["list_programme_working_history"]
    reader.side_effect = None
    reader.return_value = (
        ()
        if missing
        else (
            queries.ProgrammeWorkingHistoryEntryProjection(
                1,
                "Different",
                "Private summary",
                owner.args["actor_id"],
                "Reason",
                datetime(2026, 9, 19, tzinfo=UTC),
                1,
            ),
        )
    )
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        core.load_programme_exit_core(**owner.args)
    owner.audit.assert_not_called()


def test_core_audit_failure_releases_nothing(owner):
    owner.audit.side_effect = RuntimeError("synthetic audit unavailable")
    with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
        core.load_programme_exit_core(**owner.args)


def test_sequence_collection_reaches_past_full_pages(monkeypatch):
    monkeypatch.setattr(queries, "MAX_PROGRAMME_QUERY_ITEMS", 2)
    read = Mock(side_effect=[(5, 4), (3, 2), (1,)])
    assert _sequence_history(read, lambda value: value, 5) == (5, 4, 3, 2, 1)
    assert [call.args[0] for call in read.call_args_list] == [None, 4, 2]


@pytest.mark.parametrize(
    ("pages", "maximum"),
    [
        ([(3, 1)], 5),
        ([(2, 2)], 5),
        ([(3, 2), ()], 5),
        ([(2, 1), (2, 1)], 5),
        ([(5, 4), (3, 2), (1,)], 4),
        ([(True,)], 5),
        ([(0,)], 5),
        ([(3, 2, 1)], 5),
    ],
)
def test_sequence_gaps_repetition_invalid_and_overflow_refuse(
    monkeypatch, pages, maximum
):
    monkeypatch.setattr(queries, "MAX_PROGRAMME_QUERY_ITEMS", 2)
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        _sequence_history(Mock(side_effect=pages), lambda value: value, maximum)


def _entry(sequence, concern="public_copy", kind="evidence"):
    return SimpleNamespace(
        sequence=sequence, concern=concern, kind=kind, item_version=sequence
    )


def test_readiness_checks_each_concern_and_kind_sequence(monkeypatch):
    monkeypatch.setattr(queries, "MAX_PROGRAMME_QUERY_ITEMS", 2)
    rows = (_entry(2), _entry(1, "host_confirmation"), _entry(1))
    assert _readiness_history(Mock(side_effect=[rows[:2], rows[2:]])) == rows


@pytest.mark.parametrize("rows", [(_entry(2),), (_entry(1), _entry(1)), (_entry(0),)])
def test_incomplete_readiness_group_is_not_complete(rows):
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        _readiness_history(Mock(return_value=rows))


def test_readiness_bound_refuses_without_partial_result(monkeypatch):
    monkeypatch.setattr(core, "MAX_CORE_READINESS_ENTRIES", 1)
    with pytest.raises(queries.ProgrammeQueryUnavailableError):
        _readiness_history(
            Mock(return_value=(_entry(1), _entry(1, "host_confirmation")))
        )
