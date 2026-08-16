"""Fail-closed database integrity readiness for Venues."""

from typing import Final

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)

VENUES_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = (
    build_database_integrity_contract(
        status_key="venues_integrity",
        app_label="venues",
        source_migration=("venues", "0002_venue_write_integrity"),
        terminal_migration=("venues", "0002_venue_write_integrity"),
        source_migration_module="maru.venues.migrations.0002_venue_write_integrity",
    )
)


def venues_database_integrity_is_ready() -> bool:
    return database_integrity_contract_is_ready(VENUES_INTEGRITY_CONTRACT)


__all__ = [
    "VENUES_INTEGRITY_CONTRACT",
    "venues_database_integrity_is_ready",
]
