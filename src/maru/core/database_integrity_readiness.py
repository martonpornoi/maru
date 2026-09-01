"""Reusable, data-free PostgreSQL integrity-catalog readiness.

Bounded contexts own their migration SQL and declare only the migration source,
terminal recorder, and Django app label.  This module derives exact trigger and
function contracts from that migration source and compares them with the live
PostgreSQL catalog without reading tenant or personal rows.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.apps import apps
from django.db import DatabaseError, connection, migrations

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_SUPPORTED_SCHEMA: Final = "public"
_REQUIRED_SEARCH_PATH: Final = ("search_path=pg_catalog, public, pg_temp",)

_IDENTIFIER = r"[a-z_][a-z0-9_]*"
_TRIGGER_RE: Final = re.compile(
    rf"CREATE\s+(?P<constraint>CONSTRAINT\s+)?TRIGGER\s+"
    rf"(?P<name>{_IDENTIFIER})\s+"
    r"(?P<timing>BEFORE|AFTER)\s+"
    r"(?P<events>(?:INSERT|UPDATE|DELETE|TRUNCATE)"
    r"(?:\s+OR\s+(?:INSERT|UPDATE|DELETE|TRUNCATE))*)\s+"
    rf"ON\s+(?P<table_schema>{_IDENTIFIER})\."
    rf"(?P<table>{_IDENTIFIER})\s+"
    r"(?:(?P<deferrable>DEFERRABLE)"
    r"(?:\s+(?P<initial>INITIALLY\s+(?:DEFERRED|IMMEDIATE)))?\s+)?"
    r"FOR\s+EACH\s+(?P<level>ROW|STATEMENT)\s+"
    rf"EXECUTE\s+FUNCTION\s+(?P<function_schema>{_IDENTIFIER})\."
    rf"(?P<function>{_IDENTIFIER})\((?P<arguments>[^)]*)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
_FUNCTION_RE: Final = re.compile(
    rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+"
    rf"(?P<schema>{_IDENTIFIER})\.(?P<name>{_IDENTIFIER})\s*"
    r"\((?P<arguments>.*?)\)\s*"
    r"RETURNS\s+(?P<result>[a-z0-9_.\s\"]+?)\s+AS\s+"
    r"(?P<delimiter>\$[a-z0-9_]*\$)"
    r"(?P<source>.*?)"
    r"(?P=delimiter)\s+LANGUAGE\s+"
    rf"(?P<language>{_IDENTIFIER})(?P<options>.*?);",
    re.IGNORECASE | re.DOTALL,
)
_DROP_TRIGGER_RE: Final = re.compile(
    rf"DROP\s+TRIGGER\s+IF\s+EXISTS\s+(?P<name>{_IDENTIFIER})\s+"
    rf"ON\s+(?P<schema>{_IDENTIFIER})\.(?P<table>{_IDENTIFIER})\s*;",
    re.IGNORECASE,
)
_DROP_FUNCTION_RE: Final = re.compile(
    rf"DROP\s+FUNCTION\s+IF\s+EXISTS\s+(?P<schema>{_IDENTIFIER})\."
    rf"(?P<name>{_IDENTIFIER})\((?P<arguments>[^)]*)\)\s*;",
    re.IGNORECASE,
)
_TRIGGER_EVENT_BITS: Final = {
    "INSERT": 4,
    "DELETE": 8,
    "UPDATE": 16,
    "TRUNCATE": 32,
}


class _IntegrityMigration(Protocol):
    FORWARD_SQL: str
    REVERSE_SQL: str
    Migration: type[migrations.Migration]


@dataclass(frozen=True, slots=True)
class TriggerContract:
    """One exact non-internal trigger attachment.

    Attributes
    ----------
    name
        The human-readable name to normalize or persist.
    table
        The database table whose integrity contract is being inspected.
    function_identity
        The function identity retained in this immutable projection.
    trigger_type
        The closed trigger type discriminator defined by the domain catalog.
    is_constraint
        Whether to is constraint.
    deferrable
        The deferrable retained in this immutable projection.
    initially_deferred
        The initially deferred retained in this immutable projection.
    """

    name: str
    table: str
    function_identity: str
    trigger_type: int
    is_constraint: bool
    deferrable: bool
    initially_deferred: bool

    @property
    def catalog_row(self) -> tuple[object, ...]:
        """Return catalog row.

        Returns
        -------
        tuple[object, ...]
            The matching catalog row records in deterministic order.
        """
        return (
            self.name,
            self.table,
            self.function_identity,
            self.trigger_type,
            "O",
            self.is_constraint,
            self.deferrable,
            self.initially_deferred,
            True,
            0,
            True,
        )


@dataclass(frozen=True, slots=True)
class FunctionContract:
    """Behavior-bearing fields for one migration-owned function.

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
    def source_sha256(self) -> str:
        """Return source sha256.

        Returns
        -------
        str
            The normalized text for source sha256.
        """
        normalized = self.source.replace("\r\n", "\n").strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DatabaseIntegrityContract:
    """One bounded context's declarative integrity contract.

    Attributes
    ----------
    status_key
        The stable status key used to authenticate or deduplicate the operation.
    app_label
        The human-readable app label shown to authorized readers.
    source_migration
        The source migration retained in this immutable projection.
    terminal_migration
        The terminal migration retained in this immutable projection.
    source_migration_module
        The source migration module retained in this immutable projection.
    triggers
        The triggers mapping to validate or transform.
    functions
        The functions mapping to validate or transform.
    source_contract_current
        The source contract current retained in this immutable projection.
    """

    status_key: str
    app_label: str
    source_migration: tuple[str, str]
    terminal_migration: tuple[str, str]
    source_migration_module: str
    triggers: Mapping[str, TriggerContract]
    functions: Mapping[str, FunctionContract]
    source_contract_current: bool

    @property
    def required_migrations(self) -> tuple[tuple[str, str], ...]:
        """Return required migrations.

        Returns
        -------
        tuple[tuple[str, str], ...]
            The matching required migrations records in deterministic order.
        """
        return tuple(dict.fromkeys((self.source_migration, self.terminal_migration)))


