"""Fail-closed database integrity readiness for Applications."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace
from importlib import import_module
from typing import Final

from django.db import migrations

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
    parse_database_integrity_sql_contracts,
)

_INTEGRITY_MIGRATION = import_module(
    "maru.applications.migrations.0005_programme_integrity_guards"
)
_DOWNGRADE_MIGRATION = import_module(
    "maru.applications.migrations.0006_programme_populated_downgrade_fence"
)
_LEGACY_INTEGRITY_MIGRATION = import_module(
    "maru.applications.migrations.0002_integrity_guards"
)
_LEGACY_ACL_MIGRATION = import_module(
    "maru.applications.migrations.0003_integrity_function_execute_boundary"
)
_IDENTITY_PROGRAMME_MIGRATION = import_module(
    "maru.identity.migrations.0020_programme_proposal_person_guard"
)
_DOWNGRADE_FENCE_SOURCE_SHA256: Final = (
    "98d8a829966e0430e480a55f99d8b463f4ed2966fae8a0ce04e701e910ce43e2"
)


def _applications_programme_migration_contract_is_current() -> bool:
    source_operations = tuple(_INTEGRITY_MIGRATION.Migration.operations)
    downgrade_operations = tuple(_DOWNGRADE_MIGRATION.Migration.operations)
    expected_reverse_suffix = (
        f"{_LEGACY_INTEGRITY_MIGRATION.FORWARD_SQL.strip()}\n\n"
        f"{_LEGACY_ACL_MIGRATION.FORWARD_SQL.strip()}"
    )
    downgrade_operation = (
        downgrade_operations[0] if len(downgrade_operations) == 1 else None
    )
    if not isinstance(downgrade_operation, migrations.RunPython):
        return False
    downgrade_source = inspect.getsource(
        _DOWNGRADE_MIGRATION.refuse_used_applications_programme_downgrade
    ).replace("\r\n", "\n")
    identity_operations = tuple(_IDENTITY_PROGRAMME_MIGRATION.Migration.operations)
    return all(
        (
            tuple(_INTEGRITY_MIGRATION.Migration.dependencies)
            == (
                ("applications", "0004_programme_calls_and_proposals"),
                ("identity", "0020_programme_proposal_person_guard"),
                ("authorization", "0021_applications_programme_capabilities"),
            ),
            len(source_operations) == 1,
            isinstance(source_operations[0], migrations.RunSQL),
            source_operations[0].sql == _INTEGRITY_MIGRATION.FORWARD_SQL,
            source_operations[0].reverse_sql == _INTEGRITY_MIGRATION.REVERSE_SQL,
            _INTEGRITY_MIGRATION.REVERSE_SQL.endswith(expected_reverse_suffix),
            tuple(_DOWNGRADE_MIGRATION.Migration.dependencies)
            == (("applications", "0005_programme_integrity_guards"),),
            downgrade_operation.code is migrations.RunPython.noop,
            downgrade_operation.reverse_code
            is _DOWNGRADE_MIGRATION.refuse_used_applications_programme_downgrade,
            hashlib.sha256(downgrade_source.encode("utf-8")).hexdigest()
            == _DOWNGRADE_FENCE_SOURCE_SHA256,
            tuple(_IDENTITY_PROGRAMME_MIGRATION.Migration.dependencies)
            == (
                ("identity", "0019_navigation_pins"),
                ("applications", "0004_programme_calls_and_proposals"),
            ),
            len(identity_operations) == 1,
            isinstance(identity_operations[0], migrations.RunSQL),
            identity_operations[0].sql == _IDENTITY_PROGRAMME_MIGRATION.FORWARD_SQL,
            identity_operations[0].reverse_sql
            == _IDENTITY_PROGRAMME_MIGRATION.REVERSE_SQL,
        )
    )


_DERIVED_APPLICATIONS_INTEGRITY_CONTRACT = build_database_integrity_contract(
    status_key="applications_integrity",
    app_label="applications",
    source_migration=("applications", "0005_programme_integrity_guards"),
    terminal_migration=(
        "applications",
        "0006_programme_populated_downgrade_fence",
    ),
    source_migration_module=(
        "maru.applications.migrations.0005_programme_integrity_guards"
    ),
)
_IDENTITY_SQL_TRIGGER_CONTRACTS, _IDENTITY_SQL_FUNCTION_CONTRACTS = (
    parse_database_integrity_sql_contracts(_IDENTITY_PROGRAMME_MIGRATION.FORWARD_SQL)
)
_IDENTITY_TRIGGER_CONTRACTS = {
    name: trigger
    for name, trigger in _IDENTITY_SQL_TRIGGER_CONTRACTS.items()
    if trigger.table.startswith("applications_")
}
_IDENTITY_FUNCTION_IDENTITIES = {
    trigger.function_identity.removeprefix("public.")
    for trigger in _IDENTITY_TRIGGER_CONTRACTS.values()
}
_IDENTITY_FUNCTION_CONTRACTS = {
    identity: function
    for identity, function in _IDENTITY_SQL_FUNCTION_CONTRACTS.items()
    if identity in _IDENTITY_FUNCTION_IDENTITIES
}
APPLICATIONS_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = replace(
    _DERIVED_APPLICATIONS_INTEGRITY_CONTRACT,
    triggers={
        **_DERIVED_APPLICATIONS_INTEGRITY_CONTRACT.triggers,
        **_IDENTITY_TRIGGER_CONTRACTS,
    },
    functions={
        **_DERIVED_APPLICATIONS_INTEGRITY_CONTRACT.functions,
        **_IDENTITY_FUNCTION_CONTRACTS,
    },
    source_contract_current=(
        _DERIVED_APPLICATIONS_INTEGRITY_CONTRACT.source_contract_current
        and _applications_programme_migration_contract_is_current()
    ),
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
