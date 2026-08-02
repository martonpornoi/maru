from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Self
from uuid import UUID

import pytest
from django.db.transaction import TransactionManagementError

from maru.workforce import writer_boundary


class _RecordingCursor(AbstractContextManager["_RecordingCursor"]):
    def __init__(self, queries: list[tuple[str, list[object]]]) -> None:
        self._queries = queries

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def execute(self, sql: str, parameters: list[object]) -> None:
        self._queries.append((sql, parameters))


class _RecordingConnection:
    def __init__(self, *, autocommit: bool, in_atomic_block: bool) -> None:
        self._autocommit = autocommit
        self.in_atomic_block = in_atomic_block
        self.queries: list[tuple[str, list[object]]] = []

    def get_autocommit(self) -> bool:
        return self._autocommit

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.queries)


def _global_boundary() -> None:
    writer_boundary.lock_page_9_structure_writer_boundary()


def _edition_mutex() -> None:
    writer_boundary.lock_edition_structure_mutex(
        organization_id=UUID("11111111-1111-1111-1111-111111111111"),
        edition_id=UUID("22222222-2222-2222-2222-222222222222"),
    )


@pytest.mark.parametrize("operation", [_global_boundary, _edition_mutex])
@pytest.mark.parametrize(
    ("autocommit", "in_atomic_block"),
    [(True, False), (True, True), (False, False)],
)
def test_writer_locks_require_an_explicit_atomic_transaction(
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[], None],
    autocommit: bool,
    in_atomic_block: bool,
) -> None:
    fake_connection = _RecordingConnection(
        autocommit=autocommit,
        in_atomic_block=in_atomic_block,
    )
    monkeypatch.setattr(writer_boundary, "connection", fake_connection)

    with pytest.raises(TransactionManagementError, match="atomic transaction"):
        operation()

    assert fake_connection.queries == []


def test_global_boundary_uses_the_exact_shared_advisory_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_connection = _RecordingConnection(autocommit=False, in_atomic_block=True)
    monkeypatch.setattr(writer_boundary, "connection", fake_connection)

    writer_boundary.lock_page_9_structure_writer_boundary()

    assert writer_boundary.PAGE_9_STRUCTURE_ACTIVATION_LOCK_KEY == 4_400_460_007
    assert fake_connection.queries == [
        (
            "SELECT pg_catalog.pg_advisory_xact_lock_shared(%s)",
            [4_400_460_007],
        )
    ]


def test_edition_mutex_uses_the_stable_existing_scope_key_and_exact_sql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_connection = _RecordingConnection(autocommit=False, in_atomic_block=True)
    monkeypatch.setattr(writer_boundary, "connection", fake_connection)
    organization_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    edition_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    writer_boundary.lock_edition_structure_mutex(
        organization_id=organization_id,
        edition_id=edition_id,
    )

    assert fake_connection.queries == [
        (
            "SELECT pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended(%s, 0))",
            [
                "maru.workforce.department:"
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:"
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
            ],
        )
    ]
