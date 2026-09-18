"""Literal isolated-helper permissions; no production grants or readiness bypass.

Thirteen invoker-security helpers only inspect/validate native source evidence.
The sole additional SECURITY DEFINER helper only tries a transaction advisory
lock and raises a retry error. Trigger entrypoints and all other owner-only
helpers gain no new execution rights.
The five existing owner metadata probes still inspect their full contracts; only
the expected ACL of explicitly listed helpers changes in the opted-in child.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from importlib import import_module
from types import MappingProxyType


class ProgrammeFunctionError(RuntimeError):
    """Expose a stable helper-contract error without private database details."""


@dataclass(frozen=True)
class HelperPermission:
    """Reviewed native metadata, independent of runtime database observations."""

    source_sha256: str
    result: str = "boolean"
    language: str = "plpgsql"
    volatility: str = "v"
    strict: bool = False
    returns_set: bool = False
    security_definer: bool = False

    @property
    def metadata(self):
        """Return the exact catalog fields checked before and after the grant."""
        return (
            self.source_sha256,
            self.language,
            self.volatility,
            "u",  # PARALLEL UNSAFE
            self.security_definer,
            False,  # Not LEAKPROOF
            self.strict,
            self.returns_set,
            "f",
            ("search_path=pg_catalog, public, pg_temp",),
            self.result,
        )


HELPERS = MappingProxyType(
    {
        "maru_applications_review_stage_ready(uuid, integer, bigint)": HelperPermission(
            "8cbc00cdf7d246cf343dac1da7b5815b656a90ca9651265f252317f747f085fa",
            volatility="s",
        ),
        "maru_programme_role_recipe(text, integer)": HelperPermission(
            "c706c56066f52fc7e94b2f239b67afec8b68111f9bdd173f2b459d222ecb0a14",
            result="jsonb",
            volatility="i",
        ),
        "maru_programme_role_scope_current(uuid, uuid, uuid, uuid)": HelperPermission(
            "2121cfdc99398e17ac2dceeb7cb50106dd47546fcee4fa9f9c8babb919296641",
        ),
        "maru_scheduling_canonical_json(jsonb)": HelperPermission(
            "1d1ebab059674d8b1dd0552fc1bd2b102bac9cf87c922359cb3011a08ec99a6d",
            result="text",
            volatility="i",
            strict=True,
        ),
        "maru_scheduling_change_notice_source_valid(uuid)": HelperPermission(
            "04e6fc733d393a5ef868f89d4aa702c4ba225af4ced80824696ff3480d8c2dae",
        ),
        "maru_scheduling_evidence_is_current(jsonb, uuid, uuid)": HelperPermission(
            "6066fe9e6efdcdf695ebad8d156485d22204fac7385d1c1b93da9bf74881630e",
            strict=True,
        ),
        "maru_scheduling_evidence_shape(jsonb)": HelperPermission(
            "74bc23a6e909700165eb4a1c3c67a47a503acf1da64ad9319381609ad4d81435",
            volatility="i",
            strict=True,
        ),
        "maru_scheduling_exact_keys(jsonb, text[])": HelperPermission(
            "6a6439058ac92a77491229b8bf863d4978697a40a0139db019114f22f54aa688",
            language="sql",
            volatility="i",
            strict=True,
        ),
        "maru_scheduling_expected_release_dependencies(uuid, uuid, uuid, uuid)": (
            HelperPermission(
                "053869731bfc5f31e256e37993476331426cb3e2d7622077c0ab41dd70aacbb7",
                result=(
                    "TABLE(kind text, source_id uuid, placement_id uuid, horizon text, "
                    "operational_ends_at timestamp with time zone)"
                ),
                language="sql",
                returns_set=True,
            )
        ),
        "maru_scheduling_release_artifact_is_exact(uuid)": HelperPermission(
            "f93418444d08b1bbc8ae0e9ddcc758f022340aeec881df96f5c706cc57eb2108",
        ),
        "maru_scheduling_release_independent(uuid, uuid, uuid, uuid)": HelperPermission(
            "67f2e46eef05afe5af38d9f7263cbca022fe64aea80cf577a4f8b3b0b5fc4519",
        ),
        "maru_scheduling_release_person_obligations_valid(uuid)": HelperPermission(
            "9103e8a53df7a5325cffce44c4e38dd054a055e50603b8df9945f3d275e539ed",
        ),
        "maru_scheduling_validate_release_approval(uuid)": HelperPermission(
            "2196d335dd04318f9c9d9199cf76a7b271883b29b098faca44e3f084fc1f32d4",
            result="void",
        ),
        "maru_workforce_page9_try_scope_mutex(bigint)": HelperPermission(
            "a3fcdd50095145e1576c19cf8c82df986702562c5a37ef7163cada9f04070518",
            result="void",
            security_definer=True,
        ),
    }
)

MUTEX_IDENTITY = "maru_workforce_page9_try_scope_mutex(bigint)"
# Legacy SQL puts LANGUAGE before AS, outside the newer shared contract parser.
# Pin its complete declaration independently; canonical provenance readiness
# continues checking the existing complete pg_proc fingerprint unchanged.
MUTEX_DECLARATION = (
    "CREATE FUNCTION public.maru_workforce_page9_try_scope_mutex(target_lock bigint)\n"
    """RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_try_mutex$
