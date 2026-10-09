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
# Empty pins deliberately refuse use during source-only implementation.
KNOWLEDGE_SCHEMA_SHA256: dict[str, str] = {}
_FENCE_SHA256 = ""


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
            terminal_migration=("knowledge", "0003_downgrade_fence"),
            source_migration_module="maru.knowledge.migrations.0002_integrity",
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
