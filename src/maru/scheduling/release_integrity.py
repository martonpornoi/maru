"""Source-pinned native release guards shared by their participating owner probes."""

from importlib import import_module
from typing import Final

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    extend_database_integrity_contract,
    parse_database_integrity_sql_contracts,
)

# Ordered installation/replacement history, including schema and populated fences.
NATIVE_RELEASE_MIGRATION_SOURCES: Final = (
    (
        "audit.0009_native_mutation_witness",
        "38ad47ee1521fbec6441eb2e1cd9f507e1f30bce9c640276832b99b2acf6179b",
    ),
    (
        "scheduling.0007_release_dependency_journal",
        "d41073484ebbfecb50a2e849f4e46adfd6dc3f92e223a011a42c9a861c9fb546",
    ),
    (
        "scheduling.0008_release_dependency_guards",
        "7f86000006e0be97090043abbfc461189ce3fcc3d5500c338af5b65f87166ca9",
    ),
    (
        "identity.0021_release_dependency_deactivation",
        "1302ad49ecc001ac547cf511a1b633fd0ec993d0f964b996ab401de9ed32a70a",
    ),
    (
        "programme.0016_release_dependency_mutations",
        "2b49d32e4f9615bdebcccedbfb5284c064465ef8b7513174ff496c87fd0b098a",
    ),
    (
        "workforce.0022_release_dependency_mutations",
        "33249e5cf9b0dd9ddcb67984bfbf4dd50d7af9699d8242455c9e13a6bf48a7ce",
    ),
    (
        "events.0011_release_dependency_mutations",
        "8966b3145e2607f7d41cdc1ea3618f89df9eabfbf92d7f45fe10f1895f42eded",
    ),
    (
        "venues.0006_release_dependency_mutations",
        "76803eaef44bb48e2e6fbdee6675fb2e5364f2f30da1daab3521b612e1feb9d9",
    ),
    (
        "venues.0007_release_physical_closure",
        "033d5554700f78119145d202a3c0d018e58fdabc432b15fa08c0f912334eb915",
    ),
    (
        "scheduling.0009_native_release_journal_writer",
        "a69312a334bd49a7f322acb045c9eb6f5016c32d308bc5c3db87abf30353ca04",
    ),
    (
        "scheduling.0010_release_approval_and_publication_schema",
        "f9ec069a06e9e52cd3fcbdb86eb4635ebfc01191b99eaf437a005f4566375d76",
    ),
    (
        "scheduling.0011_release_source_baseline",
        "3a3b5881e395d1a19f51d28c8e9b3bd8ddf1065ff4c5b34a129e77094edde7fa",
    ),
    (
        "venues.0008_release_first_capture",
        "0837f75aaab7bfa4f276e255590fb3395d74d551ea2cc277aae822d46f5ec5ef",
    ),
    (
        "scheduling.0012_release_native_execution_boundary",
        "6d4c17bae80333ccdea91149cab6133f198b4dc60dc2b64f3d75108be1da0dc3",
    ),
    (
        "scheduling.0013_person_obligation_dependency_kind",
        "3edde9edbf94ef51e8881ca63c46ee65cddc3ad298d844f66a798825a10e992d",
    ),
    (
        "identity.0022_person_obligation_source_identity",
        "7cc87ab7c7de41a801b7d83b3efb9119c4875fdf3610192711672a0f2da50a8e",
    ),
    (
        "workforce.0023_global_person_obligation_generation",
        "87c4d701d222ab15031c4acf12c0dca40ec8f785a3d266cb7679add7408883f5",
    ),
    (
        "scheduling.0014_person_obligation_native_source",
        "3da3174fa2b2eaa948bb31712f5b3d54a9f11d234dfd8ae455d54f603fda44f1",
    ),
    (
        "scheduling.0015_release_dependency_membership",
        "c84188978c0f67d5b030cd3d4cdea1883e578e1820346e53a7aca9729fb5971d",
    ),
    (
        "scheduling.0016_release_review_graph",
        "b6e8c34c87a80429c15db9d620755ae8e14404d37122552f8443a289d5a55ca7",
    ),
    (
        "scheduling.0017_atomic_release_graph",
        "bbae7795773d9ca15a3f2a5afd1fe44ec843c252aca6cbaedd298583ac960bf5",
    ),
    (
        "programme.0017_operational_public_review",
        "c27d7778cef2e35275f3b6d99af221f3e953b966fdbbafaaf3f98c653281ed24",
    ),
    (
        "programme.0018_public_copy_withdrawal",
        "a9c0a65284e6264bce8bfd44e0e7a0149d074cfc9f85edab416195515bfcbe49",
    ),
    (
        "programme.0019_public_copy_withdrawal_integrity",
        "8d124ccdedf0b4f9d79ee8b257006d5f4c5e9b79448dc488afaede6204770db6",
    ),
    (
        "scheduling.0018_published_person_conflict_source",
        "19183e6eca07428820994c98357643b92f91e91f5230f6f948a7baedc3d0c083",
    ),
    (
        "workforce.0024_published_host_obligation_guard",
        "f127a30a9e0a78cb1ae3525fa6e3189ffbd3a6d8cacc673b3d21ec1baf001559",
    ),
    (
        "scheduling.0019_reciprocal_published_person_guard",
        "7bdbe745a164460f655dfb28f624ce1094aff1e85af3d36ef2771131fc9e3f5d",
    ),
    (
        "scheduling.0020_release_recovery_fence",
        "bf03c76e4afc7b7f4938eec1312aef4baba8e0ebe842260bd49ed04b61f97e4a",
    ),
)
NATIVE_RELEASE_RUNTIME_FUNCTIONS: Final = frozenset(
    {
        "maru_audit_current_native_transaction_stamp()",
        "maru_identity_release_deactivation_valid(uuid, uuid)",
        "maru_programme_release_mutation_sources(uuid)",
        "maru_programme_release_change_valid(text, uuid, uuid, uuid, uuid)",
        "maru_workforce_release_mutation_sources(uuid)",
        "maru_workforce_release_change_valid(text, uuid, uuid, uuid, uuid)",
        "maru_events_release_change_valid(uuid, uuid, uuid, uuid)",
        "maru_venues_release_mutation_sources(uuid)",
        "maru_venues_release_change_valid(text, uuid, uuid, uuid, uuid)",
        "maru_scheduling_lock_release_source(text, uuid, uuid, uuid)",
        "maru_scheduling_release_native_change_valid(text, uuid, uuid, uuid, uuid)",
        "maru_scheduling_record_native_release_change(text, uuid, uuid)",
        "maru_scheduling_published_person_conflict("
        "uuid, timestamptz, timestamptz, timestamptz, uuid)",
    }
)
_DEFINER_FUNCTIONS: Final = frozenset(
    {
        "maru_audit_capture_native_mutation()",
        "maru_scheduling_record_native_release_change(text, uuid, uuid)",
    }
)


def with_native_release_integrity(
    contract: DatabaseIntegrityContract,
) -> DatabaseIntegrityContract:
    """Add exact native dependency guards without granting runtime permissions.

    Parameters
    ----------
    contract : DatabaseIntegrityContract
        Participating owner's existing closed integrity contract.

    Returns
    -------
    DatabaseIntegrityContract
        Earlier invariants plus source-pinned native functions, attached owner
        triggers, recorder dependencies and the explicit runtime execution set.
    """
    for reference, digest in NATIVE_RELEASE_MIGRATION_SOURCES:
        app, name = reference.split(".", 1)
        module_name = f"maru.{app}.migrations.{name}"
        module = import_module(module_name)
        _triggers, functions = parse_database_integrity_sql_contracts(
            getattr(module, "FORWARD_SQL", "")
        )
        contract = extend_database_integrity_contract(
            contract,
            migration_module=module_name,
            source_sha256=digest,
            runtime_executable_functions=NATIVE_RELEASE_RUNTIME_FUNCTIONS
            & functions.keys(),
            security_definer_functions=_DEFINER_FUNCTIONS & functions.keys(),
        )
    return contract
