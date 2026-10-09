"""Data-free integrity for Guidance foundation and accepted adoption receipts."""

import hashlib
import inspect
from dataclasses import replace
from importlib import import_module

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError

from maru.core.database_integrity_readiness import (
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
    parse_database_integrity_sql_contracts,
)
from maru.core.relation_schema_readiness import relation_schema_is_current

GUIDANCE_SETUP_RELATIONS = (
    "events_guidanceadoptionsetupreceipt",
    "events_guidanceactivationrequest",
    "events_guidanceactivationdecision",
    "events_guidanceactivationreceipt",
)
# EventEdition carries the new immutable adoption revision and exact pair constraint.
GUIDANCE_SETUP_SCHEMA_RELATIONS = (*GUIDANCE_SETUP_RELATIONS, "events_eventedition")
# Intentionally unobserved until the first approved fresh PostgreSQL migration.
GUIDANCE_SETUP_SCHEMA_SHA256: dict[str, str] = {}
_GUIDANCE_SOURCE_SHA256: dict[str, str] = {
    "maru.events.migrations.0022_guidance_adoption_profiles": (
        "c35e5287337e6d865420965b597a171f236632b47ad99bfd3135d0c216694810"
    ),
    "maru.events.migrations.0023_guidance_adoption_integrity": (
        "cd6ac2e5fc04957a422dc78003c341970c5f35e3863837ca7e8da949f3ae304c"
    ),
    "maru.events.migrations.0024_guidance_adoption_downgrade_fence": (
        "3e75eee14a19641e6b645e6f7b8a44da37fd0cb221481d69e00b9d933b3d7444"
    ),
}


def guidance_setup_database_integrity_is_ready() -> bool:
    """Verify native setup receipts and adoption graph without reading tenant rows.

    Returns
    -------
    bool
        Whether the complete exact contract is currently satisfied.
    """
    try:
        base = build_database_integrity_contract(
            status_key="guidance_setup_integrity",
            app_label="events",
            source_migration=("events", "0023_guidance_adoption_integrity"),
            terminal_migration=("events", "0024_guidance_adoption_downgrade_fence"),
            source_migration_module=(
                "maru.events.migrations.0023_guidance_adoption_integrity"
            ),
        )
        aggregate = import_module(
            "maru.events.migrations.0023_guidance_adoption_integrity"
        )
        _, aggregate_functions = parse_database_integrity_sql_contracts(
            (
                "CREATE FUNCTION "
                "public.maru_validate_edition_aggregate_version() "
                "RETURNS trigger AS $$"
            )
            + aggregate.next_source()
            + "$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;"
        )
        aggregate_triggers, _ = parse_database_integrity_sql_contracts(
            "CREATE TRIGGER events_aggregate_version_guard BEFORE INSERT OR UPDATE "
            "ON public.events_eventedition FOR EACH ROW EXECUTE FUNCTION "
            "public.maru_validate_edition_aggregate_version();"
        )
        contract = replace(
            base,
            functions={**base.functions, **aggregate_functions},
            source_contract_current=base.source_contract_current
            and all(
                hashlib.sha256(
                    inspect.getsource(import_module(name))
                    .replace("\r\n", "\n")
                    .encode()
                ).hexdigest()
                == expected
                for name, expected in _GUIDANCE_SOURCE_SHA256.items()
            ),
            triggers={
                name: trigger
                for name, trigger in base.triggers.items()
                if trigger.table in GUIDANCE_SETUP_RELATIONS
            },
            supporting_triggers={
                **{
                    name: trigger
                    for name, trigger in base.triggers.items()
                    if trigger.table == "events_eventedition"
                },
                **aggregate_triggers,
            },
            owned_relations=GUIDANCE_SETUP_RELATIONS,
            supporting_owned_relations=("events_eventedition",),
            supporting_migrations=(
                ("events", "0022_guidance_adoption_profiles"),
                ("authorization", "0047_guidance_qualified_lineage"),
            ),
        )
        return (
            set(GUIDANCE_SETUP_SCHEMA_SHA256) == set(GUIDANCE_SETUP_SCHEMA_RELATIONS)
            and database_integrity_contract_is_ready(contract)
            and relation_schema_is_current(GUIDANCE_SETUP_SCHEMA_SHA256)
        )
    except (
        DatabaseError,
        ImportError,
        LookupError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def require_guidance_setup_integrity() -> None:
    """Fail closed before any Guidance setup or decision data can be used.

    Raises
    ------
    PermissionDenied
        If the installed native source, schema or trigger protection is unavailable.
    """
    if not guidance_setup_database_integrity_is_ready():
        raise PermissionDenied("Guidance setup protection is unavailable.")