BEGIN
    IF NOT pg_catalog.pg_try_advisory_xact_lock(target_lock) THEN
        RAISE EXCEPTION
            'Page 9 edition structure is being changed; retry the complete transaction'
            USING ERRCODE = '40001';
    END IF;
END;
$page9_try_mutex$;"""
)

# Exact pre-overlay contracts, including source-current flags, every trigger,
# migration, function body/attribute, relation and previous execution expectation.
# Shared native release helpers occur in Programme and Venues probes as well.
OWNER_CONTRACTS = (
    (
        "maru.applications.readiness",
        "APPLICATIONS_INTEGRITY_CONTRACT",
        "f2d205f6dea6b1cb33b8bc1e971d8e299d440f7c492a524f13ebf2747cc1d57f",
    ),
    (
        "maru.authorization.programme_role_readiness",
        "PROGRAMME_ROLE_INTEGRITY_CONTRACT",
        "b83f605f48caf3b944bfcaa6019eb2fda8f8a431c7d1d24565a02a200cb2d72b",
    ),
    (
        "maru.scheduling.readiness",
        "SCHEDULING_INTEGRITY_CONTRACT",
        "ffe9c6eb285b633900ec278170c2c5f99fea64ec6e68be9b83f8127b0860c77f",
    ),
    (
        "maru.programme.readiness",
        "PROGRAMME_INTEGRITY_CONTRACT",
        "013fbe7d51ba59d568ee156f93f505b184495504cce1e6b0f4516339d90eb29d",
    ),
    (
        "maru.venues.readiness",
        "VENUES_INTEGRITY_CONTRACT",
        "3b8effa6929e9648cc0ed231cabc1b03d94642c76fa24a8b98d2d0db9fabdaad",
    ),
)


def _encode(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return value.hex()


def contract_digest(contract):
    """Fingerprint all baseline owner evidence deterministically, without a DB."""
    encoded = json.dumps(
        asdict(contract), sort_keys=True, default=_encode, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def candidate_function_contracts():
    """Validate every baseline before returning any isolated ACL expectation.

    Returns
    -------
    tuple
        Owner module, attribute, original and projected contract; no mutation or
        query occurs here. Caller must enforce the runtime opt-in before install.
    """
    changes = []
    mutex = import_module("maru.workforce.migrations.0007_structure_write_integrity")
    if mutex.INSTALL_BARRIER_FUNCTIONS_SQL.count(MUTEX_DECLARATION) != 1:
        raise ProgrammeFunctionError("candidate_mutex_source_changed")
    mutex_source = MUTEX_DECLARATION.split("$page9_try_mutex$")[1].strip()
    if HELPERS[MUTEX_IDENTITY].metadata != (
        hashlib.sha256(mutex_source.encode()).hexdigest(),
        "plpgsql",
        "v",
        "u",
        True,
        False,
        False,
        False,
        "f",
        ("search_path=pg_catalog, public, pg_temp",),
        "void",
    ):
        raise ProgrammeFunctionError("candidate_mutex_metadata_changed")
    seen = {MUTEX_IDENTITY}
    for module_name, attribute, digest in OWNER_CONTRACTS:
        module = import_module(module_name)
        original = getattr(module, attribute)
        if not original.source_contract_current or contract_digest(original) != digest:
            raise ProgrammeFunctionError("candidate_function_contract_changed")
        helpers = HELPERS.keys() & original.functions.keys()
        if helpers & original.runtime_executable_functions:
            raise ProgrammeFunctionError("candidate_function_baseline_changed")
        for identity in helpers:
            function = original.functions[identity]
            actual = (
                function.source_sha256,
                function.language,
                function.volatility,
                function.parallel,
                function.security_definer,
                function.leakproof,
                function.strict,
                function.returns_set,
                function.kind,
                function.configuration,
                function.result,
            )
            if actual != HELPERS[identity].metadata:
                raise ProgrammeFunctionError("candidate_function_metadata_changed")
        seen.update(helpers)
        changes.append(
            (
                module,
                attribute,
                original,
                replace(
                    original,
                    runtime_executable_functions=(
                        original.runtime_executable_functions | helpers
                    ),
                ),
            )
        )
    if seen != HELPERS.keys():
        raise ProgrammeFunctionError("candidate_function_inventory_incomplete")
    return tuple(changes)
