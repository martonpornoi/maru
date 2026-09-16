"""Data-free readiness for the dormant setup receipt, not the whole Events app."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace
from importlib import import_module
from typing import Final

from django.db import DatabaseError

from maru.core.database_integrity_readiness import (
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)
from maru.core.relation_schema_readiness import relation_schema_is_current

PROGRAMME_SETUP_RELATION: Final = "events_programmeadoptionsetupreceipt"
_MIGRATION_SOURCE_SHA256: Final = {
    "0012_programme_setup_receipt": (
        "a210e147ae4a5413c4d2524018b7f5496bbe9871e81cfd8a7f3036d4956b185b"
    ),
    "0014_programme_setup_downgrade_fence": (
        "4cbba2f24413eff3abe3f78fbeb24fcae94f3d614c8cadc6cfccdefc5c2eeff9"
    ),
}


def _retained_migration_sources_current() -> bool:
    return all(
        hashlib.sha256(
            inspect.getsource(import_module(f"maru.events.migrations.{name}"))
            .replace("\r\n", "\n")
            .encode()
        ).hexdigest()
        == expected
        for name, expected in _MIGRATION_SOURCE_SHA256.items()
    )


_BASE = build_database_integrity_contract(
    status_key="programme_setup_integrity",
    app_label="events",
    source_migration=("events", "0013_programme_setup_integrity"),
    terminal_migration=("events", "0014_programme_setup_downgrade_fence"),
    source_migration_module="maru.events.migrations.0013_programme_setup_integrity",
)
PROGRAMME_SETUP_INTEGRITY_CONTRACT = replace(
    _BASE,
    source_contract_current=(
        _BASE.source_contract_current and _retained_migration_sources_current()
    ),
    supporting_migrations=(("events", "0012_programme_setup_receipt"),),
    owned_relations=(PROGRAMME_SETUP_RELATION,),
)
# Observed on PostgreSQL 17.11 by the approved disposable schema-only migration.
# This is relation/catalog evidence, not database workflow or migration-test acceptance.
PROGRAMME_SETUP_SCHEMA_SHA256: Final[dict[str, str]] = {
    PROGRAMME_SETUP_RELATION: (
        "8f7eed1463c6214ec8b5153fcc67856cd4f96dc24cdcd111892d599941183ab5"
    ),
}


def programme_setup_database_integrity_is_ready() -> bool:
    """Require the complete receipt shape and exact native attachments/privileges.

    Returns
    -------
    bool
        Whether setup receipt storage matches its reviewed source and metadata.
        This grants no write authority, profile registration or setup permission.
    """
    try:
        return (
            set(PROGRAMME_SETUP_SCHEMA_SHA256) == {PROGRAMME_SETUP_RELATION}
            and database_integrity_contract_is_ready(PROGRAMME_SETUP_INTEGRITY_CONTRACT)
            and relation_schema_is_current(PROGRAMME_SETUP_SCHEMA_SHA256)
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False
