"""Discover unchanged Events history plus one explicit fixture-only migration."""

from pathlib import Path

from maru.events import migrations as owner_migrations

__path__ = [str(Path(__file__).parent), *owner_migrations.__path__]
