"""Database-free checks of actual retained Announcements setup source contracts."""

import hashlib
import inspect
from importlib import import_module

import pytest

from maru.events import announcements_setup_readiness as readiness


@pytest.mark.parametrize("migration", readiness._MIGRATION_SOURCE_SHA256)
def test_checked_in_setup_migrations_match_their_reviewed_source_pins(migration):
    source = inspect.getsource(import_module(f"maru.events.migrations.{migration}"))
    actual = hashlib.sha256(source.replace("\r\n", "\n").encode()).hexdigest()
    assert actual == readiness._MIGRATION_SOURCE_SHA256[migration]


def test_checked_in_setup_source_is_current_before_native_database_checks():
    assert readiness._retained_migration_sources_current()
    assert readiness.ANNOUNCEMENTS_SETUP_INTEGRITY_CONTRACT.source_contract_current
