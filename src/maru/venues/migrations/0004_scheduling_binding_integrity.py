"""Keep physical reservations reciprocal, independently approved and unpublished."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_guard_venue_scheduling_binding()
RETURNS trigger AS $$
DECLARE
    intent public.scheduling_schedulingreservationintent%ROWTYPE;
    placement public.scheduling_schedulingplacementrevision%ROWTYPE;
    booking public.venues_venuebooking%ROWTYPE;
    selection public.venues_editionspaceselection%ROWTYPE;
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        IF public.maru_authority_provenance_test_reset_allowed() THEN RETURN NULL; END IF;
        RAISE EXCEPTION 'Venue Scheduling bindings cannot be truncated' USING ERRCODE = '23514';
    END IF;
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Venue Scheduling bindings are immutable' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.events_eventedition
        WHERE id = NEW.edition_id AND organization_id = NEW.organization_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Venue Scheduling binding scope is unavailable' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT intent FROM public.scheduling_schedulingreservationintent WHERE id = NEW.source_intent_id;
    SELECT * INTO STRICT placement FROM public.scheduling_schedulingplacementrevision WHERE id = NEW.placement_id;
    SELECT * INTO STRICT booking FROM public.venues_venuebooking WHERE id = NEW.booking_id;
    IF intent.operation <> 'reservation_replace' OR intent.target_booking_id IS DISTINCT FROM NEW.booking_id
       OR (intent.organization_id, intent.edition_id, intent.occurrence_id, intent.placement_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, NEW.occurrence_id, NEW.placement_id)
       OR (placement.organization_id, placement.edition_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id)
       OR NEW.occurrence_id IS DISTINCT FROM (
            SELECT occurrence_id FROM public.scheduling_schedulingoccurrencerevision WHERE id = placement.occurrence_revision_id)
       OR NEW.source_actor_id IS DISTINCT FROM (
            SELECT actor_id FROM public.scheduling_schedulingcandidaterevision WHERE id = placement.introduced_in_id)
       OR (booking.organization_id, booking.edition_id, booking.created_by_id, booking.last_modified_by_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, intent.actor_id, intent.actor_id)
       OR booking.aggregate_version <> 1 OR booking.lifecycle <> 'active' OR booking.review_state <> 'draft'
       OR booking.approved_by_id IS NOT NULL OR booking.approved_at IS NOT NULL
       OR booking.kind <> 'programme' OR booking.internal_title <> 'Programme reservation'
       OR booking.external_reference <> '' OR booking.public_title <> '' OR booking.public_description <> ''
       OR booking.publication_state <> 'unpublished' OR booking.public_layout_id IS NOT NULL
       OR booking.published_by_id IS NOT NULL OR booking.published_at IS NOT NULL
       OR (booking.space_selection_id, booking.setup_starts_at, booking.effective_starts_at,
           booking.effective_ends_at, booking.teardown_ends_at, booking.capacity_mode, booking.expected_attendance)
          IS DISTINCT FROM (placement.space_selection_id, placement.setup_starts_at, placement.effective_starts_at,
           placement.effective_ends_at, placement.teardown_ends_at, placement.capacity_mode, placement.expected_attendance)
    THEN
        RAISE EXCEPTION 'Venue binding requires its exact newly reserved placement' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingcandidatemember member
        JOIN public.scheduling_schedulingcandidaterevision revision ON revision.id = member.revision_id
        JOIN public.scheduling_schedulingcandidate candidate ON candidate.id = revision.candidate_id
        JOIN public.scheduling_schedulingoccurrencerevision occurrence_revision ON occurrence_revision.id = placement.occurrence_revision_id
        JOIN public.scheduling_schedulingoccurrence occurrence ON occurrence.id = occurrence_revision.occurrence_id
        JOIN public.scheduling_schedulingservicedayrevision day_revision ON day_revision.id = placement.day_revision_id
        JOIN public.scheduling_schedulingserviceday day ON day.id = day_revision.day_id
        JOIN public.events_eventedition edition ON edition.id = NEW.edition_id
        WHERE member.revision_id = intent.candidate_revision_id AND member.occurrence_id = NEW.occurrence_id AND member.placement_id = NEW.placement_id
          AND candidate.lifecycle = 'draft' AND candidate.aggregate_version = revision.sequence
          AND occurrence.lifecycle = 'active' AND occurrence.aggregate_version = occurrence_revision.sequence
          AND day.lifecycle = 'active' AND day.aggregate_version = day_revision.sequence
          AND day_revision.starts_at >= edition.starts_on::timestamp AT TIME ZONE edition.time_zone
          AND day_revision.ends_at <= (edition.ends_on + 1)::timestamp AT TIME ZONE edition.time_zone
          AND placement.setup_starts_at >= day_revision.starts_at AND placement.teardown_ends_at <= day_revision.ends_at
          AND NOT EXISTS (SELECT 1 FROM unnest(ARRAY[placement.setup_starts_at, placement.effective_starts_at,
              placement.effective_ends_at, placement.teardown_ends_at]) boundary(value)
              WHERE mod(extract(epoch FROM boundary.value - day_revision.starts_at), day_revision.precision_minutes * 60) <> 0)
    ) THEN
        RAISE EXCEPTION 'Venue reservation requires current candidate, occurrence and service-day intent' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.identity_account WHERE id IN (NEW.source_actor_id, intent.actor_id) ORDER BY id FOR UPDATE;
    IF EXISTS (SELECT 1 FROM public.identity_account WHERE id IN (NEW.source_actor_id, intent.actor_id)
        AND (NOT is_active OR email_verified_at IS NULL OR account_kind <> 'person')) THEN
        RAISE EXCEPTION 'Venue binding requires current verified people' USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.venues_venuespace physical WHERE physical.id IN (
        SELECT source_space_id FROM public.venues_editionspacemember WHERE space_selection_id = booking.space_selection_id
    ) ORDER BY physical.id FOR UPDATE;
    SELECT * INTO STRICT selection FROM public.venues_editionspaceselection WHERE id = booking.space_selection_id FOR UPDATE;
    IF (selection.organization_id, selection.edition_id, selection.responsible_department_id)
          IS DISTINCT FROM (NEW.organization_id, NEW.edition_id, booking.responsible_department_id)
       OR selection.lifecycle <> 'active'
       OR NOT EXISTS (SELECT 1 FROM public.venues_editionvenueselection venue
           JOIN public.venues_venueproperty property ON property.id = venue.property_id
           WHERE venue.id = selection.venue_selection_id AND venue.lifecycle = 'active' AND property.lifecycle = 'active')
       OR NOT EXISTS (SELECT 1 FROM public.venues_editionspacemember WHERE space_selection_id = selection.id)
       OR EXISTS (SELECT 1 FROM public.venues_editionspacemember member
           JOIN public.venues_venuespace physical ON physical.id = member.source_space_id
           WHERE member.space_selection_id = selection.id AND (NOT physical.is_active
               OR member.organization_id <> NEW.organization_id OR member.edition_id <> NEW.edition_id
               OR physical.organization_id <> NEW.organization_id))
       OR booking.expected_attendance > LEAST(selection.fire_capacity, CASE booking.capacity_mode
           WHEN 'seated' THEN selection.seated_capacity WHEN 'standing' THEN selection.standing_capacity
           WHEN 'table' THEN selection.table_capacity ELSE 0 END)
       OR NOT EXISTS (SELECT 1 FROM public.venues_editionspaceavailabilitywindow hard_window
           WHERE hard_window.space_selection_id = selection.id AND hard_window.organization_id = NEW.organization_id
             AND hard_window.edition_id = NEW.edition_id AND hard_window.availability_version = selection.current_availability_version
             AND hard_window.starts_at <= booking.setup_starts_at AND hard_window.ends_at >= booking.teardown_ends_at)
    THEN
        RAISE EXCEPTION 'Venue binding requires current physical capacity and hard availability' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM public.venues_venueschedulingbinding binding
        JOIN public.venues_venuebooking held ON held.id = binding.booking_id
        WHERE binding.occurrence_id = NEW.occurrence_id AND held.lifecycle = 'active') THEN
        RAISE EXCEPTION 'An occurrence has only one active physical reservation' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_scheduling_linked_booking()
RETURNS trigger AS $$
DECLARE
    source_actor uuid;
BEGIN
    SELECT source_actor_id INTO source_actor FROM public.venues_venueschedulingbinding WHERE booking_id = OLD.id;
    IF NOT FOUND THEN RETURN NEW; END IF;
    PERFORM 1 FROM public.events_eventedition WHERE id = OLD.edition_id FOR UPDATE;
    IF (to_jsonb(NEW) - ARRAY['updated_at','aggregate_version','lifecycle','review_state','approved_by_id','approved_at','last_modified_by_id'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['updated_at','aggregate_version','lifecycle','review_state','approved_by_id','approved_at','last_modified_by_id'])
       OR NEW.aggregate_version <> OLD.aggregate_version + 1 OR OLD.lifecycle <> 'active'
    THEN
        RAISE EXCEPTION 'Linked physical facts change only through Scheduling replacement' USING ERRCODE = '23514';
    END IF;
    IF NEW.lifecycle = 'cancelled' THEN
        IF (NEW.review_state, NEW.approved_by_id, NEW.approved_at)
           IS DISTINCT FROM (OLD.review_state, OLD.approved_by_id, OLD.approved_at) THEN
            RAISE EXCEPTION 'Cancellation must preserve independent review history' USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.lifecycle = 'active' AND OLD.review_state = 'draft' AND NEW.review_state = 'approved' THEN
        PERFORM 1 FROM public.identity_account WHERE id = NEW.approved_by_id FOR UPDATE;
        IF NEW.approved_by_id IS DISTINCT FROM NEW.last_modified_by_id OR NEW.approved_at IS NULL
           OR NEW.approved_by_id IN (OLD.created_by_id, OLD.last_modified_by_id, source_actor)
           OR NOT EXISTS (SELECT 1 FROM public.identity_account WHERE id = NEW.approved_by_id
               AND is_active AND email_verified_at IS NOT NULL AND account_kind = 'person') THEN
            RAISE EXCEPTION 'Linked Venue approval requires an independent current person' USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'Linked booking supports only independent approval or cancellation' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_scheduling_linked_booking(booking_key uuid)
RETURNS void AS $$
DECLARE
    booking public.venues_venuebooking%ROWTYPE;
    binding public.venues_venueschedulingbinding%ROWTYPE;
BEGIN
    SELECT * INTO binding FROM public.venues_venueschedulingbinding WHERE booking_id = booking_key;
    IF NOT FOUND THEN RETURN; END IF;
    SELECT * INTO STRICT booking FROM public.venues_venuebooking WHERE id = booking_key;
    IF NOT EXISTS (SELECT 1 FROM public.venues_venueschedulingbinding retained
        JOIN public.venues_venuebookinghistory initial ON initial.booking_id = retained.booking_id AND initial.sequence = 1
        WHERE retained.id = binding.id AND retained.xmin = initial.xmin AND initial.action = 'created'
          AND initial.occurred_at = retained.occurred_at) THEN
        RAISE EXCEPTION 'Binding and initial physical evidence must be written together' USING ERRCODE = '23514';
    END IF;
    IF (SELECT count(*) FROM public.venues_venuebookinghistory WHERE booking_id = booking_key) <> booking.aggregate_version
       OR EXISTS (SELECT 1 FROM public.venues_venuebookinghistory history
            WHERE history.booking_id = booking_key AND (history.sequence < 1 OR history.sequence > booking.aggregate_version
              OR history.booking_version <> history.sequence OR history.organization_id <> booking.organization_id
              OR history.edition_id <> booking.edition_id OR history.reason = ''
              OR (history.new_setup_starts_at, history.new_effective_starts_at, history.new_effective_ends_at, history.new_teardown_ends_at)
                 IS DISTINCT FROM (booking.setup_starts_at, booking.effective_starts_at, booking.effective_ends_at, booking.teardown_ends_at)
              OR history.action NOT IN ('created','approved','cancelled')
              OR NOT EXISTS (
                  SELECT 1 FROM public.venues_venuecommandreceipt receipt
                  JOIN public.audit_auditevent audit ON audit.target_id = receipt.result_object_id
                  JOIN public.effects_domainevent event ON event.causation_id = audit.id
                  JOIN public.effects_outboxmessage outbox ON outbox.event_id = event.id
                  WHERE receipt.result_object_id = booking_key AND receipt.resulting_version = history.booking_version
                    AND receipt.actor_id = history.actor_id AND receipt.organization_id = booking.organization_id AND receipt.edition_id = booking.edition_id
                    AND receipt.operation = CASE history.action WHEN 'created' THEN 'booking.create' WHEN 'approved' THEN 'booking.approve' ELSE 'booking.cancel' END
                    AND audit.organization_id = booking.organization_id AND audit.event_edition_id = booking.edition_id
                    AND audit.principal_kind = 'account' AND audit.principal_id = history.actor_id
                    AND audit.target_type = 'venues.booking' AND audit.operation = 'venues.' || receipt.operation
                    AND audit.capability_code = 'venues.manage_space_schedule' AND audit.outcome = 'allow'
                    AND audit.correlation_id = receipt.correlation_id AND audit.source_channel = receipt.source_channel
                    AND audit.idempotency_key_hash = encode(sha256(convert_to(receipt.idempotency_key::text, 'UTF8')), 'hex')
                    AND audit.occurred_at = history.occurred_at AND audit.retention_class = 'venue-operational'
                    AND event.organization_id = booking.organization_id AND event.event_edition_id = booking.edition_id
                    AND event.event_name = 'venues.record.changed.v1' AND event.schema_version = 1
                    AND event.aggregate_type = 'venues.booking' AND event.aggregate_id = booking_key AND event.aggregate_version = history.booking_version
                    AND event.actor_kind = 'account' AND event.actor_id = history.actor_id AND event.correlation_id = receipt.correlation_id
                    AND event.occurred_at = history.occurred_at AND event.retention_class = 'venue-operational'
                    AND event.payload = jsonb_build_object('action', history.action, 'record_type', 'venues.booking', 'record_id', booking_key::text)
                    AND outbox.organization_id = booking.organization_id AND outbox.destination = 'internal' AND outbox.workload_pool = 'default'
              )))
       OR NOT EXISTS (SELECT 1 FROM public.venues_venuebookinghistory latest
           WHERE latest.booking_id = booking_key AND latest.sequence = booking.aggregate_version
             AND latest.actor_id = booking.last_modified_by_id AND latest.to_lifecycle = booking.lifecycle
             AND latest.to_review_state = booking.review_state AND latest.to_publication_state = booking.publication_state)
    THEN
        RAISE EXCEPTION 'Linked booking lacks complete reciprocal command history and effects' USING ERRCODE = '23514';
    END IF;
    IF booking.lifecycle = 'active' THEN
        IF (SELECT count(*) FROM public.venues_venueschedulingbinding other
            JOIN public.venues_venuebooking held ON held.id = other.booking_id
            WHERE other.occurrence_id = binding.occurrence_id AND held.lifecycle = 'active') <> 1
           OR (SELECT count(*) FROM public.venues_venuebookingoccupancy WHERE booking_id = booking_key AND active)
              <> 2 * (SELECT count(*) FROM public.venues_editionspacemember WHERE space_selection_id = booking.space_selection_id)
           OR NOT EXISTS (SELECT 1 FROM public.venues_editionspacemember WHERE space_selection_id = booking.space_selection_id)
        THEN
            RAISE EXCEPTION 'Active linked booking requires one complete physical reservation' USING ERRCODE = '23514';
        END IF;
    ELSIF EXISTS (SELECT 1 FROM public.venues_venuebookingoccupancy WHERE booking_id = booking_key AND active) THEN
        RAISE EXCEPTION 'Cancelled linked booking cannot retain active occupancy' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM public.venues_venuebookingoccupancy occupancy WHERE occupancy.booking_id = booking_key
        AND (occupancy.organization_id <> booking.organization_id OR occupancy.edition_id <> booking.edition_id
          OR occupancy.booking_version <> 1 OR occupancy.conflict_group NOT IN ('setup_effective','effective_teardown')
          OR occupancy.occupied_range IS DISTINCT FROM (CASE occupancy.conflict_group
              WHEN 'setup_effective' THEN tstzrange(booking.setup_starts_at, booking.effective_ends_at, '[)')
              ELSE tstzrange(booking.effective_starts_at, booking.teardown_ends_at, '[)') END)
          OR NOT EXISTS (SELECT 1 FROM public.venues_editionspacemember member
              WHERE member.space_selection_id = booking.space_selection_id AND member.source_space_id = occupancy.source_space_id))) THEN
        RAISE EXCEPTION 'Linked occupancy must exactly derive from retained physical facts' USING ERRCODE = '23514';
    END IF;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_venue_scheduling_graph()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    intent public.scheduling_schedulingreservationintent%ROWTYPE;
    parent public.scheduling_schedulingcommandreceipt%ROWTYPE;
    receipt public.venues_venuecommandreceipt%ROWTYPE;
    binding public.venues_venueschedulingbinding%ROWTYPE;
    history public.venues_venuebookinghistory%ROWTYPE;
    booking_key uuid;
BEGIN
    IF TG_TABLE_NAME <> 'scheduling_schedulingreservationintent' THEN
        booking_key := CASE WHEN TG_TABLE_NAME = 'venues_venuebooking' THEN NEW.id ELSE (body->>'booking_id')::uuid END;
        PERFORM public.maru_validate_scheduling_linked_booking(booking_key);
        RETURN NULL;
    END IF;
    SELECT * INTO STRICT intent FROM public.scheduling_schedulingreservationintent WHERE id = NEW.id;
    SELECT * INTO STRICT parent FROM public.scheduling_schedulingcommandreceipt WHERE id = intent.command_receipt_id;
    SELECT * INTO STRICT receipt FROM public.venues_venuecommandreceipt WHERE id = intent.venue_receipt_id;
    IF (receipt.organization_id, receipt.edition_id, receipt.actor_id, receipt.idempotency_key, receipt.correlation_id, receipt.source_channel)
       IS DISTINCT FROM (intent.organization_id, intent.edition_id, intent.actor_id, intent.id, parent.correlation_id, parent.source_channel) THEN
        RAISE EXCEPTION 'Reservation intent requires its exact reciprocal Venue receipt' USING ERRCODE = '23514';
    END IF;
    IF intent.operation = 'reservation_replace' THEN
        SELECT * INTO binding FROM public.venues_venueschedulingbinding WHERE source_intent_id = intent.id;
        IF NOT FOUND OR binding.booking_id IS DISTINCT FROM intent.target_booking_id
           OR receipt.operation <> 'booking.create' OR receipt.result_object_id IS DISTINCT FROM intent.target_booking_id OR receipt.resulting_version <> 1 THEN
            RAISE EXCEPTION 'Replacement requires the exact new Venue binding and receipt' USING ERRCODE = '23514';
        END IF;
        SELECT * INTO STRICT history FROM public.venues_venuebookinghistory WHERE booking_id = binding.booking_id AND sequence = 1;
        IF history.actor_id IS DISTINCT FROM intent.actor_id OR history.reason IS DISTINCT FROM intent.reason
           OR NOT EXISTS (SELECT 1 FROM public.venues_venuecommandreceipt retained
               JOIN public.venues_venueschedulingbinding link ON link.source_intent_id = intent.id
               WHERE retained.id = receipt.id AND retained.xmin = link.xmin) THEN
            RAISE EXCEPTION 'New reservation evidence must be atomic and exactly attributed' USING ERRCODE = '23514';
        END IF;
        PERFORM public.maru_validate_scheduling_linked_booking(binding.booking_id);
    ELSIF receipt.operation <> 'booking.cancel' OR receipt.result_object_id IS DISTINCT FROM intent.previous_booking_id
          OR receipt.resulting_version <> intent.expected_booking_version + 1 THEN
        RAISE EXCEPTION 'Cancellation requires its exact versioned Venue receipt' USING ERRCODE = '23514';
    END IF;
    IF intent.previous_booking_id IS NOT NULL THEN
        SELECT * INTO binding FROM public.venues_venueschedulingbinding WHERE booking_id = intent.previous_booking_id;
        IF NOT FOUND OR (binding.organization_id, binding.edition_id, binding.occurrence_id)
           IS DISTINCT FROM (intent.organization_id, intent.edition_id, intent.occurrence_id) THEN
            RAISE EXCEPTION 'Previous reservation must belong to the exact occurrence' USING ERRCODE = '23514';
        END IF;
        IF intent.operation = 'reservation_cancel' AND binding.placement_id <> intent.placement_id THEN
            RAISE EXCEPTION 'Cancellation requires the exact retained placement' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.venues_venuebookinghistory cancelled
            JOIN public.venues_venuecommandreceipt cancellation ON cancellation.result_object_id = cancelled.booking_id
            WHERE cancelled.booking_id = intent.previous_booking_id AND cancelled.sequence = intent.expected_booking_version + 1
              AND cancelled.action = 'cancelled' AND cancelled.actor_id = intent.actor_id AND cancelled.reason = intent.reason
              AND cancellation.operation = 'booking.cancel' AND cancellation.idempotency_key = intent.id
              AND cancellation.actor_id = intent.actor_id AND cancellation.resulting_version = cancelled.sequence
              AND cancellation.correlation_id = parent.correlation_id AND cancellation.source_channel = parent.source_channel
              AND cancellation.xmin = cancelled.xmin) THEN
            RAISE EXCEPTION 'Previous hold must be cancelled atomically with reciprocal evidence' USING ERRCODE = '23514';
        END IF;
        PERFORM public.maru_validate_scheduling_linked_booking(intent.previous_booking_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER venue_scheduling_binding_row BEFORE INSERT OR UPDATE OR DELETE ON public.venues_venueschedulingbinding
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_venue_scheduling_binding();
CREATE TRIGGER venue_scheduling_binding_truncate BEFORE TRUNCATE ON public.venues_venueschedulingbinding
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_venue_scheduling_binding();
CREATE TRIGGER venue_scheduling_linked_booking BEFORE UPDATE ON public.venues_venuebooking
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_scheduling_linked_booking();
"""

