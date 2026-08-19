"""Fail-closed database integrity readiness for Charities."""

from typing import Final

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)

CHARITIES_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = (
    build_database_integrity_contract(
        status_key="charities_integrity",
        app_label="charities",
        source_migration=("charities", "0002_charity_write_integrity"),
        terminal_migration=("charities", "0002_charity_write_integrity"),
        source_migration_module="maru.charities.migrations.0002_charity_write_integrity",
    )
)


def charities_database_integrity_is_ready() -> bool:
    return database_integrity_contract_is_ready(CHARITIES_INTEGRITY_CONTRACT)


__all__ = [
    "CHARITIES_INTEGRITY_CONTRACT",
    "charities_database_integrity_is_ready",
]
