"""Fail-closed database integrity readiness for Catalog."""

from typing import Final

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)

CATALOG_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = (
    build_database_integrity_contract(
        status_key="catalog_integrity",
        app_label="catalog",
        source_migration=("catalog", "0003_catalog_evidence_guards"),
        terminal_migration=("catalog", "0003_catalog_evidence_guards"),
        source_migration_module="maru.catalog.migrations.0003_catalog_evidence_guards",
    )
)


def catalog_database_integrity_is_ready() -> bool:
    """Verify catalog database integrity is ready.

    Returns
    -------
    bool
        Whether the requested condition is satisfied.
    """
    return database_integrity_contract_is_ready(CATALOG_INTEGRITY_CONTRACT)


__all__ = [
    "CATALOG_INTEGRITY_CONTRACT",
    "catalog_database_integrity_is_ready",
]
