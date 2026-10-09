"""Paged Guides inboxes preserve admission without scanning retained history."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.test import RequestFactory
from django.utils import timezone

from maru.authorization import guidance_access_queries as queries
from maru.authorization import guidance_readiness, provenance_readiness
from maru.core import navigation
from maru.events import guidance_activation_queries, guidance_setup_readiness
from maru.identity.models import Account


def matches(row, condition):
    if isinstance(condition, Q):
        values = [matches(row, child) for child in condition.children]
        result = any(values) if condition.connector == "OR" else all(values)
        return not result if condition.negated else result
    key, expected = condition
    field, _, operator = key.partition("__")
    actual = getattr(row, field)
    if operator == "gt":
        return actual > expected
    if operator == "lt":
        return actual < expected
    if operator == "in":
        return actual in expected
    if operator == "isnull":
        return (actual is None) is expected
    return actual == expected


class Records:
    """In-memory candidate selection; owner admission remains separately mocked."""

    def __init__(self, rows, fields=None, *, flat=False):
        self.rows, self.fields, self.flat = tuple(rows), fields, flat

    def filter(self, *conditions, **values):
        predicate = Q(*conditions, **values)
        return Records(row for row in self.rows if matches(row, predicate))

    def exclude(self, **values):
        return Records(row for row in self.rows if not matches(row, Q(**values)))

    def order_by(self, *fields):
        return Records(
            sorted(
                self.rows,
                key=lambda row: tuple(
                    getattr(row, field.removeprefix("-")) for field in fields
                ),
                reverse=fields[0].startswith("-"),
            )
        )

    def values_list(self, *fields, flat=False):
        return Records(self.rows, fields, flat=flat)

    def distinct(self):
        return tuple(dict.fromkeys(self))

    def only(self, *_fields):
        return self

    def iterator(self, **_kwargs):
        raise AssertionError("A personal page must not exhaust an unbounded iterator")

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        for row in self.rows:
            if self.fields:
                values = tuple(getattr(row, field) for field in self.fields)
                yield values[0] if self.flat else values
            else:
                yield row

    def __getitem__(self, selected):
        return tuple(self)[selected]


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(
        guidance_readiness,
        "guidance_authority_database_integrity_is_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        provenance_readiness,
        "authority_provenance_runtime_contract_is_ready",
        lambda: True,
    )
    actor = Account(id=UUID(int=5000), is_active=True)
    created_at = timezone.now()
    rows = [
        SimpleNamespace(
            id=UUID(int=index),
            organization_id=UUID(int=7000),
            edition_id=UUID(int=8000),
            requested_by_id=UUID(int=5001),
            approver_id=actor.pk,
            decision=object() if index <= 900 else None,
            decision_deadline=timezone.now() + timedelta(days=1),
            created_at=created_at + timedelta(seconds=index // 2),
        )
        for index in range(1, 1002)
    ]
    monkeypatch.setattr(
        queries, "GuidanceAccessRequest", SimpleNamespace(objects=Records(rows))
    )
    resolve = Mock(
        return_value=SimpleNamespace(
            adoption_profile_code="guidance_only",
            adoption_profile_version=1,
        )
    )
    monkeypatch.setattr(queries, "resolve_knowledge_edition_scope", resolve)
    load = Mock(
        side_effect=lambda **values: SimpleNamespace(
            request_id=values["request_id"],
            can_answer=True,
        )
    )
    monkeypatch.setattr(queries, "load_guidance_access_request", load)
    identity = Mock(return_value=SimpleNamespace(account_id=actor.id))
    monkeypatch.setattr(queries, "resolve_active_verified_account_reference", identity)
    return SimpleNamespace(
        actor=actor, rows=rows, load=load, resolve=resolve, identity=identity
    )


def page(store, **kwargs):
    return queries.list_my_guidance_access_requests_page(
        actor=store.actor, correlation_id=uuid4(), **kwargs
    )


def test_over_one_thousand_retained_requests_reach_live_pending_continuation(store):
    first = page(store, pending_only=True)
    assert len(first.items) == 100
    assert first.items[0].request_id == UUID(int=1001)
    assert first.next_cursor
    second = page(store, pending_only=True, cursor=first.next_cursor)
    assert [item.request_id for item in second.items] == [UUID(int=901)]
    assert second.next_cursor is None
    assert all(
        call.kwargs["actor"] is store.actor for call in store.load.call_args_list
    )


def test_denied_or_changed_sources_never_supply_rows_but_keep_continuation(store):
    def load(**values):
        identifier = values["request_id"]
        if identifier.int > 951:
            raise PermissionDenied
        return SimpleNamespace(request_id=identifier, can_answer=identifier.int == 901)

    store.load.side_effect = load
    first = page(store, pending_only=True)
    assert first.items == ()
    assert first.next_cursor
    second = page(store, pending_only=True, cursor=first.next_cursor)
    assert [item.request_id for item in second.items] == [UUID(int=901)]


def test_history_is_paged_instead_of_counted_as_pending(store):
    first = page(store)
    assert [item.request_id.int for item in first.items] == list(range(1001, 901, -1))
    assert first.next_cursor
    assert page(store, cursor=first.next_cursor).items[0].request_id == UUID(int=901)


@pytest.mark.parametrize("profile", ["guidance_only", "announcements_guidance"])
def test_new_facade_pages_every_profile_without_widening_old_api(store, profile):
    store.resolve.return_value.adoption_profile_code = profile
    result = page(store, pending_only=True)
    assert len(result.items) == 100
    assert result.next_cursor
    assert store.load.call_count == 100


def test_original_facade_still_has_original_complete_or_error_contract(store):
    with pytest.raises(ValidationError, match="Too many retained"):
        queries.list_my_guidance_access_requests(
            actor=store.actor, correlation_id=uuid4()
        )
    store.load.assert_not_called()


def test_earlier_profile_small_complete_page_stays_available(store, monkeypatch):
    store.resolve.return_value.adoption_profile_code = "guidance_only"
    monkeypatch.setattr(
        queries,
        "GuidanceAccessRequest",
        SimpleNamespace(objects=Records(store.rows[-2:])),
    )
    result = page(store, pending_only=True)
    assert len(result.items) == 2
    assert result.next_cursor is None


@pytest.mark.parametrize("change", ["actor", "mode", "tamper"])
def test_cursor_cannot_change_person_or_pending_history_purpose(store, change):
    cursor = page(store, pending_only=True).next_cursor
    store.load.reset_mock()
    if change == "actor":
        store.actor = Account(id=UUID(int=6000), is_active=True)
    if change == "tamper":
        cursor += "tampered"
    with pytest.raises(ValidationError, match="Restart"):
        page(store, pending_only=change != "mode", cursor=cursor)
    store.load.assert_not_called()


def test_inactive_actor_is_refused_before_any_scope_or_request_read(store):
    store.actor.is_active = False
    with pytest.raises(PermissionDenied):
        page(store)
    store.resolve.assert_not_called()
    store.load.assert_not_called()


@pytest.fixture
def discovery(store, monkeypatch):
    monkeypatch.setattr(
        "maru.events.guidance_activation_queries.has_current_guidance_activation_tasks",
        lambda **_values: False,
    )
    for row in store.rows:
        row.decision = None
    admission = Mock()
    current = Mock(return_value=False)
    audit = Mock()
    monkeypatch.setattr(queries, "require_guidance_access_actor", admission)
    monkeypatch.setattr(queries, "_request_sources_are_current", current)
    monkeypatch.setattr(queries, "_audit", audit)
    return SimpleNamespace(admission=admission, current=current, audit=audit)


def test_thousand_stale_pending_requests_have_fixed_discovery_budget(store, discovery):
    result = queries.discover_guidance_tasks(actor=store.actor, correlation_id=uuid4())
    assert result.has_current_work is False
    assert result.access_cursor
    assert discovery.current.call_count == 100
    assert discovery.admission.call_count == 1  # One identical current scope.
    discovery.audit.assert_not_called()
    store.load.assert_not_called()
    continuation = page(store, pending_only=True, cursor=result.access_cursor)
    assert continuation.items[0].request_id == UUID(int=901)
    assert store.load.call_count == 100


def test_discovery_never_reads_sources_before_current_scope_admission(store, discovery):
    discovery.admission.side_effect = PermissionDenied
    result = queries.discover_guidance_tasks(actor=store.actor, correlation_id=uuid4())
    assert result == queries.GuidanceTaskDiscovery(
        has_current_work=False, access_cursor=result.access_cursor
    )
    assert result.access_cursor
    discovery.current.assert_not_called()
    discovery.audit.assert_not_called()


def test_verified_identity_loss_refuses_even_generic_continuation(store, discovery):
    store.identity.return_value = None
    assert queries.discover_guidance_tasks(
        actor=store.actor, correlation_id=uuid4()
    ) == queries.GuidanceTaskDiscovery(has_current_work=False, access_cursor=None)
    discovery.admission.assert_not_called()
    discovery.current.assert_not_called()


def test_discovery_only_claims_a_proven_current_decision(store, discovery):
    discovery.current.return_value = True
    assert queries.discover_guidance_tasks(
        actor=store.actor, correlation_id=uuid4()
    ) == queries.GuidanceTaskDiscovery(has_current_work=True, access_cursor=None)
    assert discovery.current.call_count == 1
    discovery.audit.assert_called_once()


def test_exhausted_small_scan_is_distinct_from_unexamined_candidates(
    store, discovery, monkeypatch
):
    monkeypatch.setattr(
        queries,
        "GuidanceAccessRequest",
        SimpleNamespace(objects=Records(store.rows[-20:])),
    )
    assert queries.discover_guidance_tasks(
        actor=store.actor, correlation_id=uuid4()
    ) == queries.GuidanceTaskDiscovery(has_current_work=False, access_cursor=None)
    assert discovery.current.call_count == 20


def test_over_one_hundred_retained_scopes_do_not_block_a_page(store):
    for index, row in enumerate(store.rows):
        row.edition_id = UUID(int=10_000 + index)
    first = page(store)
    assert len(first.items) == 100
    assert first.next_cursor
    assert len(page(store, cursor=first.next_cursor).items) == 100
    assert store.load.call_count == 200


def test_mixed_profile_history_overflow_is_paged_in_global_newest_order(store):
    for index, row in enumerate(store.rows):
        row.edition_id = UUID(int=8000 + index % 3)
    first = page(store)
    second = page(store, cursor=first.next_cursor)
    assert [item.request_id.int for item in (*first.items, *second.items)] == list(
        range(1001, 801, -1)
    )
    assert store.load.call_count == 200
    with pytest.raises(ValidationError, match="Too many retained"):
        queries.list_my_guidance_access_requests(
            actor=store.actor, correlation_id=uuid4()
        )


def test_original_sources_are_rechecked_when_following_a_valid_cursor(store):
    first = page(store, pending_only=True)
    store.load.reset_mock()
    store.load.side_effect = PermissionDenied
    following = page(store, pending_only=True, cursor=first.next_cursor)
    assert following.items == ()
    assert following.next_cursor is None
    assert store.load.call_args.kwargs["request_id"] == UUID(int=901)


def test_equal_timestamps_use_id_tiebreaker_without_duplicate_or_missing_rows(store):
    created_at = store.rows[0].created_at
    for row in store.rows:
        row.created_at = created_at
    first = page(store, page_size=3)
    second = page(store, cursor=first.next_cursor, page_size=3)
    assert [item.request_id.int for item in (*first.items, *second.items)] == [
        1001,
        1000,
        999,
        998,
        997,
        996,
    ]


def test_earlier_profile_preserves_original_newest_first_history(store, monkeypatch):
    store.resolve.return_value.adoption_profile_code = "guidance_only"
    monkeypatch.setattr(
        queries,
        "GuidanceAccessRequest",
        SimpleNamespace(objects=Records(store.rows[-2:])),
    )
    result = page(store)
    assert [item.request_id.int for item in result.items] == [1001, 1000]
    assert result.next_cursor is None


@pytest.mark.parametrize("pending_only", [False, True])
@pytest.mark.parametrize("failure_at", [1, 2, 3])
def test_page_integrity_failure_never_becomes_empty_or_continuation(
    store, monkeypatch, pending_only, failure_at
):
    native = Mock(side_effect=[True] * (failure_at - 1) + [False])
    monkeypatch.setattr(
        guidance_readiness, "guidance_authority_database_integrity_is_ready", native
    )

    def load(**values):
        guidance_readiness.require_guidance_authority_integrity()
        return SimpleNamespace(request_id=values["request_id"], can_answer=True)

    store.load.side_effect = load
    with pytest.raises(guidance_readiness.GuidanceAuthorityUnavailable):
        page(store, pending_only=pending_only, page_size=2)
    assert native.call_count == failure_at


@pytest.mark.parametrize("row_count", [1, 101])
def test_discovery_integrity_loss_after_denial_refuses_empty_and_continuation(
    store, discovery, monkeypatch, row_count
):
    monkeypatch.setattr(
        queries,
        "GuidanceAccessRequest",
        SimpleNamespace(objects=Records(store.rows[-row_count:])),
    )
    native = Mock(side_effect=[True, False])
    monkeypatch.setattr(
        guidance_readiness, "guidance_authority_database_integrity_is_ready", native
    )

    def deny(**_values):
        guidance_readiness.require_guidance_authority_integrity()
        raise PermissionDenied("Ordinary current-source loss")

    discovery.admission.side_effect = deny
    with pytest.raises(guidance_readiness.GuidanceAuthorityUnavailable):
        queries.discover_guidance_tasks(actor=store.actor, correlation_id=uuid4())
    assert native.call_count == 2
    discovery.current.assert_not_called()


def test_discovery_distinguishes_initial_native_failure_from_row_denial(
    store, discovery, monkeypatch
):
    monkeypatch.setattr(
        guidance_readiness,
        "guidance_authority_database_integrity_is_ready",
        lambda: False,
    )
    discovery.admission.side_effect = lambda **_values: (
        guidance_readiness.require_guidance_authority_integrity()
    )
    with pytest.raises(guidance_readiness.GuidanceAuthorityUnavailable):
        queries.discover_guidance_tasks(actor=store.actor, correlation_id=uuid4())
    assert discovery.admission.call_count == 1
    discovery.current.assert_not_called()


def test_discovery_final_positive_audit_propagates_integrity_loss(
    store, discovery, monkeypatch
):
    native = Mock(side_effect=[True, False])
    monkeypatch.setattr(
        guidance_readiness, "guidance_authority_database_integrity_is_ready", native
    )
    discovery.admission.side_effect = lambda **_values: (
        guidance_readiness.require_guidance_authority_integrity()
    )
    discovery.current.return_value = True
    discovery.audit.side_effect = lambda *_args: (
        guidance_readiness.require_guidance_authority_integrity()
    )
    with pytest.raises(guidance_readiness.GuidanceAuthorityUnavailable):
        queries.discover_guidance_tasks(actor=store.actor, correlation_id=uuid4())
    assert native.call_count == 2


def test_legacy_access_tuple_retains_denial_and_count_compatibility(store, monkeypatch):
    monkeypatch.setattr(
        queries,
        "GuidanceAccessRequest",
        SimpleNamespace(objects=Records(store.rows[-1:])),
    )
    store.load.side_effect = guidance_readiness.GuidanceAuthorityUnavailable
    assert (
        queries.list_my_guidance_access_requests(
            actor=store.actor, correlation_id=uuid4()
        )
        == ()
    )


def test_no_guides_candidates_leave_unrelated_personal_navigation_available(
    store, monkeypatch
):
    monkeypatch.setattr(
        queries, "GuidanceAccessRequest", SimpleNamespace(objects=Records(()))
    )
    monkeypatch.setattr(
        guidance_activation_queries,
        "GuidanceActivationRequest",
        SimpleNamespace(objects=Records(())),
    )
    unused = Mock(side_effect=AssertionError("Unused Guides readiness was queried"))
    monkeypatch.setattr(
        guidance_readiness, "guidance_authority_database_integrity_is_ready", unused
    )
    monkeypatch.setattr(
        guidance_setup_readiness, "guidance_setup_database_integrity_is_ready", unused
    )
    monkeypatch.setattr(
        provenance_readiness, "authority_provenance_runtime_contract_is_ready", unused
    )
    assert page(store).items == ()
    request = RequestFactory().get("/my/")
    request.user = store.actor
    assert navigation._guidance_decision_items(request) == []
    assert queries.discover_guidance_tasks(
        actor=store.actor, correlation_id=uuid4()
    ) == queries.GuidanceTaskDiscovery(has_current_work=False, access_cursor=None)
    unused.assert_not_called()


def test_exact_provenance_unavailability_is_not_filtered_as_ordinary_denial(
    store, monkeypatch
):
    monkeypatch.setattr(
        provenance_readiness,
        "authority_provenance_runtime_contract_is_ready",
        lambda: False,
    )
    store.load.side_effect = lambda **_values: (
        guidance_readiness.require_guidance_authority_integrity()
    )
    with pytest.raises(guidance_readiness.GuidanceAuthorityUnavailable):
        page(store)
    assert store.load.call_count == 1
