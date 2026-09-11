"""Protect auxiliary physical facts behind their release-tracked owner rows."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_venues_release_auxiliary_guard()
RETURNS trigger AS $$
DECLARE
    owner_id uuid;
    owner_organization uuid;
    owner_edition uuid;
    owner_version bigint;
    availability_version bigint;
    dependency_kind text;
    tracked_dependency_id uuid;
    record_values jsonb := to_jsonb(NEW);
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Venue release physical writes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF TG_ARGV[0] = 'occupancy' THEN
        dependency_kind := 'venue_booking';
        SELECT id, organization_id, edition_id, aggregate_version
          INTO owner_id, owner_organization, owner_edition, owner_version
          FROM public.venues_venuebooking WHERE id = NEW.booking_id FOR UPDATE;
    ELSE
        dependency_kind := 'venue_selection';
        SELECT id, organization_id, edition_id, aggregate_version,
               current_availability_version
          INTO owner_id, owner_organization, owner_edition, owner_version,
               availability_version
          FROM public.venues_editionspaceselection
          WHERE id = NEW.space_selection_id FOR UPDATE;
    END IF;
    SELECT id INTO tracked_dependency_id
      FROM public.scheduling_schedulingreleasedependencykey
      WHERE kind = dependency_kind AND source_id = owner_id;
    IF tracked_dependency_id IS NULL THEN RETURN NEW; END IF;
    IF TG_ARGV[0] = 'member' THEN
        RAISE EXCEPTION 'tracked physical membership requires a new native contract'
            USING ERRCODE = '23514';
    END IF;
    IF (owner_organization, owner_edition) IS DISTINCT FROM
       (NEW.organization_id, NEW.edition_id) THEN
        RAISE EXCEPTION 'tracked physical fact requires exact owner scope'
            USING ERRCODE = '23514';
    END IF;
    IF TG_WHEN = 'BEFORE' THEN
        IF TG_ARGV[0] = 'availability' AND
           (record_values->>'availability_version')::bigint <>
               availability_version THEN
            RAISE EXCEPTION 'tracked availability requires the new owner version'
                USING ERRCODE = '23514';
        END IF;
        -- The native command changes its parent before auxiliary rows and
        -- seals its receipt afterwards. Even a same-transaction append after
        -- that seal cannot alter the already journaled version underneath a
        -- later approval/publication. A new version needs a new native journal.
        IF EXISTS (
            SELECT 1 FROM public.venues_venuecommandreceipt receipt
            WHERE receipt.result_object_id = owner_id
              AND receipt.resulting_version = owner_version
              AND receipt.organization_id = owner_organization
              AND receipt.edition_id = owner_edition
              AND receipt.operation IN (
                  'availability.set', 'booking.create', 'booking.reschedule',
                  'booking.approve', 'booking.publish', 'booking.withdraw',
                  'booking.cancel')
        ) THEN
            RAISE EXCEPTION 'sealed physical source version cannot gain raw changes'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = change.source_audit_id
        CROSS JOIN LATERAL
            public.maru_venues_release_mutation_sources(witness.audit_event_id) ref
        WHERE change.dependency_id = tracked_dependency_id
          AND witness.transaction_stamp =
              public.maru_audit_current_native_transaction_stamp()
          AND ref.source_id = owner_id AND ref.kind = dependency_kind
          AND ref.organization_id = owner_organization
          AND ref.edition_id = owner_edition
          AND ref.resulting_version = owner_version
    ) THEN
        RAISE EXCEPTION 'physical source requires its current native release journal'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_venues_release_selected_parent_guard()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND
       (NEW.id, NEW.organization_id, NEW.edition_id, NEW.property_id,
        NEW.responsible_department_id, NEW.lifecycle) IS NOT DISTINCT FROM
       (OLD.id, OLD.organization_id, OLD.edition_id, OLD.property_id,
        OLD.responsible_department_id, OLD.lifecycle) THEN RETURN NEW; END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Venue release selected-parent writes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    -- First tracking locks the same native selections. No foreign release
    -- pointer is read, discovered or locked by this fail-closed owner guard.
    PERFORM id FROM public.venues_editionspaceselection
      WHERE venue_selection_id = OLD.id ORDER BY id FOR UPDATE;
    IF EXISTS (
        SELECT 1 FROM public.venues_editionspaceselection selection
        JOIN public.scheduling_schedulingreleasedependencykey dependency
          ON dependency.kind = 'venue_selection'
         AND dependency.source_id = selection.id
        WHERE selection.venue_selection_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'tracked selected venue requires a new native contract'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER venue_release_selected_parent
BEFORE UPDATE OR DELETE ON public.venues_editionvenueselection
FOR EACH ROW EXECUTE FUNCTION public.maru_venues_release_selected_parent_guard();
CREATE TRIGGER venue_release_physical_member
BEFORE INSERT ON public.venues_editionspacemember
FOR EACH ROW EXECUTE FUNCTION public.maru_venues_release_auxiliary_guard('member');
"""

AUXILIARY = (
    ("availability", "venues_editionspaceavailabilitywindow", "INSERT"),
    ("occupancy", "venues_venuebookingoccupancy", "INSERT OR UPDATE"),
)
for kind, table, operations in AUXILIARY:
    FORWARD_SQL += f"""
CREATE TRIGGER venue_release_{kind}_shape
BEFORE {operations} ON public.{table}
FOR EACH ROW EXECUTE FUNCTION
    public.maru_venues_release_auxiliary_guard('{kind}');
CREATE CONSTRAINT TRIGGER venue_release_{kind}_evidence
AFTER {operations} ON public.{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
    public.maru_venues_release_auxiliary_guard('{kind}');
"""

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER venue_release_{kind}_{suffix} ON public.{table};"
        for kind, table, _ in reversed(AUXILIARY)
        for suffix in ("evidence", "shape")
    )
    + r"""
DROP TRIGGER venue_release_physical_member ON public.venues_editionspacemember;
DROP TRIGGER venue_release_selected_parent ON public.venues_editionvenueselection;
DROP FUNCTION public.maru_venues_release_selected_parent_guard();
DROP FUNCTION public.maru_venues_release_auxiliary_guard();
"""
)


def refuse_tracked_physical_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain auxiliary physical guards after a Venue release source is used."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(kind__startswith="venue_").exists():
        raise RuntimeError("Tracked physical release sources exist; fix forward.")


class Migration(migrations.Migration):
    """Keep membership, current windows and occupancy behind native source seals."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("venues", "0006_release_dependency_mutations"),
        ("scheduling", "0009_native_release_journal_writer"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_physical_downgrade
        ),
    ]
