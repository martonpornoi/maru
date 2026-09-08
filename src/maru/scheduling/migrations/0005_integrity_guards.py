# ruff: noqa: E501
"""Enforce Scheduling ownership, immutable complete graphs and command evidence."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

TABLE_SUFFIXES = (
    "schedulingeditioncontrol",
    "schedulingserviceday",
    "schedulingservicedayrevision",
    "schedulingoccurrence",
    "schedulingoccurrencerevision",
    "schedulingcandidate",
    "schedulingcandidaterevision",
    "schedulingplacementrevision",
    "schedulingcandidatemember",
    "schedulingplacementhostpresence",
    "schedulingevaluation",
    "schedulingconflict",
    "schedulingwarningacknowledgement",
    "schedulingreservationintent",
    "schedulingcommandreceipt",
)

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_scheduling_canonical_json(value jsonb)
RETURNS text AS $$
DECLARE result text;
BEGIN
    CASE jsonb_typeof(value)
    WHEN 'object' THEN
        SELECT '{' || COALESCE(string_agg(to_jsonb(key)::text || ':' || public.maru_scheduling_canonical_json(content), ',' ORDER BY key COLLATE "C"), '') || '}'
          INTO result FROM jsonb_each(value) AS pairs(key, content);
    WHEN 'array' THEN
        SELECT '[' || COALESCE(string_agg(public.maru_scheduling_canonical_json(content), ',' ORDER BY position), '') || ']'
          INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS items(content, position);
    ELSE result := value::text;
    END CASE;
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_exact_keys(value jsonb, keys text[])
RETURNS boolean AS $$
    SELECT jsonb_typeof(value) = 'object' AND value ?& keys AND value - keys = '{}'::jsonb;
$$ LANGUAGE sql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_evidence_shape(value jsonb)
RETURNS boolean AS $$
DECLARE
    source jsonb;
    rows jsonb;
    entry jsonb;
    field record;
    position integer;
    collection_name text;
    allowed text[];
    maximum integer;
    identity_field text;
    uuid_pattern text := '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
BEGIN
    IF jsonb_typeof(value) IS DISTINCT FROM 'array' OR jsonb_array_length(value) <> 3 OR octet_length(value::text) > 4194304 THEN RETURN FALSE; END IF;
    FOR position IN 0..2 LOOP
        source := value->position;
        allowed := CASE position
          WHEN 0 THEN ARRAY['source_code','schema_version','not_evaluated','revision_id','manifest_digest','edition_version','occurrences','days']
          WHEN 1 THEN ARRAY['source_code','available','edition_version','items','hosts']
          ELSE ARRAY['source_code','available','edition_version','spaces','busy_sources','reservations','physical_bindings'] END;
        IF public.maru_scheduling_exact_keys(source, allowed) IS DISTINCT FROM TRUE
           OR source->>'source_code' IS DISTINCT FROM (CASE position WHEN 0 THEN 'scheduling.service-day-and-placement@1'
               WHEN 1 THEN 'programme.item-and-host-availability@1' ELSE 'venues.physical-scheduling-dependencies@1' END)
           OR (source->'edition_version' <> 'null'::jsonb AND (jsonb_typeof(source->'edition_version') IS DISTINCT FROM 'number' OR source->>'edition_version' !~ '^[1-9][0-9]{0,18}$')) THEN RETURN FALSE; END IF;
        IF position = 0 THEN
            IF source->'schema_version' <> '1'::jsonb OR source->'not_evaluated' <> '["staffing","rest","accessibility_fit","release_readiness"]'::jsonb
               OR source->>'revision_id' !~ uuid_pattern OR source->>'manifest_digest' !~ '^[0-9a-f]{64}$' THEN RETURN FALSE; END IF;
        ELSIF jsonb_typeof(source->'available') IS DISTINCT FROM 'boolean' OR (source->'available' = 'false'::jsonb AND source->'edition_version' <> 'null'::jsonb) THEN
            RETURN FALSE;
        END IF;
        FOREACH collection_name IN ARRAY (CASE position WHEN 0 THEN ARRAY['occurrences','days']
            WHEN 1 THEN ARRAY['items','hosts'] ELSE ARRAY['spaces','busy_sources','reservations','physical_bindings'] END) LOOP
            rows := source->collection_name;
            maximum := CASE collection_name WHEN 'days' THEN 128 WHEN 'hosts' THEN 1999 WHEN 'spaces' THEN 256 WHEN 'busy_sources' THEN 40000 ELSE 2000 END;
            IF jsonb_typeof(rows) IS DISTINCT FROM 'array' OR jsonb_array_length(rows) > maximum THEN RETURN FALSE; END IF;
            IF position > 0 AND source->'available' = 'false'::jsonb AND collection_name <> 'physical_bindings' AND jsonb_array_length(rows) <> 0 THEN RETURN FALSE; END IF;
            allowed := CASE collection_name
              WHEN 'occurrences' THEN ARRAY['id','version','active'] WHEN 'days' THEN ARRAY['id','version','active']
              WHEN 'items' THEN ARRAY['id','version','lifecycle','hosting_required']
              WHEN 'hosts' THEN ARRAY['id','version','availability_version','status']
              WHEN 'spaces' THEN ARRAY['id','version','availability_version','active']
              WHEN 'busy_sources' THEN ARRAY['id','version']
              WHEN 'reservations' THEN ARRAY['placement_id','booking_id','version','review_state']
              ELSE ARRAY['placement_id','state'] END;
            FOR entry IN SELECT content FROM jsonb_array_elements(rows) AS items(content) LOOP
                IF public.maru_scheduling_exact_keys(entry, allowed) IS DISTINCT FROM TRUE THEN RETURN FALSE; END IF;
                FOR field IN SELECT key, content FROM jsonb_each(entry) AS fields(key,content) LOOP
                    CASE field.key
                    WHEN 'id', 'placement_id', 'booking_id' THEN
                        IF jsonb_typeof(field.content) IS DISTINCT FROM 'string' OR field.content #>> '{}' !~ uuid_pattern THEN RETURN FALSE; END IF;
                    WHEN 'version' THEN
                        IF jsonb_typeof(field.content) IS DISTINCT FROM 'number' OR field.content #>> '{}' !~ '^[1-9][0-9]{0,18}$' THEN RETURN FALSE; END IF;
                    WHEN 'availability_version' THEN
                        IF jsonb_typeof(field.content) IS DISTINCT FROM 'number' OR field.content #>> '{}' !~ '^(0|[1-9][0-9]{0,18})$' THEN RETURN FALSE; END IF;
                    WHEN 'active', 'hosting_required' THEN
                        IF jsonb_typeof(field.content) IS DISTINCT FROM 'boolean' THEN RETURN FALSE; END IF;
                    WHEN 'lifecycle' THEN
                        IF field.content NOT IN ('"active"'::jsonb, '"retired"'::jsonb) THEN RETURN FALSE; END IF;
                    WHEN 'review_state' THEN
                        IF field.content NOT IN ('"draft"'::jsonb, '"approved"'::jsonb) THEN RETURN FALSE; END IF;
                    WHEN 'state' THEN
                        IF field.content NOT IN ('"unavailable"'::jsonb, '"unreserved"'::jsonb, '"reserved_draft"'::jsonb, '"reserved_approved"'::jsonb) THEN RETURN FALSE; END IF;
                    WHEN 'status' THEN
                        IF field.content NOT IN ('"ended"'::jsonb,'"inactive"'::jsonb,'"unconfirmed"'::jsonb,'"not_shared"'::jsonb,'"outside_edition"'::jsonb,'"unavailable"'::jsonb,'"shared"'::jsonb) THEN RETURN FALSE; END IF;
                    END CASE;
                END LOOP;
            END LOOP;
            identity_field := CASE WHEN collection_name IN ('reservations','physical_bindings') THEN 'placement_id' ELSE 'id' END;
            IF (SELECT count(DISTINCT elements.content->>identity_field) FROM jsonb_array_elements(rows) AS elements(content)) <> jsonb_array_length(rows) THEN RETURN FALSE; END IF;
        END LOOP;
    END LOOP;
    RETURN TRUE;
EXCEPTION WHEN data_exception THEN RETURN FALSE;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_scheduling_evidence_is_current(value jsonb, expected_organization uuid, expected_edition uuid)
RETURNS boolean AS $$
DECLARE
    selected_revision uuid;
    current_edition record;
    current_busy jsonb;
    recorded_busy jsonb;
BEGIN
    IF public.maru_scheduling_evidence_shape(value) IS DISTINCT FROM TRUE THEN RETURN FALSE; END IF;
    selected_revision := (value->0->>'revision_id')::uuid;
    SELECT aggregate_version, starts_on::timestamp AT TIME ZONE time_zone AS starts_at,
           (ends_on + 1)::timestamp AT TIME ZONE time_zone AS ends_at
      INTO current_edition FROM public.events_eventedition WHERE id = expected_edition AND organization_id = expected_organization;
    IF current_edition.aggregate_version IS NULL OR (value->0->>'edition_version')::bigint IS DISTINCT FROM current_edition.aggregate_version
       OR value->1->'available' <> 'true'::jsonb OR value->2->'available' <> 'true'::jsonb
       OR (value->1->>'edition_version')::bigint IS DISTINCT FROM current_edition.aggregate_version
       OR (value->2->>'edition_version')::bigint IS DISTINCT FROM current_edition.aggregate_version
       OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidaterevision revision
            JOIN public.scheduling_schedulingcandidate candidate ON candidate.id = revision.candidate_id
            WHERE revision.id = selected_revision AND revision.organization_id = expected_organization AND revision.edition_id = expected_edition
              AND revision.sequence = candidate.aggregate_version AND candidate.lifecycle = 'draft'
              AND revision.manifest_digest = value->0->>'manifest_digest') THEN RETURN FALSE; END IF;
    IF jsonb_array_length(value->0->'occurrences') <> (SELECT count(*) FROM public.scheduling_schedulingcandidatemember WHERE revision_id = selected_revision)
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(value->0->'occurrences') AS input(content)
            LEFT JOIN public.scheduling_schedulingoccurrence occurrence ON occurrence.id = (input.content->>'id')::uuid
            WHERE occurrence.organization_id IS DISTINCT FROM expected_organization OR occurrence.edition_id IS DISTINCT FROM expected_edition
              OR occurrence.aggregate_version IS DISTINCT FROM (input.content->>'version')::bigint
              OR (occurrence.lifecycle = 'active') IS DISTINCT FROM (input.content->>'active')::boolean
              OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember WHERE revision_id = selected_revision AND occurrence_id = occurrence.id)) THEN RETURN FALSE; END IF;
    IF jsonb_array_length(value->0->'days') <> (SELECT count(DISTINCT day.day_id) FROM public.scheduling_schedulingcandidatemember member
            JOIN public.scheduling_schedulingplacementrevision placement ON placement.id = member.placement_id
            JOIN public.scheduling_schedulingservicedayrevision day ON day.id = placement.day_revision_id WHERE member.revision_id = selected_revision)
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(value->0->'days') AS input(content)
            LEFT JOIN public.scheduling_schedulingserviceday day ON day.id = (input.content->>'id')::uuid
            WHERE day.organization_id IS DISTINCT FROM expected_organization OR day.edition_id IS DISTINCT FROM expected_edition
              OR day.aggregate_version IS DISTINCT FROM (input.content->>'version')::bigint
              OR (day.lifecycle = 'active') IS DISTINCT FROM (input.content->>'active')::boolean
              OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember member
                  JOIN public.scheduling_schedulingplacementrevision placement ON placement.id = member.placement_id
                  JOIN public.scheduling_schedulingservicedayrevision revision ON revision.id = placement.day_revision_id
                  WHERE member.revision_id = selected_revision AND revision.day_id = day.id)) THEN RETURN FALSE; END IF;
    IF jsonb_array_length(value->1->'items') <> (SELECT count(DISTINCT occurrence.programme_item_id) FROM public.scheduling_schedulingcandidatemember member
            JOIN public.scheduling_schedulingoccurrence occurrence ON occurrence.id = member.occurrence_id WHERE member.revision_id = selected_revision)
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(value->1->'items') AS input(content)
            LEFT JOIN public.programme_programmeitem item ON item.id = (input.content->>'id')::uuid
            WHERE item.organization_id IS DISTINCT FROM expected_organization OR item.edition_id IS DISTINCT FROM expected_edition
              OR item.aggregate_version IS DISTINCT FROM (input.content->>'version')::bigint OR item.lifecycle IS DISTINCT FROM input.content->>'lifecycle'
              OR (input.content->>'hosting_required')::boolean IS DISTINCT FROM NOT EXISTS (SELECT 1 FROM public.programme_programmereadinessrequirement requirement
                  WHERE requirement.item_id = item.id AND requirement.concern = 'host_confirmation' AND requirement.disposition = 'not_applicable')
              OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember member JOIN public.scheduling_schedulingoccurrence occurrence ON occurrence.id = member.occurrence_id
                  WHERE member.revision_id = selected_revision AND occurrence.programme_item_id = item.id)) THEN RETURN FALSE; END IF;
    IF jsonb_array_length(value->1->'hosts') <> (SELECT count(DISTINCT presence.host_relationship_id) FROM public.scheduling_schedulingcandidatemember member
            JOIN public.scheduling_schedulingplacementhostpresence presence ON presence.placement_id = member.placement_id WHERE member.revision_id = selected_revision)
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(value->1->'hosts') AS input(content)
            LEFT JOIN public.programme_programmehostrelationship host ON host.id = (input.content->>'id')::uuid
            LEFT JOIN public.identity_account person ON person.id = host.account_id
            WHERE host.organization_id IS DISTINCT FROM expected_organization OR host.edition_id IS DISTINCT FROM expected_edition
              OR host.version IS DISTINCT FROM (input.content->>'version')::bigint OR host.availability_version IS DISTINCT FROM (input.content->>'availability_version')::bigint
              OR input.content->>'status' IS DISTINCT FROM (CASE WHEN host.state IN ('declined','withdrawn','removed') THEN 'ended'
                  WHEN person.is_active IS DISTINCT FROM TRUE OR person.email_verified_at IS NULL OR person.account_kind <> 'person' THEN 'inactive'
                  WHEN host.state <> 'confirmed' THEN 'unconfirmed' WHEN host.availability_state <> 'shared' THEN 'not_shared'
                  WHEN EXISTS (SELECT 1 FROM public.programme_programmehostavailabilitywindow period WHERE period.host_id = host.id
                      AND (period.starts_at < current_edition.starts_at OR period.ends_at > current_edition.ends_at)) THEN 'outside_edition'
                  WHEN NOT EXISTS (SELECT 1 FROM public.programme_programmehostavailabilitywindow period WHERE period.host_id = host.id) THEN 'unavailable' ELSE 'shared' END)
              OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember member JOIN public.scheduling_schedulingplacementhostpresence presence ON presence.placement_id = member.placement_id
                  WHERE member.revision_id = selected_revision AND presence.host_relationship_id = host.id)) THEN RETURN FALSE; END IF;
    IF jsonb_array_length(value->2->'spaces') <> (SELECT count(DISTINCT placement.space_selection_id) FROM public.scheduling_schedulingcandidatemember member
            JOIN public.scheduling_schedulingplacementrevision placement ON placement.id = member.placement_id WHERE member.revision_id = selected_revision)
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(value->2->'spaces') AS input(content)
            LEFT JOIN public.venues_editionspaceselection space ON space.id = (input.content->>'id')::uuid
            LEFT JOIN public.venues_editionvenueselection venue ON venue.id = space.venue_selection_id
            LEFT JOIN public.venues_venueproperty property ON property.id = venue.property_id
            WHERE space.organization_id IS DISTINCT FROM expected_organization OR space.edition_id IS DISTINCT FROM expected_edition
              OR space.aggregate_version IS DISTINCT FROM (input.content->>'version')::bigint OR space.current_availability_version IS DISTINCT FROM (input.content->>'availability_version')::bigint
              OR (input.content->>'active')::boolean IS DISTINCT FROM (space.lifecycle = 'active' AND venue.lifecycle = 'active' AND property.lifecycle = 'active'
                  AND NOT EXISTS (SELECT 1 FROM public.venues_editionspacemember member JOIN public.venues_venuespace physical ON physical.id = member.source_space_id
                      WHERE member.space_selection_id = space.id AND NOT physical.is_active))
              OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember member JOIN public.scheduling_schedulingplacementrevision placement ON placement.id = member.placement_id
                  WHERE member.revision_id = selected_revision AND placement.space_selection_id = space.id)) THEN RETURN FALSE; END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object('id', live.key, 'version', live.version) ORDER BY live.key), '[]'::jsonb)
      INTO current_busy FROM (SELECT DISTINCT
          substring(encode(sha256(convert_to('venue-physical-conflict@1:' || expected_edition::text || ':' || booking.id::text, 'UTF8')), 'hex'), 1, 32)::uuid AS key,
          booking.aggregate_version AS version
        FROM public.venues_venuebookingoccupancy occupancy JOIN public.venues_venuebooking booking ON booking.id = occupancy.booking_id
        WHERE occupancy.organization_id = expected_organization AND occupancy.active AND booking.lifecycle = 'active'
          AND occupancy.occupied_range && tstzrange(current_edition.starts_at, current_edition.ends_at, '[)')
          AND occupancy.source_space_id IN (SELECT physical.source_space_id FROM public.scheduling_schedulingcandidatemember member
              JOIN public.scheduling_schedulingplacementrevision placement ON placement.id = member.placement_id
              JOIN public.venues_editionspacemember physical ON physical.space_selection_id = placement.space_selection_id
              WHERE member.revision_id = selected_revision)
      ) live;
    SELECT COALESCE(jsonb_agg(input.content ORDER BY input.content->>'id'), '[]'::jsonb) INTO recorded_busy FROM jsonb_array_elements(value->2->'busy_sources') AS input(content);
    IF current_busy <> recorded_busy THEN RETURN FALSE; END IF;
    IF jsonb_array_length(value->2->'physical_bindings') <> (SELECT count(*) FROM public.scheduling_schedulingcandidatemember WHERE revision_id = selected_revision)
       OR EXISTS (SELECT 1 FROM jsonb_array_elements(value->2->'physical_bindings') AS input(content)
            LEFT JOIN public.scheduling_schedulingcandidatemember member ON member.revision_id = selected_revision AND member.placement_id = (input.content->>'placement_id')::uuid
            LEFT JOIN LATERAL (SELECT booking.id, booking.review_state FROM public.venues_venueschedulingbinding binding
                JOIN public.venues_venuebooking booking ON booking.id = binding.booking_id AND booking.lifecycle = 'active'
                WHERE binding.placement_id = member.placement_id) AS live_binding ON TRUE
            WHERE member.id IS NULL OR input.content->>'state' IS DISTINCT FROM (CASE WHEN live_binding.id IS NULL THEN 'unreserved'
                WHEN live_binding.review_state = 'approved' THEN 'reserved_approved' ELSE 'reserved_draft' END)) THEN RETURN FALSE; END IF;
    IF jsonb_array_length(value->2->'reservations') <> (SELECT count(*) FROM public.scheduling_schedulingcandidatemember member
        JOIN public.venues_venueschedulingbinding binding ON binding.placement_id = member.placement_id
        JOIN public.venues_venuebooking booking ON booking.id = binding.booking_id AND booking.lifecycle = 'active'
        WHERE member.revision_id = selected_revision) THEN RETURN FALSE; END IF;
    IF EXISTS (SELECT 1 FROM jsonb_array_elements(value->2->'reservations') AS input(content)
        LEFT JOIN public.venues_venueschedulingbinding binding ON binding.booking_id = (input.content->>'booking_id')::uuid
        LEFT JOIN public.venues_venuebooking booking ON booking.id = binding.booking_id
        WHERE binding.organization_id IS DISTINCT FROM expected_organization OR binding.edition_id IS DISTINCT FROM expected_edition
          OR binding.placement_id::text IS DISTINCT FROM input.content->>'placement_id' OR booking.lifecycle IS DISTINCT FROM 'active'
          OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember WHERE revision_id = selected_revision AND placement_id = binding.placement_id)
          OR booking.aggregate_version IS DISTINCT FROM (input.content->>'version')::bigint OR booking.review_state IS DISTINCT FROM input.content->>'review_state') THEN RETURN FALSE; END IF;
    RETURN TRUE;
END;
$$ LANGUAGE plpgsql VOLATILE STRICT
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_scheduling_row()
RETURNS trigger AS $$
DECLARE
    body jsonb;
    prior jsonb;
    edition_row record;
    target record;
    owner_ref record;
    principal_id uuid;
    version_value bigint;
    total bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Scheduling rows require retained lifecycle transitions' USING ERRCODE = '23514';
    END IF;
    body := to_jsonb(NEW);
    SELECT edition.organization_id, edition.lifecycle, edition.aggregate_version
      INTO edition_row FROM public.events_eventedition edition
      JOIN public.organizations_conventionseries series ON series.id = edition.series_id AND series.organization_id = edition.organization_id
     WHERE edition.id = NEW.edition_id FOR UPDATE OF edition;
    IF edition_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR edition_row.lifecycle NOT IN ('draft', 'preparing', 'ready', 'live') THEN
        RAISE EXCEPTION 'Scheduling requires a coherent writable edition' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF TG_TABLE_NAME NOT IN ('scheduling_schedulingeditioncontrol', 'scheduling_schedulingserviceday', 'scheduling_schedulingoccurrence', 'scheduling_schedulingcandidate') THEN
            RAISE EXCEPTION 'Scheduling evidence is immutable' USING ERRCODE = '23514';
        END IF;
        prior := to_jsonb(OLD);
        IF body - ARRAY['aggregate_version', 'lifecycle', 'updated_at'] IS DISTINCT FROM prior - ARRAY['aggregate_version', 'lifecycle', 'updated_at']
           OR (body->>'aggregate_version')::bigint <> (prior->>'aggregate_version')::bigint + 1
           OR prior->>'lifecycle' IN ('retired', 'archived') THEN
            RAISE EXCEPTION 'Scheduling identity, terminal state or version changed illegally' USING ERRCODE = '23514';
        END IF;
    ELSIF body ? 'aggregate_version' AND (body->>'aggregate_version')::bigint <> 1 THEN
        RAISE EXCEPTION 'Scheduling aggregates begin at version one' USING ERRCODE = '23514';
    END IF;
    IF body ? 'aggregate_version' AND TG_TABLE_NAME <> 'scheduling_schedulingeditioncontrol' THEN
        version_value := (body->>'aggregate_version')::bigint;
        IF TG_TABLE_NAME = 'scheduling_schedulingcandidate' THEN
            IF version_value > (CASE WHEN body->>'lifecycle' = 'archived' THEN 10001 ELSE 10000 END) THEN
                RAISE EXCEPTION 'Scheduling candidate history limit exceeded' USING ERRCODE = '23514';
            END IF;
        ELSIF version_value > (CASE WHEN body->>'lifecycle' = 'retired' THEN 1001 ELSE 1000 END) THEN
            RAISE EXCEPTION 'Scheduling metadata history limit exceeded' USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF body->>'lifecycle' IS DISTINCT FROM (CASE WHEN TG_TABLE_NAME = 'scheduling_schedulingcandidate' THEN 'draft' ELSE 'active' END) THEN
                RAISE EXCEPTION 'Scheduling aggregates begin in their planning lifecycle' USING ERRCODE = '23514';
            END IF;
            EXECUTE format('SELECT count(*) FROM public.%I WHERE edition_id = $1', TG_TABLE_NAME) INTO total USING NEW.edition_id;
            IF total >= (CASE TG_TABLE_NAME WHEN 'scheduling_schedulingserviceday' THEN 128 WHEN 'scheduling_schedulingcandidate' THEN 100 ELSE 2000 END) THEN
                RAISE EXCEPTION 'Scheduling retained record limit exceeded' USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    principal_id := COALESCE((body->>'actor_id')::uuid, CASE WHEN TG_OP = 'INSERT' THEN (body->>'created_by_id')::uuid ELSE NULL END);
    IF principal_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.identity_account WHERE id = principal_id AND is_active AND email_verified_at IS NOT NULL AND account_kind = 'person'
    ) THEN
        RAISE EXCEPTION 'Scheduling evidence requires a current verified person' USING ERRCODE = '23514';
    END IF;
    IF body ? 'reason' AND (btrim(body->>'reason') = '' OR body->>'reason' <> normalize(body->>'reason', NFC) OR body->>'reason' ~ '[[:cntrl:]]') THEN
        RAISE EXCEPTION 'Scheduling evidence requires normalized human rationale' USING ERRCODE = '23514';
    END IF;
    FOR owner_ref IN SELECT * FROM (VALUES
        ('programme_item_id', 'programme_programmeitem'), ('space_selection_id', 'venues_editionspaceselection'),
        ('host_relationship_id', 'programme_programmehostrelationship'), ('day_id', 'scheduling_schedulingserviceday'),
        ('occurrence_id', 'scheduling_schedulingoccurrence'), ('other_occurrence_id', 'scheduling_schedulingoccurrence'),
        ('candidate_id', 'scheduling_schedulingcandidate'), ('revision_id', 'scheduling_schedulingcandidaterevision'),
        ('candidate_revision_id', 'scheduling_schedulingcandidaterevision'), ('source_revision_id', 'scheduling_schedulingcandidaterevision'),
        ('introduced_in_id', 'scheduling_schedulingcandidaterevision'), ('occurrence_revision_id', 'scheduling_schedulingoccurrencerevision'),
        ('day_revision_id', 'scheduling_schedulingservicedayrevision'), ('placement_id', 'scheduling_schedulingplacementrevision'),
        ('evaluation_id', 'scheduling_schedulingevaluation'), ('conflict_id', 'scheduling_schedulingconflict'),
        ('previous_booking_id', 'venues_venuebooking')
    ) AS refs(field_name, table_name) LOOP
        IF body->>owner_ref.field_name IS NOT NULL THEN
            EXECUTE format('SELECT organization_id, edition_id FROM public.%I WHERE id = $1', owner_ref.table_name)
               INTO target USING (body->>owner_ref.field_name)::uuid;
            IF target.organization_id IS DISTINCT FROM NEW.organization_id OR target.edition_id IS DISTINCT FROM NEW.edition_id THEN
                RAISE EXCEPTION 'Scheduling dependency owner scope mismatch' USING ERRCODE = '23514';
            END IF;
        END IF;
    END LOOP;
    IF TG_TABLE_NAME = 'scheduling_schedulingoccurrence' AND body->>'lifecycle' = 'active' AND NOT EXISTS (
        SELECT 1 FROM public.programme_programmeitem WHERE id = (body->>'programme_item_id')::uuid AND lifecycle = 'active'
    ) THEN
        RAISE EXCEPTION 'Scheduling occurrence requires an active Programme item' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'scheduling_schedulingcommandreceipt' THEN
        IF NEW.control_version <> (SELECT aggregate_version FROM public.scheduling_schedulingeditioncontrol WHERE edition_id = NEW.edition_id)
           OR NEW.request_digest !~ '^[0-9a-f]{64}$' OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$' THEN
            RAISE EXCEPTION 'Scheduling receipt does not match the active control version' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME IN ('scheduling_schedulingservicedayrevision', 'scheduling_schedulingoccurrencerevision', 'scheduling_schedulingcandidaterevision') THEN
        EXECUTE format('SELECT aggregate_version, lifecycle FROM public.%I WHERE id = $1',
            replace(TG_TABLE_NAME, 'revision', '')) INTO target USING
            (body->>(CASE TG_TABLE_NAME WHEN 'scheduling_schedulingservicedayrevision' THEN 'day_id' WHEN 'scheduling_schedulingoccurrencerevision' THEN 'occurrence_id' ELSE 'candidate_id' END))::uuid;
        IF target.aggregate_version IS DISTINCT FROM NEW.sequence OR (body ? 'lifecycle' AND body->>'lifecycle' IS DISTINCT FROM target.lifecycle) THEN
            RAISE EXCEPTION 'Scheduling revision does not match the current aggregate' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'scheduling_schedulingplacementrevision' THEN
        IF NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingservicedayrevision revision JOIN public.scheduling_schedulingserviceday day ON day.id = revision.day_id
            WHERE revision.id = NEW.day_revision_id AND revision.sequence = day.aggregate_version AND day.lifecycle = 'active')
           OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingoccurrencerevision revision JOIN public.scheduling_schedulingoccurrence occurrence ON occurrence.id = revision.occurrence_id
            WHERE revision.id = NEW.occurrence_revision_id AND revision.sequence = occurrence.aggregate_version AND occurrence.lifecycle = 'active') THEN
            RAISE EXCEPTION 'Scheduling placement requires current active metadata revisions' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'scheduling_schedulingevaluation' THEN
        IF public.maru_scheduling_evidence_shape(NEW.source_evidence) IS DISTINCT FROM TRUE
           OR NEW.dependency_digest <> encode(sha256(convert_to(public.maru_scheduling_canonical_json(jsonb_build_object('sources', NEW.source_evidence)), 'UTF8')), 'hex')
           OR NEW.source_evidence->0->>'revision_id' IS DISTINCT FROM NEW.revision_id::text
           OR NEW.source_evidence->0->>'manifest_digest' IS DISTINCT FROM (SELECT manifest_digest FROM public.scheduling_schedulingcandidaterevision WHERE id = NEW.revision_id) THEN
            RAISE EXCEPTION 'Scheduling evaluation requires closed calendar-free exact dependency evidence' USING ERRCODE = '23514';
        END IF;
        IF NEW.is_complete AND public.maru_scheduling_evidence_is_current(NEW.source_evidence, NEW.organization_id, NEW.edition_id) IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Scheduling complete evaluation requires current complete source versions' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'scheduling_schedulingconflict' THEN
        IF NEW.code NOT IN (
            'edition_unavailable','day_changed','day_retired','edition_bounds','day_bounds','minute_grid','occurrence_changed','occurrence_retired',
            'programme_unavailable','item_retired','host_required','host_not_current','host_source_unavailable','host_unavailable','host_outside_availability','host_outside_preference','host_overlap',
            'venue_unavailable','venue_inactive','venue_capacity','venue_availability_missing','venue_hard_availability','candidate_room_overlap','reserved_room_overlap','turnover_overlap','evaluation_limit')
           OR NEW.severity IS DISTINCT FROM (CASE WHEN NEW.code IN ('host_outside_preference','turnover_overlap') THEN 'warning'
              WHEN NEW.code IN ('edition_unavailable','programme_unavailable','host_source_unavailable','venue_unavailable','evaluation_limit') THEN 'unavailable' ELSE 'blocker' END)
           OR NEW.source_code IS DISTINCT FROM (CASE WHEN NEW.code IN ('edition_unavailable','day_changed','day_retired','edition_bounds','day_bounds','minute_grid','occurrence_changed','occurrence_retired','evaluation_limit') THEN 'scheduling.service-day-and-placement@1'
              WHEN NEW.code IN ('programme_unavailable','item_retired','host_required','host_not_current','host_source_unavailable','host_unavailable','host_outside_availability','host_outside_preference','host_overlap') THEN 'programme.item-and-host-availability@1' ELSE 'venues.physical-scheduling-dependencies@1' END) THEN
            RAISE EXCEPTION 'Scheduling finding source, code and severity must match the closed contract' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'scheduling_schedulingwarningacknowledgement' THEN
        SELECT evaluation.source_evidence INTO target FROM public.scheduling_schedulingconflict conflict
          JOIN public.scheduling_schedulingevaluation evaluation ON evaluation.id = conflict.evaluation_id
          WHERE conflict.id = NEW.conflict_id AND conflict.severity = 'warning' AND evaluation.is_complete;
        IF target.source_evidence IS NULL OR public.maru_scheduling_evidence_is_current(target.source_evidence, NEW.organization_id, NEW.edition_id) IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Scheduling warning dependency evidence is stale or unavailable' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_scheduling_graph()
RETURNS trigger AS $$
DECLARE
    body jsonb := to_jsonb(NEW);
    result_row record;
    previous_row record;
    parent_row record;
    edition_row record;
    count_value bigint;
    digest_value text;
    expected_operation text;
    object_id uuid;
    version_value bigint;
    expected_capability text;
    same_change boolean;
BEGIN
    CASE TG_TABLE_NAME
    WHEN 'scheduling_schedulingeditioncontrol' THEN
        IF NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcommandreceipt WHERE edition_id = NEW.edition_id AND control_version = NEW.aggregate_version) THEN
            RAISE EXCEPTION 'Scheduling control lacks its exact command receipt' USING ERRCODE = '23514';
        END IF;
    WHEN 'scheduling_schedulingserviceday', 'scheduling_schedulingoccurrence', 'scheduling_schedulingcandidate' THEN
        EXECUTE format('SELECT to_jsonb(row) AS body FROM public.%I row WHERE %I = $1 AND sequence = $2',
            TG_TABLE_NAME || 'revision', CASE TG_TABLE_NAME WHEN 'scheduling_schedulingserviceday' THEN 'day_id' WHEN 'scheduling_schedulingoccurrence' THEN 'occurrence_id' ELSE 'candidate_id' END)
            INTO result_row USING NEW.id, NEW.aggregate_version;
        IF result_row.body IS NULL OR (TG_TABLE_NAME <> 'scheduling_schedulingcandidate' AND result_row.body->>'lifecycle' IS DISTINCT FROM NEW.lifecycle)
           OR (TG_TABLE_NAME = 'scheduling_schedulingcandidate' AND (result_row.body->>'operation' = 'candidate_archive') IS DISTINCT FROM (NEW.lifecycle = 'archived')) THEN
            RAISE EXCEPTION 'Scheduling aggregate lacks matching immutable history' USING ERRCODE = '23514';
        END IF;
    WHEN 'scheduling_schedulingservicedayrevision' THEN
        SELECT * INTO parent_row FROM public.scheduling_schedulingserviceday WHERE id = NEW.day_id;
        IF parent_row.aggregate_version < NEW.sequence THEN
            RAISE EXCEPTION 'Scheduling day revision is ahead of its aggregate' USING ERRCODE = '23514';
        END IF;
        IF NEW.sequence > 1 AND NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingservicedayrevision WHERE day_id = NEW.day_id AND sequence = NEW.sequence - 1 AND lifecycle = 'active') THEN
            RAISE EXCEPTION 'Scheduling day history is not contiguous' USING ERRCODE = '23514';
        END IF;
        IF NEW.lifecycle = 'active' THEN
            SELECT aggregate_version, starts_on::timestamp AT TIME ZONE time_zone AS starts_at,
                   (ends_on + 1)::timestamp AT TIME ZONE time_zone AS ends_at
              INTO edition_row FROM public.events_eventedition WHERE id = NEW.edition_id;
            IF NEW.edition_version <> edition_row.aggregate_version OR edition_row.starts_at IS NULL OR edition_row.ends_at IS NULL
               OR NEW.starts_at < edition_row.starts_at OR NEW.ends_at > edition_row.ends_at
               OR date_trunc('minute', NEW.starts_at) <> NEW.starts_at OR date_trunc('minute', NEW.ends_at) <> NEW.ends_at THEN
                RAISE EXCEPTION 'Scheduling day requires current minute-aligned edition bounds' USING ERRCODE = '23514';
            END IF;
            IF parent_row.aggregate_version = NEW.sequence AND parent_row.lifecycle = 'active' THEN
                IF EXISTS (SELECT 1 FROM public.scheduling_schedulingserviceday day
                    JOIN public.scheduling_schedulingservicedayrevision revision ON revision.day_id = day.id AND revision.sequence = day.aggregate_version
                    WHERE day.edition_id = NEW.edition_id AND day.lifecycle = 'active' AND day.id <> NEW.day_id
                      AND revision.starts_at < NEW.ends_at AND NEW.starts_at < revision.ends_at)
                   OR (SELECT count(*) FROM public.scheduling_schedulingserviceday WHERE edition_id = NEW.edition_id AND lifecycle = 'active') > 32 THEN
                    RAISE EXCEPTION 'Scheduling active service-day windows overlap or exceed the bound' USING ERRCODE = '23514';
                END IF;
            END IF;
        END IF;
        expected_operation := CASE WHEN NEW.sequence = 1 THEN 'day_create' WHEN NEW.lifecycle = 'retired' THEN 'day_retire' ELSE 'day_revise' END;
        object_id := NEW.day_id; version_value := NEW.sequence;
    WHEN 'scheduling_schedulingoccurrencerevision' THEN
        IF NEW.sequence > 1 AND NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingoccurrencerevision WHERE occurrence_id = NEW.occurrence_id AND sequence = NEW.sequence - 1 AND lifecycle = 'active') THEN
            RAISE EXCEPTION 'Scheduling occurrence history is not contiguous' USING ERRCODE = '23514';
        END IF;
        IF NEW.lifecycle = 'active' AND NEW.group_key IS NOT NULL
           AND NEW.sequence = (SELECT aggregate_version FROM public.scheduling_schedulingoccurrence WHERE id = NEW.occurrence_id)
           AND EXISTS (
            SELECT 1 FROM public.scheduling_schedulingoccurrence occurrence
            JOIN public.scheduling_schedulingoccurrencerevision revision ON revision.occurrence_id = occurrence.id AND revision.sequence = occurrence.aggregate_version
            WHERE occurrence.edition_id = NEW.edition_id AND occurrence.lifecycle = 'active' AND occurrence.id <> NEW.occurrence_id
              AND revision.group_key = NEW.group_key AND revision.group_sequence = NEW.group_sequence
        ) THEN
            RAISE EXCEPTION 'Scheduling active occurrence group sequence is already used' USING ERRCODE = '23514';
        END IF;
        IF NEW.lifecycle = 'retired' AND EXISTS (SELECT 1 FROM public.venues_venueschedulingbinding binding JOIN public.venues_venuebooking booking ON booking.id = binding.booking_id
            WHERE binding.occurrence_id = NEW.occurrence_id AND booking.lifecycle = 'active') THEN
            RAISE EXCEPTION 'Scheduling occurrence still owns a physical reservation' USING ERRCODE = '23514';
        END IF;
        expected_operation := CASE WHEN NEW.sequence = 1 THEN 'occurrence_create' WHEN NEW.lifecycle = 'retired' THEN 'occurrence_retire' ELSE 'occurrence_revise' END;
        object_id := NEW.occurrence_id; version_value := NEW.sequence;
    WHEN 'scheduling_schedulingcandidaterevision' THEN
        SELECT count(*), encode(sha256(convert_to('{"members":[' || COALESCE(string_agg(
            '{"occurrence_id":' || to_jsonb(occurrence_id::text)::text || ',"placement_id":' || to_jsonb(placement_id::text)::text || '}', ',' ORDER BY occurrence_id), '') || ']}', 'UTF8')), 'hex')
          INTO count_value, digest_value FROM public.scheduling_schedulingcandidatemember WHERE revision_id = NEW.id;
        IF count_value <> NEW.placement_count OR digest_value <> NEW.manifest_digest OR btrim(NEW.label) = '' THEN
            RAISE EXCEPTION 'Scheduling candidate manifest is incomplete or changed' USING ERRCODE = '23514';
        END IF;
        IF NEW.sequence = 1 THEN
            IF NEW.operation NOT IN ('candidate_create', 'candidate_copy') OR (NEW.operation = 'candidate_create' AND (NEW.placement_count <> 0 OR NEW.source_revision_id IS NOT NULL)) THEN
                RAISE EXCEPTION 'Scheduling initial candidate revision has invalid provenance' USING ERRCODE = '23514';
            END IF;
        ELSE
            SELECT * INTO previous_row FROM public.scheduling_schedulingcandidaterevision WHERE candidate_id = NEW.candidate_id AND sequence = NEW.sequence - 1;
            IF previous_row.id IS NULL OR previous_row.operation = 'candidate_archive' OR NEW.operation NOT IN ('placement_set', 'placement_remove', 'candidate_restore', 'candidate_archive') THEN
                RAISE EXCEPTION 'Scheduling candidate history is not contiguous' USING ERRCODE = '23514';
            END IF;
            IF NEW.operation = 'candidate_archive' AND NEW.manifest_digest <> previous_row.manifest_digest THEN
                RAISE EXCEPTION 'Scheduling archival cannot rewrite the manifest' USING ERRCODE = '23514';
            END IF;
        END IF;
        IF NEW.operation IN ('candidate_copy', 'candidate_restore') THEN
            SELECT * INTO result_row FROM public.scheduling_schedulingcandidaterevision WHERE id = NEW.source_revision_id;
            IF result_row.id IS NULL OR result_row.manifest_digest <> NEW.manifest_digest OR result_row.id = NEW.id
               OR (NEW.operation = 'candidate_restore' AND (result_row.candidate_id <> NEW.candidate_id OR result_row.sequence >= NEW.sequence)) THEN
                RAISE EXCEPTION 'Scheduling candidate copy or restore has mismatched source' USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.source_revision_id IS NOT NULL THEN
            RAISE EXCEPTION 'Scheduling operation cannot invent copy provenance' USING ERRCODE = '23514';
        END IF;
        IF NEW.operation = 'placement_set' THEN
            SELECT occurrence.occurrence_id AS occurrence_id, placement.id AS placement_id INTO result_row
              FROM public.scheduling_schedulingplacementrevision placement
              JOIN public.scheduling_schedulingoccurrencerevision occurrence ON occurrence.id = placement.occurrence_revision_id
              WHERE placement.introduced_in_id = NEW.id;
            IF result_row.placement_id IS NULL OR EXISTS (
                (SELECT occurrence_id, placement_id FROM public.scheduling_schedulingcandidatemember WHERE revision_id = previous_row.id AND occurrence_id <> result_row.occurrence_id
                 EXCEPT SELECT occurrence_id, placement_id FROM public.scheduling_schedulingcandidatemember WHERE revision_id = NEW.id)
                UNION ALL
                (SELECT occurrence_id, placement_id FROM public.scheduling_schedulingcandidatemember WHERE revision_id = NEW.id AND occurrence_id <> result_row.occurrence_id
                 EXCEPT SELECT occurrence_id, placement_id FROM public.scheduling_schedulingcandidatemember WHERE revision_id = previous_row.id)
            ) THEN
                RAISE EXCEPTION 'Scheduling placement edit changed unrelated manifest members' USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.operation = 'placement_remove' THEN
            IF NEW.placement_count <> previous_row.placement_count - 1 OR EXISTS (
                SELECT occurrence_id, placement_id FROM public.scheduling_schedulingcandidatemember WHERE revision_id = NEW.id
                EXCEPT SELECT occurrence_id, placement_id FROM public.scheduling_schedulingcandidatemember WHERE revision_id = previous_row.id
            ) THEN
                RAISE EXCEPTION 'Scheduling unplacement must remove exactly one existing occurrence' USING ERRCODE = '23514';
            END IF;
        END IF;
        expected_operation := NEW.operation; object_id := NEW.candidate_id; version_value := NEW.sequence;
    WHEN 'scheduling_schedulingcandidatemember' THEN
        SELECT child.xmin = parent.xmin INTO same_change
          FROM public.scheduling_schedulingcandidatemember child JOIN public.scheduling_schedulingcandidaterevision parent ON parent.id = child.revision_id
          WHERE child.id = NEW.id;
        IF same_change IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Scheduling manifest members require the same command as their immutable revision' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingplacementrevision placement
            JOIN public.scheduling_schedulingoccurrencerevision occurrence ON occurrence.id = placement.occurrence_revision_id
            WHERE placement.id = NEW.placement_id AND occurrence.occurrence_id = NEW.occurrence_id) THEN
            RAISE EXCEPTION 'Scheduling manifest changes stable occurrence identity' USING ERRCODE = '23514';
        END IF;
    WHEN 'scheduling_schedulingplacementrevision' THEN
        SELECT child.xmin = parent.xmin INTO same_change
          FROM public.scheduling_schedulingplacementrevision child JOIN public.scheduling_schedulingcandidaterevision parent ON parent.id = child.introduced_in_id
          WHERE child.id = NEW.id;
        IF same_change IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Scheduling placement requires the same command as its introducing revision' USING ERRCODE = '23514';
        END IF;
        SELECT * INTO parent_row FROM public.scheduling_schedulingcandidaterevision WHERE id = NEW.introduced_in_id;
        IF parent_row.operation <> 'placement_set' OR NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember WHERE revision_id = NEW.introduced_in_id AND placement_id = NEW.id)
           OR (SELECT count(*) FROM public.scheduling_schedulingplacementhostpresence WHERE placement_id = NEW.id) <> NEW.host_presence_count
           OR (SELECT count(*) FROM public.scheduling_schedulingplacementrevision WHERE introduced_in_id = NEW.introduced_in_id) <> 1
           OR date_trunc('minute', NEW.setup_starts_at) <> NEW.setup_starts_at OR date_trunc('minute', NEW.effective_starts_at) <> NEW.effective_starts_at
           OR date_trunc('minute', NEW.effective_ends_at) <> NEW.effective_ends_at OR date_trunc('minute', NEW.teardown_ends_at) <> NEW.teardown_ends_at THEN
            RAISE EXCEPTION 'Scheduling placement evidence is incomplete or malformed' USING ERRCODE = '23514';
        END IF;
    WHEN 'scheduling_schedulingplacementhostpresence' THEN
        SELECT child.xmin = parent.xmin INTO same_change
          FROM public.scheduling_schedulingplacementhostpresence child JOIN public.scheduling_schedulingplacementrevision parent ON parent.id = child.placement_id
          WHERE child.id = NEW.id;
        IF same_change IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Scheduling host presence requires the same command as its immutable placement' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingplacementrevision placement
            JOIN public.scheduling_schedulingoccurrencerevision revision ON revision.id = placement.occurrence_revision_id
            JOIN public.scheduling_schedulingoccurrence occurrence ON occurrence.id = revision.occurrence_id
            JOIN public.programme_programmehostrelationship host ON host.item_id = occurrence.programme_item_id
            WHERE placement.id = NEW.placement_id AND host.id = NEW.host_relationship_id
              AND NEW.starts_at >= placement.setup_starts_at AND NEW.ends_at <= placement.teardown_ends_at)
           OR date_trunc('minute', NEW.starts_at) <> NEW.starts_at OR date_trunc('minute', NEW.ends_at) <> NEW.ends_at THEN
            RAISE EXCEPTION 'Scheduling host presence has no exact placement purpose' USING ERRCODE = '23514';
        END IF;
    WHEN 'scheduling_schedulingevaluation' THEN
        IF (SELECT count(*) FROM public.scheduling_schedulingconflict WHERE evaluation_id = NEW.id) <> NEW.conflict_count
           OR NEW.conflict_count > 10000
           OR NEW.is_complete IS DISTINCT FROM NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingconflict WHERE evaluation_id = NEW.id AND severity = 'unavailable') THEN
            RAISE EXCEPTION 'Scheduling evaluation is incomplete or misclassified' USING ERRCODE = '23514';
        END IF;
        expected_operation := 'evaluation_record'; object_id := NEW.id; version_value := 1;
    WHEN 'scheduling_schedulingconflict' THEN
        SELECT child.xmin = parent.xmin INTO same_change
          FROM public.scheduling_schedulingconflict child JOIN public.scheduling_schedulingevaluation parent ON parent.id = child.evaluation_id
          WHERE child.id = NEW.id;
        IF same_change IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Scheduling findings require the same command as their immutable evaluation' USING ERRCODE = '23514';
        END IF;
        SELECT * INTO parent_row FROM public.scheduling_schedulingevaluation WHERE id = NEW.evaluation_id;
        IF NEW.fingerprint <> encode(sha256(convert_to(public.maru_scheduling_canonical_json(jsonb_build_object(
            'dependency_digest', parent_row.dependency_digest, 'source_code', NEW.source_code, 'code', NEW.code, 'severity', NEW.severity,
            'occurrence_id', NEW.occurrence_id, 'other_occurrence_id', NEW.other_occurrence_id)), 'UTF8')), 'hex')
           OR (NEW.occurrence_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember WHERE revision_id = parent_row.revision_id AND occurrence_id = NEW.occurrence_id))
           OR (NEW.other_occurrence_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingcandidatemember WHERE revision_id = parent_row.revision_id AND occurrence_id = NEW.other_occurrence_id)) THEN
            RAISE EXCEPTION 'Scheduling finding is not bound to its exact evaluation' USING ERRCODE = '23514';
        END IF;
    WHEN 'scheduling_schedulingwarningacknowledgement' THEN
        IF NOT EXISTS (SELECT 1 FROM public.scheduling_schedulingconflict conflict
            JOIN public.scheduling_schedulingevaluation evaluation ON evaluation.id = conflict.evaluation_id
            JOIN public.scheduling_schedulingcandidaterevision revision ON revision.id = evaluation.revision_id
            JOIN public.scheduling_schedulingcandidate candidate ON candidate.id = revision.candidate_id
            WHERE conflict.id = NEW.conflict_id AND conflict.severity = 'warning' AND evaluation.is_complete
              AND candidate.lifecycle = 'draft' AND candidate.aggregate_version = revision.sequence) THEN
            RAISE EXCEPTION 'Scheduling acknowledgement is not for a current complete warning' USING ERRCODE = '23514';
        END IF;
        expected_operation := 'warning_acknowledge'; object_id := NEW.id; version_value := 1;
    WHEN 'scheduling_schedulingreservationintent' THEN
        expected_operation := NEW.operation; object_id := NEW.id; version_value := 1;
    WHEN 'scheduling_schedulingcommandreceipt' THEN
        CASE
        WHEN NEW.operation IN ('day_create', 'day_revise', 'day_retire') THEN
            SELECT to_jsonb(revision) AS body INTO result_row FROM public.scheduling_schedulingservicedayrevision revision
             WHERE day_id = NEW.result_object_id AND sequence = NEW.resulting_version;
            expected_capability := 'scheduling.manage_service_days';
        WHEN NEW.operation IN ('occurrence_create', 'occurrence_revise', 'occurrence_retire') THEN
            SELECT to_jsonb(revision) AS body INTO result_row FROM public.scheduling_schedulingoccurrencerevision revision
             WHERE occurrence_id = NEW.result_object_id AND sequence = NEW.resulting_version;
            expected_capability := 'scheduling.manage_occurrences';
        WHEN NEW.operation IN ('candidate_create', 'candidate_copy', 'placement_set', 'placement_remove', 'candidate_restore', 'candidate_archive') THEN
            SELECT to_jsonb(revision) AS body INTO result_row FROM public.scheduling_schedulingcandidaterevision revision
             WHERE candidate_id = NEW.result_object_id AND sequence = NEW.resulting_version AND operation = NEW.operation;
            expected_capability := 'scheduling.manage_candidates';
        WHEN NEW.operation = 'evaluation_record' AND NEW.resulting_version = 1 THEN
            SELECT to_jsonb(evaluation) AS body INTO result_row FROM public.scheduling_schedulingevaluation evaluation WHERE id = NEW.result_object_id;
            expected_capability := 'scheduling.evaluate_candidates';
        WHEN NEW.operation = 'warning_acknowledge' AND NEW.resulting_version = 1 THEN
            SELECT to_jsonb(acknowledgement) AS body INTO result_row FROM public.scheduling_schedulingwarningacknowledgement acknowledgement WHERE id = NEW.result_object_id;
            expected_capability := 'scheduling.acknowledge_warnings';
        WHEN NEW.operation IN ('reservation_replace', 'reservation_cancel') AND NEW.resulting_version = 1 THEN
            SELECT to_jsonb(intent) AS body INTO result_row FROM public.scheduling_schedulingreservationintent intent
             WHERE id = NEW.result_object_id AND command_receipt_id = NEW.id AND operation = NEW.operation;
            expected_capability := 'scheduling.manage_reservations';
        ELSE
            RAISE EXCEPTION 'Scheduling receipt has an unknown result operation' USING ERRCODE = '23514';
        END CASE;
        IF result_row.body IS NULL OR result_row.body->>'organization_id' IS DISTINCT FROM NEW.organization_id::text
           OR result_row.body->>'edition_id' IS DISTINCT FROM NEW.edition_id::text OR result_row.body->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
           OR result_row.body->>'reason' IS DISTINCT FROM NEW.reason OR (result_row.body->>'occurred_at')::timestamptz IS DISTINCT FROM NEW.occurred_at THEN
            RAISE EXCEPTION 'Scheduling receipt is not bound to its attributed result' USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.audit_auditevent audit
            JOIN public.effects_domainevent event ON event.causation_id = audit.id
            JOIN public.effects_outboxmessage outbox ON outbox.event_id = event.id AND outbox.organization_id = NEW.organization_id
             AND outbox.destination = 'internal' AND outbox.workload_pool = 'default'
            WHERE audit.principal_kind = 'account' AND audit.principal_id = NEW.actor_id
              AND audit.organization_id = NEW.organization_id AND audit.event_edition_id = NEW.edition_id
              AND audit.operation = 'scheduling.command.' || NEW.operation AND audit.capability_code = expected_capability
              AND audit.target_type = 'scheduling.object' AND audit.target_id = NEW.result_object_id
              AND audit.outcome = 'allow' AND 'audit' = ANY(audit.obligations)
              AND audit.correlation_id = NEW.correlation_id AND audit.source_channel = NEW.source_channel
              AND audit.idempotency_key_hash = encode(sha256(convert_to(NEW.idempotency_key::text, 'UTF8')), 'hex')
              AND audit.occurred_at = NEW.occurred_at AND event.occurred_at = NEW.occurred_at
              AND event.organization_id = NEW.organization_id AND event.event_edition_id = NEW.edition_id
              AND event.event_name = 'scheduling.planning.changed.v1' AND event.schema_version = 1
              AND event.aggregate_type = 'scheduling.edition' AND event.aggregate_id = NEW.edition_id AND event.aggregate_version = NEW.control_version
              AND event.actor_kind = 'account' AND event.actor_id = NEW.actor_id AND event.correlation_id = NEW.correlation_id
              AND event.payload = jsonb_build_object('operation', NEW.operation) AND event.retention_class = 'programme-restricted'
        ) THEN
            RAISE EXCEPTION 'Scheduling command lacks exact audit, event or outbox evidence' USING ERRCODE = '23514';
        END IF;
    END CASE;
    IF expected_operation IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.scheduling_schedulingcommandreceipt receipt
        WHERE receipt.organization_id = NEW.organization_id AND receipt.edition_id = NEW.edition_id
          AND receipt.operation = expected_operation AND receipt.result_object_id = object_id AND receipt.resulting_version = version_value
          AND receipt.actor_id = (body->>'actor_id')::uuid AND receipt.reason = body->>'reason'
          AND receipt.occurred_at = (body->>'occurred_at')::timestamptz
    ) THEN
        RAISE EXCEPTION 'Scheduling result lacks exact attributed command evidence' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_refuse_scheduling_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Scheduling history cannot be truncated' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;
"""

