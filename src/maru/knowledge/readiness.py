"""Fail-closed native Knowledge contract and independently observed schema pins."""

import hashlib
import inspect
from importlib import import_module

from django.db import DatabaseError

from maru.authorization.guidance_readiness import (
    guidance_authority_database_integrity_is_ready,
)
from maru.authorization.provenance_readiness import (
    authority_provenance_runtime_contract_is_ready,
)
from maru.core.database_integrity_readiness import (
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
    extend_database_integrity_contract,
)
from maru.core.relation_schema_readiness import relation_schema_is_current
from maru.events.guidance_setup_readiness import (
    guidance_setup_database_integrity_is_ready,
)

from .errors import GuidanceError

KNOWLEDGE_SCHEMA_RELATIONS = (
    "knowledge_guidancecontrol",
    "knowledge_guidanceitem",
    "knowledge_guidancesettingsrevision",
    "knowledge_guidancerevision",
    "knowledge_guidancereview",
    "knowledge_guidancecommandreceipt",
)

# Populated only from the fresh PostgreSQL schema observation after migration.
# Verified against the isolated PostgreSQL 17.11 catalog on 2026-10-09.
KNOWLEDGE_SCHEMA_SHA256: dict[str, str] = {
    "knowledge_guidancecommandreceipt": (
        "b3f8794df4f9a3bc091dbcc4bb060d6b9eaee2af3174f063596ed2a66a5b6248"
    ),
    "knowledge_guidancecontrol": (
        "0f425abda46e7d2eebdc33730df6985171fc16644fc245c852d96ceecff8bff1"
    ),
    "knowledge_guidanceitem": (
        "16e555dbe9d775475b67d2840cc63e95527379068000a433dc253e80b5946bca"
    ),
    "knowledge_guidancereview": (
        "236d733b445bc91a4d40fe7222e83074ee9ebe4058c273d2b08918ec098de35e"
    ),
    "knowledge_guidancerevision": (
        "7aed362956dd6e5d82f2f72c1990c3ad0a9b1f7da61e87c2cc19796867a5d528"
    ),
    "knowledge_guidancesettingsrevision": (
        "cf73b78f52a1d45d25be4ac7a9a205963095cdc9e2763ff07ce85a5ab8296c85"
    ),
}
_FENCE_SHA256 = "8918489c3e935d795d48772770307bfad4611e1518f9ae55a724e44b870bb340"

_PLACEMENTS_SUCCESSOR_SHA256 = (
    "0bde789da6ede1110af2437fc4aa5734db10cfa905a28e572ccf7ac37454f76b"
)


def knowledge_database_integrity_is_ready() -> bool:
    """Require the exact installed native owner contract and observed relation shapes.

    Returns
    -------
    bool
        False for missing, changed, unobserved or unavailable native protections.
    """
    if (
        set(KNOWLEDGE_SCHEMA_SHA256) != set(KNOWLEDGE_SCHEMA_RELATIONS)
        or not _FENCE_SHA256
    ):
        return False
    try:
        if not (
            guidance_setup_database_integrity_is_ready()
            and guidance_authority_database_integrity_is_ready()
            and authority_provenance_runtime_contract_is_ready()
        ):
            return False
        contract = build_database_integrity_contract(
            status_key="knowledge_integrity",
            app_label="knowledge",
            source_migration=("knowledge", "0002_integrity"),
            terminal_migration=("knowledge", "0004_optional_guidance_placements"),
            source_migration_module="maru.knowledge.migrations.0002_integrity",
        )
        contract = extend_database_integrity_contract(
            contract,
            migration_module="maru.knowledge.migrations.0004_optional_guidance_placements",
            source_sha256=_PLACEMENTS_SUCCESSOR_SHA256,
        )
        fence = import_module("maru.knowledge.migrations.0003_downgrade_fence")
        return (
            database_integrity_contract_is_ready(contract)
            and relation_schema_is_current(KNOWLEDGE_SCHEMA_SHA256)
            and hashlib.sha256(
                inspect.getsource(fence).replace("\r\n", "\n").encode()
            ).hexdigest()
            == _FENCE_SHA256
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


def require_knowledge_integrity() -> None:
    """Refuse reads and writes if any native evidence protection is unavailable.

    Raises
    ------
    GuidanceError
        If owner or foundation protections, including active exact provenance, fail.
    """
    if not knowledge_database_integrity_is_ready():
        raise GuidanceError
