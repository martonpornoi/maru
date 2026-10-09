"""Data-free native readiness for the Announcements setup receipt."""

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

ANNOUNCEMENTS_SETUP_RELATION: Final = "events_announcementsadoptionsetupreceipt"
_MIGRATION_SOURCE_SHA256: Final = {
    "0019_announcements_adoption_profile": (
        "e66794f16f6f142774021d35149ec2182f61f693d9cc41cfa4fe1d74951ef6b2"
    ),
    "0021_announcements_setup_downgrade_fence": (
        "f0fb832ba3a4495dc4ca7bcfad3f15a66dc28fa02e94de546ad55097cef19ff0"
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
    status_key="announcements_setup_integrity",
    app_label="events",
    source_migration=("events", "0020_announcements_setup_integrity"),
    terminal_migration=("events", "0021_announcements_setup_downgrade_fence"),
    source_migration_module="maru.events.migrations.0020_announcements_setup_integrity",
)
ANNOUNCEMENTS_SETUP_INTEGRITY_CONTRACT = replace(
    _BASE,
    source_contract_current=(
        _BASE.source_contract_current and _retained_migration_sources_current()
    ),
    owned_relations=(ANNOUNCEMENTS_SETUP_RELATION,),
    supporting_migrations=(("events", "0019_announcements_adoption_profile"),),
)
# Observed from the approved disposable PostgreSQL 17.10 migrated catalog.
ANNOUNCEMENTS_SETUP_SCHEMA_SHA256: Final[dict[str, str]] = {
    "events_announcementsadoptionsetupreceipt": (
        "3378689556c4ddaae4312e00efb87bcc0dfbd21227e85189a5de85c7facbb637"
    )
}


def announcements_setup_database_integrity_is_ready() -> bool:
    """Check exact native receipt shape, source, attachments and runtime privileges.

    Returns
    -------
    bool
        Whether reviewed setup integrity is installed; grants no authority.
    """
    try:
        return (
            set(ANNOUNCEMENTS_SETUP_SCHEMA_SHA256) == {ANNOUNCEMENTS_SETUP_RELATION}
            and database_integrity_contract_is_ready(
                ANNOUNCEMENTS_SETUP_INTEGRITY_CONTRACT
            )
            and relation_schema_is_current(ANNOUNCEMENTS_SETUP_SCHEMA_SHA256)
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False
