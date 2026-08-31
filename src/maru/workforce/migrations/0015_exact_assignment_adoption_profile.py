"""Bind Workforce assignment evidence to exact adoption-profile versions."""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from django.db import migrations

_PRIOR_SOURCE_SHA256 = (
    "b7199a042fbefbfc4d8bc3a157f1382dc8d57019995979752d797a4e541f30aa"
)
_EXACT_PROFILE_SOURCE_SHA256 = (
    "768710cc292c4a9e10fec5fbcfeb46c0bb52d01dc4679ca1c71647bf12180c41"
)
_SAFE_SEARCH_PATH = ("search_path=pg_catalog, public, pg_temp",)
_CAPACITY_BRANCH_OCCURRENCES = 2


def _source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(
            "Refusing to transform an unrecognized Workforce assignment guard."
        )
    return source.replace(old, new)


def _assignment_source(source: str, *, enable: bool) -> str:
    """Transform the assignment guard between code-only and exact-pair lookup."""
    old_declaration = """    assignment_profile_code varchar;
BEGIN"""
    new_declaration = """    assignment_profile_code varchar;
    assignment_profile_version integer;
    assignment_requires_participation boolean;
BEGIN"""
    old_profile_lookup = """    SELECT edition.adoption_profile_code
      INTO assignment_profile_code
      FROM public.events_eventedition AS edition
     WHERE edition.id = NEW.edition_id
     FOR KEY SHARE;
    IF assignment_profile_code IS NULL THEN
        RAISE EXCEPTION 'workforce assignment edition profile is unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF assignment_profile_code = 'workforce_only'
       AND NEW.participation_capacity_id IS NOT NULL
    THEN
        RAISE EXCEPTION 'Workforce-only assignment cannot create Participation evidence'
            USING ERRCODE = '23514';
    END IF;"""
    new_profile_lookup = """    SELECT edition.adoption_profile_code,
           edition.adoption_profile_version
      INTO assignment_profile_code,
           assignment_profile_version
      FROM public.events_eventedition AS edition
     WHERE edition.id = NEW.edition_id
     FOR KEY SHARE;
    IF assignment_profile_code = 'full_convention'
       AND assignment_profile_version = 1
    THEN
        assignment_requires_participation := TRUE;
    ELSIF assignment_profile_code = 'workforce_only'
          AND assignment_profile_version = 1
    THEN
        assignment_requires_participation := FALSE;
    ELSE
        RAISE EXCEPTION 'workforce assignment exact adoption profile is unsupported'
            USING ERRCODE = '23514';
    END IF;
    IF NOT assignment_requires_participation
       AND NEW.participation_capacity_id IS NOT NULL
    THEN
        RAISE EXCEPTION 'Workforce-only assignment cannot create Participation evidence'
            USING ERRCODE = '23514';
    END IF;"""
    old_active_evidence = """            assignment_profile_code = 'full_convention'
            AND NEW.participation_capacity_id IS NULL"""
    new_active_evidence = """            assignment_requires_participation
            AND NEW.participation_capacity_id IS NULL"""
    old_governed_capacity = """                (
                    assignment_profile_code = 'full_convention'
                    AND NEW.participation_capacity_id IS NOT NULL
                )
                OR (
                    assignment_profile_code = 'workforce_only'
                    AND NEW.participation_capacity_id IS NULL
                )"""
    new_governed_capacity = """                (
                    assignment_requires_participation
                    AND NEW.participation_capacity_id IS NOT NULL
                )
                OR (
                    NOT assignment_requires_participation
                    AND NEW.participation_capacity_id IS NULL
                )"""
    if enable:
        rewritten = _replace_once(source, old_declaration, new_declaration)
        rewritten = _replace_once(rewritten, old_profile_lookup, new_profile_lookup)
        rewritten = _replace_once(
            rewritten,
            old_active_evidence,
            new_active_evidence,
        )
        if rewritten.count(old_governed_capacity) != _CAPACITY_BRANCH_OCCURRENCES:
            raise RuntimeError(
                "Refusing to transform unrecognized governed assignment evidence."
            )
        return rewritten.replace(old_governed_capacity, new_governed_capacity)
    rewritten = _replace_once(source, new_declaration, old_declaration)
    rewritten = _replace_once(rewritten, new_profile_lookup, old_profile_lookup)
    rewritten = _replace_once(
        rewritten,
        new_active_evidence,
        old_active_evidence,
    )
    if rewritten.count(new_governed_capacity) != _CAPACITY_BRANCH_OCCURRENCES:
        raise RuntimeError(
            "Refusing to restore unrecognized governed assignment evidence."
        )
    return rewritten.replace(new_governed_capacity, old_governed_capacity)


