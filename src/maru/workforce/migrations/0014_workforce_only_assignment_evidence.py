"""Keep Workforce-only assignments independent from Participation evidence."""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from django.db import migrations


_PRIOR_SOURCE_SHA256 = (
    "e51b2e0ff6aad3e50f9eec7648599b6d7f25d2ef11fe06c8f3432b09497b1469"
)
_PROFILE_SOURCE_SHA256 = (
    "b7199a042fbefbfc4d8bc3a157f1382dc8d57019995979752d797a4e541f30aa"
)
_SAFE_SEARCH_PATH = ("search_path=pg_catalog, public, pg_temp",)


def _source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(
            "Refusing to transform an unrecognized Workforce assignment guard."
        )
    return source.replace(old, new)


def _assignment_source(source: str, *, enable: bool) -> str:
    old_declaration = """    has_end boolean;
BEGIN"""
    new_declaration = """    has_end boolean;
    assignment_profile_code varchar;
BEGIN"""
    old_profile_lookup = """    IF NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id = NEW.proposed_by_id
    THEN"""
    new_profile_lookup = """    SELECT edition.adoption_profile_code
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
    END IF;
    IF NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id = NEW.proposed_by_id
    THEN"""
    old_active_evidence = """    IF NEW.status = 'active' AND (
        NEW.approved_by_id IS NULL
        OR NEW.role_assignment_id IS NULL
        OR NEW.participation_capacity_id IS NULL
    ) THEN"""
    new_active_evidence = """    IF NEW.status = 'active' AND (
        NEW.approved_by_id IS NULL
        OR NEW.role_assignment_id IS NULL
        OR (
            assignment_profile_code = 'full_convention'
            AND NEW.participation_capacity_id IS NULL
        )
    ) THEN"""
    old_governed_capacity = (
        "            AND NEW.participation_capacity_id IS NOT NULL\n"
    )
    new_governed_capacity = """            AND (
                (
                    assignment_profile_code = 'full_convention'
                    AND NEW.participation_capacity_id IS NOT NULL
                )
                OR (
                    assignment_profile_code = 'workforce_only'
                    AND NEW.participation_capacity_id IS NULL
                )
            )
"""
    if enable:
        rewritten = _replace_once(source, old_declaration, new_declaration)
        rewritten = _replace_once(rewritten, old_profile_lookup, new_profile_lookup)
        rewritten = _replace_once(
            rewritten,
            old_active_evidence,
            new_active_evidence,
        )
        if rewritten.count(old_governed_capacity) != 2:
            raise RuntimeError(
                "Refusing to transform unrecognized governed assignment evidence."
            )
        return rewritten.replace(
            old_governed_capacity,
            new_governed_capacity,
        )
    rewritten = _replace_once(source, new_declaration, old_declaration)
    rewritten = _replace_once(rewritten, new_profile_lookup, old_profile_lookup)
    rewritten = _replace_once(
        rewritten,
        new_active_evidence,
        old_active_evidence,
    )
    if rewritten.count(new_governed_capacity) != 2:
        raise RuntimeError(
            "Refusing to restore unrecognized governed assignment evidence."
        )
    return rewritten.replace(
        new_governed_capacity,
        old_governed_capacity,
    )


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
            "Refusing to replace a Workforce assignment guard with unexpected safety attributes."
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


def enable_profile_matched_assignment_evidence(
    apps: Any,
    schema_editor: Any,
) -> None:
    del apps
    with schema_editor.connection.cursor() as cursor:
        source = _function_source(cursor)
        if _source_sha256(source) != _PRIOR_SOURCE_SHA256:
            raise RuntimeError(
                "Refusing to transform an unknown Workforce assignment guard."
            )
        rewritten = _assignment_source(source, enable=True)
        if _source_sha256(rewritten) != _PROFILE_SOURCE_SHA256:
            raise RuntimeError(
                "The profile-matched Workforce assignment guard fingerprint drifted."
            )
        _replace_function(cursor, rewritten)


def restore_participation_assignment_evidence(
    apps: Any,
    schema_editor: Any,
) -> None:
    assignment = apps.get_model("workforce", "PositionAssignment")
    edition = apps.get_model("events", "EventEdition")
    if assignment.objects.filter(
        edition_id__in=edition.objects.filter(
            adoption_profile_code="workforce_only"
        ).values("id"),
        status__in=("active", "ended"),
        participation_capacity_id__isnull=True,
    ).exists():
        raise RuntimeError(
            "Cannot restore Participation-required assignment evidence after a "
            "Workforce-only assignment exists; keep compatible code and fix forward."
        )
    with schema_editor.connection.cursor() as cursor:
        source = _function_source(cursor)
        if _source_sha256(source) != _PROFILE_SOURCE_SHA256:
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
    """Make assignment evidence match the edition's immutable adoption profile."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0010_workforce_adoption_profile"),
        ("workforce", "0013_shift_journey"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            enable_profile_matched_assignment_evidence,
            reverse_code=restore_participation_assignment_evidence,
        )
    ]
