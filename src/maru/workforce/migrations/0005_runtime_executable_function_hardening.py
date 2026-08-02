"""Pin the workforce runtime evidence helper to trusted relations."""

from __future__ import annotations

import hashlib
import re
from typing import ClassVar

from django.db import migrations

_SAFE_SEARCH_PATH = ("search_path=pg_catalog, public, pg_temp",)


def _trigger_ddl(name: str) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION public.{name}()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        CALLED ON NULL INPUT
        SECURITY INVOKER
        PARALLEL UNSAFE
        SET search_path = pg_catalog, public, pg_temp
        AS %s
    """


_FUNCTIONS = (
    {
        "identity": (
            "public.maru_workforce_role_evidence_matches_position"
            "(uuid,uuid,uuid,uuid,uuid,uuid)"
        ),
        "old_source_sha256": (
            "a5283050bbcc829971853aacfbebe4ee9e4b9446c2532a6413c4ee75540ede8f"
        ),
        "new_source_sha256": (
            "ad84a484c0c07fa30a99a1567035f6ced37215cbef2a141dd4ef7eb0cc5b27e0"
        ),
        "identifiers": (
            ("authorization_roleassignment", 1),
            ("authorization_scopedresourcebinding", 1),
        ),
        "ddl": """
            CREATE OR REPLACE FUNCTION
                public.maru_workforce_role_evidence_matches_position(
                    evidence_id uuid,
                    expected_position_id uuid,
                    expected_organization_id uuid,
                    expected_edition_id uuid,
                    expected_department_id uuid,
                    expected_account_id uuid
                )
            RETURNS boolean
            LANGUAGE sql
            STABLE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
        """,
    },
    {
        "identity": "public.maru_guard_workforce_position()",
        "old_source_sha256": (
            "97e4c1aaac0910a405dd99791c09955637c481f0d8678b2d1ce6982d8d7d0ae6"
        ),
        "new_source_sha256": (
            "5b63d29a0feed730d8f8c8355044638a27be2f41cc5e658b146f4df3869d34ac"
        ),
        "identifiers": (
            ("authorization_rolebundle", 1),
            ("authorization_scopedresourcebinding", 2),
            ("events_eventedition", 1),
            ("workforce_department", 1),
            ("workforce_position", 4),
            ("workforce_positionassignment", 1),
            ("workforce_positiontemplate", 1),
            ("maru_workforce_role_evidence_matches_position", 1),
        ),
        "ddl": _trigger_ddl("maru_guard_workforce_position"),
    },
    {
        "identity": "public.maru_guard_workforce_assignment()",
        "old_source_sha256": (
            "7dcca43397fd9c1cb36305a624d42481aaa6b54b733986fd2e2899fd1b531958"
        ),
        "new_source_sha256": (
            "d3e13cf6ed62e4ddf35acb0ef8ee72ca53b273f3a323a49d0760310769c02385"
        ),
        "identifiers": (
            ("participation_participation", 1),
            ("participation_participationcapacity", 1),
            ("workforce_position", 1),
            ("maru_workforce_role_evidence_matches_position", 1),
        ),
        "ddl": _trigger_ddl("maru_guard_workforce_assignment"),
    },
)


def _source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _rewrite_source(
    source: str,
    identifiers: tuple[tuple[str, int], ...],
    *,
    qualify: bool,
) -> str:
    rewritten = source
    for identifier, expected_count in identifiers:
        source_name = identifier if qualify else f"public.{identifier}"
        target_name = f"public.{identifier}" if qualify else identifier
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_.]){re.escape(source_name)}(?![A-Za-z0-9_])"
        )
        matches = pattern.findall(rewritten)
        if len(matches) != expected_count:
            direction = "upgrade" if qualify else "downgrade"
            raise RuntimeError(
                f"Refusing workforce runtime function {direction}: "
                f"{source_name} occurred {len(matches)} times, expected "
                f"{expected_count}."
            )
        rewritten = pattern.sub(target_name, rewritten)
    return rewritten


def _function_state(  # type: ignore[no-untyped-def]
    cursor,
    identity: str,
) -> tuple[object, str, tuple[str, ...], object, object]:
    cursor.execute(
        """
        SELECT procedure.oid,
               procedure.prosrc,
               procedure.proconfig,
               procedure.proowner,
               procedure.proacl
          FROM pg_catalog.pg_proc AS procedure
          JOIN pg_catalog.pg_namespace AS namespace
            ON namespace.oid = procedure.pronamespace
         WHERE procedure.oid = pg_catalog.to_regprocedure(%s)
           AND namespace.nspname = 'public'
        """,
        [identity],
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Required runtime function {identity} is missing.")
    return (row[0], str(row[1]), tuple(row[2] or ()), row[3], row[4])


def _rewrite_functions(schema_editor, *, qualify: bool) -> None:  # type: ignore[no-untyped-def]
    with schema_editor.connection.cursor() as cursor:
        for contract in _FUNCTIONS:
            before = _function_state(cursor, contract["identity"])
            expected_hash = (
                contract["old_source_sha256"]
                if qualify
                else contract["new_source_sha256"]
            )
            expected_config = () if qualify else _SAFE_SEARCH_PATH
            if _source_sha256(before[1]) != expected_hash:
                raise RuntimeError(
                    "Refusing to rewrite an unrecognized workforce runtime "
                    f"function: {contract['identity']}."
                )
            if before[2] != expected_config:
                raise RuntimeError(
                    "Refusing to rewrite a workforce runtime function with "
                    f"unexpected configuration: {contract['identity']}."
                )

            rewritten = _rewrite_source(
                before[1],
                contract["identifiers"],
                qualify=qualify,
            )
            target_hash = (
                contract["new_source_sha256"]
                if qualify
                else contract["old_source_sha256"]
            )
            if _source_sha256(rewritten) != target_hash:
                raise RuntimeError(
                    "Workforce runtime function rewrite did not produce the "
                    f"code-owned definition: {contract['identity']}."
                )

            cursor.execute(contract["ddl"], [rewritten])
            if not qualify:
                cursor.execute(
                    f"ALTER FUNCTION {contract['identity']} RESET search_path"
                )

            after = _function_state(cursor, contract["identity"])
            target_config = _SAFE_SEARCH_PATH if qualify else ()
            if (
                after[0] != before[0]
                or after[2] != target_config
                or after[3] != before[3]
                or after[4] != before[4]
                or _source_sha256(after[1]) != target_hash
            ):
                raise RuntimeError(
                    "Workforce runtime function identity, ACL, or definition "
                    f"changed unexpectedly: {contract['identity']}."
                )


def harden_runtime_function(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del apps
    _rewrite_functions(schema_editor, qualify=True)


def restore_runtime_function(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del apps
    _rewrite_functions(schema_editor, qualify=False)


def refuse_activated_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Do not weaken runtime helpers once durable cutover evidence exists."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                to_regclass(
                    'public.authorization_authorityprovenanceactivation'
                ),
                to_regclass('public.authorization_provenanceactivationlatch'),
                to_regclass('public.audit_auditevent')
            """
        )
        relations = cursor.fetchone()
        if relations is None:
            raise RuntimeError(
                "Cannot prove dormant authority provenance state before downgrade."
            )
        marker_table, latch_table, audit_table = relations
        if marker_table is None and latch_table is None:
            if audit_table is None:
                return
            cursor.execute(
                """
                SELECT COUNT(*)
                  FROM public.audit_auditevent
                 WHERE operation =
                       'authorization.authority_provenance.activate'
                """
            )
            if int(cursor.fetchone()[0]) == 0:
                return
            raise RuntimeError(
                "Cannot reverse runtime-executable function hardening while "
                "activation audit evidence exists."
            )
        if marker_table is None or latch_table is None or audit_table is None:
            raise RuntimeError(
                "Cannot prove complete authority provenance state before downgrade."
            )

    schema_editor.execute(
        """
        LOCK TABLE
            public.audit_auditevent,
            public.authorization_authorityprovenanceactivation,
            public.authorization_provenanceactivationlatch
        IN ACCESS EXCLUSIVE MODE
        """
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*)
                   FROM public.authorization_authorityprovenanceactivation),
                (SELECT COUNT(*)
                   FROM public.audit_auditevent
                  WHERE operation =
                        'authorization.authority_provenance.activate'),
                (SELECT COUNT(*)
                   FROM public.authorization_provenanceactivationlatch),
                EXISTS (
                    SELECT 1
                      FROM public.authorization_provenanceactivationlatch
                     WHERE singleton IS TRUE AND generation = 0
                )
            """
        )
        row = cursor.fetchone()
    if row is None or not (
        int(row[0]) == 0 and int(row[1]) == 0 and int(row[2]) == 1 and bool(row[3])
    ):
        raise RuntimeError(
            "Cannot reverse runtime-executable function hardening after "
            "authority provenance activation. Keep compatible code and fix "
            "forward, or restore the whole database to one consistent "
            "pre-activation point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0004_scope_v2_integrity"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            harden_runtime_function,
            reverse_code=restore_runtime_function,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_activated_downgrade,
        ),
    ]
