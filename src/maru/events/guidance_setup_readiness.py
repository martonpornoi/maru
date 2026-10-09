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
# Observed from the isolated PostgreSQL 17.11 fresh schema on 2026-10-09.
GUIDANCE_SETUP_SCHEMA_SHA256: dict[str, str] = {
    "events_eventedition": (
        "44d54921e563ab839bb9ae15685dd0768fdf48ab5e5e0c327ce1a9679d4b4d47"
    ),
    "events_guidanceactivationdecision": (
        "3e48e1c42c42625b845e13b96350e00b41a16f6a073d3c9b63175dedea11fe8d"
    ),
    "events_guidanceactivationreceipt": (
        "7a685aa3598f0f3a9940dc3625c1c4662977ea5f3202d963e8469e7631bd9172"
    ),
    "events_guidanceactivationrequest": (
        "fa8c1380cb57b100da289b6434897c8e6de55ceb8c49f89e982fd7a88d79b2f7"
    ),
    "events_guidanceadoptionsetupreceipt": (
        "e2670721d793778f4366424d7bf606fa27d007155c27131e162305a42f687be8"
    ),
}
_GUIDANCE_SOURCE_SHA256: dict[str, str] = {
    "maru.events.migrations.0022_guidance_adoption_profiles": (
        "c35e5287337e6d865420965b597a171f236632b47ad99bfd3135d0c216694810"
    ),
    "maru.events.migrations.0023_guidance_adoption_integrity": (
        "79a8765a3edc1cb63fc8ffc2b6659b35e7a820640c7ba8c738d8d42445c8b5a6"
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


class GuidanceSetupUnavailable(PermissionDenied):
    """Installed Guides protection is unavailable, rather than an actor being denied."""


def require_guidance_setup_integrity() -> None:
    """Fail closed before any Guidance setup or decision data can be used.

    Raises
    ------
    GuidanceSetupUnavailable
        If the installed native source, schema or trigger protection is unavailable.
    """
    if not guidance_setup_database_integrity_is_ready():
        raise GuidanceSetupUnavailable("Guidance setup protection is unavailable.")
