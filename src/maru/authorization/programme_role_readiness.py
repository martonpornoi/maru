"""Purpose-scoped data-free readiness for retained Programme role approvals."""

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

PROGRAMME_ROLE_RELATIONS: Final = (
    "authorization_programmeroledecisionrecord",
    "authorization_programmerolerequest",
)
_MIGRATION_SOURCE_SHA256: Final = {
    "0032_programme_role_approval_records": (
        "b8a6cdbddf9b18a822d629e74f91c9f6bb17f24a9439128a1b40bb3e86f6a781"
    ),
    "0034_programme_role_approval_downgrade_fence": (
        "ed33bdccfccddac6d8c5f634f9423009f07ec72974d79b83f218ba411b02e1d0"
    ),
}


def _retained_migration_sources_current() -> bool:
    return all(
        hashlib.sha256(
            inspect.getsource(import_module(f"maru.authorization.migrations.{name}"))
            .replace("\r\n", "\n")
            .encode()
        ).hexdigest()
        == expected
        for name, expected in _MIGRATION_SOURCE_SHA256.items()
    )


_BASE = build_database_integrity_contract(
    status_key="programme_role_approval_integrity",
    app_label="authorization",
    source_migration=("authorization", "0033_programme_role_approval_integrity"),
    terminal_migration=(
        "authorization",
        "0034_programme_role_approval_downgrade_fence",
    ),
    source_migration_module="maru.authorization.migrations.0033_programme_role_approval_integrity",
)
PROGRAMME_ROLE_INTEGRITY_CONTRACT = replace(
    _BASE,
    source_contract_current=_BASE.source_contract_current
    and _retained_migration_sources_current(),
    supporting_migrations=(("authorization", "0032_programme_role_approval_records"),),
    owned_relations=PROGRAMME_ROLE_RELATIONS,
)
# Observed on PostgreSQL 17.11 by the approved disposable schema-only migration.
# Relation/catalog evidence is not native workflow or migration-test acceptance.
PROGRAMME_ROLE_SCHEMA_SHA256: Final[dict[str, str]] = {
    "authorization_programmeroledecisionrecord": (
        "ce773dc6573d27c9e3c44e13777ad9d5a29fc326c83e835292835d491a91fe32"
    ),
    "authorization_programmerolerequest": (
        "dffe250128cc2459f2457cf7a612111e339b26627aa868d80b3401324dad842d"
    ),
}


def programme_role_database_integrity_is_ready() -> bool:
    """Require exact approval relations, native guards and permission attachments.

    Returns
    -------
    bool
        Whether the dormant evidence boundary matches reviewed migration metadata.
        This is not actor authorization, a role grant or Programme activation.
    """
    try:
        return (
            set(PROGRAMME_ROLE_SCHEMA_SHA256) == set(PROGRAMME_ROLE_RELATIONS)
            and database_integrity_contract_is_ready(PROGRAMME_ROLE_INTEGRITY_CONTRACT)
            and relation_schema_is_current(PROGRAMME_ROLE_SCHEMA_SHA256)
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False
