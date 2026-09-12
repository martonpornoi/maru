"""Reject native volunteer work that conflicts with an operative published host."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module(
    "maru.workforce.migrations.0023_global_person_obligation_generation"
)
_start = _previous.FORWARD_SQL.index(
    "CREATE FUNCTION public.maru_workforce_release_person_guard()"
)
_end_marker = "SET search_path = pg_catalog, public, pg_temp;"
_end = _previous.FORWARD_SQL.index(_end_marker, _start) + len(_end_marker)
_original = _previous.FORWARD_SQL[_start:_end].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
)
_marker = "    RETURN NEW;"
if _original.count(_marker) != 1:
    raise RuntimeError("The frozen Workforce person serialization guard changed.")
_check = r"""
    IF NEW.status IN ('claimed', 'confirmed') AND NOT EXISTS (
        SELECT 1 FROM public.maru_scheduling_published_person_conflict(
            NEW.account_id, NEW.starts_at, NEW.ends_at, NEW.rest_ends_at, NULL
        ) consequence
        WHERE consequence.has_overlap IS FALSE
          AND consequence.has_rest_conflict IS FALSE
          AND consequence.evidence_digest IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Work conflicts with operative published person obligations'
          USING ERRCODE = '23514';
    END IF;
    RETURN NEW;"""
FORWARD_SQL = _original.replace(_marker, _check)
REVERSE_SQL = _original


def refuse_published_host_guard_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep reciprocal native protection after the first retained release."""
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingrelease IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("scheduling", "SchedulingRelease").objects.exists():
        raise RuntimeError("Published host obligations exist; fix forward.")


class Migration(migrations.Migration):
    """Keep the existing exact-account lock and append a minimized source check."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0023_global_person_obligation_generation"),
        ("scheduling", "0018_published_person_conflict_source"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_published_host_guard_downgrade
        ),
    ]
