"""Exact dormant Scheduling integrity, reciprocal guards and schema readiness."""

from __future__ import annotations

import hashlib
import inspect
from dataclasses import replace
from importlib import import_module
from typing import Final

from django.db import DatabaseError, connection

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)
from maru.core.relation_schema_readiness import relation_schema_is_current

_BASE = build_database_integrity_contract(
    status_key="scheduling_integrity",
    app_label="scheduling",
    source_migration=("scheduling", "0005_integrity_guards"),
    terminal_migration=("scheduling", "0006_scheduling_downgrade_fence"),
    source_migration_module="maru.scheduling.migrations.0005_integrity_guards",
)
_VENUE = build_database_integrity_contract(
    status_key="venues_integrity",
    app_label="venues",
    source_migration=("venues", "0004_scheduling_binding_integrity"),
    terminal_migration=("venues", "0005_scheduling_downgrade_fence"),
    source_migration_module="maru.venues.migrations.0004_scheduling_binding_integrity",
)
_FENCE = import_module("maru.scheduling.migrations.0006_scheduling_downgrade_fence")
_FENCE_SHA256 = "1d7fb01e7311dadbbd9d48899a240a37a9fccf4f47bf001da24d24528d6803b6"
SCHEDULING_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = replace(
    _BASE,
    triggers={
        **_BASE.triggers,
        **{
            name: trigger
            for name, trigger in _VENUE.triggers.items()
            if trigger.table.startswith("scheduling_")
        },
    },
    functions={**_BASE.functions, **_VENUE.functions},
    source_contract_current=(
        _BASE.source_contract_current
        and _VENUE.source_contract_current
        and hashlib.sha256(
            inspect.getsource(_FENCE).replace("\r\n", "\n").encode()
        ).hexdigest()
        == _FENCE_SHA256
    ),
)
SCHEDULING_SCHEMA_SHA256: Final = {
    "scheduling_schedulingcandidate": (
        "2f8518f5624a2349f621fc46f2436e32d88a79defffec7ac7d38198f123d32fa"
    ),
    "scheduling_schedulingcandidatemember": (
        "5b076c4a0f48333895e825f5c8c994a203703d9b77fb75ff9d1b8f50bc0bbe10"
    ),
    "scheduling_schedulingcandidaterevision": (
        "307fe3e44d7db5f44f460bc8602dd5006aec7abda05102bb17db6b7606fbac73"
    ),
    "scheduling_schedulingcommandreceipt": (
        "3bd7e36974aa7af5a1b897a1df783087ac53f618d4b3f23766b2338a51b431d2"
    ),
    "scheduling_schedulingconflict": (
        "f8ad18e82e6a9a05b61707371a088c41f9cb02223f062eceec0fb78af596bc29"
    ),
    "scheduling_schedulingeditioncontrol": (
        "90b0c069a553b20ece44cf08e8d1454f77ab40879d38630679684d839a514522"
    ),
    "scheduling_schedulingevaluation": (
        "afdbcb8f656e23ac4d558351efa6b1b04dde660ee52722b7238a9d1bd0ccbddb"
    ),
    "scheduling_schedulingoccurrence": (
        "574ad9029ff6fff043dcc65b070e8647aa3e7d3238775c2e01b2330a35fd8a47"
    ),
    "scheduling_schedulingoccurrencerevision": (
        "a1efbb98488747e6fb21dcffcd8b541f0eac88de9d56e79d5ccce987517598d6"
    ),
    "scheduling_schedulingplacementhostpresence": (
        "22ee669161f36205fd32ba83c6afa8f68f94b30c16d06adaa2259c9095e71248"
    ),
    "scheduling_schedulingplacementrevision": (
        "4141c6cfe17698462109d36fea29ff7e2f13ebacc937a30da448f136629d2603"
    ),
    "scheduling_schedulingreservationintent": (
        "b72d25da54b2bc1e2b1767b84721be858d75e4d93a03516118f525a9b5adf1ee"
    ),
    "scheduling_schedulingserviceday": (
        "997b718313fc7be5242f04f8e606b370d5d09f57d32467b0e1325bfb3131d40f"
    ),
    "scheduling_schedulingservicedayrevision": (
        "16f530256c0d0ec21107be95bfc231aaec9d9633a03da870f7860ffe09bc6789"
    ),
    "scheduling_schedulingwarningacknowledgement": (
        "f9ab1833021328313dcfa5488b5da3d7d945112625ba7583bee38e29c5538c64"
    ),
}


def scheduling_database_integrity_is_ready() -> bool:
    """Require exact guards, populated recovery fences and data-free schema shapes.

    Returns
    -------
    bool
        Whether every retained Scheduling relation matches its reviewed contract.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT relation.relname::text FROM pg_catalog.pg_class relation "
                "JOIN pg_catalog.pg_namespace namespace "
                "ON namespace.oid = relation.relnamespace "
                "WHERE namespace.nspname = 'public' "
                "AND relation.relkind NOT IN ('i','I') "
                "AND left(relation.relname, 11) = 'scheduling_'"
            )
            names = {row[0] for row in cursor.fetchall()}
        return (
            names == set(SCHEDULING_SCHEMA_SHA256)
            and database_integrity_contract_is_ready(SCHEDULING_INTEGRITY_CONTRACT)
            and relation_schema_is_current(SCHEDULING_SCHEMA_SHA256)
        )
    except (DatabaseError, LookupError, TypeError, ValueError):
        return False