def _function_source(cursor: Any) -> str:
    cursor.execute(
        """
        SELECT procedure.prosrc,
               procedure.proconfig,
               procedure.prosecdef,
               procedure.provolatile,
               procedure.proparallel
          FROM pg_catalog.pg_proc AS procedure
         WHERE procedure.oid = pg_catalog.to_regprocedure(
             'public.maru_guard_workforce_assignment()'
         )
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("The Workforce assignment guard is missing.")
    if (
        tuple(row[1] or ()) != _SAFE_SEARCH_PATH
        or bool(row[2])
        or str(row[3]) != "v"
        or str(row[4]) != "u"
    ):
        raise RuntimeError(
            "Refusing to replace a Workforce assignment guard with unexpected "
            "safety attributes."
        )
    return str(row[0])


def _replace_function(cursor: Any, source: str) -> None:
    cursor.execute(
        """
        CREATE OR REPLACE FUNCTION public.maru_guard_workforce_assignment()
        RETURNS trigger
        LANGUAGE plpgsql
        VOLATILE
        CALLED ON NULL INPUT
        SECURITY INVOKER
        PARALLEL UNSAFE
        SET search_path = pg_catalog, public, pg_temp
        AS %s
        """,
        [source],
    )


def enable_exact_profile_assignment_evidence(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Replace the reviewed code-only guard with its exact-pair successor."""
    del apps
    with schema_editor.connection.cursor() as cursor:
        source = _function_source(cursor)
        if _source_sha256(source) != _PRIOR_SOURCE_SHA256:
            raise RuntimeError(
                "Refusing to transform an unknown Workforce assignment guard."
            )
        rewritten = _assignment_source(source, enable=True)
        if _source_sha256(rewritten) != _EXACT_PROFILE_SOURCE_SHA256:
            raise RuntimeError(
                "The exact-profile Workforce assignment guard fingerprint drifted."
            )
        _replace_function(cursor, rewritten)


def restore_code_only_assignment_evidence(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Restore the predecessor only before governed assignment evidence exists."""
    assignment = apps.get_model("workforce", "PositionAssignment")
    if assignment.objects.filter(command_version__isnull=False).exists():
        raise RuntimeError(
            "Cannot remove exact-profile assignment evidence after a governed "
            "assignment exists; keep compatible code and fix forward."
        )
    with schema_editor.connection.cursor() as cursor:
        source = _function_source(cursor)
        if _source_sha256(source) != _EXACT_PROFILE_SOURCE_SHA256:
            raise RuntimeError(
                "Refusing to restore an unknown Workforce assignment guard."
            )
        restored = _assignment_source(source, enable=False)
        if _source_sha256(restored) != _PRIOR_SOURCE_SHA256:
            raise RuntimeError(
                "The restored Workforce assignment guard fingerprint drifted."
            )
        _replace_function(cursor, restored)


class Migration(migrations.Migration):
    """Require an exact manifest pair for Workforce assignment evidence."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0010_workforce_adoption_profile"),
        ("workforce", "0014_workforce_only_assignment_evidence"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            enable_exact_profile_assignment_evidence,
            reverse_code=restore_code_only_assignment_evidence,
        )
    ]