@dataclass(frozen=True, slots=True)
class DatabaseIntegrityCatalog:
    """Identifier-free result of one bounded catalog inspection.

    Attributes
    ----------
    source_contract_current
        The source contract current retained in this immutable projection.
    required_migrations_applied
        The required migrations applied retained in this immutable projection.
    relations_installed
        The relations installed retained in this immutable projection.
    relation_ownership_consistent
        The relation ownership consistent retained in this immutable projection.
    trigger_contract_current
        The trigger contract current retained in this immutable projection.
    function_contract_current
        The function contract current retained in this immutable projection.
    function_execute_owner_only
        The function execute owner only retained in this immutable projection.
    function_ownership_current
        The function ownership current retained in this immutable projection.
    """

    source_contract_current: bool
    required_migrations_applied: bool
    relations_installed: bool
    relation_ownership_consistent: bool
    trigger_contract_current: bool
    function_contract_current: bool
    function_execute_owner_only: bool
    function_ownership_current: bool

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
                self.source_contract_current,
                self.required_migrations_applied,
                self.relations_installed,
                self.relation_ownership_consistent,
                self.trigger_contract_current,
                self.function_contract_current,
                self.function_execute_owner_only,
                self.function_ownership_current,
            )
        )


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
        if match.group("arguments").strip():
            raise ValueError("integrity trigger functions must not take SQL arguments")
        name = match.group("name").lower()
        events = {event.strip().upper() for event in match.group("events").split("OR")}
        trigger_type = 1 if match.group("level").upper() == "ROW" else 0
        if match.group("timing").upper() == "BEFORE":
            trigger_type |= 2
        for event in events:
            trigger_type |= _TRIGGER_EVENT_BITS[event]
        table_schema = match.group("table_schema").lower()
        function_schema = match.group("function_schema").lower()
        if table_schema != _SUPPORTED_SCHEMA or function_schema != _SUPPORTED_SCHEMA:
            raise ValueError(
                "integrity contracts must use the public schema explicitly"
            )
        contract = TriggerContract(
            name=name,
            table=match.group("table").lower(),
            function_identity=(
                f"{function_schema}.{match.group('function').lower()}()"
            ),
            trigger_type=trigger_type,
            is_constraint=match.group("constraint") is not None,
            deferrable=match.group("deferrable") is not None,
            initially_deferred=(
                (match.group("initial") or "").upper() == "INITIALLY DEFERRED"
            ),
        )
        if name in contracts:
            raise ValueError(f"duplicate integrity trigger declaration: {name}")
        contracts[name] = contract
    return contracts


