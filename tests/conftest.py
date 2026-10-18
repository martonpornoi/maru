"""Shared test-suite fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import setup_databases, teardown_databases

from tests.support.migrations import flush_then_restore_current_migration_graph

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django.fixtures import DjangoDbBlocker


@pytest.fixture(scope="session")
def _shared_history_database(
    django_db_setup: None,
    django_db_blocker: DjangoDbBlocker,
) -> Iterator[None]:
    """Ensure standalone shared histories have the ordinary default test database.

    Pytest-django discovers aliases from database markers and per-case fixtures.
    These histories own their case transactions, so they use neither. When the
    ordinary session setup has no alias to create, use Django's normal fresh
    test-database setup and teardown. Mixed sessions retain their existing test
    database and its original owner; no per-case transaction or flush is added.
    """

    del django_db_setup
    configuration = None
    if not str(connection.settings_dict["NAME"]).startswith("test_"):
        with django_db_blocker.unblock():
            configuration = setup_databases(
                verbosity=0,
                interactive=False,
                aliases={"default"},
                serialized_aliases=set(),
                keepdb=False,
            )
    try:
        yield
    finally:
        if configuration is not None:
            with django_db_blocker.unblock():
                teardown_databases(configuration, verbosity=0, keepdb=False)


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
