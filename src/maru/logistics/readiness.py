"""Data-free PostgreSQL readiness for the Logistics integrity boundary.

The Logistics write-integrity migration is intentionally large and is still
ordinary migration source, not a second handwritten readiness catalog.  This
module imports that source and derives the reviewed trigger and function sets
from ``FORWARD_SQL``/``REVERSE_SQL``.  Relation privilege profiles and model
constraints remain independently checked so weakening either layer fails the
production gate closed.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.apps import apps
from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.db import DatabaseError, connection, migrations, models
from django.db.models import CheckConstraint, Deferrable, UniqueConstraint

from maru.authorization.database_role_safety import (
    RUNTIME_DATABASE_SELECT_INSERT_RELATIONS,
    RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS,
    RuntimeDatabaseRoleProbeError,
    probe_runtime_database_role_safety,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from django.db.backends.utils import CursorWrapper

_SUPPORTED_DATABASE_SCHEMA: Final = "public"
_SUPPORTED_POSTGRESQL_SERVER_MAJOR: Final = 17
_REVIEWED_MIGRATIONS: Final = (
    ("logistics", "0001_initial"),
    ("authorization", "0016_logistics_capabilities_and_resource_kind"),
    ("venues", "0001_initial"),
    ("logistics", "0002_logistics_write_integrity"),
)
_INTEGRITY_MIGRATION_MODULE: Final = (
    "maru.logistics.migrations.0002_logistics_write_integrity"
)
_INTEGRITY_MIGRATION_DEPENDENCIES: Final = (
    ("authorization", "0016_logistics_capabilities_and_resource_kind"),
    ("logistics", "0001_initial"),
    ("venues", "0001_initial"),
)
_DOWNGRADE_FENCE_SOURCE_SHA256: Final = (
    "d2818e98ab9c187c3fcae23eb3735e3112060b4ee8fd56a73859faf2a070e49f"
)
_LOGISTICS_MODEL_COUNT: Final = 25
_INTEGRITY_MIGRATION_OPERATION_COUNT: Final = 2


class _IntegrityMigration(Protocol):
    APPEND_ONLY_TABLES: tuple[str, ...]
    ENTITY_TABLES: tuple[str, ...]
    TRUNCATE_TABLES: tuple[str, ...]
    CATALOG_SCOPE_TABLES: tuple[str, ...]
    EVIDENCE_SCOPE_TABLES: tuple[str, ...]
    LOGISTICS_MODEL_NAMES: tuple[str, ...]
    FORWARD_SQL: str
    REVERSE_SQL: str


_migration = cast(
    "_IntegrityMigration",
    import_module(_INTEGRITY_MIGRATION_MODULE),
)


@dataclass(frozen=True, slots=True)
class TriggerContract:
    """Exact non-internal trigger attachment derived from migration SQL.

    Attributes
    ----------
    name
        The human-readable name to normalize or persist.
    table
        The database table whose integrity contract is being inspected.
    function
        The function retained in this immutable projection.
    trigger_type
        The closed trigger type discriminator defined by the domain catalog.
    deferrable
        The deferrable retained in this immutable projection.
    initially_deferred
        The initially deferred retained in this immutable projection.
    """

    name: str
    table: str
    function: str
    trigger_type: int
    deferrable: bool
    initially_deferred: bool


@dataclass(frozen=True, slots=True)
class FunctionContract:
    """Behavior-bearing ``pg_proc`` fields derived from migration SQL.

    Attributes
    ----------
    identity
        The identity retained in this immutable projection.
    source
        The immutable source record or definition from which data is derived.
    language
        The language retained in this immutable projection.
    volatility
        The volatility retained in this immutable projection.
    parallel
        The parallel retained in this immutable projection.
    security_definer
        The security definer retained in this immutable projection.
    leakproof
        The leakproof retained in this immutable projection.
    strict
        The strict retained in this immutable projection.
    returns_set
        The returns set retained in this immutable projection.
    kind
        The closed discriminator selecting the requested behavior.
    configuration
        The configuration retained in this immutable projection.
    result
        The result retained in this immutable projection.
    """

    identity: str
    source: str
    language: str
    volatility: str
    parallel: str
    security_definer: bool
    leakproof: bool
    strict: bool
    returns_set: bool
    kind: str
    configuration: tuple[str, ...]
    result: str

    @property
    def definition_sha256(self) -> str:
        """Verify definition sha256.

        Returns
        -------
        str
            The normalized text for definition sha256.
        """
        return _function_definition_fingerprint(
            (
                self.source,
                self.language,
                self.volatility,
                self.parallel,
                self.security_definer,
                self.leakproof,
                self.strict,
                self.returns_set,
                self.kind,
                self.configuration,
                self.result,
            )
        )


@dataclass(frozen=True, slots=True)
class SchemaObjectContract:
    """One named model constraint or unique index.

    Attributes
    ----------
    name
        The human-readable name to normalize or persist.
    table
        The database table whose integrity contract is being inspected.
    catalog_kind
        The closed catalog kind discriminator defined by the domain catalog.
    constraint_type
        The closed constraint type discriminator defined by the domain catalog.
    deferrable
        The deferrable retained in this immutable projection.
    initially_deferred
        The initially deferred retained in this immutable projection.
    has_expressions
        Whether to has expressions.
    has_predicate
        Whether to has predicate.
    """

    name: str
    table: str
    catalog_kind: str
    constraint_type: str | None
    deferrable: bool
    initially_deferred: bool
    has_expressions: bool = False
    has_predicate: bool = False

    @property
    def key(self) -> str:
        """Verify key.

        Returns
        -------
        str
            The normalized text for key.
        """
        return f"{self.catalog_kind}:{self.name}"


@dataclass(frozen=True, slots=True)
class ImplicitUniqueContract:
    """One Django field-level uniqueness contract without a stable SQL name.

    Attributes
    ----------
    table
        The database table whose integrity contract is being inspected.
    columns
        The columns retained in this immutable projection.
    """

    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LogisticsProductionCatalog:
    """Identifier-free result of one bounded PostgreSQL catalog inspection.

    Attributes
    ----------
    server_version_supported
        The server version supported retained in this immutable projection.
    schema_order_safe
        The schema order safe retained in this immutable projection.
    reviewed_migrations_applied
        The reviewed migrations applied retained in this immutable projection.
    relations_installed
        The relations installed retained in this immutable projection.
    relation_ownership_consistent
        The relation ownership consistent retained in this immutable projection.
    relation_privilege_profiles_declared
        The relation privilege profiles declared retained in this immutable projection.
    btree_gist_installed
        The btree gist installed retained in this immutable projection.
    schema_definition_fingerprints_finalized
        Whether every schema-definition fingerprint is finalized.
    schema_definitions_current
        The schema definitions current retained in this immutable projection.
    implicit_uniques_current
        The implicit uniques current retained in this immutable projection.
    trigger_contract_current
        The trigger contract current retained in this immutable projection.
    function_contract_current
        The function contract current retained in this immutable projection.
    function_execute_boundary_closed
        The function execute boundary closed retained in this immutable projection.
    function_ownership_current
        The function ownership current retained in this immutable projection.
    runtime_function_execute_boundary_closed
        Whether runtime execution is denied outside the explicit allowlist.
    configured_runtime_role_safe
        The configured runtime role safe retained in this immutable projection.
    migration_contract_symmetric
        The migration contract symmetric retained in this immutable projection.
    """

    server_version_supported: bool
    schema_order_safe: bool
    reviewed_migrations_applied: bool
    relations_installed: bool
    relation_ownership_consistent: bool
    relation_privilege_profiles_declared: bool
    btree_gist_installed: bool
    schema_definition_fingerprints_finalized: bool
    schema_definitions_current: bool
    implicit_uniques_current: bool
    trigger_contract_current: bool
    function_contract_current: bool
    function_execute_boundary_closed: bool
    function_ownership_current: bool
    runtime_function_execute_boundary_closed: bool
    configured_runtime_role_safe: bool
    migration_contract_symmetric: bool

    @property
    def ready(self) -> bool:
        """Initialize the Django application integrations.

        Returns
        -------
        bool
            `True` when Initialize the Django application integrations; otherwise
            `False`.
        """
        return all(
            (
                self.server_version_supported,
                self.schema_order_safe,
                self.reviewed_migrations_applied,
                self.relations_installed,
                self.relation_ownership_consistent,
                self.relation_privilege_profiles_declared,
                self.btree_gist_installed,
                self.schema_definition_fingerprints_finalized,
                self.schema_definitions_current,
                self.implicit_uniques_current,
                self.trigger_contract_current,
                self.function_contract_current,
                self.function_execute_boundary_closed,
                self.function_ownership_current,
                self.runtime_function_execute_boundary_closed,
                self.configured_runtime_role_safe,
                self.migration_contract_symmetric,
            )
        )


_TRIGGER_RE: Final = re.compile(
    r"CREATE\s+(?:CONSTRAINT\s+)?TRIGGER\s+"
    r"(?P<name>[a-z0-9_]+)\s+"
    r"(?P<timing>BEFORE|AFTER)\s+"
    r"(?P<events>(?:INSERT|UPDATE|DELETE|TRUNCATE)"
    r"(?:\s+OR\s+(?:INSERT|UPDATE|DELETE|TRUNCATE))*)\s+"
    r"ON\s+public\.(?P<table>[a-z0-9_]+)\s+"
    r"(?:(?P<deferrable>DEFERRABLE)"
    r"(?:\s+(?P<initial>INITIALLY\s+(?:DEFERRED|IMMEDIATE)))?\s+)?"
    r"FOR\s+EACH\s+(?P<level>ROW|STATEMENT)\s+"
    r"EXECUTE\s+FUNCTION\s+public\.(?P<function>[a-z0-9_]+)"
    r"\((?P<arguments>[^)]*)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_DROP_TRIGGER_RE: Final = re.compile(
    r"DROP\s+TRIGGER\s+IF\s+EXISTS\s+(?P<name>[a-z0-9_]+)\s+"
    r"ON\s+public\.(?P<table>[a-z0-9_]+)\s*;",
    re.IGNORECASE,
)
_FUNCTION_RE: Final = re.compile(
    r"CREATE\s+FUNCTION\s+public\.(?P<name>[a-z0-9_]+)\s*"
    r"\((?P<arguments>.*?)\)\s*"
    r"RETURNS\s+(?P<result>[a-z0-9_]+)\s+AS\s+\$\$"
    r"(?P<source>.*?)\$\$\s+LANGUAGE\s+(?P<language>[a-z0-9_]+)"
    r"(?P<options>.*?);",
    re.IGNORECASE | re.DOTALL,
)
_DROP_FUNCTION_RE: Final = re.compile(
    r"DROP\s+FUNCTION\s+IF\s+EXISTS\s+public\."
    r"(?P<name>[a-z0-9_]+)\((?P<arguments>[^)]*)\)\s*;",
    re.IGNORECASE,
)
_REVOKE_FUNCTION_BLOCK_RE: Final = re.compile(
    r"REVOKE\s+ALL\s+ON\s+FUNCTION(?P<functions>.*?)FROM\s+PUBLIC\s*;",
    re.IGNORECASE | re.DOTALL,
)
_QUALIFIED_FUNCTION_RE: Final = re.compile(
    r"public\.(?P<name>[a-z0-9_]+)\((?P<arguments>[^)]*)\)",
    re.IGNORECASE,
)

_TRIGGER_EVENT_BITS: Final = {
    "INSERT": 4,
    "DELETE": 8,
    "UPDATE": 16,
    "TRUNCATE": 32,
}


def _canonical_type_list(arguments: str, *, declarations: bool) -> str:
    if not arguments.strip():
        return ""
    types: list[str] = []
    for argument in arguments.split(","):
        tokens = argument.strip().split()
        if not tokens:
            continue
        argument_type = " ".join(tokens[1:] if declarations else tokens)
        types.append(argument_type.lower())
    return ", ".join(types)


def _parse_trigger_contracts(sql: str) -> dict[str, TriggerContract]:
    contracts: dict[str, TriggerContract] = {}
    for match in _TRIGGER_RE.finditer(sql):
        name = match.group("name").lower()
        events = {event.strip().upper() for event in match.group("events").split("OR")}
        trigger_type = 0
        if match.group("level").upper() == "ROW":
            trigger_type |= 1
        if match.group("timing").upper() == "BEFORE":
            trigger_type |= 2
        for event in events:
            trigger_type |= _TRIGGER_EVENT_BITS[event]
        arguments = _canonical_type_list(
            match.group("arguments"),
            declarations=False,
        )
        contract = TriggerContract(
            name=name,
            table=match.group("table").lower(),
            function=f"{match.group('function').lower()}({arguments})",
            trigger_type=trigger_type,
            deferrable=match.group("deferrable") is not None,
            initially_deferred=(
                (match.group("initial") or "").upper() == "INITIALLY DEFERRED"
            ),
        )
        if name in contracts:
            raise RuntimeError(f"duplicate Logistics trigger declaration: {name}")
        contracts[name] = contract
    return contracts


def _parse_function_contracts(sql: str) -> dict[str, FunctionContract]:
    contracts: dict[str, FunctionContract] = {}
    for match in _FUNCTION_RE.finditer(sql):
        arguments = _canonical_type_list(
            match.group("arguments"),
            declarations=True,
        )
        identity = f"{match.group('name').lower()}({arguments})"
        options = " ".join(match.group("options").upper().split())
        volatility = (
            "s" if "STABLE" in options else "i" if "IMMUTABLE" in options else "v"
        )
        parallel = (
            "s"
            if "PARALLEL SAFE" in options
            else "r"
            if "PARALLEL RESTRICTED" in options
            else "u"
        )
        search_path = re.search(
            r"SET\s+SEARCH_PATH\s*=\s*([^;]+)",
            match.group("options"),
            re.IGNORECASE,
        )
        configuration = (
            (f"search_path={search_path.group(1).strip()}",)
            if search_path is not None
            else ()
        )
        contract = FunctionContract(
            identity=identity,
            source=match.group("source"),
            language=match.group("language").lower(),
            volatility=volatility,
            parallel=parallel,
            security_definer="SECURITY DEFINER" in options,
            leakproof="LEAKPROOF" in options,
            strict=(
                " STRICT" in f" {options}" or "RETURNS NULL ON NULL INPUT" in options
            ),
            returns_set=False,
            kind="f",
            configuration=configuration,
            result=match.group("result").lower(),
        )
        if identity in contracts:
            raise RuntimeError(f"duplicate Logistics function declaration: {identity}")
        contracts[identity] = contract
    return contracts


def _parse_dropped_trigger_keys(sql: str) -> set[tuple[str, str]]:
    return {
        (match.group("name").lower(), match.group("table").lower())
        for match in _DROP_TRIGGER_RE.finditer(sql)
    }


def _parse_dropped_function_identities(sql: str) -> set[str]:
    return {
        (
            f"{match.group('name').lower()}"
            f"({_canonical_type_list(match.group('arguments'), declarations=False)})"
        )
        for match in _DROP_FUNCTION_RE.finditer(sql)
    }


def _parse_revoked_function_identities(sql: str) -> set[str]:
    identities: set[str] = set()
    for block in _REVOKE_FUNCTION_BLOCK_RE.finditer(sql):
        for match in _QUALIFIED_FUNCTION_RE.finditer(block.group("functions")):
            arguments = _canonical_type_list(
                match.group("arguments"),
                declarations=False,
            )
            identities.add(f"{match.group('name').lower()}({arguments})")
    return identities


def _migration_contract_is_symmetric(forward_sql: str, reverse_sql: str) -> bool:
    triggers = _parse_trigger_contracts(forward_sql)
    functions = _parse_function_contracts(forward_sql)
    return all(
        (
            bool(triggers),
            bool(functions),
            {(contract.name, contract.table) for contract in triggers.values()}
            == _parse_dropped_trigger_keys(reverse_sql),
            set(functions) == _parse_dropped_function_identities(reverse_sql),
            set(functions) == _parse_revoked_function_identities(forward_sql),
        )
    )


def _migration_operations_are_reviewed() -> bool:
    migration_class = getattr(_migration, "Migration", None)
    operations = tuple(getattr(migration_class, "operations", ()))
    dependencies = tuple(getattr(migration_class, "dependencies", ()))
    downgrade_fence = getattr(
        _migration,
        "refuse_logistics_integrity_downgrade",
        None,
    )
    if not callable(downgrade_fence):
        return False
    try:
        downgrade_fence_source = (
            inspect.getsource(downgrade_fence).replace("\r\n", "\n").strip()
        )
    except (OSError, TypeError):
        return False
    if (
        dependencies != _INTEGRITY_MIGRATION_DEPENDENCIES
        or len(operations) != _INTEGRITY_MIGRATION_OPERATION_COUNT
    ):
        return False
    sql_operation, fence_operation = operations
    if not isinstance(sql_operation, migrations.RunSQL) or not isinstance(
        fence_operation,
        migrations.RunPython,
    ):
        return False
    model_names = tuple(_migration.LOGISTICS_MODEL_NAMES)
    return all(
        (
            sql_operation.sql == _migration.FORWARD_SQL,
            sql_operation.reverse_sql == _migration.REVERSE_SQL,
            fence_operation.code is migrations.RunPython.noop,
            fence_operation.reverse_code is downgrade_fence,
            len(model_names) == _LOGISTICS_MODEL_COUNT,
            len(set(model_names)) == _LOGISTICS_MODEL_COUNT,
            hashlib.sha256(downgrade_fence_source.encode("utf-8")).hexdigest()
            == _DOWNGRADE_FENCE_SOURCE_SHA256,
        )
    )


TRIGGER_CONTRACTS: Final[Mapping[str, TriggerContract]] = _parse_trigger_contracts(
    _migration.FORWARD_SQL
)
FUNCTION_CONTRACTS: Final[Mapping[str, FunctionContract]] = _parse_function_contracts(
    _migration.FORWARD_SQL
)
MIGRATION_CONTRACT_SYMMETRIC: Final = (
    _migration_contract_is_symmetric(
        _migration.FORWARD_SQL,
        _migration.REVERSE_SQL,
    )
    and _migration_operations_are_reviewed()
)


def _function_definition_fingerprint(definition: tuple[object, ...]) -> str:
    """Hash behavior-bearing ``pg_proc`` fields without exposing source.

    Parameters
    ----------
    definition : tuple[object, ...]
        The versioned definition governing the requested behavior.

    Returns
    -------
    str
        The normalized text for function definition fingerprint.
    """
    configuration = definition[9]
    normalized_configuration = (
        tuple(str(value) for value in cast("Iterable[object]", configuration))
        if configuration is not None
        else ()
    )
    payload = {
        "source": str(definition[0]).replace("\r\n", "\n").strip(),
        "language": definition[1],
        "volatility": definition[2],
        "parallel": definition[3],
        "security_definer": definition[4],
        "leakproof": definition[5],
        "strict": definition[6],
        "returns_set": definition[7],
        "kind": definition[8],
        "config": normalized_configuration,
        "result": definition[10],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _constraint_catalog_kind(constraint: models.BaseConstraint) -> str:
    if isinstance(constraint, UniqueConstraint):
        _, _, options = constraint.deconstruct()
        if any(
            (
                bool(constraint.condition),
                bool(constraint.expressions),
                bool(options.get("include")),
                bool(options.get("opclasses")),
                constraint.nulls_distinct is not None,
            )
        ):
            return "index"
    return "constraint"


def _constraint_type(constraint: models.BaseConstraint) -> str | None:
    if isinstance(constraint, CheckConstraint):
        return "c"
    if isinstance(constraint, ExclusionConstraint):
        return "x"
    if isinstance(constraint, UniqueConstraint):
        return "u" if _constraint_catalog_kind(constraint) == "constraint" else None
    raise TypeError(f"unsupported Logistics constraint type: {type(constraint)!r}")


@lru_cache(maxsize=1)
def logistics_relation_names() -> tuple[str, ...]:
    """Verify logistics relation names.

    Returns
    -------
    tuple[str, ...]
        The authorized logistics relation names records in deterministic order.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    """
    relations = tuple(
        cast("models.Model", apps.get_model("logistics", model_name))._meta.db_table
        for model_name in _migration.LOGISTICS_MODEL_NAMES
    )
    if len(relations) != len(set(relations)):
        raise RuntimeError("duplicate Logistics model relation declaration")
    return relations


@lru_cache(maxsize=1)
def declared_schema_object_contracts() -> Mapping[str, SchemaObjectContract]:
    """Verify declared schema object contracts.

    Returns
    -------
    Mapping[str, SchemaObjectContract]
        A disclosure-safe mapping for declared schema object contracts.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    """
    contracts: dict[str, SchemaObjectContract] = {}
    for model_name in _migration.LOGISTICS_MODEL_NAMES:
        model = apps.get_model("logistics", model_name)
        for constraint in model._meta.constraints:
            catalog_kind = _constraint_catalog_kind(constraint)
            deferrable = getattr(constraint, "deferrable", None)
            contract = SchemaObjectContract(
                name=constraint.name,
                table=model._meta.db_table,
                catalog_kind=catalog_kind,
                constraint_type=_constraint_type(constraint),
                deferrable=deferrable is not None,
                initially_deferred=deferrable == Deferrable.DEFERRED,
                has_expressions=(
                    isinstance(constraint, UniqueConstraint)
                    and bool(constraint.expressions)
                ),
                has_predicate=(
                    isinstance(constraint, UniqueConstraint)
                    and bool(constraint.condition)
                ),
            )
            if contract.key in contracts:
                raise RuntimeError(
                    f"duplicate Logistics schema contract: {contract.key}"
                )
            contracts[contract.key] = contract
    return contracts


@lru_cache(maxsize=1)
def declared_implicit_unique_contracts() -> tuple[ImplicitUniqueContract, ...]:
    """Verify declared implicit unique contracts.

    Returns
    -------
    tuple[ImplicitUniqueContract, ...]
        The declared implicit uniqueness contracts in deterministic order.
    """
    contracts: list[ImplicitUniqueContract] = []
    for model_name in _migration.LOGISTICS_MODEL_NAMES:
        model = apps.get_model("logistics", model_name)
        contracts.extend(
            ImplicitUniqueContract(
                table=model._meta.db_table,
                columns=(field.column,),
            )
            for field in model._meta.local_fields
            if field.unique and not field.primary_key
        )
    return tuple(sorted(contracts, key=lambda item: (item.table, item.columns)))


# Populated only from a freshly migrated PostgreSQL catalog after 0002's SQL
# digest settles.  An incomplete mapping deliberately keeps readiness blocked.
SCHEMA_DEFINITION_SHA256: Final[Mapping[str, str]] = {
    "constraint:log_acceptance_subject_one": (
        "acaa62f76d925d9af2230a186534a3115076ce777e4fdcce283c5d6215985cd9"
    ),
    "constraint:log_address_life_choice": (
        "0ef57bc184dc53b3d32769826576c6b060e94815625a2f3e1aa2ba96d732c296"
    ),
    "constraint:log_address_purpose_choice": (
        "c80e9ebb08262c6d5eb1aec393b9cc93bf26dbbe74ee37462598bf591443609f"
    ),
    "constraint:log_address_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_agree_asset_no_overlap": (
        "38c54d6fe953c3b8676edfac1daf510bd3164a8ca938100aa330c4c4bca125eb"
    ),
    "constraint:log_agree_key_no_overlap": (
        "b7765579d8646e4aacb55a6e9fdb223da59212e76a479378ae3399d2d380eece"
    ),
    "constraint:log_agree_lot_no_overlap": (
        "b61d1a21d6f7d09e536564f04def0a2134c079e27b941b85784349e3c2a52307"
    ),
    "constraint:log_agree_node_no_overlap": (
        "2fd4ea91dacc622ea9632091635f4882e10d860b7a761137031494973eb16c26"
    ),
    "constraint:log_agreement_interval": (
        "f7f53564896884f1edf5917820a7ba41f7cffde42c77a1d84f965bcfaa474baf"
    ),
    "constraint:log_agreement_kind_choice": (
        "95cf9ea4682fcd6b1ebf121507abd47f4dba236baf0d63afbaa09bc8c9891665"
    ),
    "constraint:log_agreement_return_due": (
        "09ae2974d37fbc9ab55665f1dada84c30a3f4f78dbd2b535a325de305e1313c5"
    ),
    "constraint:log_agreement_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_asset_acquire_choice": (
        "4ab8fedcc1ab529da830d73d5d2530dbb7847f62ebc6b670b7a9fd74777b5f57"
    ),
    "constraint:log_asset_lifecycle_choice": (
        "19f7d3ea5bb462f8c7f12c431a1d962d9e31e693e3459379238d2cc31f0d975c"
    ),
    "constraint:log_asset_owner_choice": (
        "77bb4660afa43f76f14ea56bca9b408266e933d51b54162a5f17d3bf3648ee85"
    ),
    "constraint:log_asset_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_command_idempotency_uq": (
        "a28d6cd046d4d2cfb9f46279cd4ef2dfc871bb3b1921935fb36157614d1ebb41"
    ),
    "constraint:log_discrepancy_kind_choice": (
        "f3c573c81cd45a24319dda6a7d3259d3a2181c493fedb41a219eceacfd76feb7"
    ),
    "constraint:log_discrepancy_status_choice": (
        "1cc156468ea63da6cd83b44300b2f8fff6742c210167d8fb0c0f48fb03487d2c"
    ),
    "constraint:log_discrepancy_subject_choice": (
        "e5dc2e517a2b3f86bd5b3b6ca4c37105af06fc4f580361835c7087d21c67dfe1"
    ),
    "constraint:log_discrepancy_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_event_sequence_pos": (
        "20190782a81fead614d4af3218b88a985a8f2d2a6de720c93939d72ab8e2baf9"
    ),
    "constraint:log_event_subject_choice": (
        "e5dc2e517a2b3f86bd5b3b6ca4c37105af06fc4f580361835c7087d21c67dfe1"
    ),
    "constraint:log_event_type_choice": (
        "2f23876981e4626f690fa4bf372485170e9c48dce43abe24c7909947f188e293"
    ),
    "constraint:log_key_lifecycle_choice": (
        "114d63acc77c90ec6a726c69fd2a0519582af5f8ad8e239944e13270d71d03c4"
    ),
    "constraint:log_key_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_keyholder_interval": (
        "b028063a057191ab09eb722844201ab7d606d84c05b1ec8748e71f3d35c65e39"
    ),
    "constraint:log_keyholder_no_overlap": (
        "1e1569d1cdabbed828a9ff8b732bc8f05133fea450c30ddec9d95910e891a2ea"
    ),
    "constraint:log_kit_lifecycle_choice": (
        "880b8febbfb7419537d3b00d8eb0bea81d6fe34ba51690d08b89d2aae092f1bc"
    ),
    "constraint:log_kit_line_count_bound": (
        "cc14db01bc4b5cd4fad12fcd8fe64166e00035479d1d99f10de3da56eb3b543c"
    ),
    "constraint:log_kit_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_label_lifecycle_choice": (
        "71262cbf96de26cabdd93618ddaa915941aa33df546c28aa4cba7036f7210998"
    ),
    "constraint:log_label_qr_digest_uq": (
        "750c5fc75e42a361d4420d9ec5ff46319287e3fb10e0be6ec18f6dc684076fd7"
    ),
    "constraint:log_label_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_lot_initial_qty_pos": (
        "7729e82a633dbf3bd7d7a8c4ec6c322eb2cb6d364ace1cadd1b1b5af11e88232"
    ),
    "constraint:log_lot_lifecycle_choice": (
        "f9701194ea33547ab9b865194722d84530fda80d8fad44b69f25b5fb72ab71bd"
    ),
    "constraint:log_lot_owner_choice": (
        "77bb4660afa43f76f14ea56bca9b408266e933d51b54162a5f17d3bf3648ee85"
    ),
    "constraint:log_lot_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_manifest_kind_choice": (
        "04e1abab09039489a5f39c8f6a172e4f82bca65b48488f55ad8241fa9b282c72"
    ),
    "constraint:log_manifest_line_count_bound": (
        "655396b60dca6a925f3204eed977c6ec8557e74e654a82062ba0c1a7778de989"
    ),
    "constraint:log_manifest_line_qty_pos": (
        "387674049a41c1e40e2bd9e794562cd507927cb45c987a5f2e69d7d56a11ce3b"
    ),
    "constraint:log_manifest_loading_window": (
        "58ccbbcd6635ec507082989680c1ab480a23dadafd670a54e5958b41cf9945e7"
    ),
    "constraint:log_manifest_number_uq": (
        "e77c9df328406d97adc6e48684ae0d2bf2cb6f2351fc905ac9a3b661da7edb32"
    ),
    "constraint:log_manifest_status_choice": (
        "3edbb35f6d961ee6c6cfae76aa2b263c9306b422e62a929539f994a49285b864"
    ),
    "constraint:log_manifest_subject_choice": (
        "e5dc2e517a2b3f86bd5b3b6ca4c37105af06fc4f580361835c7087d21c67dfe1"
    ),
    "constraint:log_manifest_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_node_kind_choice": (
        "1c0af37920dbbaeaf6fecfc4d31e47870a542c8b94a006a66106621d9b71e4fc"
    ),
    "constraint:log_node_lifecycle_choice": (
        "d1676e7a1747b8c66a0cf1f8f1527733503e9ae5c8e97ea0e98700213fdd9ed4"
    ),
    "constraint:log_node_vehicle_plate": (
        "f7adfb6cb10af625529d78ca0f6fee3b9383136b561c613a290cc15ae5194594"
    ),
    "constraint:log_node_venue_shape": (
        "aedf92b33dcbe9a97efc79ed3e0c9e7e4dd3edff46328d072f59c07881168cdf"
    ),
    "constraint:log_node_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_offer_history_choice": (
        "282310c24e2d72880832ec449dd77c01ea9bad68609c90efb606b6fe62ab3f93"
    ),
    "constraint:log_offer_history_version_uq": (
        "8c3cb8a1cfbe2c52cfaf6ed34df2429705eefa26f1c9b6c75adb22990336c8dd"
    ),
    "constraint:log_offer_interval_order": (
        "30f396fb6226721e29c8ba663ce3052fca85895bd081b923dfa31708d7349174"
    ),
    "constraint:log_offer_item_kind_choice": (
        "d35be113e84109a7669e3b68004dcebaf86d51ef1dce6908b7b3f4c629459c31"
    ),
    "constraint:log_offer_item_kind_qty": (
        "a4a0b483d03441af7e8bc7ea515d0b48992f1ceef1a0bc0752352d714fac51f7"
    ),
    "constraint:log_offer_item_qty_pos": (
        "387674049a41c1e40e2bd9e794562cd507927cb45c987a5f2e69d7d56a11ce3b"
    ),
    "constraint:log_offer_return_order": (
        "cdb66ba87e98d2e8738e208737e412e8c482bed86c9942e0721b22698b064bf2"
    ),
    "constraint:log_offer_status_choice": (
        "282310c24e2d72880832ec449dd77c01ea9bad68609c90efb606b6fe62ab3f93"
    ),
    "constraint:log_offer_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_offline_action_choice": (
        "eacab38ba1cfaa081c990b7fbcec4a04dbee4d7e8775bf9f06b9a51a3f325930"
    ),
    "constraint:log_offline_batch_key_uq": (
        "279549d2d3fbcbbbf604f665432fbaac02d4753ac0094cdfa52ff6e2f60477ee"
    ),
    "constraint:log_offline_batch_seq_uq": (
        "3bb8c4baf56244e23ea32acd2be17a65fcfd20101816315e002e1a868007d0dd"
    ),
    "constraint:log_offline_operation_bound": (
        "be51b7a8847431a7ccd08052a244eda7abae7ee5456569bed0226f97d20e32d6"
    ),
    "constraint:log_offline_receipt_choice": (
        "6ec0cba5b66a08a844255d3729aa0419702feaf16fb193746d696cb6d5f5b44f"
    ),
    "constraint:log_offline_result_choice": (
        "6ec0cba5b66a08a844255d3729aa0419702feaf16fb193746d696cb6d5f5b44f"
    ),
    "constraint:log_offline_sequence_pos": (
        "ddfd70c30577468691d352ae838281ec74c56efd9d5ec1c3e32967cf9ef5c6ed"
    ),
    "constraint:log_offline_status_choice": (
        "4ff94fb74c8dbf3d400c86133ac21cbf194aea6748296f4368fef47b0bef41da"
    ),
    "constraint:log_offline_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_party_kind_choice": (
        "f1f1c76f6238c9ba9c0076468bec54a63575f24ba376fd36b2b07b1cbb0af7cf"
    ),
    "constraint:log_party_lifecycle_choice": (
        "880b8febbfb7419537d3b00d8eb0bea81d6fe34ba51690d08b89d2aae092f1bc"
    ),
    "constraint:log_party_role_choice": (
        "a08ebf34c29e8d3f033e51974870b2ea99abd0f9b146f8d6ff1fdc0705031e3c"
    ),
    "constraint:log_party_version_pos": (
        "eff5a1c1622da30175eeef5347ec7f15d20253dc5970b72392c83e10f98c4c15"
    ),
    "constraint:log_person_addr_retention": (
        "f04141dd5f66395d847352250024d8ad450a6d3e8e33eed80139b1a0573e00aa"
    ),
    "constraint:log_receipt_version_pos": (
        "3d31f63dfb793da13bf1294a25c711b2dcc61ca8da79f8901912a643aa8c8b85"
    ),
    "constraint:log_state_choice": (
        "0c684b8e93e54ee4e14285e265a9077666a47396a16dbb66da398e794a56ff97"
    ),
    "constraint:log_state_event_seq_pos": (
        "20190782a81fead614d4af3218b88a985a8f2d2a6de720c93939d72ab8e2baf9"
    ),
    "index:log_acceptance_asset_uq": (
        "09da43bf313ffd3b88f81c886433d23a9b70215c7d1aa2d179f33ac3a163f764"
    ),
    "index:log_acceptance_lot_uq": (
        "9a6a91366a29522504473e9b5ad1ce40af878c7f77da6e8d335d43475a83fe48"
    ),
    "index:log_asset_event_seq_uq": (
        "f5366c53cbe0d10fb30f27f3f1ca7dee10f94f8e0c00c2e5017765081aae945e"
    ),
    "index:log_asset_org_code_uq": (
        "c892e145875a84e0a3affdca2498f33a53f2f3ac0b6b8cf8cbf38eedd85d85d0"
    ),
    "index:log_asset_serial_uq": (
        "34b98d86d86e5f97246312e73e0ba37e7e637eda0a15599bc8a69078baee75fb"
    ),
    "index:log_discrepancy_event_uq": (
        "ef05d722b32507594c8683fe12198c45b1ed93c3a98795e3b06e7e3b5146f107"
    ),
    "index:log_key_event_seq_uq": (
        "017df3edb0aea609c8bf23e0a2073f24572ecf19f08c4d7577b51384785332b6"
    ),
    "index:log_key_org_code_uq": (
        "1f45de6505b52de59a16d4786a4b7ac6deecfca613000362efe02685de3a6d73"
    ),
    "index:log_kit_asset_line_uq": (
        "088ad0c639a888ca1155fbba2e351101b1f88ce18266c7d733565fe7632619d4"
    ),
    "index:log_kit_key_line_uq": (
        "a7a2b95445998ab38038747c6915db84590b58ef063619262c43c3af6ab22ddd"
    ),
    "index:log_kit_lot_line_uq": (
        "39f19f3911bf641a532a8b1d17120a3bd802cd422e76972fe06835f8e1e84bb8"
    ),
    "index:log_kit_org_code_uq": (
        "1f6a8c8e62cccc211f1ff709d871befc56890137f4068549975377a6fc03e112"
    ),
    "index:log_label_org_code_uq": (
        "4ce2c0cbbdac7e4bc4ece833667e7e88c5108aec00756797bed6cb3f0919ad90"
    ),
    "index:log_lot_event_seq_uq": (
        "13fd9bf9244400ef59e8dc21b034f246c22d2a7d8dcd6c6b3e9f60e598c2cdf4"
    ),
    "index:log_lot_org_code_uq": (
        "d5987dae6c353d51cccc543e960e9bc431d5dd2101fc701462fcc1e7bcce55b6"
    ),
    "index:log_manifest_asset_line_uq": (
        "d1f1a2ee3e8bdec969f5502f9a33ee17b14f89e886c15a5e06b79c0a913e8d68"
    ),
    "index:log_manifest_event_line_type_uq": (
        "452395e056ff1546bd01c5016684ea87e12fbd3013ad54846ef941c6a150fbbc"
    ),
    "index:log_manifest_key_line_uq": (
        "113ae0bc31f50de3e03c6f82dd4dfe0d3e8cd6cf748acd8e8f2ed97cec226bf1"
    ),
    "index:log_manifest_lot_line_uq": (
        "6f19f928c4309ac6d2ed8a7d5a670cf5321dd973c0dca560281667d7f632dbcc"
    ),
    "index:log_manifest_node_line_uq": (
        "96f0239404d221637353acbac05cb75b7046969c2a81afa50788fb0072d9d3f5"
    ),
    "index:log_node_event_seq_uq": (
        "b6d543bdf33ce6fec8214b5cbc7bbae250a7c22d3b6bedeb407b13c49304339a"
    ),
    "index:log_node_org_code_uq": (
        "41c489bc56f2ed5a9168396ce66e4946be7552b69154d5c6ae0daf73358e96f0"
    ),
    "index:log_offline_discrepancy_nondup_uq": (
        "03bbfe478dcc6bc690b5922fcf4a96de2bff78ab57d7a5bd30221ff79894e9f2"
    ),
    "index:log_offline_event_nondup_uq": (
        "bfe9ba8a455fa0712564d0a437d56518cefb74ae63e7b452aaab4940752fa3d0"
    ),
    "index:log_party_org_code_uq": (
        "39cd1019370f3af2b5f975a50600bba4428ee29c055aae60c5231164b4048aa2"
    ),
}


def relation_privilege_profiles_are_declared() -> bool:
    """Prove all Logistics relations have exactly one least-privilege profile.

    Returns
    -------
    bool
        `True` when Prove all Logistics relations have exactly one least-
        privilege profile; otherwise `False`.
    """
    expected = {f"public.{relation}" for relation in logistics_relation_names()}
    select_insert = {
        relation
        for relation in RUNTIME_DATABASE_SELECT_INSERT_RELATIONS
        if relation.startswith("public.logistics_")
    }
    select_insert_update = {
        relation
        for relation in RUNTIME_DATABASE_SELECT_INSERT_UPDATE_RELATIONS
        if relation.startswith("public.logistics_")
    }
    declared = [
        relation
        for profile in (select_insert, select_insert_update)
        for relation in profile
    ]
    return (
        set(declared) == expected
        and len(declared) == len(expected)
        and not select_insert.intersection(select_insert_update)
    )


def _migration_is_applied(
    cursor: CursorWrapper,
    migration: tuple[str, str],
) -> bool:
    cursor.execute(
        """
        SELECT count(*) = 1
          FROM public.django_migrations
         WHERE app = %s AND name = %s
        """,
        migration,
    )
    return bool(cursor.fetchone()[0])


def _schema_definition_rows(
    cursor: CursorWrapper,
    contracts: Mapping[str, SchemaObjectContract],
) -> dict[str, tuple[object, ...]]:
    constraint_contracts = {
        contract.name: contract
        for contract in contracts.values()
        if contract.catalog_kind == "constraint"
    }
    index_contracts = {
        contract.name: contract
        for contract in contracts.values()
        if contract.catalog_kind == "index"
    }
    rows: dict[str, tuple[object, ...]] = {}
    cursor.execute(
        """
        SELECT constraint_record.conname::text,
               relation.relname::text,
               constraint_record.contype::text,
               constraint_record.condeferrable,
               constraint_record.condeferred,
               constraint_record.convalidated,
               access_method.amname::text,
               index_record.indisunique,
               index_record.indisvalid,
               index_record.indisready,
               index_record.indislive,
               index_record.indisprimary,
               index_record.indisexclusion,
               pg_catalog.encode(
                   pg_catalog.sha256(
                       pg_catalog.convert_to(
                           pg_catalog.pg_get_constraintdef(
                               constraint_record.oid,
                               TRUE
                           ),
                           'UTF8'
                       )
                   ),
                   'hex'
               )
          FROM pg_catalog.pg_constraint AS constraint_record
          JOIN pg_catalog.pg_class AS relation
            ON relation.oid = constraint_record.conrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          LEFT JOIN pg_catalog.pg_index AS index_record
            ON index_record.indexrelid = constraint_record.conindid
          LEFT JOIN pg_catalog.pg_class AS index_relation
            ON index_relation.oid = index_record.indexrelid
          LEFT JOIN pg_catalog.pg_am AS access_method
            ON access_method.oid = index_relation.relam
         WHERE namespace.nspname = 'public'
           AND constraint_record.conname = ANY(%s::text[])
         ORDER BY constraint_record.conname
        """,
        [list(constraint_contracts)],
    )
    for row in cursor.fetchall():
        rows[f"constraint:{row[0]}"] = tuple(row[1:])

    cursor.execute(
        """
        SELECT index_relation.relname::text,
               table_relation.relname::text,
               access_method.amname::text,
               index_record.indisunique,
               index_record.indisvalid,
               index_record.indisready,
               index_record.indislive,
               index_record.indisprimary,
               index_record.indisexclusion,
               index_record.indexprs IS NOT NULL,
               index_record.indpred IS NOT NULL,
               pg_catalog.encode(
                   pg_catalog.sha256(
                       pg_catalog.convert_to(
                           pg_catalog.pg_get_indexdef(index_record.indexrelid),
                           'UTF8'
                       )
                   ),
                   'hex'
               )
          FROM pg_catalog.pg_index AS index_record
          JOIN pg_catalog.pg_class AS index_relation
            ON index_relation.oid = index_record.indexrelid
          JOIN pg_catalog.pg_namespace AS index_namespace
            ON index_namespace.oid = index_relation.relnamespace
          JOIN pg_catalog.pg_class AS table_relation
            ON table_relation.oid = index_record.indrelid
          JOIN pg_catalog.pg_namespace AS table_namespace
            ON table_namespace.oid = table_relation.relnamespace
          JOIN pg_catalog.pg_am AS access_method
            ON access_method.oid = index_relation.relam
         WHERE index_namespace.nspname = 'public'
           AND table_namespace.nspname = 'public'
           AND index_relation.relname = ANY(%s::text[])
         ORDER BY index_relation.relname
        """,
        [list(index_contracts)],
    )
    for row in cursor.fetchall():
        rows[f"index:{row[0]}"] = tuple(row[1:])
    return rows


def collect_logistics_schema_definition_sha256() -> dict[str, str]:
    """Return data-free installed definition digests for contract finalization.

    Returns
    -------
    dict[str, str]
        A mapping containing the resolved collect logistics schema definition
        sha256 data.
    """
    contracts = declared_schema_object_contracts()
    with connection.cursor() as cursor:
        rows = _schema_definition_rows(cursor, contracts)
    return {key: str(row[-1]) for key, row in rows.items()}


def _schema_definitions_are_current(
    rows: Mapping[str, tuple[object, ...]],
    contracts: Mapping[str, SchemaObjectContract],
) -> bool:
    if set(SCHEMA_DEFINITION_SHA256) != set(contracts):
        return False
    expected: dict[str, tuple[object, ...]] = {}
    for key, contract in contracts.items():
        if contract.catalog_kind == "constraint":
            backing_index = {
                "c": (None, None, None, None, None, None, None),
                "u": ("btree", True, True, True, True, False, False),
                "x": ("gist", False, True, True, True, False, True),
            }[cast("str", contract.constraint_type)]
            expected[key] = (
                contract.table,
                contract.constraint_type,
                contract.deferrable,
                contract.initially_deferred,
                True,
                *backing_index,
                SCHEMA_DEFINITION_SHA256[key],
            )
        else:
            expected[key] = (
                contract.table,
                "btree",
                True,
                True,
                True,
                True,
                False,
                False,
                contract.has_expressions,
                contract.has_predicate,
                SCHEMA_DEFINITION_SHA256[key],
            )
    return dict(rows) == expected


def _implicit_uniques_are_current(
    cursor: CursorWrapper,
    contracts: tuple[ImplicitUniqueContract, ...],
    explicit_constraint_names: tuple[str, ...],
) -> bool:
    relations = sorted({contract.table for contract in contracts})
    cursor.execute(
        """
        SELECT table_relation.relname::text,
               constraint_record.conname::text,
               ARRAY(
                   SELECT attribute.attname::text
                     FROM pg_catalog.unnest(index_record.indkey::smallint[])
                          WITH ORDINALITY AS selected(attnum, position)
                     JOIN pg_catalog.pg_attribute AS attribute
                       ON attribute.attrelid = index_record.indrelid
                      AND attribute.attnum = selected.attnum
                    WHERE selected.position <= index_record.indnkeyatts
                    ORDER BY selected.position
               ),
               index_record.indisunique,
               index_record.indisvalid,
               index_record.indisready,
               index_record.indislive,
               index_record.indisprimary,
               index_record.indisexclusion,
               index_record.indexprs IS NULL,
               index_record.indpred IS NULL,
               constraint_record.contype::text,
               constraint_record.condeferrable,
               constraint_record.condeferred,
               constraint_record.convalidated
          FROM pg_catalog.pg_index AS index_record
          JOIN pg_catalog.pg_class AS table_relation
            ON table_relation.oid = index_record.indrelid
          JOIN pg_catalog.pg_namespace AS table_namespace
            ON table_namespace.oid = table_relation.relnamespace
          LEFT JOIN pg_catalog.pg_constraint AS constraint_record
            ON constraint_record.conindid = index_record.indexrelid
           AND constraint_record.contype = 'u'
         WHERE table_namespace.nspname = 'public'
           AND table_relation.relname = ANY(%s::text[])
           AND index_record.indisunique
           AND NOT index_record.indisprimary
           AND constraint_record.oid IS NOT NULL
           AND (
                constraint_record.conname IS NULL
                OR NOT (constraint_record.conname = ANY(%s::text[]))
           )
        """,
        [relations, list(explicit_constraint_names)],
    )
    installed = Counter(
        (
            str(row[0]),
            tuple(row[2] or ()),
            *tuple(row[3:]),
        )
        for row in cursor.fetchall()
    )
    expected = Counter(
        (
            contract.table,
            contract.columns,
            True,
            True,
            True,
            True,
            False,
            False,
            True,
            True,
            "u",
            False,
            False,
            True,
        )
        for contract in contracts
    )
    return installed == expected


def inspect_logistics_production_catalog() -> LogisticsProductionCatalog:
    """Inspect Logistics integrity without reading tenant or personal rows.

    Returns
    -------
    LogisticsProductionCatalog
        The LogisticsProductionCatalog produced by inspect logistics production
        catalog.
    """
    relations = logistics_relation_names()
    trigger_contracts = dict(TRIGGER_CONTRACTS)
    function_contracts = dict(FUNCTION_CONTRACTS)
    schema_contracts = declared_schema_object_contracts()
    implicit_unique_contracts = declared_implicit_unique_contracts()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_catalog.current_setting('server_version_num')::integer / 10000"
        )
        server_version_supported = (
            cast("int", cursor.fetchone()[0]) == _SUPPORTED_POSTGRESQL_SERVER_MAJOR
        )
        cursor.execute("SELECT pg_catalog.current_schemas(TRUE)")
        schemas = tuple(cast("Iterable[str]", cursor.fetchone()[0]))
        schema_order_safe = schemas[:2] == (
            "pg_catalog",
            _SUPPORTED_DATABASE_SCHEMA,
        )
        reviewed_migrations_applied = all(
            _migration_is_applied(cursor, migration)
            for migration in _REVIEWED_MIGRATIONS
        )
        cursor.execute(
            """
            SELECT count(*) = %s,
                   count(DISTINCT relation.relowner) = 1
              FROM pg_catalog.unnest(%s::text[]) AS required(name)
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = pg_catalog.to_regclass(
                    'public.' || required.name
                )
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname = 'public'
               AND relation.relkind IN ('r', 'p')
            """,
            [len(relations), list(relations)],
        )
        relation_row = cursor.fetchone()
        relations_installed = bool(relation_row[0])
        relation_ownership_consistent = bool(relation_row[1])
        cursor.execute(
            """
            SELECT count(*) = 1
              FROM pg_catalog.pg_extension
             WHERE extname = 'btree_gist'
            """
        )
        btree_gist_installed = bool(cursor.fetchone()[0])

        schema_rows = _schema_definition_rows(cursor, schema_contracts)
        implicit_uniques_current = _implicit_uniques_are_current(
            cursor,
            implicit_unique_contracts,
            tuple(contract.name for contract in schema_contracts.values()),
        )

        cursor.execute(
            """
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   procedure_namespace.nspname || '.' ||
                       procedure.proname || '(' ||
                       pg_catalog.oidvectortypes(procedure.proargtypes) || ')',
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgdeferrable,
                   trigger.tginitdeferred,
                   trigger.tgqual IS NULL,
                   trigger.tgnargs,
                   cardinality(trigger.tgattr::smallint[]) = 0
              FROM pg_catalog.pg_trigger AS trigger
              JOIN pg_catalog.pg_class AS relation
                ON relation.oid = trigger.tgrelid
              JOIN pg_catalog.pg_namespace AS relation_namespace
                ON relation_namespace.oid = relation.relnamespace
              JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = trigger.tgfoid
              JOIN pg_catalog.pg_namespace AS procedure_namespace
                ON procedure_namespace.oid = procedure.pronamespace
             WHERE NOT trigger.tgisinternal
               AND relation_namespace.nspname = 'public'
               AND relation.relname = ANY(%s::text[])
             ORDER BY trigger.tgname
            """,
            [list(relations)],
        )
        trigger_rows = cursor.fetchall()

        cursor.execute(
            """
            SELECT required.identity,
                   procedure.oid IS NOT NULL,
                   procedure.prosrc,
                   language.lanname::text,
                   procedure.provolatile::text,
                   procedure.proparallel::text,
                   procedure.prosecdef,
                   procedure.proleakproof,
                   procedure.proisstrict,
                   procedure.proretset,
                   procedure.prokind::text,
                   procedure.proconfig,
                   pg_catalog.pg_get_function_result(procedure.oid),
                    NOT EXISTS (
                        SELECT 1
                          FROM pg_catalog.aclexplode(
                              COALESCE(
                                 procedure.proacl,
                                 pg_catalog.acldefault('f', procedure.proowner)
                             )
                         ) AS privilege
                         WHERE privilege.privilege_type = 'EXECUTE'
                           AND privilege.grantee <> procedure.proowner
                    ),
                   procedure.proowner = (
                       SELECT relation.relowner
                         FROM pg_catalog.pg_class AS relation
                         JOIN pg_catalog.pg_namespace AS namespace
                           ON namespace.oid = relation.relnamespace
                        WHERE namespace.nspname = 'public'
                          AND relation.relname = %s
                   )
              FROM pg_catalog.unnest(%s::text[]) AS required(identity)
              LEFT JOIN pg_catalog.pg_proc AS procedure
                ON procedure.oid = pg_catalog.to_regprocedure(
                    'public.' || required.identity
                )
              LEFT JOIN pg_catalog.pg_language AS language
                ON language.oid = procedure.prolang
             ORDER BY required.identity
            """,
            [relations[0], list(function_contracts)],
        )
        function_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT procedure.proname || '(' ||
                   pg_catalog.oidvectortypes(procedure.proargtypes) || ')'
              FROM pg_catalog.pg_proc AS procedure
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = procedure.pronamespace
             WHERE namespace.nspname = 'public'
               AND (
                    procedure.proname LIKE 'maru\\_%logistics%' ESCAPE '\\'
                    OR procedure.proname = 'maru_logistics_person_is_eligible'
               )
             ORDER BY 1
            """
        )
        installed_function_identities = {str(row[0]) for row in cursor.fetchall()}
        runtime_role_name = getattr(settings, "RUNTIME_DATABASE_ROLE", "")
        cursor.execute(
            """
            WITH target_role AS (
                SELECT role.oid
                  FROM pg_catalog.pg_roles AS role
                 WHERE role.rolname = %s
                   AND role.rolcanlogin
            ),
            required_function AS (
                SELECT procedure.oid
                  FROM pg_catalog.unnest(%s::text[]) AS required(identity)
                  JOIN pg_catalog.pg_proc AS procedure
                    ON procedure.oid = pg_catalog.to_regprocedure(
                        'public.' || required.identity
                    )
            )
            SELECT (SELECT count(*) FROM target_role) = 1
               AND (SELECT count(*) FROM required_function) = %s
               AND NOT EXISTS (
                   SELECT 1
                     FROM target_role
                     CROSS JOIN required_function
                    WHERE pg_catalog.has_function_privilege(
                        target_role.oid,
                        required_function.oid,
                        'EXECUTE'
                    )
               )
            """,
            [runtime_role_name, list(function_contracts), len(function_contracts)],
        )
        runtime_function_execute_boundary_closed = bool(cursor.fetchone()[0])

    expected_triggers = {
        name: (
            contract.table,
            f"public.{contract.function}",
            contract.trigger_type,
            "O",
            contract.deferrable,
            contract.initially_deferred,
            True,
            0,
            True,
        )
        for name, contract in trigger_contracts.items()
    }
    installed_triggers = {str(row[0]): tuple(row[1:]) for row in trigger_rows}
    trigger_counts = Counter(str(row[0]) for row in trigger_rows)
    trigger_contract_current = (
        all(trigger_counts[name] == 1 for name in trigger_contracts)
        and installed_triggers == expected_triggers
    )

    installed_function_hashes = {
        str(row[0]): _function_definition_fingerprint(tuple(row[2:13]))
        for row in function_rows
        if bool(row[1])
    }
    expected_function_hashes = {
        identity: contract.definition_sha256
        for identity, contract in function_contracts.items()
    }
    function_contract_current = (
        installed_function_identities == set(function_contracts)
        and installed_function_hashes == expected_function_hashes
    )
    function_execute_boundary_closed = len(function_rows) == len(
        function_contracts
    ) and all(bool(row[1]) and bool(row[13]) for row in function_rows)
    function_ownership_current = len(function_rows) == len(function_contracts) and all(
        bool(row[1]) and bool(row[14]) for row in function_rows
    )
    try:
        configured_runtime_role_safe = bool(runtime_role_name) and (
            probe_runtime_database_role_safety(
                role_name=runtime_role_name,
            ).target_role_is_safe
        )
    except (DatabaseError, RuntimeDatabaseRoleProbeError):
        configured_runtime_role_safe = False
    fingerprints_finalized = set(SCHEMA_DEFINITION_SHA256) == set(schema_contracts)
    return LogisticsProductionCatalog(
        server_version_supported=server_version_supported,
        schema_order_safe=schema_order_safe,
        reviewed_migrations_applied=reviewed_migrations_applied,
        relations_installed=relations_installed,
        relation_ownership_consistent=relation_ownership_consistent,
        relation_privilege_profiles_declared=(
            relation_privilege_profiles_are_declared()
        ),
        btree_gist_installed=btree_gist_installed,
        schema_definition_fingerprints_finalized=fingerprints_finalized,
        schema_definitions_current=(
            fingerprints_finalized
            and _schema_definitions_are_current(schema_rows, schema_contracts)
        ),
        implicit_uniques_current=implicit_uniques_current,
        trigger_contract_current=trigger_contract_current,
        function_contract_current=function_contract_current,
        function_execute_boundary_closed=function_execute_boundary_closed,
        function_ownership_current=function_ownership_current,
        runtime_function_execute_boundary_closed=(
            runtime_function_execute_boundary_closed
        ),
        configured_runtime_role_safe=configured_runtime_role_safe,
        migration_contract_symmetric=MIGRATION_CONTRACT_SYMMETRIC,
    )


