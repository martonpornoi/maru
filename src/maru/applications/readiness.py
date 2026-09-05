"""Fail-closed database integrity readiness for Applications."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, replace
from importlib import import_module
from typing import TYPE_CHECKING, Final

from django.apps import apps
from django.db import DatabaseError, connection, migrations
from django.db.models.fields import NOT_PROVIDED

from maru.core.database_integrity_readiness import (
    DatabaseIntegrityContract,
    build_database_integrity_contract,
    database_integrity_contract_is_ready,
    parse_database_integrity_sql_contracts,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from django.db.backends.utils import CursorWrapper
    from django.db.models import Model

_INTEGRITY_MIGRATION = import_module(
    "maru.applications.migrations.0011_programme_department_ownership_integrity"
)
_DOWNGRADE_MIGRATION = import_module(
    "maru.applications.migrations.0012_programme_department_ownership_downgrade_fence"
)
_PERSISTENCE_MIGRATION = import_module(
    "maru.applications.migrations.0010_programme_department_ownership_persistence"
)
_IMPORT_INTEGRITY_MIGRATION = import_module(
    "maru.applications.migrations.0008_programme_import_integrity_guards"
)
_PROGRAMME_INTEGRITY_MIGRATION = import_module(
    "maru.applications.migrations.0005_programme_integrity_guards"
)
_IDENTITY_PROGRAMME_MIGRATION = import_module(
    "maru.identity.migrations.0020_programme_proposal_person_guard"
)
_DOWNGRADE_FENCE_SOURCE_SHA256: Final = (
    "8e2f365fae30521ad40a4bb590bb01b1ab580e72811b721e3d7da38fe4599e21"
)
_SHA256_HEX_LENGTH: Final = 64
_REVIEW_DOWNGRADE_MIGRATION = import_module(
    "maru.applications.migrations.0015_programme_review_downgrade_fence"
)
_REVIEW_DOWNGRADE_FENCE_SOURCE_SHA256: Final = (
    "78b3cc885aa5b72106ced0ec0f244b6523ea88f9686a0028169f77d2dd3be151"
)


def _review_downgrade_contract_is_current() -> bool:
    operations = tuple(_REVIEW_DOWNGRADE_MIGRATION.Migration.operations)
    if len(operations) != 1 or not isinstance(operations[0], migrations.RunPython):
        return False
    reverse = _REVIEW_DOWNGRADE_MIGRATION.refuse_populated_programme_review_downgrade
    source = inspect.getsource(reverse).replace("\r\n", "\n")
    return (
        operations[0].code is migrations.RunPython.noop
        and operations[0].reverse_code is reverse
        and tuple(_REVIEW_DOWNGRADE_MIGRATION.Migration.dependencies)
        == (("applications", "0014_programme_review_integrity"),)
        and hashlib.sha256(source.encode("utf-8")).hexdigest()
        == _REVIEW_DOWNGRADE_FENCE_SOURCE_SHA256
    )


def _applications_programme_migration_contract_is_current() -> bool:
    source_operations = tuple(_INTEGRITY_MIGRATION.Migration.operations)
    downgrade_operations = tuple(_DOWNGRADE_MIGRATION.Migration.operations)
    expected_reverse_suffix = _IMPORT_INTEGRITY_MIGRATION.FORWARD_SQL.strip()
    downgrade_operation = (
        downgrade_operations[0] if len(downgrade_operations) == 1 else None
    )
    if not isinstance(downgrade_operation, migrations.RunPython):
        return False
    downgrade_source = inspect.getsource(
        _DOWNGRADE_MIGRATION.refuse_populated_ownership_continuity_downgrade
    ).replace("\r\n", "\n")
    identity_operations = tuple(_IDENTITY_PROGRAMME_MIGRATION.Migration.operations)
    return all(
        (
            ("applications", "0009_programme_import_populated_downgrade_fence")
            in tuple(_PERSISTENCE_MIGRATION.Migration.dependencies),
            ("workforce", "0017_programme_import_department_fk_contract")
            in tuple(_PERSISTENCE_MIGRATION.Migration.dependencies),
            tuple(_INTEGRITY_MIGRATION.Migration.dependencies)
            == (
                (
                    "applications",
                    "0010_programme_department_ownership_persistence",
                ),
                (
                    "authorization",
                    "0023_programme_department_ownership_recovery",
                ),
            ),
            len(source_operations) == 1,
            isinstance(source_operations[0], migrations.RunSQL),
            source_operations[0].sql == _INTEGRITY_MIGRATION.FORWARD_SQL,
            source_operations[0].reverse_sql == _INTEGRITY_MIGRATION.REVERSE_SQL,
            _INTEGRITY_MIGRATION.REVERSE_SQL.endswith(expected_reverse_suffix),
            tuple(_DOWNGRADE_MIGRATION.Migration.dependencies)
            == (
                (
                    "applications",
                    "0011_programme_department_ownership_integrity",
                ),
            ),
            downgrade_operation.code is migrations.RunPython.noop,
            downgrade_operation.reverse_code
            is _DOWNGRADE_MIGRATION.refuse_populated_ownership_continuity_downgrade,
            hashlib.sha256(downgrade_source.encode("utf-8")).hexdigest()
            == _DOWNGRADE_FENCE_SOURCE_SHA256,
            tuple(_IDENTITY_PROGRAMME_MIGRATION.Migration.dependencies)
            == (
                ("identity", "0019_navigation_pins"),
                ("applications", "0004_programme_calls_and_proposals"),
            ),
            len(identity_operations) == 1,
            isinstance(identity_operations[0], migrations.RunSQL),
            identity_operations[0].sql == _IDENTITY_PROGRAMME_MIGRATION.FORWARD_SQL,
            identity_operations[0].reverse_sql
            == _IDENTITY_PROGRAMME_MIGRATION.REVERSE_SQL,
        )
    )


_DERIVED_APPLICATIONS_INTEGRITY_CONTRACT = build_database_integrity_contract(
    status_key="applications_integrity",
    app_label="applications",
    source_migration=(
        "applications",
        "0011_programme_department_ownership_integrity",
    ),
    terminal_migration=(
        "applications",
        "0012_programme_department_ownership_downgrade_fence",
    ),
    source_migration_module=(
        "maru.applications.migrations.0011_programme_department_ownership_integrity"
    ),
)
_IDENTITY_SQL_TRIGGER_CONTRACTS, _IDENTITY_SQL_FUNCTION_CONTRACTS = (
    parse_database_integrity_sql_contracts(_IDENTITY_PROGRAMME_MIGRATION.FORWARD_SQL)
)
_REVIEW_INTEGRITY_CONTRACT = build_database_integrity_contract(
    status_key="applications_integrity",
    app_label="applications",
    source_migration=("applications", "0014_programme_review_integrity"),
    terminal_migration=("applications", "0015_programme_review_downgrade_fence"),
    source_migration_module="maru.applications.migrations.0014_programme_review_integrity",
)
_IDENTITY_TRIGGER_CONTRACTS = {
    name: trigger
    for name, trigger in _IDENTITY_SQL_TRIGGER_CONTRACTS.items()
    if trigger.table.startswith("applications_")
}
_IDENTITY_FUNCTION_IDENTITIES = {
    trigger.function_identity.removeprefix("public.")
    for trigger in _IDENTITY_TRIGGER_CONTRACTS.values()
}
_IDENTITY_FUNCTION_CONTRACTS = {
    identity: function
    for identity, function in _IDENTITY_SQL_FUNCTION_CONTRACTS.items()
    if identity in _IDENTITY_FUNCTION_IDENTITIES
}
APPLICATIONS_INTEGRITY_CONTRACT: Final[DatabaseIntegrityContract] = replace(
    _REVIEW_INTEGRITY_CONTRACT,
    triggers={
        **_DERIVED_APPLICATIONS_INTEGRITY_CONTRACT.triggers,
        **_IDENTITY_TRIGGER_CONTRACTS,
        **_REVIEW_INTEGRITY_CONTRACT.triggers,
    },
    functions={
        **_DERIVED_APPLICATIONS_INTEGRITY_CONTRACT.functions,
        **_IDENTITY_FUNCTION_CONTRACTS,
        **_REVIEW_INTEGRITY_CONTRACT.functions,
    },
    source_contract_current=(
        _DERIVED_APPLICATIONS_INTEGRITY_CONTRACT.source_contract_current
        and _applications_programme_migration_contract_is_current()
        and _REVIEW_INTEGRITY_CONTRACT.source_contract_current
        and _review_downgrade_contract_is_current()
    ),
)


@dataclass(frozen=True, slots=True)
class ApplicationsSchemaCatalog:
    """Data-free result of the Applications-owned relation-shape inspection.

    Attributes
    ----------
    schema_fingerprints_finalized
        Whether the immutable constraint/index digest catalog is complete.
    relations_current
        Whether every Applications relation has the exact declared table
        semantics and no unexpected Applications relation exists.
    columns_current
        Whether every column matches its declared type, nullability, default,
        generation, identity, and collation semantics.
    constraints_current
        Whether the complete constraint set and canonical definitions match.
    indexes_current
        Whether the complete index set, canonical definitions, and operational
        metadata match.
    """

    schema_fingerprints_finalized: bool
    relations_current: bool
    columns_current: bool
    constraints_current: bool
    indexes_current: bool

    @property
    def ready(self) -> bool:
        """Return whether every Applications relation shape is exact."""
        return all(
            (
                self.schema_fingerprints_finalized,
                self.relations_current,
                self.columns_current,
                self.constraints_current,
                self.indexes_current,
            )
        )


APPLICATIONS_RELATION_SEMANTICS: Final[
    Mapping[str, tuple[str, str, bool, bool, bool, str]]
] = {
    "applications_applicationanswerrevision": ("r", "p", False, False, False, "d"),
    "applications_applicationcommandreceipt": ("r", "p", False, False, False, "d"),
    "applications_applicationdefinition": ("r", "p", False, False, False, "d"),
    "applications_applicationfilereceipt": ("r", "p", False, False, False, "d"),
    "applications_applicationownerdepartment": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_applicationquestion": ("r", "p", False, False, False, "d"),
    "applications_applicationreviewdecision": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_applicationreviewerperson": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_applicationreviewerrole": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_applicationsection": ("r", "p", False, False, False, "d"),
    "applications_applicationsubmission": ("r", "p", False, False, False, "d"),
    "applications_applicationtargetrecord": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmereviewpolicy": ("r", "p", False, False, False, "d"),
    "applications_programmereviewcase": ("r", "p", False, False, False, "d"),
    "applications_programmereviewassignment": ("r", "p", False, False, False, "d"),
    "applications_programmereviewentry": ("r", "p", False, False, False, "d"),
    "applications_programmereviewdecision": ("r", "p", False, False, False, "d"),
    "applications_programmedecisionacknowledgement": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmereviewreceipt": ("r", "p", False, False, False, "d"),
    "applications_programmecall": ("r", "p", False, False, False, "d"),
    "applications_programmecallcontributorfield": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmecallformat": ("r", "p", False, False, False, "d"),
    "applications_programmecalltrack": ("r", "p", False, False, False, "d"),
    "applications_programmecommandreceipt": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeimportappliedcommand": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeimportbatch": ("r", "p", False, False, False, "d"),
    "applications_programmeimportcommandreceipt": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeimportitem": ("r", "p", False, False, False, "d"),
    "applications_programmeimportpreviewitemresult": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeimportpreviewrevision": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeimportsourcebinding": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposal": ("r", "p", False, False, False, "d"),
    "applications_programmeproposalcollaborator": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposalcollaboratortransition": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposalcontributorprofilerevision": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposalrevision": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposalrevisionanswer": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposalrevisioncontributor": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposalrevisionresponse": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
    "applications_programmeproposalselectionrevision": (
        "r",
        "p",
        False,
        False,
        False,
        "d",
    ),
}

_NO_COLLATION_IDENTITY: Final = (None,) * 10
_DEFAULT_COLLATION_IDENTITY: Final = (
    "pg_catalog",
    "default",
    "d",
    True,
    -1,
    None,
    None,
    None,
    None,
    None,
)

# Finalized only from a freshly migrated PostgreSQL 17 catalog. Each entry
# records the complete object count and SHA-256 over the sorted object names,
# immutable catalog metadata digests, and canonical definition digests from
# pg_get_constraintdef(..., TRUE) or pg_get_indexdef(...). An incomplete entry
# deliberately keeps Applications readiness blocked.
APPLICATIONS_SCHEMA_CATALOG_SHA256: Final[Mapping[str, tuple[int, str]]] = {
    "constraint:": (
        437,
        "d6ad577b25b7ac87592a27fb40169adf32453c96d69010526449f0022dd1b2de",
    ),
    "index:": (
        303,
        "abeb82036b95c051d009bb05a4809e7e868078e0afa0b6f60a014b8e5638fb4d",
    ),
}


def _applications_models() -> tuple[type[Model], ...]:
    return tuple(
        model
        for model in apps.get_app_config("applications").get_models()
        if model._meta.managed and not model._meta.proxy  # noqa: SLF001
    )


def _applications_relation_names() -> tuple[str, ...]:
    return tuple(
        sorted(
            model._meta.db_table  # noqa: SLF001
            for model in _applications_models()
        )
    )


def _canonical_database_type(value: object) -> str:
    return (
        " ".join(str(value).lower().split())
        .replace("character varying", "varchar")
        .replace(", ", ",")
    )


def _expected_column_collation(
    database_type: str,
    explicit: str | None,
) -> tuple[object, ...]:
    base_type = database_type.partition("(")[0]
    if base_type not in {"char", "text", "varchar"}:
        return _NO_COLLATION_IDENTITY
    if explicit is not None:
        message = "Applications column collation is not finalized in the schema catalog"
        raise RuntimeError(message)
    return _DEFAULT_COLLATION_IDENTITY


def _expected_applications_columns() -> set[tuple[object, ...]]:
    expected: set[tuple[object, ...]] = set()
    for model in _applications_models():
        for field in model._meta.local_fields:  # noqa: SLF001
            database_type = _canonical_database_type(field.db_type(connection))
            expected.add(
                (
                    model._meta.db_table,  # noqa: SLF001
                    field.column,
                    database_type,
                    not field.null,
                    field.db_default is not NOT_PROVIDED,
                    "",
                    "",
                    *_expected_column_collation(
                        database_type,
                        getattr(field, "db_collation", None),
                    ),
                )
            )
    return expected


def _nullable_text(value: object) -> str | None:
    return None if value is None else str(value)


def _metadata_sha256(metadata: tuple[object, ...]) -> str:
    canonical = json.dumps(
        metadata,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema_definition_rows(
    cursor: CursorWrapper,
    relations: tuple[str, ...],
) -> dict[str, tuple[str, str]]:
    rows: dict[str, tuple[str, str]] = {}
    cursor.execute(
        """
        SELECT relation.relname::text,
               constraint_record.conname::text,
               constraint_record.contype::text,
               constraint_record.condeferrable,
               constraint_record.condeferred,
               constraint_record.convalidated,
               constraint_record.confupdtype::text,
               constraint_record.confdeltype::text,
               constraint_record.confmatchtype::text,
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
         WHERE namespace.nspname = 'public'
           AND relation.relname = ANY(%s::text[])
         ORDER BY relation.relname, constraint_record.conname
        """,
        [list(relations)],
    )
    for row in cursor.fetchall():
        key = f"constraint:{row[0]}:{row[1]}"
        constraint_metadata = (
            str(row[0]),
            str(row[2]),
            bool(row[3]),
            bool(row[4]),
            bool(row[5]),
            str(row[6]),
            str(row[7]),
            str(row[8]),
        )
        rows[key] = (_metadata_sha256(constraint_metadata), str(row[9]))

    cursor.execute(
        """
        SELECT table_relation.relname::text,
               index_relation.relname::text,
               access_method.amname::text,
               index_record.indisunique,
               index_record.indisvalid,
               index_record.indisready,
               index_record.indislive,
               index_record.indisprimary,
               index_record.indisexclusion,
               index_record.indisclustered,
               index_record.indisreplident,
               index_record.indexprs IS NOT NULL,
               index_record.indpred IS NOT NULL,
               index_record.indnkeyatts,
               index_record.indnatts,
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
           AND table_relation.relname = ANY(%s::text[])
         ORDER BY table_relation.relname, index_relation.relname
        """,
        [list(relations)],
    )
    for row in cursor.fetchall():
        key = f"index:{row[0]}:{row[1]}"
        index_metadata = (
            str(row[0]),
            str(row[2]),
            bool(row[3]),
            bool(row[4]),
            bool(row[5]),
            bool(row[6]),
            bool(row[7]),
            bool(row[8]),
            bool(row[9]),
            bool(row[10]),
            bool(row[11]),
            bool(row[12]),
            int(row[13]),
            int(row[14]),
        )
        rows[key] = (_metadata_sha256(index_metadata), str(row[15]))
    return rows


def collect_applications_schema_object_sha256() -> dict[str, tuple[str, str]]:
    """Return installed data-free fingerprints for migration finalization.

    Returns
    -------
    dict[str, tuple[str, str]]
        Complete constraint and index metadata/definition digests keyed by
        catalog kind, Applications relation, and object name.
    """
    with connection.cursor() as cursor:
        return _schema_definition_rows(
            cursor,
            tuple(sorted(APPLICATIONS_RELATION_SEMANTICS)),
        )


def _schema_object_catalog_sha256(
    rows: Mapping[str, tuple[str, str]],
    *,
    prefix: str,
) -> tuple[int, str]:
    selected = tuple(
        sorted(
            (key, metadata_sha256, definition_sha256)
            for key, (metadata_sha256, definition_sha256) in rows.items()
            if key.startswith(prefix)
        )
    )
    canonical = json.dumps(selected, ensure_ascii=True, separators=(",", ":"))
    return len(selected), hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema_object_rows_are_current(
    rows: Mapping[str, tuple[str, str]],
    expected_catalog: Mapping[str, tuple[int, str]],
    *,
    prefix: str,
) -> bool:
    expected = expected_catalog.get(prefix)
    return (
        expected is not None
        and _schema_object_catalog_sha256(
            rows,
            prefix=prefix,
        )
        == expected
    )


def _installed_column_rows(
    cursor: CursorWrapper,
    relations: tuple[str, ...],
) -> set[tuple[object, ...]]:
    cursor.execute(
        """
        SELECT relation.relname::text,
               attribute.attname::text,
               pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
               attribute.attnotnull,
               attribute.atthasdef,
               attribute.attidentity::text,
               attribute.attgenerated::text,
               collation_namespace.nspname::text,
               collation_record.collname::text,
               collation_record.collprovider::text,
               collation_record.collisdeterministic,
               collation_record.collencoding,
               collation_record.collcollate,
               collation_record.collctype,
               collation_record.colllocale,
               collation_record.collicurules,
               collation_record.collversion
          FROM pg_catalog.pg_attribute AS attribute
          JOIN pg_catalog.pg_class AS relation
            ON relation.oid = attribute.attrelid
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = relation.relnamespace
          LEFT JOIN pg_catalog.pg_collation AS collation_record
            ON collation_record.oid = attribute.attcollation
          LEFT JOIN pg_catalog.pg_namespace AS collation_namespace
            ON collation_namespace.oid = collation_record.collnamespace
         WHERE namespace.nspname = 'public'
           AND relation.relname = ANY(%s::text[])
           AND attribute.attnum > 0
           AND NOT attribute.attisdropped
         ORDER BY relation.relname, attribute.attnum
        """,
        [list(relations)],
    )
    return {
        (
            str(row[0]),
            str(row[1]),
            _canonical_database_type(row[2]),
            bool(row[3]),
            bool(row[4]),
            str(row[5]),
            str(row[6]),
            _nullable_text(row[7]),
            _nullable_text(row[8]),
            _nullable_text(row[9]),
            None if row[10] is None else bool(row[10]),
            None if row[11] is None else int(row[11]),
            _nullable_text(row[12]),
            _nullable_text(row[13]),
            _nullable_text(row[14]),
            _nullable_text(row[15]),
            _nullable_text(row[16]),
        )
        for row in cursor.fetchall()
    }


def inspect_applications_schema_catalog() -> ApplicationsSchemaCatalog:
    """Inspect exact relations, columns, and constraint/index definitions.

    Returns
    -------
    ApplicationsSchemaCatalog
        Data-free readiness evidence for every Applications-owned schema layer.
    """
    relations = tuple(sorted(APPLICATIONS_RELATION_SEMANTICS))
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT relation.relname::text,
                   relation.relkind::text,
                   relation.relpersistence::text,
                   relation.relrowsecurity,
                   relation.relforcerowsecurity,
                   relation.relispartition,
                   relation.relreplident::text
              FROM pg_catalog.pg_class AS relation
              JOIN pg_catalog.pg_namespace AS namespace
                ON namespace.oid = relation.relnamespace
             WHERE namespace.nspname = 'public'
               AND relation.relname LIKE 'applications\\_%' ESCAPE '\\'
               AND relation.relkind IN ('r', 'p', 'f', 'v', 'm', 'S', 'c')
             ORDER BY relation.relname
            """
        )
        installed_relations = {
            str(row[0]): (
                str(row[1]),
                str(row[2]),
                bool(row[3]),
                bool(row[4]),
                bool(row[5]),
                str(row[6]),
            )
            for row in cursor.fetchall()
        }
        installed_columns = _installed_column_rows(cursor, relations)
        schema_rows = _schema_definition_rows(cursor, relations)

    fingerprints_finalized = all(
        (
            set(APPLICATIONS_SCHEMA_CATALOG_SHA256) == {"constraint:", "index:"},
            all(
                count > 0 and len(digest) == _SHA256_HEX_LENGTH
                for count, digest in APPLICATIONS_SCHEMA_CATALOG_SHA256.values()
            ),
        )
    )
    return ApplicationsSchemaCatalog(
        schema_fingerprints_finalized=fingerprints_finalized,
        relations_current=(
            _applications_relation_names() == relations
            and installed_relations == APPLICATIONS_RELATION_SEMANTICS
        ),
        columns_current=installed_columns == _expected_applications_columns(),
        constraints_current=(
            fingerprints_finalized
            and _schema_object_rows_are_current(
                schema_rows,
                APPLICATIONS_SCHEMA_CATALOG_SHA256,
                prefix="constraint:",
            )
        ),
        indexes_current=(
            fingerprints_finalized
            and _schema_object_rows_are_current(
                schema_rows,
                APPLICATIONS_SCHEMA_CATALOG_SHA256,
                prefix="index:",
            )
        ),
    )


def applications_database_integrity_is_ready() -> bool:
    """Verify applications database integrity is ready.

    Returns
    -------
    bool
        Whether the requested condition is satisfied.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) = 2 FROM public.django_migrations "
                "WHERE app = 'applications' AND name IN (%s, %s)",
                (
                    "0011_programme_department_ownership_integrity",
                    "0012_programme_department_ownership_downgrade_fence",
                ),
            )
            if cursor.fetchone() != (True,):
                return False
        return (
            database_integrity_contract_is_ready(APPLICATIONS_INTEGRITY_CONTRACT)
            and inspect_applications_schema_catalog().ready
        )
    except (DatabaseError, LookupError, RuntimeError, TypeError, ValueError):
        return False


__all__ = [
    "APPLICATIONS_INTEGRITY_CONTRACT",
    "APPLICATIONS_RELATION_SEMANTICS",
    "APPLICATIONS_SCHEMA_CATALOG_SHA256",
    "ApplicationsSchemaCatalog",
    "applications_database_integrity_is_ready",
    "collect_applications_schema_object_sha256",
    "inspect_applications_schema_catalog",
]
