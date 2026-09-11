"""Fail-closed database integrity readiness for Venues."""

import hashlib
import inspect
from dataclasses import replace
from importlib import import_module
from typing import Final

from django.db import DatabaseError

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)
from maru.core.relation_schema_readiness import relation_schema_is_current
from maru.scheduling.release_integrity import with_native_release_integrity

_BASE_INTEGRITY_CONTRACT = build_database_integrity_contract(
    status_key="venues_integrity",
    app_label="venues",
    source_migration=("venues", "0002_venue_write_integrity"),
    terminal_migration=("venues", "0002_venue_write_integrity"),
    source_migration_module="maru.venues.migrations.0002_venue_write_integrity",
)

_BINDING_CONTRACT = build_database_integrity_contract(
    status_key="venues_integrity",
    app_label="venues",
    source_migration=("venues", "0004_scheduling_binding_integrity"),
    terminal_migration=("venues", "0005_scheduling_downgrade_fence"),
    source_migration_module="maru.venues.migrations.0004_scheduling_binding_integrity",
)
_FENCE = import_module("maru.venues.migrations.0005_scheduling_downgrade_fence")
_FENCE_SHA256 = "2061e11ca829831da07ddd96a51ef9dac3fd1e59de093e8ec37d2e19d1eaf3ed"
VENUES_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = (
    with_native_release_integrity(
        replace(
            _BINDING_CONTRACT,
            triggers={
                **_BASE_INTEGRITY_CONTRACT.triggers,
                **{
                    name: trigger
                    for name, trigger in _BINDING_CONTRACT.triggers.items()
                    if trigger.table.startswith("venues_")
                },
            },
            functions={
                **_BASE_INTEGRITY_CONTRACT.functions,
                **_BINDING_CONTRACT.functions,
            },
            runtime_executable_functions=frozenset(
                {"maru_validate_scheduling_linked_booking(uuid)"}
            ),
            source_contract_current=(
                _BASE_INTEGRITY_CONTRACT.source_contract_current
                and _BINDING_CONTRACT.source_contract_current
                and hashlib.sha256(
                    inspect.getsource(_FENCE).replace("\r\n", "\n").encode()
                ).hexdigest()
                == _FENCE_SHA256
            ),
        )
    )
)
VENUE_BINDING_SCHEMA_SHA256: Final = {
    "venues_venueschedulingbinding": (
        "37405b4dfe098f75b7867b5eb40d48b6262c56d186ecaeb4ee34fa20f4dea3d7"
    ),
}


def venues_database_integrity_is_ready() -> bool:
    """Verify venues database integrity is ready.

    Returns
    -------
    bool
        Whether the requested condition is satisfied.
    """
    try:
        return database_integrity_contract_is_ready(
            VENUES_INTEGRITY_CONTRACT
        ) and relation_schema_is_current(VENUE_BINDING_SCHEMA_SHA256)
    except (DatabaseError, LookupError, TypeError, ValueError):
        return False


__all__ = [
    "VENUES_INTEGRITY_CONTRACT",
    "venues_database_integrity_is_ready",
]
