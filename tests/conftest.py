"""Shared test-suite fixtures."""

from collections.abc import Iterator

import pytest

from tests.support.migrations import flush_then_restore_current_migration_graph


@pytest.fixture
def restores_current_migration_graph(transactional_db: None) -> Iterator[None]:
    """Restore schema leaves after a test exercises historical migrations."""

    del transactional_db
    try:
        yield
    finally:
        flush_then_restore_current_migration_graph()


@pytest.fixture
def proves_safe_runtime_database_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep lineage tests focused while the real role probe has its own suite."""

    from maru.authorization import provenance_readiness  # noqa: PLC0415

    monkeypatch.setattr(
        provenance_readiness,
        "_configured_runtime_database_role_is_safe",
        lambda: True,
    )
