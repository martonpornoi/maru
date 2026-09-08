"""Data-free, owner-pinned PostgreSQL relation-shape verification."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from django.db import connection

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def collect_relation_schema_fingerprints(
    relation_names: Sequence[str],
) -> dict[str, str]:
    """Fingerprint exact public relation shapes without reading business records.

    Parameters
    ----------
    relation_names : Sequence[str]
        Explicit owner-controlled unqualified relation names; always bound as data.

    Returns
    -------
    dict[str, str]
        SHA-256 of canonical relation, column, constraint and index metadata.
        Missing relations are omitted so equality against a pinned catalog fails.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
    SELECT relation.relname::text,
           jsonb_build_object(
               'relation', jsonb_build_array(
                   relation.relkind::text, relation.relpersistence::text,
                   relation.relrowsecurity, relation.relforcerowsecurity,
                   relation.relhasrules, relation.relreplident::text,
                   relation.relispartition, relation.relhassubclass,
                   relation.reloptions, relation.reltablespace <> 0
               ),
               'columns', COALESCE((
                   SELECT jsonb_agg(jsonb_build_array(
                       attribute.attnum, attribute.attname::text,
                       pg_catalog.format_type(attribute.atttypid, attribute.atttypmod),
                       attribute.attnotnull, attribute.attidentity::text,
                       attribute.attgenerated::text, attribute.attisdropped,
                       attribute.attislocal, attribute.attinhcount,
                       attribute.attstorage::text, attribute.attcompression::text,
                       pg_catalog.pg_get_expr(
                           default_value.adbin, default_value.adrelid),
                       collation_namespace.nspname::text,
                       column_collation.collname::text,
                       column_collation.collprovider::text,
                       column_collation.collisdeterministic,
                       column_collation.collencoding,
                       column_collation.collcollate::text,
                       column_collation.collctype::text,
                       column_collation.colllocale::text,
                       column_collation.collicurules::text,
                       column_collation.collversion::text
                   ) ORDER BY attribute.attnum)
                   FROM pg_catalog.pg_attribute attribute
                   LEFT JOIN pg_catalog.pg_attrdef default_value
                       ON default_value.adrelid = attribute.attrelid
                      AND default_value.adnum = attribute.attnum
                   LEFT JOIN pg_catalog.pg_collation column_collation
                       ON column_collation.oid = attribute.attcollation
                   LEFT JOIN pg_catalog.pg_namespace collation_namespace
                       ON collation_namespace.oid = column_collation.collnamespace
                   WHERE attribute.attrelid = relation.oid AND attribute.attnum > 0
               ), '[]'::jsonb),
               'constraints', COALESCE((
                   SELECT jsonb_agg(jsonb_build_array(
                       constraint_row.conname::text, constraint_row.contype::text,
                       pg_catalog.pg_get_constraintdef(constraint_row.oid, false),
                       constraint_row.condeferrable, constraint_row.condeferred,
                       constraint_row.convalidated, constraint_row.conislocal,
                       constraint_row.coninhcount, constraint_row.connoinherit,
                       constraint_row.conparentid <> 0
                   ) ORDER BY constraint_row.conname)
                   FROM pg_catalog.pg_constraint constraint_row
                   WHERE constraint_row.conrelid = relation.oid
               ), '[]'::jsonb),
               'indexes', COALESCE((
                   SELECT jsonb_agg(jsonb_build_array(
                       index_namespace.nspname::text, index_relation.relname::text,
                       pg_catalog.pg_get_indexdef(index_row.indexrelid, 0, false),
                       index_row.indisunique, index_row.indisprimary,
                       index_row.indisexclusion, index_row.indimmediate,
                       index_row.indisvalid, index_row.indisready,
                       index_row.indislive, index_row.indisclustered,
                       index_row.indisreplident, index_row.indnullsnotdistinct,
                       index_relation.reloptions, index_relation.reltablespace <> 0
                   ) ORDER BY index_relation.relname)
                   FROM pg_catalog.pg_index index_row
                   JOIN pg_catalog.pg_class index_relation
                       ON index_relation.oid = index_row.indexrelid
                   JOIN pg_catalog.pg_namespace index_namespace
                       ON index_namespace.oid = index_relation.relnamespace
                   WHERE index_row.indrelid = relation.oid
               ), '[]'::jsonb)
           )
      FROM pg_catalog.pg_class relation
      JOIN pg_catalog.pg_namespace namespace ON namespace.oid = relation.relnamespace
     WHERE namespace.nspname = 'public' AND relation.relname = ANY(%s::text[])
     ORDER BY relation.relname
            """,
            [list(relation_names)],
        )
        rows = cursor.fetchall()
    fingerprints: dict[str, str] = {}
    for name, metadata in rows:
        # Django may return JSONB as text or decoded objects.
        payload = json.loads(metadata) if isinstance(metadata, str) else metadata
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        fingerprints[str(name)] = hashlib.sha256(encoded).hexdigest()
    return fingerprints


def relation_schema_is_current(expected: Mapping[str, str]) -> bool:
    """Compare every exact relation against an explicitly pinned owner catalog.

    Parameters
    ----------
    expected : Mapping[str, str]
        Reviewed nonempty relation-to-SHA-256 catalog. Empty placeholders fail closed.

    Returns
    -------
    bool
        Whether the complete requested schema exactly matches its pinned shapes.
    """
    return bool(expected) and collect_relation_schema_fingerprints(
        tuple(expected)
    ) == dict(expected)