def _parse_function_contracts(sql: str) -> dict[str, FunctionContract]:
    contracts: dict[str, FunctionContract] = {}
    for match in _FUNCTION_RE.finditer(sql):
        if match.group("schema").lower() != _SUPPORTED_SCHEMA:
            raise ValueError(
                "integrity contracts must use the public schema explicitly"
            )
        arguments = _canonical_type_list(
            match.group("arguments"),
            declarations=True,
        )
        identity = f"{match.group('name').lower()}({arguments})"
        options = " ".join(match.group("options").upper().split())
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
            volatility=(
                "s" if "STABLE" in options else "i" if "IMMUTABLE" in options else "v"
            ),
            parallel=(
                "s"
                if "PARALLEL SAFE" in options
                else "r"
                if "PARALLEL RESTRICTED" in options
                else "u"
            ),
            security_definer="SECURITY DEFINER" in options,
            leakproof="LEAKPROOF" in options,
            strict=(
                " STRICT" in f" {options}" or "RETURNS NULL ON NULL INPUT" in options
            ),
            returns_set=False,
            kind="f",
            configuration=configuration,
            result=" ".join(match.group("result").lower().split()),
        )
        if identity in contracts:
            raise ValueError(f"duplicate integrity function declaration: {identity}")
        contracts[identity] = contract
    return contracts


def parse_database_integrity_sql_contracts(
    sql: str,
) -> tuple[dict[str, TriggerContract], dict[str, FunctionContract]]:
    """Parse supported trigger and function contracts from migration-owned SQL.

    This public seam lets a bounded context compose integrity guards installed
    by a supporting module without depending on Core's parser implementation.
    It does not inspect the database or business rows.

    Parameters
    ----------
    sql : str
        The PostgreSQL migration SQL containing the integrity declarations.

    Returns
    -------
    tuple[dict[str, TriggerContract], dict[str, FunctionContract]]
        Parsed trigger contracts followed by parsed function contracts.

    """
    return _parse_trigger_contracts(sql), _parse_function_contracts(sql)


def _dropped_trigger_keys(sql: str) -> set[tuple[str, str]]:
    return {
        (match.group("name").lower(), match.group("table").lower())
        for match in _DROP_TRIGGER_RE.finditer(sql)
        if match.group("schema").lower() == _SUPPORTED_SCHEMA
    }


def _dropped_function_identities(sql: str) -> set[str]:
    return {
        (
            f"{match.group('name').lower()}"
            f"({_canonical_type_list(match.group('arguments'), declarations=False)})"
        )
        for match in _DROP_FUNCTION_RE.finditer(sql)
        if match.group("schema").lower() == _SUPPORTED_SCHEMA
    }


def _migration_operation_is_current(
    migration: _IntegrityMigration,
    forward_sql: str,
    reverse_sql: str,
) -> bool:
    operations = tuple(getattr(migration.Migration, "operations", ()))
    return len(operations) == 1 and all(
        (
            isinstance(operations[0], migrations.RunSQL),
            getattr(operations[0], "sql", None) == forward_sql,
            getattr(operations[0], "reverse_sql", None) == reverse_sql,
        )
    )