FORWARD_SQL += "\n".join(
    f"""
CREATE TRIGGER sch_{index}_row_guard BEFORE INSERT OR UPDATE OR DELETE ON public.scheduling_{suffix}
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_scheduling_row();
CREATE CONSTRAINT TRIGGER sch_{index}_graph_guard AFTER INSERT OR UPDATE ON public.scheduling_{suffix}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_validate_scheduling_graph();
CREATE TRIGGER sch_{index}_no_truncate BEFORE TRUNCATE ON public.scheduling_{suffix}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_scheduling_truncate();
"""
    for index, suffix in enumerate(TABLE_SUFFIXES)
)
FUNCTIONS = (
    "maru_scheduling_exact_keys(jsonb,text[])",
    "maru_scheduling_evidence_shape(jsonb)",
    "maru_scheduling_evidence_is_current(jsonb,uuid,uuid)",
    "maru_scheduling_canonical_json(jsonb)",
    "maru_guard_scheduling_row()",
    "maru_validate_scheduling_graph()",
    "maru_refuse_scheduling_truncate()",
)
FORWARD_SQL += "\n".join(
    f"REVOKE ALL ON FUNCTION public.{identity} FROM PUBLIC;" for identity in FUNCTIONS
)
REVERSE_SQL = (
    "\n".join(
        f"DROP TRIGGER IF EXISTS sch_{index}_{kind} ON public.scheduling_{suffix};"
        for index, suffix in enumerate(TABLE_SUFFIXES)
        for kind in ("row_guard", "graph_guard", "no_truncate")
    )
    + "\n"
    + "\n".join(f"DROP FUNCTION IF EXISTS public.{identity};" for identity in reversed(FUNCTIONS))
)


class Migration(migrations.Migration):
    """Protect the dormant complete Scheduling graph without granting runtime writes."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0004_conflict_vocabulary"),
        ("venues", "0003_scheduling_reservation_sources"),
        ("authorization", "0027_scheduling_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)
    ]
