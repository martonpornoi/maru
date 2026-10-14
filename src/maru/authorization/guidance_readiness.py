"""Data-free native contracts for closed Guidance authority evidence."""

import hashlib
import inspect
from dataclasses import replace
from importlib import import_module

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError

from maru.core.database_integrity_readiness import (
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
)
from maru.core.relation_schema_readiness import relation_schema_is_current

GUIDANCE_AUTHORITY_RELATIONS = (
    "authorization_guidanceteam",
    "authorization_guidanceauthoritysetupreceipt",
    "authorization_guidancerecipequalification",
    "authorization_guidanceaccessrequest",
    "authorization_guidanceaccessdecision",
    "authorization_guidancerevocationreceipt",
)
GUIDANCE_AUTHORITY_SUPPORTING_RELATIONS = (
    "authorization_rolebundle",
    "authorization_roleassignment",
    "authorization_capabilitygrant",
)
# Observed from the isolated PostgreSQL 17.11 fresh schema on 2026-10-09.
GUIDANCE_AUTHORITY_SCHEMA_SHA256: dict[str, str] = {
    "authorization_guidanceaccessdecision": (
        "a65c429a310b516a1069d7957cc43060b417334b76da929574c8485ea6438d5b"
    ),
    "authorization_guidanceaccessrequest": (
        "04ee4ed2a65f684e74ca566309f33f8eb7d9e2bbf6ea8930a739847f4ad9f1fe"
    ),
    "authorization_guidanceauthoritysetupreceipt": (
        "baba43f9e8408c0418ff797fde2943399977d853940929cb07af25a0a85c1180"
    ),
    "authorization_guidancerecipequalification": (
        "a8b51bdcba9f1836620448c27691501d5b714bd2bb99be5ba3da5d0c36322b6b"
    ),
    "authorization_guidancerevocationreceipt": (
        "e207e82a64b2494b1d848fb73a3ee4579f8ecbdebd2f8be5418ac39c59ecae2f"
    ),
    "authorization_guidanceteam": (
        "6a93549e44432ed485620aa09577fa7d6acaf887709123ea2424a79c8bfa3811"
    ),
}
_GUIDANCE_SOURCE_SHA256: dict[str, str] = {
    "maru.authorization.migrations.0043_guidance_capabilities": (
        "5266a15a32787e0626d0e6f9d065c33cc460cf483c472e569920d5e983fbc4b9"
    ),
    "maru.organizations.migrations.0016_workspace_representation": (
        "d41a0c7b6b84eaef9896d1242ed8f3777dfb7ca1b174c37821df931fb485421e"
    ),
    "maru.authorization.migrations.0044_workspace_operator_lineage": (
        "6f8991c14d3b6f1239bab6b04fcebe581aecee9508d40c8f9a257274b6e565f9"
    ),
    "maru.authorization.migrations.0045_guidance_authority_records": (
        "4bbe6d2ac0ad08869326779f147014a87812ec013d7cc0c64af5eaa1dd3f1b19"
    ),
    "maru.authorization.migrations.0046_guidance_authority_integrity": (
        "dfb0bb65e19cef0ad3c402526a21ee740c6ba232e2ed3818b9339ae669d087cf"
    ),
    "maru.authorization.migrations.0047_guidance_qualified_lineage": (
        "31b9db0ea10ea280af30b8e1d0f55b11615931787af6a6e3b731aaf986466eb7"
    ),
}


def guidance_authority_database_integrity_is_ready() -> bool:
    """Check exact installed source, attachments, schema and helper privileges.

    Returns
    -------
    bool
        Whether the complete exact contract is currently satisfied.
    """
    try:
        module = import_module(
            "maru.authorization.migrations.0046_guidance_authority_integrity"
        )
        base = build_database_integrity_contract(
            status_key="guidance_authority_integrity",
            app_label="authorization",
            source_migration=("authorization", "0046_guidance_authority_integrity"),
            terminal_migration=("authorization", "0047_guidance_qualified_lineage"),
            source_migration_module=module.__name__,
        )
        contract = replace(
            base,
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
                if trigger.table in GUIDANCE_AUTHORITY_RELATIONS
            },
            supporting_triggers={
                name: trigger
                for name, trigger in base.triggers.items()
                if trigger.table in GUIDANCE_AUTHORITY_SUPPORTING_RELATIONS
            },
            owned_relations=GUIDANCE_AUTHORITY_RELATIONS,
            supporting_owned_relations=GUIDANCE_AUTHORITY_SUPPORTING_RELATIONS,
            supporting_migrations=tuple(
                (name.split(".")[1], name.split(".")[-1])
                for name in _GUIDANCE_SOURCE_SHA256
            ),
            runtime_executable_functions=frozenset(module.NEW_FUNCTION_IDENTITIES),
        )
        return (
            set(GUIDANCE_AUTHORITY_SCHEMA_SHA256) == set(GUIDANCE_AUTHORITY_RELATIONS)
            and database_integrity_contract_is_ready(contract)
            and relation_schema_is_current(GUIDANCE_AUTHORITY_SCHEMA_SHA256)
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


class GuidanceAuthorityUnavailable(PermissionDenied):
    """Installed Guides protection is unavailable, rather than an actor being denied."""


def require_guidance_authority_integrity() -> None:
    """Refuse protected reads and commands unless exact native authority is ready.

    Raises
    ------
    GuidanceAuthorityUnavailable
        If current actor, purpose, scope or native protection is unavailable.
    """
    from maru.authorization.provenance_readiness import (  # noqa: PLC0415
        authority_provenance_runtime_contract_is_ready,
    )

    if (
        not guidance_authority_database_integrity_is_ready()
        or not authority_provenance_runtime_contract_is_ready()
    ):
        raise GuidanceAuthorityUnavailable(
            "Guidance responsibility protection is unavailable."
        )
