"""Permit native invalidation without general runtime Scheduling writes."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_record_native_release_change(
    dependency_kind text, source uuid, audit_id uuid
) RETURNS void AS $$
DECLARE
    dependency public.scheduling_schedulingreleasedependencykey%ROWTYPE;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'native release journal requires READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO dependency
      FROM public.scheduling_schedulingreleasedependencykey
      WHERE kind = dependency_kind AND source_id = source;
    -- No tracking is created by an owner change. First tracking instead locks
    -- that same owner row, then captures its current source state/generation.
    IF dependency.id IS NULL THEN RETURN; END IF;
    IF public.maru_scheduling_release_native_change_valid(
        dependency.kind, dependency.source_id, dependency.organization_id,
        dependency.edition_id, audit_id
    ) IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'exact current native mutation is required'
            USING ERRCODE = '23514';
    END IF;
    IF public.maru_scheduling_lock_release_source(
        dependency.kind, dependency.source_id,
        dependency.organization_id, dependency.edition_id
    ) IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'exact locked native source is required'
            USING ERRCODE = '23514';
    END IF;
    SELECT * INTO dependency
      FROM public.scheduling_schedulingreleasedependencykey
      WHERE kind = dependency_kind AND source_id = source FOR UPDATE;
    IF dependency.id IS NULL OR
       public.maru_scheduling_release_native_change_valid(
           dependency.kind, dependency.source_id, dependency.organization_id,
           dependency.edition_id, audit_id
       ) IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'exact current native mutation is required'
            USING ERRCODE = '23514';
    END IF;
    -- Multiple native receipt paths may report the same exact consequence.
    -- A historical audit cannot reach this branch: proof was checked above.
    IF EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencychange
        WHERE dependency_id = dependency.id AND source_audit_id = audit_id
    ) THEN RETURN; END IF;
    UPDATE public.scheduling_schedulingreleasedependencykey
       SET generation = generation + 1
       WHERE id = dependency.id;
    INSERT INTO public.scheduling_schedulingreleasedependencychange
        (id, created_at, updated_at, organization_id, edition_id,
         dependency_id, generation, source_audit_id, recorded_at)
    VALUES (gen_random_uuid(), clock_timestamp(), clock_timestamp(),
            dependency.organization_id, dependency.edition_id, dependency.id,
            dependency.generation + 1, audit_id, clock_timestamp());
END;
$$ LANGUAGE plpgsql VOLATILE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_scheduling_record_native_release_change(text, uuid, uuid)
    FROM PUBLIC;
"""

REVERSE_SQL = """
DROP FUNCTION public.maru_scheduling_record_native_release_change(text, uuid, uuid);
"""


def refuse_tracked_native_join_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain the runtime join after any release dependency has been tracked."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.exists():
        raise RuntimeError(
            "Release sources exist; retain native writer and fix forward."
        )


class Migration(migrations.Migration):
    """Close all owner proofs before enabling the narrow native journal writer."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0008_release_dependency_guards"),
        ("identity", "0021_release_dependency_deactivation"),
        ("programme", "0016_release_dependency_mutations"),
        ("workforce", "0022_release_dependency_mutations"),
        ("events", "0011_release_dependency_mutations"),
        ("venues", "0006_release_dependency_mutations"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_native_join_downgrade
        ),
    ]
