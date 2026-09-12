"""Expose only minimized operative-host consequences, not foreign calendars."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_published_person_conflict(
    person uuid, starts timestamptz, ends timestamptz, rest_ends timestamptz,
    replaced_edition uuid
) RETURNS TABLE(has_overlap boolean, has_rest_conflict boolean, evidence_digest text)
AS $$
BEGIN
    IF person IS NULL OR starts IS NULL OR ends IS NULL OR rest_ends IS NULL
       OR NOT starts < ends OR NOT ends <= rest_ends
       OR NOT isfinite(starts) OR NOT isfinite(ends) OR NOT isfinite(rest_ends) THEN
        RAISE EXCEPTION 'Exact bounded person-obligation input is required'
          USING ERRCODE = '23514';
    END IF;
    RETURN QUERY
    WITH retained AS MATERIALIZED (
        SELECT presence.id, presence.starts_at, presence.ends_at,
            release.id AS release_id, pointer.active_release_id,
            pointer.version AS pointer_version, host.version AS host_version,
            host.state AS host_state
        FROM public.programme_programmehostrelationship host
        JOIN public.scheduling_schedulingplacementhostpresence presence
          ON presence.host_relationship_id = host.id
         AND presence.organization_id = host.organization_id
         AND presence.edition_id = host.edition_id
        JOIN public.scheduling_schedulingreleaseapprovalplacement selection
          ON selection.placement_id = presence.placement_id
         AND selection.organization_id = presence.organization_id
         AND selection.edition_id = presence.edition_id
        JOIN public.scheduling_schedulingrelease release
          ON release.approval_id = selection.approval_id
         AND release.organization_id = selection.organization_id
         AND release.edition_id = selection.edition_id
        JOIN public.scheduling_schedulingreleasepointer pointer
          ON pointer.edition_id = release.edition_id
         AND pointer.organization_id = release.organization_id
        WHERE host.account_id = person
          AND (replaced_edition IS NULL OR release.edition_id <> replaced_edition)
        ORDER BY release.id, presence.id
        LIMIT 10001
    ), aggregate AS (
        SELECT count(*) AS count,
            coalesce(bool_or(
                active_release_id = release_id AND host_state = 'confirmed'
                AND starts_at < ends AND ends_at > starts
            ), FALSE) AS overlap,
            coalesce(bool_or(
                active_release_id = release_id AND host_state = 'confirmed'
                AND ends <= starts_at AND starts_at < rest_ends
            ), FALSE) AS rest,
            coalesce(string_agg(
                release_id::text || ':' || id::text || ':' || pointer_version::text
                || ':' || host_version::text || ':' || host_state,
                ',' ORDER BY release_id, id
            ), '') AS fingerprint
        FROM retained
    )
    SELECT CASE WHEN count > 10000 THEN NULL::boolean ELSE overlap END,
        CASE WHEN count > 10000 THEN NULL::boolean ELSE rest END,
        CASE WHEN count > 10000 THEN NULL::text
             ELSE encode(sha256(convert_to(fingerprint, 'UTF8')), 'hex') END
    FROM aggregate;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_scheduling_published_person_conflict(
    uuid, timestamptz, timestamptz, timestamptz, uuid) FROM PUBLIC;
"""
REVERSE_SQL = """
DROP FUNCTION public.maru_scheduling_published_person_conflict(
    uuid, timestamptz, timestamptz, timestamptz, uuid);
"""


def refuse_published_person_source_downgrade(apps: Any, schema_editor: Any) -> None:
    """Preserve reciprocal protection once a retained release can own host time."""
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingrelease IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("scheduling", "SchedulingRelease").objects.exists():
        raise RuntimeError("Published person obligations exist; fix forward.")


class Migration(migrations.Migration):
    """Add an owner-only read seam without runtime or profile activation."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0017_atomic_release_graph"),
        ("programme", "0019_public_copy_withdrawal_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_published_person_source_downgrade
        ),
    ]
