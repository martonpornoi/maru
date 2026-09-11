"""Join native Venue physical changes to retained release source generations."""

from typing import Any, ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_venues_release_mutation_sources(audit_id uuid)
RETURNS TABLE(receipt_id uuid, kind text, source_id uuid, organization_id uuid,
              edition_id uuid, resulting_version bigint) AS $$
    SELECT receipt.id,
           CASE event.target_type
               WHEN 'venues.property' THEN 'venue_property'
               WHEN 'venues.edition_space' THEN 'venue_selection'
               WHEN 'venues.booking' THEN 'venue_booking'
           END,
           receipt.result_object_id, receipt.organization_id, receipt.edition_id,
           receipt.resulting_version
    FROM public.venues_venuecommandreceipt receipt
    JOIN public.audit_auditevent event
      ON event.id = audit_id AND event.outcome = 'allow'
     AND event.principal_kind = 'account' AND event.principal_context_id IS NULL
     AND event.principal_id = receipt.actor_id
     AND event.target_id = receipt.result_object_id
     AND event.organization_id = receipt.organization_id
     AND event.event_edition_id IS NOT DISTINCT FROM receipt.edition_id
     AND event.operation = 'venues.' || receipt.operation
     AND event.correlation_id = receipt.correlation_id
     AND event.source_channel = receipt.source_channel
     AND event.idempotency_key_hash = encode(
         sha256(convert_to(receipt.idempotency_key::text, 'UTF8')), 'hex')
    WHERE (event.target_type = 'venues.property' AND receipt.edition_id IS NULL
           AND receipt.operation = 'catalog.add'
           AND event.changed_fields && ARRAY[
               'lifecycle', 'location_name',
               'postal_address', 'country_code']::varchar[])
       OR (event.target_type = 'venues.edition_space' AND receipt.edition_id IS NOT NULL
           AND receipt.operation = 'availability.set'
           AND event.changed_fields @> ARRAY[
               'current_availability_version', 'availability_windows']::varchar[])
       OR (event.target_type = 'venues.booking' AND receipt.edition_id IS NOT NULL
           AND receipt.operation IN (
               'booking.reschedule', 'booking.approve', 'booking.cancel'));
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_venues_release_change_valid(
    dependency_kind text, source uuid, organization uuid, edition uuid, audit_id uuid
) RETURNS boolean AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.maru_venues_release_mutation_sources(audit_id) reference
        WHERE reference.kind = dependency_kind AND reference.source_id = source
          AND reference.organization_id = organization
          AND reference.edition_id IS NOT DISTINCT FROM edition
    );
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_venues_release_source_guard()
RETURNS trigger AS $$
DECLARE
    old_values jsonb := to_jsonb(OLD);
    new_values jsonb := to_jsonb(NEW);
    field_name text;
    required_fields varchar[] := ARRAY[]::varchar[];
    tracked_dependency_id uuid;
BEGIN
    FOREACH field_name IN ARRAY TG_ARGV[1:] LOOP
        IF old_values->field_name IS DISTINCT FROM new_values->field_name THEN
            required_fields := array_append(required_fields, CASE
                WHEN TG_ARGV[0] = 'venue_booking' AND field_name IN
                    ('setup_starts_at', 'effective_starts_at',
                     'effective_ends_at', 'teardown_ends_at') THEN 'schedule'
                WHEN TG_ARGV[0] = 'venue_booking' AND field_name IN
                    ('capacity_mode', 'expected_attendance') THEN 'capacity'
                WHEN TG_ARGV[0] = 'venue_booking' AND field_name IN
                    ('approved_by_id', 'approved_at') THEN 'review_state'
                ELSE field_name END);
        END IF;
    END LOOP;
    IF cardinality(required_fields) = 0 THEN RETURN NEW; END IF;
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Venue release source writes require READ COMMITTED'
            USING ERRCODE = '23514';
    END IF;
    IF TG_WHEN = 'BEFORE' THEN RETURN NEW; END IF;
    SELECT id INTO tracked_dependency_id
        FROM public.scheduling_schedulingreleasedependencykey
        WHERE kind = TG_ARGV[0] AND source_id = OLD.id;
    IF tracked_dependency_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingreleasedependencychange change
        JOIN public.audit_auditnativemutationwitness witness
          ON witness.audit_event_id = change.source_audit_id
        JOIN public.audit_auditevent event ON event.id = witness.audit_event_id
        CROSS JOIN LATERAL
            public.maru_venues_release_mutation_sources(event.id) reference
        WHERE change.dependency_id = tracked_dependency_id
          AND witness.transaction_stamp =
              public.maru_audit_current_native_transaction_stamp()
          AND reference.kind = TG_ARGV[0] AND reference.source_id = OLD.id
          AND reference.resulting_version = NEW.aggregate_version
          AND reference.organization_id = NEW.organization_id
          AND reference.edition_id IS NOT DISTINCT FROM
              (new_values->>'edition_id')::uuid
          AND event.changed_fields @> required_fields
    ) THEN
        RAISE EXCEPTION
            'Venue source change requires its exact native release invalidation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
