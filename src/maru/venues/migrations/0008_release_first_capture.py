"""Do not invalidate a first capture for a native change already included in it."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations


def _definition(module: str, name: str) -> str:
    statement = import_module(module).FORWARD_SQL
    start = statement.index(f"CREATE FUNCTION public.{name}()")
    ending = "SET search_path = pg_catalog, public, pg_temp;"
    end = statement.index(ending, start) + len(ending)
    return statement[start:end].replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )


_source = _definition(
    "maru.venues.migrations.0006_release_dependency_mutations",
    "maru_venues_release_source_guard",
)
_auxiliary = _definition(
    "maru.venues.migrations.0007_release_physical_closure",
    "maru_venues_release_auxiliary_guard",
)
REVERSE_SQL = _source + "\n" + _auxiliary

_version_guard = r"""
    IF TG_WHEN = 'BEFORE' AND EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = TG_ARGV[0] AND source_id = OLD.id
          AND initial_source_version > 0
    ) AND (NEW.aggregate_version < OLD.aggregate_version OR
           (cardinality(required_fields) > 0 AND
            NEW.aggregate_version <> OLD.aggregate_version + 1)) THEN
        RAISE EXCEPTION 'tracked operational source requires one new native version'
            USING ERRCODE = '23514';
    END IF;
"""
_source_baseline = r"""
    -- Earlier native versions in this transaction preceded first capture.
    -- New updates cannot reuse them: the BEFORE guard enforces monotonicity
    -- and first tracking itself requires the completed current native receipt.
    IF EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = TG_ARGV[0] AND source_id = OLD.id
          AND initial_source_version >= NEW.aggregate_version
          AND initial_source_version > 0
    ) THEN RETURN NULL; END IF;
"""
if (
    _source.count("    IF cardinality(required_fields) = 0") != 1
    or _source.count("    SELECT id INTO tracked_dependency_id") != 1
):
    raise RuntimeError("The frozen native Venue source guard shape changed.")
_source = _source.replace(
    "    IF cardinality(required_fields) = 0",
    _version_guard + "    IF cardinality(required_fields) = 0",
).replace(
    "    SELECT id INTO tracked_dependency_id",
    _source_baseline + "    SELECT id INTO tracked_dependency_id",
)

_auxiliary_baseline = r"""
    IF EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencykey
        WHERE id = tracked_dependency_id
          AND initial_source_version = owner_version AND initial_source_version > 0
    ) THEN RETURN NULL; END IF;
"""
if _auxiliary.count("    IF NOT EXISTS (") != 1:
    raise RuntimeError("The frozen auxiliary Venue source guard shape changed.")
_auxiliary = _auxiliary.replace(
    "    IF NOT EXISTS (", _auxiliary_baseline + "    IF NOT EXISTS ("
)
FORWARD_SQL = _source + "\n" + _auxiliary


def refuse_used_first_capture_downgrade(apps: Any, schema_editor: Any) -> None:
    """Preserve the tracked source version guards after first-capture use."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(initial_source_version__gt=0).exists():
        raise RuntimeError(
            "Venue release baselines exist; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Keep pre-capture versions current and post-capture changes journal-governed."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("venues", "0007_release_physical_closure"),
        ("scheduling", "0011_release_source_baseline"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_first_capture_downgrade
        ),
    ]
