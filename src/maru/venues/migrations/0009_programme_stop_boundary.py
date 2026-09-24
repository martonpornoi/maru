"""Freeze stopped edition operation, retaining exact audited physical correction."""

# ruff: noqa: S608 -- SQL identifiers are the frozen literal owner inventory.

from typing import Any, ClassVar

from django.db import migrations

GUARDED_MODELS = (
    "editionvenueselection",
    "editionspaceselection",
    "editionspacemember",
    "editionspaceavailabilitywindow",
    "venuebooking",
    "venuebookinghistory",
    "venuebookingoccupancy",
    "venueschedulingbinding",
    "venuecommandreceipt",
)
CORRECTION_MODELS = (
    "venuebooking",
    "venuebookinghistory",
    "venuebookingoccupancy",
    "venuecommandreceipt",
)

FORWARD_SQL = (
    r"""
CREATE FUNCTION public.maru_venues_programme_stop_guard()
RETURNS trigger AS $$
DECLARE
    rows jsonb := '[]'::jsonb;
    body jsonb;
    scope record;
    edition record;
    stopped boolean := FALSE;
    correction boolean := FALSE;
BEGIN
    IF TG_OP <> 'INSERT' THEN rows := rows || jsonb_build_array(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN rows := rows || jsonb_build_array(to_jsonb(NEW)); END IF;
    FOR body IN SELECT value FROM jsonb_array_elements(rows) LOOP
        IF TG_TABLE_NAME = 'venues_venuecommandreceipt'
           AND body->>'edition_id' IS NULL THEN
            IF body->>'operation' NOT IN (
                'property.create', 'catalog.add', 'media.add', 'media.review',
                'layout.add', 'layout.review', 'room_inventory.set'
            ) THEN
                RAISE EXCEPTION 'Scoped Venue receipts require an edition'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF body->>'edition_id' IS NULL OR body->>'organization_id' IS NULL THEN
            RAISE EXCEPTION 'Venue stop boundary requires an exact scope'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;
    FOR scope IN
        SELECT DISTINCT (value->>'edition_id')::uuid AS edition_id,
                        (value->>'organization_id')::uuid AS organization_id
        FROM jsonb_array_elements(rows) WHERE value->>'edition_id' IS NOT NULL
        ORDER BY edition_id, organization_id
    LOOP
        SELECT e.adoption_profile_code, e.adoption_profile_version, e.lifecycle
          INTO edition FROM public.events_eventedition e
         WHERE e.id = scope.edition_id AND e.organization_id = scope.organization_id
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Venue stop boundary requires an exact edition'
                USING ERRCODE = '23514';
        END IF;
        IF edition.adoption_profile_code = 'programme_operations' THEN
            IF edition.adoption_profile_version <> 1
               OR current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Programme Venues requires current exact scope'
                    USING ERRCODE = '23514';
            END IF;
            stopped := stopped OR edition.lifecycle IN ('archived', 'cancelled');
        END IF;
    END LOOP;
    IF stopped THEN
        CASE TG_TABLE_NAME
        WHEN 'venues_venuebooking' THEN
            IF TG_OP = 'UPDATE' THEN
                correction := OLD.lifecycle = 'active'
                    AND NEW.aggregate_version = OLD.aggregate_version + 1
                    AND to_jsonb(NEW) - ARRAY[
                        'lifecycle', 'publication_state', 'last_modified_by_id',
                        'aggregate_version', 'updated_at'
                    ] = to_jsonb(OLD) - ARRAY[
                        'lifecycle', 'publication_state', 'last_modified_by_id',
                        'aggregate_version', 'updated_at'
                    ] AND (
                        (NEW.lifecycle = 'cancelled' AND NEW.publication_state =
                         CASE WHEN OLD.publication_state = 'published'
                              THEN 'withdrawn' ELSE OLD.publication_state END)
                        OR (NEW.lifecycle = 'active'
                            AND OLD.publication_state = 'published'
                            AND NEW.publication_state = 'withdrawn')
                    );
            END IF;
        WHEN 'venues_venuebookingoccupancy' THEN
            IF TG_OP = 'UPDATE' THEN
                correction := OLD.active AND NOT NEW.active
                    AND to_jsonb(NEW) - 'active' = to_jsonb(OLD) - 'active';
            END IF;
        WHEN 'venues_venuebookinghistory' THEN
            IF TG_OP = 'INSERT' THEN
                correction := NEW.action IN ('cancelled', 'withdrawn')
                    AND NEW.sequence = NEW.booking_version
                    AND NEW.booking_version > 1;
            END IF;
        WHEN 'venues_venuecommandreceipt' THEN
            IF TG_OP = 'INSERT' THEN
                correction := NEW.operation IN ('booking.cancel', 'booking.withdraw');
            END IF;
        ELSE correction := FALSE;
        END CASE;
        IF correction IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Stopped Programme refuses ordinary Venue writes'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_venues_programme_stop_correction()
RETURNS trigger AS $$
DECLARE
    target_id uuid;
    target_version bigint;
    booking public.venues_venuebooking%ROWTYPE;
    history public.venues_venuebookinghistory%ROWTYPE;
    previous public.venues_venuebookinghistory%ROWTYPE;
    expected_operation text;
    expected_capability text;
    expected_fields varchar[];
    expected_digest text;
BEGIN
    -- Ordinary writes admitted before terminal state need no new correction
    -- evidence. The BEFORE guard independently refuses them once stopped.
    CASE TG_TABLE_NAME
    WHEN 'venues_venuebooking' THEN
        IF TG_OP <> 'UPDATE' THEN RETURN NULL; END IF;
        IF OLD.lifecycle <> 'active' OR NOT (
            NEW.lifecycle = 'cancelled' OR (
                OLD.publication_state = 'published'
                AND NEW.publication_state = 'withdrawn'
            )
        ) THEN RETURN NULL; END IF;
        target_id := NEW.id;
        target_version := NEW.aggregate_version;
    WHEN 'venues_venuebookingoccupancy' THEN
        IF TG_OP <> 'UPDATE' THEN RETURN NULL; END IF;
        IF NOT OLD.active OR NEW.active THEN RETURN NULL; END IF;
        target_id := NEW.booking_id;
    WHEN 'venues_venuebookinghistory' THEN
        IF TG_OP <> 'INSERT' THEN RETURN NULL; END IF;
        IF NEW.action NOT IN ('cancelled', 'withdrawn') THEN RETURN NULL; END IF;
        target_id := NEW.booking_id;
        target_version := NEW.booking_version;
    WHEN 'venues_venuecommandreceipt' THEN
        IF TG_OP <> 'INSERT' THEN RETURN NULL; END IF;
        IF NEW.operation NOT IN ('booking.cancel', 'booking.withdraw')
            THEN RETURN NULL; END IF;
        target_id := NEW.result_object_id;
        target_version := NEW.resulting_version;
    ELSE RETURN NULL;
    END CASE;

    PERFORM 1 FROM public.events_eventedition e
     WHERE e.id = NEW.edition_id AND e.organization_id = NEW.organization_id
       AND e.adoption_profile_code = 'programme_operations'
       AND e.adoption_profile_version = 1
       AND e.lifecycle IN ('archived', 'cancelled') FOR UPDATE;
    IF NOT FOUND THEN RETURN NULL; END IF;

    SELECT b.* INTO booking FROM public.venues_venuebooking b
     WHERE b.id = target_id AND b.organization_id = NEW.organization_id
       AND b.edition_id = NEW.edition_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Stopped Venue correction requires its exact retained booking'
            USING ERRCODE = '23514';
    END IF;
    target_version := COALESCE(target_version, booking.aggregate_version);
    SELECT h.* INTO history FROM public.venues_venuebookinghistory h
     WHERE h.booking_id = booking.id AND h.sequence = target_version
       AND h.booking_version = target_version
       AND h.organization_id = booking.organization_id
       AND h.edition_id = booking.edition_id;
    IF NOT FOUND OR history.action NOT IN ('cancelled', 'withdrawn') THEN
        RAISE EXCEPTION 'Stopped Venue correction requires exact retained history'
            USING ERRCODE = '23514';
    END IF;
    SELECT h.* INTO previous FROM public.venues_venuebookinghistory h
     WHERE h.booking_id = booking.id AND h.sequence = target_version - 1
       AND h.booking_version = target_version - 1
       AND h.organization_id = booking.organization_id
       AND h.edition_id = booking.edition_id;
    IF NOT FOUND OR booking.aggregate_version < target_version
       OR btrim(history.reason) = ''
       OR history.from_lifecycle <> 'active'
       OR history.from_lifecycle IS DISTINCT FROM previous.to_lifecycle
       OR history.from_review_state IS DISTINCT FROM previous.to_review_state
       OR history.from_publication_state IS DISTINCT FROM previous.to_publication_state
       OR history.to_review_state IS DISTINCT FROM history.from_review_state
       OR ROW(history.old_setup_starts_at, history.old_effective_starts_at,
              history.old_effective_ends_at, history.old_teardown_ends_at)
          IS DISTINCT FROM ROW(booking.setup_starts_at, booking.effective_starts_at,
                               booking.effective_ends_at, booking.teardown_ends_at)
       OR ROW(history.new_setup_starts_at, history.new_effective_starts_at,
              history.new_effective_ends_at, history.new_teardown_ends_at)
          IS DISTINCT FROM ROW(booking.setup_starts_at, booking.effective_starts_at,
                               booking.effective_ends_at, booking.teardown_ends_at)
       OR ROW(previous.new_setup_starts_at, previous.new_effective_starts_at,
              previous.new_effective_ends_at, previous.new_teardown_ends_at)
          IS DISTINCT FROM ROW(booking.setup_starts_at, booking.effective_starts_at,
                               booking.effective_ends_at, booking.teardown_ends_at)
    THEN
        RAISE EXCEPTION 'Stopped Venue correction must preserve its original obligation'
            USING ERRCODE = '23514';
    END IF;
    IF history.action = 'cancelled' THEN
        expected_operation := 'booking.cancel';
        expected_capability := 'venues.manage_space_schedule';
        expected_fields := ARRAY[
            'lifecycle', 'physical_occupancy', 'publication_state'];
        IF history.to_lifecycle <> 'cancelled' OR history.to_publication_state <>
            (CASE WHEN history.from_publication_state = 'published'
                  THEN 'withdrawn' ELSE history.from_publication_state END) THEN
            RAISE EXCEPTION 'Stopped Venue cancellation evidence differs'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        expected_operation := 'booking.withdraw';
        expected_capability := 'venues.publish_space_schedule';
        expected_fields := ARRAY['publication_state'];
        IF history.to_lifecycle <> 'active'
           OR history.from_publication_state <> 'published'
           OR history.to_publication_state <> 'withdrawn' THEN
            RAISE EXCEPTION 'Stopped Venue withdrawal evidence differs'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    CASE TG_TABLE_NAME
    WHEN 'venues_venuebooking' THEN
        IF history.actor_id <> NEW.last_modified_by_id
           OR ROW(history.from_lifecycle, history.from_publication_state,
                  history.from_review_state) IS DISTINCT FROM
              ROW(OLD.lifecycle, OLD.publication_state, OLD.review_state)
           OR ROW(history.to_lifecycle, history.to_publication_state,
                  history.to_review_state) IS DISTINCT FROM
              ROW(NEW.lifecycle, NEW.publication_state, NEW.review_state) THEN
            RAISE EXCEPTION 'Stopped Venue mutation and history differ'
                USING ERRCODE = '23514';
        END IF;
    WHEN 'venues_venuebookingoccupancy' THEN
        IF booking.lifecycle <> 'cancelled' OR history.action <> 'cancelled'
           OR NEW.booking_version >= target_version THEN
            RAISE EXCEPTION 'Stopped occupancy requires its exact cancellation'
                USING ERRCODE = '23514';
        END IF;
    WHEN 'venues_venuebookinghistory' THEN
        IF NEW.id <> history.id THEN
            RAISE EXCEPTION 'Stopped Venue history identity differs'
                USING ERRCODE = '23514';
        END IF;
    WHEN 'venues_venuecommandreceipt' THEN
        IF NEW.operation <> expected_operation OR NEW.actor_id <> history.actor_id THEN
            RAISE EXCEPTION 'Stopped Venue receipt identity differs'
                USING ERRCODE = '23514';
        END IF;
    END CASE;
    -- The existing command's canonical UTF-8 intent binds the retained reason
    -- and exact prior version without introducing a callable JSON helper.
    expected_digest := encode(sha256(convert_to(
        '{"booking_id":' || to_json(booking.id)::text ||
        ',"edition_id":' || to_json(booking.edition_id)::text ||
        ',"expected_version":' || (target_version - 1)::text ||
        ',"organization_id":' || to_json(booking.organization_id)::text ||
        ',"reason":' || to_json(history.reason)::text ||
        ',"space_selection_id":' || to_json(booking.space_selection_id)::text || '}',
        'UTF8')), 'hex');
    IF NOT EXISTS (
        SELECT 1 FROM public.venues_venuecommandreceipt r
          JOIN public.audit_auditevent a
            ON a.operation = 'venues.' || r.operation
           AND a.correlation_id = r.correlation_id
          JOIN public.audit_auditnativemutationwitness w ON w.audit_event_id = a.id
         WHERE r.result_object_id = booking.id
           AND r.resulting_version = target_version
           AND r.organization_id = booking.organization_id
           AND r.edition_id = booking.edition_id
           AND r.operation = expected_operation AND r.actor_id = history.actor_id
           AND r.request_digest = expected_digest
           AND a.outcome = 'allow' AND a.principal_kind = 'account'
           AND a.principal_context_id IS NULL AND a.principal_id = r.actor_id
           AND a.target_type = 'venues.booking' AND a.target_id = booking.id
           AND a.organization_id = r.organization_id
           AND a.event_edition_id = r.edition_id
           AND a.source_channel = r.source_channel
           AND a.idempotency_key_hash = encode(
               sha256(convert_to(r.idempotency_key::text, 'UTF8')), 'hex')
           AND a.capability_code = expected_capability
           AND a.changed_fields = expected_fields
           AND a.retention_class = 'venue-operational'
           AND w.transaction_stamp =
               public.maru_audit_current_native_transaction_stamp()
           AND (TG_TABLE_NAME <> 'venues_venuecommandreceipt' OR r.id = NEW.id)
    ) THEN
        RAISE EXCEPTION 'Stopped Venue correction requires native receipt and audit'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_venues_programme_stop_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_venues_programme_stop_correction() FROM PUBLIC;
"""
    + "\n".join(
        f"CREATE TRIGGER a00_venues_programme_stop_{index} "
        f"BEFORE INSERT OR UPDATE OR DELETE ON public.venues_{model} "
        "FOR EACH ROW EXECUTE FUNCTION public.maru_venues_programme_stop_guard();"
        for index, model in enumerate(GUARDED_MODELS)
    )
    + "\n"
    + "\n".join(
        f"CREATE CONSTRAINT TRIGGER venues_programme_stop_correction_{index} "
        f"AFTER INSERT OR UPDATE ON public.venues_{model} "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION public.maru_venues_programme_stop_correction();"
        for index, model in enumerate(CORRECTION_MODELS)
    )
)

REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER venues_programme_stop_correction_{index} "
        f"ON public.venues_{model};"
        for index, model in reversed(tuple(enumerate(CORRECTION_MODELS)))
    )
    + "\n"
    + "\n".join(
        f"DROP TRIGGER a00_venues_programme_stop_{index} ON public.venues_{model};"
        for index, model in reversed(tuple(enumerate(GUARDED_MODELS)))
    )
    + "\nDROP FUNCTION public.maru_venues_programme_stop_correction();"
    "\nDROP FUNCTION public.maru_venues_programme_stop_guard();"
)


def refuse_used_stop_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain the exact physical correction boundary once stop evidence is used."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError(
            "Programme stop evidence exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Add terminal owner guards without cancelling physical obligations at stop."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("venues", "0008_release_first_capture"),
        ("events", "0015_programme_stop_receipt"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_stop_boundary_downgrade
        ),
    ]