"""

# Unsupported catalog edits fail closed once tracked; adding a native owner
# command later must explicitly define its physical receipt/evidence contract.
SOURCES = (
    (
        "venue_property",
        "venues_venueproperty",
        (
            "lifecycle",
            "location_name",
            "postal_address",
            "country_code",
        ),
    ),
    (
        "venue_member",
        "venues_venuespace",
        (
            "property_id",
            "site_id",
            "building_id",
            "kind",
            "is_active",
            "accessibility_features",
            "known_barriers",
            "equipment_facts",
        ),
    ),
    (
        "venue_selection",
        "venues_editionspaceselection",
        (
            "venue_selection_id",
            "responsible_department_id",
            "source_space_id",
            "source_combination_id",
            "selected_configuration_id",
            "seated_capacity",
            "standing_capacity",
            "table_capacity",
            "fire_capacity",
            "public_access_info",
            "opening_restrictions",
            "current_availability_version",
            "lifecycle",
        ),
    ),
    (
        "venue_booking",
        "venues_venuebooking",
        (
            "space_selection_id",
            "responsible_department_id",
            "capacity_mode",
            "expected_attendance",
            "setup_starts_at",
            "effective_starts_at",
            "effective_ends_at",
            "teardown_ends_at",
            "lifecycle",
            "review_state",
            "approved_by_id",
            "approved_at",
        ),
    ),
)
for kind, table, fields in SOURCES:
    arguments = ", ".join(f"'{value}'" for value in (kind, *fields))
    FORWARD_SQL += f"""
CREATE TRIGGER {kind}_release_identity
BEFORE UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION
    public.maru_scheduling_release_source_identity_guard('{kind}');
CREATE TRIGGER {kind}_release_isolation
BEFORE UPDATE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_venues_release_source_guard({arguments});
CREATE CONSTRAINT TRIGGER {kind}_release_evidence
AFTER UPDATE ON public.{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_venues_release_source_guard({arguments});
"""

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER {kind}_release_{suffix} ON public.{table};"
        for kind, table, _ in reversed(SOURCES)
        for suffix in ("evidence", "isolation", "identity")
    )
    + r"""
DROP FUNCTION public.maru_venues_release_source_guard();
DROP FUNCTION public.maru_venues_release_change_valid(text, uuid, uuid, uuid, uuid);
DROP FUNCTION public.maru_venues_release_mutation_sources(uuid);
"""
)


def refuse_tracked_venue_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep native physical consequences after any Venue source is tracked."""
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    schema_editor.execute(
        "LOCK TABLE public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if key.objects.filter(kind__startswith="venue_").exists():
        raise RuntimeError(
            "Release-tracked Venue sources exist; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Require exact native consequences without coupling publication surfaces."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("venues", "0005_scheduling_downgrade_fence"),
        ("scheduling", "0008_release_dependency_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop, refuse_tracked_venue_downgrade),
    ]
