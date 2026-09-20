"""Correct ADR 0080 representation lineage under active native provenance."""

import hashlib
import json
import re
from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation

_ORIGINAL = import_module(
    "maru.authorization.migrations.0007_authority_provenance_activation_guards"
)
_ADOPTION = import_module(
    "maru.authorization.migrations.0019_progressive_adoption_authority"
)
_COMPLETE = "maru_assert_authority_issuance_complete_internal(bigint,bigint[],integer)"
_BUNDLE = "maru_authority_bundle_historical_v1(uuid,timestamptz,uuid,bigint[],integer)"
_ASSIGNMENT = (
    "maru_authority_issuance_valid_v1(bigint,uuid,character varying,uuid,uuid,"
    "uuid,uuid,timestamptz,timestamptz,timestamptz,boolean,boolean,bigint[],integer)"
)
_PREVIOUS_FINGERPRINTS = {
    _COMPLETE: "e094e76364a1a24f204f858f8b7e50f5112b3010a6681070edbe20f0b96c7963",
    _BUNDLE: "99c48835597a25b37560a94104921008380a2ea9dc9543a8cf50ede6ee871e2c",
    _ASSIGNMENT: "b9e6aed373ea09fa3c2095c9711b5c1443d65e022aa3b68d2ec06b41e449f666",
}


def _once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError("Unrecognized frozen representation-lineage source.")
    return source.replace(old, new)


def _neutral_ceremony(block: str) -> str:
    """Clone only the frozen special ceremony, retaining every evidence predicate."""
    capabilities = sorted(_ADOPTION.MARU_OPERATOR_CAPABILITIES)
    array = "ARRAY[\n" + ",\n".join(f"               '{c}'" for c in capabilities)
    array += "\n           ]::varchar[]"
    pattern = r"ARRAY\[\n\s*'audit\.view_security'.*?\]::varchar\[\]"
    if len(re.findall(pattern, block, re.DOTALL)) != 1:
        raise RuntimeError("Unrecognized frozen representation capability array.")
    block = re.sub(pattern, lambda _match: array, block, flags=re.DOTALL)
    return (
        block.replace("'executive-board'", "'maru-operators'")
        .replace("'executive_board'", "'maru_operators'")
        .replace("'Executive Board'", "'Maru operators'")
        .replace("'Executive Board controller'", "'Maru operator'")
        .replace("!= 12", "!= 22")
    )


def function_sql(identity: str, *, corrected: bool) -> str:
    """Return a frozen validator, optionally with the accepted second ceremony."""
    name = identity.split("(", 1)[0]
    pattern = (
        rf"CREATE (?:OR REPLACE )?FUNCTION public\.{name}\(.*?"
        r"\$\$ LANGUAGE plpgsql(?: STABLE)?\n"
        r"SET search_path = pg_catalog, public, pg_temp;"
    )
    matches = re.findall(pattern, _ORIGINAL.FORWARD_SQL, re.DOTALL)
    # 0007 declares a bundle stub before replacing it for mutual recursion.
    if len(matches) != (2 if identity == _BUNDLE else 1):
        raise RuntimeError("Frozen representation validator is unavailable.")
    sql = matches[-1].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
    if not corrected:
        return sql
    if identity == _COMPLETE:
        return _once(
            sql,
            "COALESCE(role_bundle.code, assignment_bundle.code) = 'executive-board'",
            "COALESCE(role_bundle.code, assignment_bundle.code) "
            "= ANY (ARRAY['executive-board', 'maru-operators'])",
        )
    if identity == _BUNDLE:
        start = "    IF bundle_code = 'executive-board' THEN"
        end = "    FOR control_record IN"
    elif identity == _ASSIGNMENT:
        start = (
            "    IF source_kind = 'assignment'\n"
            "       AND source_bundle_code = 'executive-board'"
        )
        end = (
            "    IF source_kind = 'assignment'\n"
            "       AND NOT public.maru_authority_bundle_historical_v1("
        )
    else:
        raise RuntimeError("Unknown representation validator.")
    first = sql.index(start)
    last = sql.index(end, first)
    block = sql[first:last]
    return _once(sql, block, _neutral_ceremony(block) + block)


def _fingerprint(definition: tuple[Any, ...]) -> str:
    keys = (
        "source",
        "language",
        "volatility",
        "parallel",
        "security_definer",
        "leakproof",
        "strict",
        "returns_set",
        "kind",
        "config",
        "result",
    )
    payload = dict(zip(keys, definition, strict=True))
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _state(cursor: Any, identity: str) -> tuple[Any, ...]:
    cursor.execute(
        """
        SELECT p.oid, p.proowner, p.proacl, p.prosrc, l.lanname::text,
               p.provolatile::text, p.proparallel::text, p.prosecdef,
               p.proleakproof, p.proisstrict, p.proretset, p.prokind::text,
               p.proconfig, pg_catalog.pg_get_function_result(p.oid)
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_language l ON l.oid = p.prolang
        WHERE p.oid = pg_catalog.to_regprocedure(%s)
        """,
        ["public." + identity],
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Native representation validator is unavailable.")
    return tuple(row)


def _replace(schema_editor: Any, *, corrected: bool) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE public.authorization_rolebundle, "
            "public.authorization_roleassignment, "
            "public.authorization_authorityissuance, "
            "public.authorization_authoritycontrol IN ACCESS EXCLUSIVE MODE"
        )
        if not corrected:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM public.authorization_rolebundle "
                "WHERE code = 'maru-operators')"
            )
            if cursor.fetchone()[0]:
                raise RuntimeError(
                    "Used Maru-operator lineage requires fix-forward recovery."
                )
        for identity, expected in _PREVIOUS_FINGERPRINTS.items():
            before = _state(cursor, identity)
            previous_source = function_sql(identity, corrected=False).split("$$")[1]
            next_source = function_sql(identity, corrected=True).split("$$")[1]
            normalized = (previous_source, *before[4:])
            if (
                before[3] != (previous_source if corrected else next_source)
                or _fingerprint(normalized) != expected
            ):
                raise RuntimeError("Refusing changed native representation lineage.")
            cursor.execute(function_sql(identity, corrected=corrected))
            after = _state(cursor, identity)
            if (
                after[:3] != before[:3]
                or after[4:] != before[4:]
                or after[3] != (next_source if corrected else previous_source)
            ):
                raise RuntimeError(
                    "Representation function identity or privileges changed."
                )


def install_lineage(apps: Any, schema_editor: Any) -> None:
    """Install the accepted two-root native lineage without rewriting evidence."""
    del apps
    _replace(schema_editor, corrected=True)


def restore_lineage(apps: Any, schema_editor: Any) -> None:
    """Permit reversal only before durable Maru-operator root use."""
    del apps
    _replace(schema_editor, corrected=False)


class Migration(migrations.Migration):
    """Preserve metadata and exact source while correcting three validators."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0038_programme_archive_recipe"),
        ("organizations", "0014_purpose_bounded_representation"),
    ]
    operations: ClassVar[list[Operation]] = [
        migrations.RunPython(install_lineage, restore_lineage),
    ]
