"""Serialize release replacement with reciprocal global host and volunteer work."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module("maru.scheduling.migrations.0017_atomic_release_graph")
_start = _previous.FORWARD_SQL.index(
    "CREATE FUNCTION public.maru_scheduling_release_pointer_guard()"
)
_end_marker = "SET search_path = pg_catalog, public, pg_temp;"
_end = _previous.FORWARD_SQL.index(_end_marker, _start) + len(_end_marker)
_original = _previous.FORWARD_SQL[_start:_end].replace(
    "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
)
_marker = "    RETURN NEW;"
if _original.count(_marker) != 1:
    raise RuntimeError("The frozen release-pointer guard changed.")
_person_check = r"""
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Published person obligations require READ COMMITTED'
          USING ERRCODE = '23514';
    END IF;
    -- Native commands hold the complete new AND replaced person union already.
    -- Raw writers cannot wait here while retaining a narrower pointer lock.
    PERFORM person.id FROM public.identity_account person
    WHERE person.id IN (
        SELECT dependency.source_id
        FROM public.scheduling_schedulingreleasedependencykey dependency
        JOIN public.scheduling_schedulingreleaseapprovaldependency capture
          ON capture.dependency_id = dependency.id
        JOIN public.scheduling_schedulingrelease selected
          ON selected.approval_id = capture.approval_id
         AND selected.organization_id = NEW.organization_id
         AND selected.edition_id = NEW.edition_id
        WHERE dependency.kind = 'identity_account'
          AND selected.id IN (
              NEW.active_release_id,
              CASE WHEN TG_OP = 'UPDATE' THEN OLD.active_release_id ELSE NULL END
          )
    ) ORDER BY person.id FOR UPDATE NOWAIT;
    IF NEW.active_release_id IS NOT NULL AND
       public.maru_scheduling_release_person_obligations_valid(
           NEW.active_release_id) IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'Release conflicts with operative person work or rest'
          USING ERRCODE = '23514';
    END IF;
    RETURN NEW;"""

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_release_person_obligations_valid(selected uuid)
RETURNS boolean AS $$
BEGIN
    RETURN (
        WITH release AS (
            SELECT id, approval_id, organization_id, edition_id
            FROM public.scheduling_schedulingrelease WHERE id = selected
        ), placements AS (
            SELECT placement.* FROM release
            JOIN public.scheduling_schedulingreleaseapprovalplacement placement
              ON placement.approval_id = release.approval_id
             AND placement.organization_id = release.organization_id
             AND placement.edition_id = release.edition_id
        ), hosts AS (
            SELECT presence.id, placement.occurrence_id, placement.edition_id,
                host.account_id, presence.starts_at, presence.ends_at
            FROM placements placement
            JOIN public.scheduling_schedulingplacementhostpresence presence
              ON presence.placement_id = placement.placement_id
             AND presence.organization_id = placement.organization_id
             AND presence.edition_id = placement.edition_id
            JOIN public.programme_programmehostrelationship host
              ON host.id = presence.host_relationship_id
             AND host.organization_id = presence.organization_id
             AND host.edition_id = presence.edition_id
        ), demands AS (
            SELECT DISTINCT dependency.source_id, release.edition_id,
                release.organization_id
            FROM release
            JOIN public.scheduling_schedulingreleaseapprovaldependency capture
              ON capture.approval_id = release.approval_id
             AND capture.organization_id = release.organization_id
             AND capture.edition_id = release.edition_id
            JOIN public.scheduling_schedulingreleasedependencykey dependency
              ON dependency.id = capture.dependency_id
             AND dependency.kind = 'workforce_demand'
        ), selected_work AS (
            SELECT commitment.* FROM demands
            JOIN public.workforce_shiftcommitment commitment
              ON commitment.demand_id = demands.source_id
             AND commitment.organization_id = demands.organization_id
             AND commitment.edition_id = demands.edition_id
             AND commitment.status IN ('claimed', 'confirmed')
        )
        SELECT EXISTS (SELECT 1 FROM release)
          AND NOT EXISTS (
            SELECT 1 FROM hosts host
            JOIN public.workforce_shiftcommitment work
              ON work.account_id = host.account_id
             AND work.status IN ('claimed', 'confirmed')
             AND work.starts_at < host.ends_at AND work.rest_ends_at > host.starts_at
          )
          AND NOT EXISTS (
            SELECT 1 FROM hosts left_host JOIN hosts right_host
              ON left_host.account_id = right_host.account_id
             AND left_host.occurrence_id <> right_host.occurrence_id
             AND left_host.starts_at < right_host.ends_at
             AND right_host.starts_at < left_host.ends_at
          )
          AND NOT EXISTS (
            SELECT 1 FROM hosts host
            CROSS JOIN LATERAL public.maru_scheduling_published_person_conflict(
                host.account_id, host.starts_at, host.ends_at, host.ends_at,
                host.edition_id
            ) consequence
            WHERE consequence.has_overlap IS DISTINCT FROM FALSE
               OR consequence.has_rest_conflict IS DISTINCT FROM FALSE
               OR consequence.evidence_digest IS NULL
          )
          AND NOT EXISTS (
            SELECT 1 FROM selected_work work
            CROSS JOIN LATERAL public.maru_scheduling_published_person_conflict(
                work.account_id, work.starts_at, work.ends_at, work.rest_ends_at,
                work.edition_id
            ) consequence
            WHERE consequence.has_overlap IS DISTINCT FROM FALSE
               OR consequence.has_rest_conflict IS DISTINCT FROM FALSE
               OR consequence.evidence_digest IS NULL
          )
    );
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
public.maru_scheduling_release_person_obligations_valid(uuid) FROM PUBLIC;
""" + _original.replace(_marker, _person_check)  # noqa: S608 - frozen code-owned SQL
REVERSE_SQL = (
    _original
    + """
DROP FUNCTION public.maru_scheduling_release_person_obligations_valid(uuid);
"""
)


def refuse_used_person_guard_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep reciprocal native protection for every retained published release."""
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingrelease IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("scheduling", "SchedulingRelease").objects.exists():
        raise RuntimeError("Published person obligations exist; fix forward.")


class Migration(migrations.Migration):
    """Add reciprocal checks without a broad mutex or foreign edition locks."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0018_published_person_conflict_source"),
        ("workforce", "0024_published_host_obligation_guard"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_person_guard_downgrade
        ),
    ]