def logistics_production_contract_is_ready() -> bool:
    """Fail closed when the catalog cannot prove the complete contract.

    Returns
    -------
    bool
        `True` when Fail closed when the catalog cannot prove the complete
        contract; otherwise `False`.
    """
    try:
        return inspect_logistics_production_catalog().ready
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False


def logistics_current_session_is_ready() -> bool:
    """Prove both the Logistics catalog and this exact runtime session.

    Returns
    -------
    bool
        `True` when Prove both the Logistics catalog and this exact runtime
        session; otherwise `False`.
    """
    runtime_role_name = getattr(settings, "RUNTIME_DATABASE_ROLE", "")
    if not runtime_role_name:
        return False
    try:
        catalog = inspect_logistics_production_catalog()
        if not catalog.ready:
            return False
        return probe_runtime_database_role_safety(
            role_name=runtime_role_name,
        ).current_session_is_safe
    except (
        DatabaseError,
        LookupError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return False


def build_logistics_readiness_report() -> dict[str, object]:
    """Return an identifier-free health payload for a later central mount.

    Returns
    -------
    dict[str, object]
        A mapping containing the resolved build logistics readiness report data.
    """
    try:
        catalog = inspect_logistics_production_catalog()
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return {
            "status": "blocked",
            "gates": {
                "catalog_inspection": "unresolved",
            },
        }
    gates = {
        "server_version": catalog.server_version_supported,
        "schema_order": catalog.schema_order_safe,
        "migration_recorders": catalog.reviewed_migrations_applied,
        "relations": catalog.relations_installed,
        "relation_owners": catalog.relation_ownership_consistent,
        "relation_privilege_profiles": (catalog.relation_privilege_profiles_declared),
        "btree_gist": catalog.btree_gist_installed,
        "schema_definition_catalog": (
            catalog.schema_definition_fingerprints_finalized
            and catalog.schema_definitions_current
        ),
        "implicit_uniques": catalog.implicit_uniques_current,
        "triggers": catalog.trigger_contract_current,
        "functions": catalog.function_contract_current,
        "function_execute_boundary": (catalog.function_execute_boundary_closed),
        "function_owners": catalog.function_ownership_current,
        "runtime_function_execute_boundary": (
            catalog.runtime_function_execute_boundary_closed
        ),
        "configured_runtime_role": catalog.configured_runtime_role_safe,
        "migration_symmetry": catalog.migration_contract_symmetric,
    }
    return {
        "status": "ready" if all(gates.values()) else "blocked",
        "gates": {
            key: "resolved" if value else "unresolved" for key, value in gates.items()
        },
    }


__all__ = [
    "FUNCTION_CONTRACTS",
    "MIGRATION_CONTRACT_SYMMETRIC",
    "SCHEMA_DEFINITION_SHA256",
    "TRIGGER_CONTRACTS",
    "FunctionContract",
    "ImplicitUniqueContract",
    "LogisticsProductionCatalog",
    "SchemaObjectContract",
    "TriggerContract",
    "build_logistics_readiness_report",
    "collect_logistics_schema_definition_sha256",
    "declared_implicit_unique_contracts",
    "declared_schema_object_contracts",
    "inspect_logistics_production_catalog",
    "logistics_current_session_is_ready",
    "logistics_production_contract_is_ready",
    "logistics_relation_names",
    "relation_privilege_profiles_are_declared",
]