def build_database_integrity_contract(
    *,
    status_key: str,
    app_label: str,
    source_migration: tuple[str, str],
    terminal_migration: tuple[str, str],
    source_migration_module: str,
) -> DatabaseIntegrityContract:
    """Derive one closed contract from app-owned migration source.

    Parameters
    ----------
    status_key : str
        The stable status key used to authenticate or deduplicate the operation.
    app_label : str
        The human-readable app label shown to authorized readers.
    source_migration : tuple[str, str]
        The migration node used to verify schema ordering and readiness.
    terminal_migration : tuple[str, str]
        The migration node used to verify schema ordering and readiness.
    source_migration_module : str
        The source migration module evaluated by the fail-closed readiness check.

    Returns
    -------
    DatabaseIntegrityContract
        The DatabaseIntegrityContract produced by build database integrity
        contract.
    """
    migration = cast(
        "_IntegrityMigration",
        import_module(source_migration_module),
    )
    forward_sql = migration.FORWARD_SQL
    reverse_sql = migration.REVERSE_SQL
    try:
        triggers, functions = parse_database_integrity_sql_contracts(forward_sql)
    except (KeyError, TypeError, ValueError):
        triggers = {}
        functions = {}
    source_contract_current = all(
        (
            bool(re.fullmatch(r"[a-z][a-z0-9_]*", status_key)),
            source_migration[0] == app_label,
            terminal_migration[0] == app_label,
            bool(triggers),
            bool(functions),
            all(not function.security_definer for function in functions.values()),
            all(
                function.configuration == _REQUIRED_SEARCH_PATH
                for function in functions.values()
            ),
            {(trigger.name, trigger.table) for trigger in triggers.values()}
            == _dropped_trigger_keys(reverse_sql),
            set(functions) == _dropped_function_identities(reverse_sql),
            _migration_operation_is_current(migration, forward_sql, reverse_sql),
        )
    )
    return DatabaseIntegrityContract(
        status_key=status_key,
        app_label=app_label,
        source_migration=source_migration,
        terminal_migration=terminal_migration,
        source_migration_module=source_migration_module,
        triggers=triggers,
        functions=functions,
        source_contract_current=source_contract_current,
    )


@cache
def bounded_context_relation_names(app_label: str) -> tuple[str, ...]:
    """Return every concrete current relation owned by one Django app.

    Parameters
    ----------
    app_label : str
        The human-readable app label shown to authorized readers.

    Returns
    -------
    tuple[str, ...]
        The matching bounded context relation names records in deterministic
        order.

    Raises
    ------
    RuntimeError
        If a required runtime invariant or dependency is unavailable.
    """
    relations = tuple(
        sorted(
            model._meta.db_table  # noqa: SLF001
            for model in apps.get_app_config(app_label).get_models()
            if model._meta.managed and not model._meta.proxy  # noqa: SLF001
        )
    )
    if not relations or len(relations) != len(set(relations)):
        raise RuntimeError("bounded integrity app relation declaration is invalid")
    return relations


def _trigger_rows_are_current(
    rows: Sequence[Sequence[object]],
    contracts: Mapping[str, TriggerContract],
) -> bool:
    installed = Counter(tuple(row) for row in rows)
    expected = Counter(contract.catalog_row for contract in contracts.values())
    return installed == expected


def _function_rows_are_current(
    rows: Sequence[Sequence[object]],
    contracts: Mapping[str, FunctionContract],
) -> tuple[bool, bool, bool]:
    if len(rows) != len(contracts):
        return False, False, False
    installed = {str(row[0]): row for row in rows}
    if set(installed) != set(contracts):
        return False, False, False
    definitions_current = True
    execute_owner_only = True
    ownership_current = True
    for identity, contract in contracts.items():
        row = installed[identity]
        present = bool(row[1])
        source = str(row[2] or "").replace("\r\n", "\n").strip()
        source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
        configuration = tuple(cast("Iterable[str]", row[11] or ()))
        definitions_current = (
            definitions_current
            and present
            and (
                source_sha256,
                row[3],
                row[4],
                row[5],
                row[6],
                row[7],
                row[8],
                row[9],
                row[10],
                configuration,
                row[12],
            )
            == (
                contract.source_sha256,
                contract.language,
                contract.volatility,
                contract.parallel,
                contract.security_definer,
                contract.leakproof,
                contract.strict,
                contract.returns_set,
                contract.kind,
                contract.configuration,
                contract.result,
            )
        )
        execute_owner_only = execute_owner_only and present and bool(row[13])
        ownership_current = ownership_current and present and bool(row[14])
    return definitions_current, execute_owner_only, ownership_current


