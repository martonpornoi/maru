"""Retain the sealed Venue version captured before first dependency tracking."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations, models

_previous = import_module("maru.scheduling.migrations.0008_release_dependency_guards")
_marker = "CREATE FUNCTION public.maru_scheduling_release_key_guard()"
_start = _previous.FORWARD_SQL.index(_marker)
_end_marker = "SET search_path = pg_catalog, public, pg_temp;"
_end = _previous.FORWARD_SQL.index(_end_marker, _start) + len(_end_marker)
REVERSE_SQL = _previous.FORWARD_SQL[_start:_end].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
)

_capture = r"""
        NEW.initial_source_version := 0;
        CASE NEW.kind
            WHEN 'venue_property' THEN
                SELECT aggregate_version INTO NEW.initial_source_version
                  FROM public.venues_venueproperty WHERE id = NEW.source_id;
            WHEN 'venue_selection' THEN
                SELECT aggregate_version INTO NEW.initial_source_version
                  FROM public.venues_editionspaceselection WHERE id = NEW.source_id;
            WHEN 'venue_booking' THEN
                SELECT aggregate_version INTO NEW.initial_source_version
                  FROM public.venues_venuebooking WHERE id = NEW.source_id;
            ELSE NULL;
        END CASE;
        IF NEW.initial_source_version > 0 AND NOT EXISTS (
            SELECT 1 FROM public.venues_venuecommandreceipt receipt
            WHERE receipt.result_object_id = NEW.source_id
              AND receipt.organization_id = NEW.organization_id
              AND receipt.edition_id IS NOT DISTINCT FROM NEW.edition_id
              AND receipt.resulting_version = NEW.initial_source_version
              AND receipt.operation = ANY(CASE NEW.kind
                  WHEN 'venue_property' THEN ARRAY['property.create', 'catalog.add']
                  WHEN 'venue_selection' THEN ARRAY['space.select', 'availability.set']
                  ELSE ARRAY['booking.create', 'booking.reschedule', 'booking.approve',
                             'booking.publish', 'booking.withdraw', 'booking.cancel']
                  END)
        ) THEN
            RAISE EXCEPTION 'release tracking requires a sealed native source version'
                USING ERRCODE = '23514';
        END IF;
"""
if REVERSE_SQL.count("        NEW.created_at := clock_timestamp();") != 1:
    raise RuntimeError("The frozen release key guard shape changed.")
FORWARD_SQL = REVERSE_SQL.replace(
    "        NEW.created_at := clock_timestamp();",
    _capture + "        NEW.created_at := clock_timestamp();",
).replace(
    "OR NEW.generation <> OLD.generation + 1 THEN",
    "OR NEW.initial_source_version IS DISTINCT FROM OLD.initial_source_version\n"
    "           OR NEW.generation <> OLD.generation + 1 THEN",
)


def refuse_used_baseline_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain the first-capture boundary after any source uses the new field."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(initial_source_version__gt=0).exists():
        raise RuntimeError("Sealed release source baselines exist; fix forward.")


class Migration(migrations.Migration):
    """Keep existing keys conservative while new keys capture a sealed owner version."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0010_release_approval_and_publication_schema"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.AddField(
            model_name="schedulingreleasedependencykey",
            name="initial_source_version",
            field=models.PositiveBigIntegerField(default=0, editable=False),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_baseline_downgrade),
    ]
