"""Shared test-suite fixtures."""

from collections.abc import Iterator

import pytest

from tests.support.migrations import restore_current_migration_graph


@pytest.fixture
def restores_current_migration_graph(transactional_db: None) -> Iterator[None]:
    """Restore schema leaves after a test exercises historical migrations."""

    del transactional_db
    try:
        yield
    finally:
        restore_current_migration_graph()