def inspect_database_integrity_catalog(
    contract: DatabaseIntegrityContract,
) -> DatabaseIntegrityCatalog:
    """Inspect one bounded context without reading business rows.

    Parameters
    ----------
    contract : DatabaseIntegrityContract
        The contract evaluated by the fail-closed readiness check.

    Returns
    -------
    DatabaseIntegrityCatalog
        The DatabaseIntegrityCatalog produced by inspect database integrity
        catalog.
    """
    relations = bounded_context_relation_names(contract.app_label)
    required_migrations = set(contract.required_migrations)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT app::text, name::text
              FROM public.django_migrations
             WHERE app = ANY(%s::text[])
            """,
            [sorted({app_label for app_label, _ in required_migrations})],
        )
        applied_migrations = {(str(row[0]), str(row[1])) for row in cursor.fetchall()}
        required_migrations_applied = required_migrations <= applied_migrations

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
            SELECT trigger.tgname::text,
                   relation.relname::text,
                   procedure_namespace.nspname || '.' ||
                       procedure.proname || '(' ||
                       pg_catalog.oidvectortypes(procedure.proargtypes) || ')',
                   trigger.tgtype,
                   trigger.tgenabled,
                   trigger.tgconstraint <> 0,
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
             ORDER BY relation.relname, trigger.tgname
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
                   (
                       SELECT count(*) = 1
                          AND bool_and(
                              privilege.grantee = procedure.proowner
                          )
                         FROM pg_catalog.aclexplode(
                             COALESCE(
                                 procedure.proacl,
                                 pg_catalog.acldefault(
                                     'f'::pg_catalog."char",
                                     procedure.proowner
                                 )
                             )
                         ) AS privilege
                        WHERE privilege.privilege_type = 'EXECUTE'
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
            [relations[0], list(contract.functions)],
        )
        function_rows = cursor.fetchall()

    functions_current, execute_owner_only, function_ownership_current = (
        _function_rows_are_current(function_rows, contract.functions)
    )
    return DatabaseIntegrityCatalog(
        source_contract_current=contract.source_contract_current,
        required_migrations_applied=required_migrations_applied,
        relations_installed=relations_installed,
        relation_ownership_consistent=relation_ownership_consistent,
        trigger_contract_current=_trigger_rows_are_current(
            trigger_rows,
            contract.triggers,
        ),
        function_contract_current=functions_current,
        function_execute_owner_only=execute_owner_only,
        function_ownership_current=function_ownership_current,
    )


def database_integrity_contract_is_ready(
    contract: DatabaseIntegrityContract,
) -> bool:
    """Fail closed when the catalog cannot prove the complete contract.

    Parameters
    ----------
    contract : DatabaseIntegrityContract
        The contract evaluated by the fail-closed readiness check.

    Returns
    -------
    bool
        `True` when Fail closed when the catalog cannot prove the complete
        contract; otherwise `False`.
    """
    try:
        return inspect_database_integrity_catalog(contract).ready
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False


__all__ = [
    "DatabaseIntegrityCatalog",
    "DatabaseIntegrityContract",
    "FunctionContract",
    "TriggerContract",
    "bounded_context_relation_names",
    "build_database_integrity_contract",
    "database_integrity_contract_is_ready",
    "inspect_database_integrity_catalog",
    "parse_database_integrity_sql_contracts",
]
