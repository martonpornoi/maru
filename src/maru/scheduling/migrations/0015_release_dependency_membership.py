"""Independently derive complete native release dependency membership."""

from typing import Any, ClassVar

from django.db import migrations, models

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_expected_release_dependencies(
    selected_revision uuid, review_actor uuid, organization uuid, edition uuid
) RETURNS TABLE(
    kind text, source_id uuid, placement_id uuid, horizon text,
    operational_ends_at timestamp with time zone
) AS $$
    WITH selected AS (
        SELECT placement.*, member.occurrence_id, occurrence.programme_item_id
        FROM public.scheduling_schedulingcandidaterevision revision
        JOIN public.scheduling_schedulingcandidatemember member
          ON member.revision_id = revision.id
         AND member.organization_id = organization AND member.edition_id = edition
        JOIN public.scheduling_schedulingplacementrevision placement
          ON placement.id = member.placement_id
         AND placement.organization_id = organization
         AND placement.edition_id = edition
        JOIN public.scheduling_schedulingoccurrence occurrence
          ON occurrence.id = member.occurrence_id
         AND occurrence.organization_id = organization
         AND occurrence.edition_id = edition
        WHERE revision.id = selected_revision
          AND revision.organization_id = organization AND revision.edition_id = edition
    ), copies AS (
        SELECT DISTINCT ON (copy.item_id)
            copy.id, copy.item_id, copy.reviewed_by_id
        FROM public.programme_programmepublicrendition copy
        WHERE copy.organization_id = organization AND copy.edition_id = edition
          AND copy.item_id IN (SELECT programme_item_id FROM selected)
        ORDER BY copy.item_id, copy.rendition_number DESC
    ), hosts AS (
        SELECT host.id, host.account_id, presence.placement_id, presence.ends_at
        FROM selected placement
        JOIN public.scheduling_schedulingplacementhostpresence presence
          ON presence.placement_id = placement.id
         AND presence.organization_id = organization AND presence.edition_id = edition
        JOIN public.programme_programmehostrelationship host
          ON host.id = presence.host_relationship_id
         AND host.item_id = placement.programme_item_id
         AND host.organization_id = organization AND host.edition_id = edition
    ), all_host_accounts AS (
        SELECT host.account_id
        FROM public.programme_programmehostrelationship host
        WHERE host.organization_id = organization AND host.edition_id = edition
          AND host.item_id IN (SELECT programme_item_id FROM selected)
          AND (host.state IN ('invited', 'confirmed')
               OR host.id IN (SELECT id FROM hosts))
    ), bound_demands AS (
        SELECT placement.id AS placement_id, demand.id AS demand_id
        FROM selected placement
        JOIN public.workforce_programmeshiftbinding binding
          ON binding.occurrence_id = placement.occurrence_id
         AND binding.item_id = placement.programme_item_id
         AND binding.organization_id = organization AND binding.edition_id = edition
        JOIN public.workforce_programmeshiftbindingrevision revision
          ON revision.binding_id = binding.id
         AND revision.organization_id = organization
         AND revision.edition_id = edition
        JOIN public.workforce_shiftdemand demand
          ON demand.id IN (revision.demand_id, revision.predecessor_id)
         AND demand.organization_id = organization AND demand.edition_id = edition
    ), work AS (
        SELECT DISTINCT bound.placement_id, commitment.account_id,
            commitment.position_assignment_id, commitment.availability_plan_id,
            commitment.ends_at
        FROM bound_demands bound
        JOIN public.workforce_shiftcommitment commitment
          ON commitment.demand_id = bound.demand_id
         AND commitment.organization_id = organization
         AND commitment.edition_id = edition
         AND commitment.status IN ('claimed', 'confirmed')
    ), people AS (
        SELECT account_id FROM all_host_accounts
        UNION SELECT reviewed_by_id FROM copies
        UNION SELECT account_id FROM work
        UNION SELECT review_actor WHERE EXISTS (SELECT 1 FROM selected)
    ), properties AS (
        SELECT placement.id AS placement_id, member.source_space_id,
            space.property_id
        FROM selected placement
        JOIN public.venues_editionspacemember member
          ON member.space_selection_id = placement.space_selection_id
         AND member.organization_id = organization AND member.edition_id = edition
        JOIN public.venues_venuespace space
          ON space.id = member.source_space_id AND space.organization_id = organization
    ), uses AS (
        SELECT 'identity_account'::text AS kind, account_id AS source_id,
            NULL::uuid AS placement_id, 'approval_only'::text AS horizon,
            NULL::timestamptz AS operational_ends_at
        FROM people
        UNION ALL
        SELECT 'workforce_person_obligations', account_id, NULL, 'approval_only', NULL
        FROM (SELECT account_id FROM hosts UNION SELECT account_id FROM work) person
        UNION ALL
        SELECT 'edition_operational', edition, id, 'operational', teardown_ends_at
        FROM selected
        UNION ALL
        SELECT 'programme_item', programme_item_id, id, 'operational', teardown_ends_at
        FROM selected
        UNION ALL
        SELECT 'venue_selection', space_selection_id, id, 'operational',
            teardown_ends_at
        FROM selected
        UNION ALL
        SELECT 'venue_property', property_id, properties.placement_id,
            'operational', selected.teardown_ends_at
        FROM properties JOIN selected ON selected.id = properties.placement_id
        UNION ALL
        SELECT 'venue_member', source_space_id, properties.placement_id,
            'operational', selected.teardown_ends_at
        FROM properties JOIN selected ON selected.id = properties.placement_id
        UNION ALL
        SELECT 'venue_booking', booking.id, selected.id, 'operational',
            selected.teardown_ends_at
        FROM selected
        JOIN public.venues_venueschedulingbinding binding
          ON binding.placement_id = selected.id
         AND binding.occurrence_id = selected.occurrence_id
         AND binding.organization_id = organization AND binding.edition_id = edition
        JOIN public.venues_venuebooking booking ON booking.id = binding.booking_id
         AND booking.space_selection_id = selected.space_selection_id
         AND booking.organization_id = organization AND booking.edition_id = edition
         AND booking.lifecycle = 'active'
        UNION ALL
        SELECT 'programme_public_copy', copies.id, selected.id, 'disclosure', NULL
        FROM selected JOIN copies ON copies.item_id = selected.programme_item_id
        UNION ALL
        SELECT 'programme_host_operational', id, placement_id, 'operational', ends_at
        FROM hosts
        UNION ALL
        SELECT 'identity_account', account_id, placement_id, 'operational', ends_at
        FROM hosts
        UNION ALL
        SELECT 'programme_host_disclosure', id, placement_id, 'disclosure', NULL
        FROM hosts
        UNION ALL
        SELECT 'workforce_demand', bound.demand_id, bound.placement_id,
            'operational', selected.teardown_ends_at
        FROM bound_demands bound JOIN selected ON selected.id = bound.placement_id
        UNION ALL
        SELECT 'identity_account', account_id, placement_id, 'operational', ends_at
        FROM work
        UNION ALL
        SELECT 'workforce_assignment', position_assignment_id, placement_id,
            'operational', ends_at FROM work
        UNION ALL
        SELECT 'workforce_availability', availability_plan_id, placement_id,
            'operational', ends_at FROM work
    )
    SELECT kind, source_id, placement_id, horizon, max(operational_ends_at)
    FROM uses
    GROUP BY kind, source_id, placement_id, horizon;
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_scheduling_expected_release_dependencies(
    uuid, uuid, uuid, uuid
) FROM PUBLIC;
"""
REVERSE_SQL = r"""
DROP FUNCTION public.maru_scheduling_expected_release_dependencies(
    uuid, uuid, uuid, uuid
);
"""


def refuse_used_release_membership_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain the complete membership contract after the first approval."""
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleaseapproval "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("scheduling", "SchedulingReleaseApproval").objects.exists():
        raise RuntimeError("Retained release approvals exist; fix forward.")


class Migration(migrations.Migration):
    """Bound complete approval dependencies and prepare owner-only graph validation."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0014_person_obligation_native_source"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RemoveConstraint(
            model_name="schedulingreleaseapproval", name="sch_release_approval_deps"
        ),
        migrations.AddConstraint(
            model_name="schedulingreleaseapproval",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    dependency_count__gte=1, dependency_count__lte=65_536
                ),
                name="sch_release_approval_deps",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_release_membership_downgrade
        ),
    ]