GRAPH_TABLES = (
    "venues_venueschedulingbinding",
    "venues_venuebooking",
    "venues_venuebookingoccupancy",
    "venues_venuebookinghistory",
    "scheduling_schedulingreservationintent",
)
FORWARD_SQL += "\n".join(
    f"""
CREATE CONSTRAINT TRIGGER venue_scheduling_graph_{index} AFTER INSERT OR UPDATE ON public.{table}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_validate_venue_scheduling_graph();
"""
    for index, table in enumerate(GRAPH_TABLES)
)
FUNCTIONS = (
    "maru_guard_venue_scheduling_binding()",
    "maru_guard_scheduling_linked_booking()",
    "maru_validate_scheduling_linked_booking(uuid)",
    "maru_validate_venue_scheduling_graph()",
)
FORWARD_SQL += "\n".join(
    f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC;" for signature in FUNCTIONS
)
REVERSE_SQL = "\n".join(
    f"DROP TRIGGER IF EXISTS venue_scheduling_graph_{index} ON public.{table};"
    for index, table in reversed(tuple(enumerate(GRAPH_TABLES)))
)
REVERSE_SQL += """
DROP TRIGGER IF EXISTS venue_scheduling_linked_booking ON public.venues_venuebooking;
DROP TRIGGER IF EXISTS venue_scheduling_binding_truncate ON public.venues_venueschedulingbinding;
DROP TRIGGER IF EXISTS venue_scheduling_binding_row ON public.venues_venueschedulingbinding;
"""
REVERSE_SQL += "\n".join(
    f"DROP FUNCTION IF EXISTS public.{signature};" for signature in reversed(FUNCTIONS)
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("venues", "0003_scheduling_reservation_sources"),
        ("scheduling", "0005_integrity_guards"),
    ]
    operations: ClassVar[list[migrations.operations.base.Operation]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
