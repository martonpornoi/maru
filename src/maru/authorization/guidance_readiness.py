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
# Intentionally unobserved until the first approved fresh PostgreSQL migration.
GUIDANCE_AUTHORITY_SCHEMA_SHA256: dict[str, str] = {}
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
        "a356a2656120d5f1391ed1b5411b5582904affb477228989d545eefcf8d388c0"
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


def require_guidance_authority_integrity() -> None:
    """Refuse protected reads and commands unless exact native authority is ready.

    Raises
    ------
    PermissionDenied
        If current actor, purpose, scope or native protection is unavailable.
    """
    from maru.authorization.provenance_readiness import (  # noqa: PLC0415
        authority_provenance_runtime_contract_is_ready,
    )

    if (
        not guidance_authority_database_integrity_is_ready()
        or not authority_provenance_runtime_contract_is_ready()
    ):
        raise PermissionDenied("Guidance responsibility protection is unavailable.")
