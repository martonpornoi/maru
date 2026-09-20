"""Exact native stop preparation, not complete terminal-command admission."""

from typing import Final

from django.db import DatabaseError

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    database_integrity_contract_is_ready,
    extend_database_integrity_contract,
)
from maru.core.relation_schema_readiness import relation_schema_is_current

PROGRAMME_STOP_RELATION: Final = "events_programmestopreceipt"
PROGRAMME_STOP_SCHEMA_SHA256: Final = {
    PROGRAMME_STOP_RELATION: (
        "e1139a40de720f1e8ef27292aac62be3ce41e5a97e00aeb52a489c34a71766c2"
    ),
}
# The first migration combines storage, guards and an unused-only reverse fence.
# Use the full-file-pinned additive parser, not the SQL-only base builder. This
# empty seed is never exported or inspected; every attachment below is mandatory.
_BASE = DatabaseIntegrityContract(
    status_key="programme_stop_preparation_integrity",
    app_label="events",
    source_migration=("events", "0015_programme_stop_receipt"),
    terminal_migration=("events", "0015_programme_stop_receipt"),
    source_migration_module="maru.events.migrations.0015_programme_stop_receipt",
    triggers={},
    functions={},
    source_contract_current=True,
    owned_relations=(PROGRAMME_STOP_RELATION,),
)
_SOURCES = (
    (
        "events.0015_programme_stop_receipt",
        "f7c9264a81dd150c92db6aa6558671feb8921c355096309d82aa33f7ffa6c288",
    ),
    (
        "scheduling.0023_programme_stop_boundary",
        "bd394658be8748c2e973203f0d8ceeb7f3e53a46d86f8f8325272e038c5544a5",
    ),
    (
        "workforce.0030_programme_stop_boundary",
        "941e61a22e56dab7129df2a5ef35445752d93f92e2a5814f73489af778d46eb5",
    ),
    (
        "authorization.0040_programme_stop_boundary",
        "c727e2e7f73bcb45f7e30a82733423f84a24f553549a508cc41053d4934e96bf",
    ),
    (
        "venues.0009_programme_stop_boundary",
        "2c06618a0dc345ea992ef8698bf89b5b5079a69eaa5f61def59d09aa8dc3a083",
    ),
)
for _source, _digest in _SOURCES:
    _owner, _migration = _source.split(".", 1)
    _BASE = extend_database_integrity_contract(
        _BASE,
        migration_module=f"maru.{_owner}.migrations.{_migration}",
        source_sha256=_digest,
    )
PROGRAMME_STOP_PREPARATION_CONTRACT = _BASE


def programme_stop_preparation_is_ready() -> bool:
    """Check installed receipt and prepared owner fences without enabling stop.

    Returns
    -------
    bool
        Whether the exact preparation catalog is installed. Other owner guards,
        complete preview, authorization, terminal evidence and acceptance remain
        separate prerequisites; this result must never authorize stopping alone.
    """
    try:
        return (
            set(PROGRAMME_STOP_SCHEMA_SHA256) == {PROGRAMME_STOP_RELATION}
            and database_integrity_contract_is_ready(
                PROGRAMME_STOP_PREPARATION_CONTRACT
            )
            and relation_schema_is_current(PROGRAMME_STOP_SCHEMA_SHA256)
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False
