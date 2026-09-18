"""Fail-closed native metadata contract for dormant Programme starter evidence."""

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

PROGRAMME_STARTER_RELATIONS: Final = (
    "workforce_programmestarterdecision",
    "workforce_programmestarterrequest",
)
# Pin all storage, native guards and serialized unused-only contraction sources.
_MIGRATION_SOURCE_SHA256: Final[dict[str, str]] = {
    "0025_programme_starter_records": (
        "652b4de67b3ab66a8acd1c0534f687495b5e28cf4323d006a753847e92f539e5"
    ),
    "0026_programme_starter_integrity": (
        "b13f12228cb14fa169e82030b601c795ec711becce86b301f4e7c561ef0d1593"
    ),
    "0027_programme_starter_downgrade_fence": (
        "0f630ac634f880be272a0f152137c10c4d283eadfa04f38b4f27324cce55ac8b"
    ),
}


def _sources_current() -> bool:
    expected = {
        "0025_programme_starter_records",
        "0026_programme_starter_integrity",
        "0027_programme_starter_downgrade_fence",
    }
    return set(_MIGRATION_SOURCE_SHA256) == expected and all(
        hashlib.sha256(
            inspect.getsource(import_module(f"maru.workforce.migrations.{name}"))
            .replace("\r\n", "\n")
            .encode()
        ).hexdigest()
        == digest
        for name, digest in _MIGRATION_SOURCE_SHA256.items()
    )


_BASE = build_database_integrity_contract(
    status_key="programme_starter_integrity",
    app_label="workforce",
    source_migration=("workforce", "0026_programme_starter_integrity"),
    terminal_migration=("workforce", "0027_programme_starter_downgrade_fence"),
    source_migration_module="maru.workforce.migrations.0026_programme_starter_integrity",
)
PROGRAMME_STARTER_INTEGRITY_CONTRACT = replace(
    _BASE,
    source_contract_current=_BASE.source_contract_current and _sources_current(),
    supporting_migrations=(("workforce", "0025_programme_starter_records"),),
    owned_relations=PROGRAMME_STARTER_RELATIONS,
)
# Observed from empty PostgreSQL 17.11 schema only; not workflow acceptance.
PROGRAMME_STARTER_SCHEMA_SHA256: Final[dict[str, str]] = {
    "workforce_programmestarterdecision": (
        "d4668b5dbedec80f0b5e62ca09f00db5eed6dc8e836164d15d649c207f91af6d"
    ),
    "workforce_programmestarterrequest": (
        "a4d2395e540d1b93445a668cef853ce5a7399138bda17391f9dd75d36f120a55"
    ),
}


def programme_starter_database_integrity_is_ready() -> bool:
    """Require exact retained tables, native guard definitions and attachments.

    Returns
    -------
    bool
        Whether the complete source-pinned native schema is current; not actor
        authorization, template creation, native workflow acceptance or activation.
    """
    try:
        return (
            set(PROGRAMME_STARTER_SCHEMA_SHA256) == set(PROGRAMME_STARTER_RELATIONS)
            and database_integrity_contract_is_ready(
                PROGRAMME_STARTER_INTEGRITY_CONTRACT
            )
            and relation_schema_is_current(PROGRAMME_STARTER_SCHEMA_SHA256)
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False
