from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test.utils import CaptureQueriesContext

from maru.workforce.writer_boundary import (
    lock_edition_structure_mutex,
    lock_page_9_structure_writer_boundary,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.integration]


def test_real_writer_locks_require_an_explicit_atomic_transaction() -> None:
    with pytest.raises(TransactionManagementError, match="atomic transaction"):
        lock_page_9_structure_writer_boundary()
    with pytest.raises(TransactionManagementError, match="atomic transaction"):
        lock_edition_structure_mutex(
            organization_id=uuid4(),
            edition_id=uuid4(),
        )


def test_real_connection_emits_the_exact_advisory_statements() -> None:
    organization_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    edition_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    with transaction.atomic(), CaptureQueriesContext(connection) as queries:
        lock_page_9_structure_writer_boundary()
        lock_edition_structure_mutex(
            organization_id=organization_id,
            edition_id=edition_id,
        )

    boundary_queries = [
        captured["sql"]
        for captured in queries.captured_queries
        if "pg_advisory_xact_lock" in captured["sql"]
    ]
    assert boundary_queries == [
        "SELECT pg_catalog.pg_advisory_xact_lock_shared(4400460007)",
        "SELECT pg_catalog.pg_advisory_xact_lock("
        "pg_catalog.hashtextextended("
        "'maru.workforce.department:"
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:"
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 0))",
    ]


def _hold_edition_mutex(
    *,
    organization_id: UUID,
    edition_id: UUID,
    acquired: Event,
    release: Event,
) -> None:
    close_old_connections()
    try:
        with transaction.atomic():
            lock_edition_structure_mutex(
                organization_id=organization_id,
                edition_id=edition_id,
            )
            acquired.set()
            assert release.wait(timeout=10)
    finally:
        acquired.set()
        close_old_connections()


def _start_mutex_holder(
    executor: ThreadPoolExecutor,
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> tuple[Future[None], Event, Event]:
    acquired = Event()
    release = Event()
    future = executor.submit(
        _hold_edition_mutex,
        organization_id=organization_id,
        edition_id=edition_id,
        acquired=acquired,
        release=release,
    )
    assert acquired.wait(timeout=10)
    return future, acquired, release


def _lock_edition_with_timeout(
    *,
    organization_id: UUID,
    edition_id: UUID,
) -> None:
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '250ms'")
        lock_edition_structure_mutex(
            organization_id=organization_id,
            edition_id=edition_id,
        )


def test_same_edition_mutex_serializes_concurrent_transactions() -> None:
    organization_id = uuid4()
    edition_id = uuid4()

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder, _acquired, release = _start_mutex_holder(
            executor,
            organization_id=organization_id,
            edition_id=edition_id,
        )
        try:
            with pytest.raises(DatabaseError):
                _lock_edition_with_timeout(
                    organization_id=organization_id,
                    edition_id=edition_id,
                )
        finally:
            release.set()
        holder.result(timeout=10)


def test_different_edition_mutexes_remain_independent() -> None:
    organization_id = uuid4()
    held_edition_id = uuid4()
    independent_edition_id = uuid4()

    with ThreadPoolExecutor(max_workers=1) as executor:
        holder, _acquired, release = _start_mutex_holder(
            executor,
            organization_id=organization_id,
            edition_id=held_edition_id,
        )
        try:
            _lock_edition_with_timeout(
                organization_id=organization_id,
                edition_id=independent_edition_id,
            )
        finally:
            release.set()
        holder.result(timeout=10)
