"""Fail-closed database integrity readiness for Applications."""

from typing import Final

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)

APPLICATIONS_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = (
    build_database_integrity_contract(
        status_key="applications_integrity",
        app_label="applications",
        source_migration=("applications", "0002_integrity_guards"),
        terminal_migration=(
            "applications",
            "0003_integrity_function_execute_boundary",
        ),
        source_migration_module="maru.applications.migrations.0002_integrity_guards",
    )
)


def applications_database_integrity_is_ready() -> bool:
    """Verify applications database integrity is ready.

    Returns
    -------
    bool
        Whether the requested condition is satisfied.
    """
    return database_integrity_contract_is_ready(APPLICATIONS_INTEGRITY_CONTRACT)


__all__ = [
    "APPLICATIONS_INTEGRITY_CONTRACT",
    "applications_database_integrity_is_ready",
]
