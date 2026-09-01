# ruff: noqa: E501
"""Install exact-scope and immutable-evidence guards for Programme."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_guard_programme_control()
RETURNS trigger
AS $programme_control_guard$
DECLARE
    edition_organization uuid;
    edition_lifecycle varchar;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme edition controls cannot be deleted normally'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM public.events_eventedition
     WHERE id = NEW.edition_id
     FOR SHARE;
    IF edition_organization IS DISTINCT FROM NEW.organization_id THEN
        RAISE EXCEPTION 'Programme control edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle NOT IN ('draft', 'preparing') THEN
        RAISE EXCEPTION 'Programme state is writable only in draft or preparing editions'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version <> 1 THEN
            RAISE EXCEPTION 'Programme control must begin at version one'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'Programme control identity and scope are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'Programme control version did not advance once'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$programme_control_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_item()
RETURNS trigger
AS $programme_item_guard$
DECLARE
    edition_organization uuid;
    edition_lifecycle varchar;
    creator_active boolean;
    modifier_active boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme items require governed retirement'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, lifecycle
      INTO edition_organization, edition_lifecycle
      FROM public.events_eventedition
     WHERE id = NEW.edition_id
     FOR SHARE;
    IF TG_OP = 'INSERT' THEN
        SELECT is_active AND email_verified_at IS NOT NULL INTO creator_active
          FROM public.identity_account WHERE id = NEW.created_by_id FOR KEY SHARE;
    END IF;
    SELECT is_active AND email_verified_at IS NOT NULL INTO modifier_active
      FROM public.identity_account WHERE id = NEW.last_modified_by_id FOR KEY SHARE;
    IF edition_organization IS DISTINCT FROM NEW.organization_id
       OR NOT EXISTS (
           SELECT 1
             FROM public.programme_programmeeditioncontrol AS control
            WHERE control.organization_id = NEW.organization_id
              AND control.edition_id = NEW.edition_id
       )
    THEN
        RAISE EXCEPTION 'Programme item edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF edition_lifecycle NOT IN ('draft', 'preparing') THEN
        RAISE EXCEPTION 'Programme items are writable only in draft or preparing editions'
            USING ERRCODE = '23514';
    END IF;
    IF modifier_active IS DISTINCT FROM TRUE
       OR (TG_OP = 'INSERT' AND creator_active IS DISTINCT FROM TRUE)
    THEN
        RAISE EXCEPTION 'Programme item actors must be active and verified'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.kind NOT IN ('ceremony', 'break', 'announcement', 'organizer_core')
       OR NEW.provenance_kind NOT IN ('organizer_core', 'applications_accepted')
       OR NEW.lifecycle NOT IN ('active', 'retired')
    THEN
        RAISE EXCEPTION 'Programme item catalog value is unsupported'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version <> 1 OR NEW.lifecycle <> 'active'
           OR NEW.created_by_id IS DISTINCT FROM NEW.last_modified_by_id
        THEN
            RAISE EXCEPTION 'Programme item must begin as actor-owned version-one active state'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.kind IS DISTINCT FROM OLD.kind
           OR NEW.provenance_kind IS DISTINCT FROM OLD.provenance_kind
           OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'Programme item identity, scope, kind, and provenance are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'Programme item version did not advance once'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.lifecycle = 'retired'
           OR NOT (
               (OLD.lifecycle = 'active' AND NEW.lifecycle = 'active')
               OR (OLD.lifecycle = 'active' AND NEW.lifecycle = 'retired')
           )
        THEN
            RAISE EXCEPTION 'Programme item lifecycle transition is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$programme_item_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_source_binding()
RETURNS trigger
AS $programme_source_guard$
DECLARE
    item_row record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme source bindings are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, provenance_kind
      INTO item_row
      FROM public.programme_programmeitem
     WHERE id = NEW.item_id
     FOR KEY SHARE;
    IF item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
    THEN
        RAISE EXCEPTION 'Programme source binding scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF item_row.provenance_kind = 'organizer_core' AND NOT (
        NEW.binding_code = 'programme.source.organizer-core@1'
        AND NEW.source_object_id IS NULL
        AND NEW.source_version IS NULL
    ) THEN
        RAISE EXCEPTION 'organizer Programme provenance cannot invent a foreign source'
            USING ERRCODE = '23514';
    ELSIF item_row.provenance_kind = 'applications_accepted' AND NOT (
        NEW.binding_code = 'programme.source.applications-accepted@1'
        AND NEW.source_object_id IS NOT NULL
        AND NEW.source_version > 0
    ) THEN
        RAISE EXCEPTION 'accepted Programme provenance requires a typed versioned source'
            USING ERRCODE = '23514';
    ELSIF item_row.provenance_kind NOT IN ('organizer_core', 'applications_accepted') THEN
        RAISE EXCEPTION 'Programme source provenance is unsupported'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$programme_source_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_layer_revision()
RETURNS trigger
AS $programme_layer_guard$
DECLARE
    item_row record;
    actor_active boolean;
    prior_sequence integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme information revisions are append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, aggregate_version, lifecycle
      INTO item_row
      FROM public.programme_programmeitem
     WHERE id = NEW.item_id
     FOR UPDATE;
    SELECT is_active AND email_verified_at IS NOT NULL INTO actor_active
      FROM public.identity_account WHERE id = NEW.actor_id FOR KEY SHARE;
    EXECUTE pg_catalog.format(
        'SELECT COALESCE(MAX(sequence), 0) FROM public.%I WHERE item_id = $1',
        TG_TABLE_NAME
    ) INTO prior_sequence USING NEW.item_id;
    IF item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.aggregate_version IS DISTINCT FROM NEW.item_version
       OR item_row.lifecycle IS DISTINCT FROM 'active'
       OR actor_active IS DISTINCT FROM TRUE
       OR NEW.sequence <> prior_sequence + 1
       OR btrim(NEW.reason) = ''
       OR NEW.occurred_at IS NULL
    THEN
        RAISE EXCEPTION 'Programme information revision evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'programme_programmeworkingrevision' THEN
        IF char_length(NEW.working_summary) > 2000 THEN
            RAISE EXCEPTION 'Programme information revision exceeds its text ceiling'
                USING ERRCODE = '23514';
        END IF;
        IF btrim(NEW.internal_title) = '' THEN
            RAISE EXCEPTION 'Programme information revision content is empty'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'programme_programmedeliveryrevision' THEN
        IF char_length(NEW.technical_requirements) > 5000
           OR char_length(NEW.accessibility_delivery) > 5000
           OR char_length(NEW.media_consent_notes) > 5000
        THEN
            RAISE EXCEPTION 'Programme information revision exceeds its text ceiling'
                USING ERRCODE = '23514';
        END IF;
        IF btrim(NEW.technical_requirements) = ''
           AND btrim(NEW.accessibility_delivery) = ''
           AND btrim(NEW.media_consent_notes) = ''
        THEN
            RAISE EXCEPTION 'Programme information revision content is empty'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'programme_programmedepartmentdiscussionentry' THEN
        IF char_length(NEW.body) > 5000 THEN
            RAISE EXCEPTION 'Programme information revision exceeds its text ceiling'
                USING ERRCODE = '23514';
        END IF;
        IF btrim(NEW.body) = '' THEN
            RAISE EXCEPTION 'Programme information revision content is empty'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unsupported Programme information revision table'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$programme_layer_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_requirement()
RETURNS trigger
AS $programme_requirement_guard$
DECLARE
    item_row record;
    modifier_active boolean;
    expected_dependency_version bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme readiness requirements are retained'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, aggregate_version, lifecycle
      INTO item_row
      FROM public.programme_programmeitem
     WHERE id = NEW.item_id
     FOR UPDATE;
    SELECT is_active AND email_verified_at IS NOT NULL INTO modifier_active
      FROM public.identity_account WHERE id = NEW.last_modified_by_id FOR KEY SHARE;
    IF item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.aggregate_version IS DISTINCT FROM NEW.item_version
       OR item_row.lifecycle IS DISTINCT FROM 'active'
       OR modifier_active IS DISTINCT FROM TRUE
       OR NEW.concern NOT IN (
           'public_copy', 'host_confirmation', 'technical_needs',
           'accessibility_delivery', 'media_consent',
           'schedule_availability', 'required_files'
       )
       OR NEW.disposition NOT IN ('required', 'not_applicable')
       OR NEW.requirement_version < 1
       OR NEW.dependency_version < 0
       OR NEW.dependency_version > NEW.item_version
    THEN
        RAISE EXCEPTION 'Programme readiness requirement evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.requirement_version <> 1 THEN
            RAISE EXCEPTION 'Programme readiness requirement must begin at version one'
                USING ERRCODE = '23514';
        END IF;
        expected_dependency_version := 0;
        IF NEW.concern = 'public_copy' THEN
            SELECT source.item_version
              INTO expected_dependency_version
              FROM public.programme_programmeworkingrevision AS source
             WHERE source.item_id = NEW.item_id
             ORDER BY source.sequence DESC, source.id DESC
             LIMIT 1;
        ELSIF NEW.concern IN (
            'technical_needs', 'accessibility_delivery', 'media_consent'
        ) THEN
            SELECT source.item_version
              INTO expected_dependency_version
              FROM public.programme_programmedeliveryrevision AS source
             WHERE source.item_id = NEW.item_id
             ORDER BY source.sequence DESC, source.id DESC
             LIMIT 1;
        END IF;
        expected_dependency_version := COALESCE(expected_dependency_version, 0);
        IF NEW.dependency_version IS DISTINCT FROM expected_dependency_version THEN
            RAISE EXCEPTION 'Programme readiness initial dependency cursor is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.item_id IS DISTINCT FROM OLD.item_id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.concern IS DISTINCT FROM OLD.concern
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'Programme readiness requirement identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.item_version <= OLD.item_version THEN
            RAISE EXCEPTION 'Programme readiness cursor must advance to a newer item version'
                USING ERRCODE = '23514';
        ELSIF NEW.requirement_version = OLD.requirement_version + 1 THEN
            IF NEW.dependency_version IS DISTINCT FROM OLD.dependency_version THEN
                RAISE EXCEPTION 'Programme readiness configuration changed the wrong cursor'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.requirement_version = OLD.requirement_version THEN
            IF NEW.disposition IS DISTINCT FROM OLD.disposition
               OR NEW.dependency_version <> NEW.item_version
               OR NEW.dependency_version <= OLD.dependency_version
            THEN
                RAISE EXCEPTION 'Programme readiness dependency cursor is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Programme readiness requirement version transition is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$programme_requirement_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_requirement_revision()
RETURNS trigger
AS $programme_requirement_revision_guard$
DECLARE
    requirement_row record;
    actor_active boolean;
    prior_sequence integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme requirement revisions are append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT item_id, organization_id, edition_id, requirement_version,
           disposition, item_version, last_modified_by_id
      INTO requirement_row
      FROM public.programme_programmereadinessrequirement
     WHERE id = NEW.requirement_id
     FOR UPDATE;
    SELECT is_active AND email_verified_at IS NOT NULL INTO actor_active
      FROM public.identity_account WHERE id = NEW.actor_id FOR KEY SHARE;
    SELECT COALESCE(MAX(sequence), 0) INTO prior_sequence
      FROM public.programme_programmereadinessrequirementrevision
     WHERE requirement_id = NEW.requirement_id;
    IF requirement_row.item_id IS DISTINCT FROM NEW.item_id
       OR requirement_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR requirement_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR requirement_row.requirement_version IS DISTINCT FROM NEW.sequence
       OR requirement_row.disposition IS DISTINCT FROM NEW.disposition
       OR requirement_row.item_version IS DISTINCT FROM NEW.item_version
       OR requirement_row.last_modified_by_id IS DISTINCT FROM NEW.actor_id
       OR actor_active IS DISTINCT FROM TRUE
       OR NEW.sequence <> prior_sequence + 1
       OR btrim(NEW.reason) = ''
       OR NEW.occurred_at IS NULL
    THEN
        RAISE EXCEPTION 'Programme requirement revision evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$programme_requirement_revision_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_readiness_evidence()
RETURNS trigger
AS $programme_readiness_evidence_guard$
DECLARE
    requirement_row record;
    item_row record;
    actor_active boolean;
    prior_sequence integer;
    source_matches boolean := FALSE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme readiness evidence is append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT item_id, organization_id, edition_id, requirement_version,
           dependency_version, concern
      INTO requirement_row
      FROM public.programme_programmereadinessrequirement
     WHERE id = NEW.requirement_id
     FOR UPDATE;
    SELECT organization_id, edition_id, aggregate_version, lifecycle
      INTO item_row
      FROM public.programme_programmeitem
     WHERE id = NEW.item_id
     FOR UPDATE;
    SELECT is_active AND email_verified_at IS NOT NULL INTO actor_active
      FROM public.identity_account WHERE id = NEW.actor_id FOR KEY SHARE;
    SELECT COALESCE(MAX(sequence), 0) INTO prior_sequence
      FROM public.programme_programmereadinessevidence
     WHERE requirement_id = NEW.requirement_id;

    IF NEW.source_code = 'programme.evidence.operator-attestation@1' THEN
        source_matches := NEW.source_object_id IS NULL AND NEW.source_version IS NULL;
    ELSIF NEW.source_code = 'programme.evidence.public-rendition@1' THEN
        SELECT EXISTS (
            SELECT 1 FROM public.programme_programmepublicrendition AS source
             WHERE source.id = NEW.source_object_id
               AND source.item_id = NEW.item_id
               AND source.organization_id = NEW.organization_id
               AND source.edition_id = NEW.edition_id
               AND source.rendition_number = NEW.source_version
               AND source.source_item_version = requirement_row.dependency_version
               AND requirement_row.concern = 'public_copy'
        ) INTO source_matches;
    ELSIF NEW.source_code = 'programme.evidence.working-revision@1' THEN
        SELECT EXISTS (
            SELECT 1 FROM public.programme_programmeworkingrevision AS source
             WHERE source.id = NEW.source_object_id
               AND source.item_id = NEW.item_id
               AND source.organization_id = NEW.organization_id
               AND source.edition_id = NEW.edition_id
               AND source.sequence = NEW.source_version
               AND source.item_version = requirement_row.dependency_version
               AND requirement_row.concern = 'public_copy'
        ) INTO source_matches;
    ELSIF NEW.source_code = 'programme.evidence.delivery-revision@1' THEN
        SELECT EXISTS (
            SELECT 1 FROM public.programme_programmedeliveryrevision AS source
             WHERE source.id = NEW.source_object_id
               AND source.item_id = NEW.item_id
               AND source.organization_id = NEW.organization_id
               AND source.edition_id = NEW.edition_id
               AND source.sequence = NEW.source_version
               AND source.item_version = requirement_row.dependency_version
               AND requirement_row.concern IN (
                   'technical_needs',
                   'accessibility_delivery',
                   'media_consent'
               )
        ) INTO source_matches;
    END IF;

    IF requirement_row.item_id IS DISTINCT FROM NEW.item_id
       OR requirement_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR requirement_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR requirement_row.requirement_version IS DISTINCT FROM NEW.requirement_version
       OR requirement_row.dependency_version IS DISTINCT FROM NEW.dependency_version
       OR item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.aggregate_version IS DISTINCT FROM NEW.item_version
       OR item_row.lifecycle IS DISTINCT FROM 'active'
       OR actor_active IS DISTINCT FROM TRUE
       OR NEW.sequence <> prior_sequence + 1
       OR NEW.state NOT IN ('satisfied', 'blocked', 'unavailable')
       OR NOT source_matches
       OR char_length(NEW.evidence_note) > 2000
       OR btrim(NEW.reason) = ''
       OR NEW.occurred_at IS NULL
    THEN
        RAISE EXCEPTION 'Programme readiness evidence does not match its requirement and source'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$programme_readiness_evidence_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_public_rendition()
RETURNS trigger
AS $programme_public_rendition_guard$
DECLARE
    item_row record;
    working_row record;
    latest_working_id uuid;
    predecessor_item_id uuid;
    predecessor_number bigint;
    reviewer_active boolean;
    prior_number integer;
    edition_lifecycle varchar;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme public renditions are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, aggregate_version, lifecycle
      INTO item_row
      FROM public.programme_programmeitem
     WHERE id = NEW.item_id
     FOR UPDATE;
    SELECT item_id, organization_id, edition_id, item_version
      INTO working_row
      FROM public.programme_programmeworkingrevision
     WHERE id = NEW.source_working_revision_id
     FOR KEY SHARE;
    SELECT id
      INTO latest_working_id
      FROM public.programme_programmeworkingrevision
     WHERE item_id = NEW.item_id
     ORDER BY sequence DESC, id DESC
     LIMIT 1
     FOR KEY SHARE;
    SELECT lifecycle
      INTO edition_lifecycle
      FROM public.events_eventedition
     WHERE id = NEW.edition_id
       AND organization_id = NEW.organization_id
     FOR SHARE;
    SELECT is_active AND email_verified_at IS NOT NULL INTO reviewer_active
      FROM public.identity_account WHERE id = NEW.reviewed_by_id FOR KEY SHARE;
    SELECT COALESCE(MAX(rendition_number), 0) INTO prior_number
      FROM public.programme_programmepublicrendition
     WHERE item_id = NEW.item_id;
    IF NEW.supersedes_id IS NOT NULL THEN
        SELECT item_id, rendition_number
          INTO predecessor_item_id, predecessor_number
          FROM public.programme_programmepublicrendition
         WHERE id = NEW.supersedes_id
         FOR KEY SHARE;
    END IF;
    IF item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.lifecycle IS DISTINCT FROM 'active'
       OR edition_lifecycle IS NULL
       OR edition_lifecycle NOT IN ('draft', 'preparing')
       OR NEW.source_item_version > item_row.aggregate_version
       OR working_row.item_id IS DISTINCT FROM NEW.item_id
       OR working_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR working_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR working_row.item_version IS DISTINCT FROM NEW.source_item_version
       OR latest_working_id IS DISTINCT FROM NEW.source_working_revision_id
       OR reviewer_active IS DISTINCT FROM TRUE
       OR NEW.rendition_number <> prior_number + 1
       OR (NEW.rendition_number = 1 AND NEW.supersedes_id IS NOT NULL)
       OR (NEW.rendition_number > 1 AND (
           NEW.supersedes_id IS NULL
           OR predecessor_item_id IS DISTINCT FROM NEW.item_id
           OR predecessor_number IS DISTINCT FROM NEW.rendition_number - 1
       ))
       OR btrim(NEW.public_title) = ''
       OR char_length(NEW.public_summary) > 2000
       OR char_length(NEW.public_content_note) > 500
       OR btrim(NEW.review_reason) = ''
       OR NEW.reviewed_at IS NULL
    THEN
        RAISE EXCEPTION 'Programme public rendition evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$programme_public_rendition_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_programme_receipt()
RETURNS trigger
AS $programme_receipt_guard$
DECLARE
    control_row record;
    item_row record;
    actor_active boolean;
    result_matches boolean := FALSE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme command receipts are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, aggregate_version
      INTO control_row
      FROM public.programme_programmeeditioncontrol
     WHERE id = NEW.control_id
     FOR KEY SHARE;
    SELECT organization_id, edition_id, aggregate_version, lifecycle,
           provenance_kind, created_by_id, last_modified_by_id
      INTO item_row
      FROM public.programme_programmeitem
     WHERE id = NEW.item_id
     FOR KEY SHARE;
    SELECT is_active AND email_verified_at IS NOT NULL INTO actor_active
      FROM public.identity_account WHERE id = NEW.actor_id FOR KEY SHARE;
    IF NEW.operation = 'item_create' THEN
        SELECT COUNT(*) = 1
          INTO result_matches
          FROM public.programme_programmeworkingrevision AS result
         WHERE NEW.result_object_id IS NOT DISTINCT FROM NEW.item_id
           AND result.item_id = NEW.item_id
           AND result.organization_id = NEW.organization_id
           AND result.edition_id = NEW.edition_id
           AND result.sequence = 1
           AND result.item_version = 1
           AND result.actor_id = NEW.actor_id
           AND result.reason = NEW.reason;
    ELSIF NEW.operation = 'working_revise' THEN
        SELECT EXISTS (
            SELECT 1
              FROM public.programme_programmeworkingrevision AS result
             WHERE result.id = NEW.result_object_id
               AND result.item_id = NEW.item_id
               AND result.organization_id = NEW.organization_id
               AND result.edition_id = NEW.edition_id
               AND result.item_version = NEW.resulting_item_version
               AND result.actor_id = NEW.actor_id
               AND result.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'delivery_revise' THEN
        SELECT EXISTS (
            SELECT 1
              FROM public.programme_programmedeliveryrevision AS result
             WHERE result.id = NEW.result_object_id
               AND result.item_id = NEW.item_id
               AND result.organization_id = NEW.organization_id
               AND result.edition_id = NEW.edition_id
               AND result.item_version = NEW.resulting_item_version
               AND result.actor_id = NEW.actor_id
               AND result.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'discussion_append' THEN
        SELECT EXISTS (
            SELECT 1
              FROM public.programme_programmedepartmentdiscussionentry AS result
             WHERE result.id = NEW.result_object_id
               AND result.item_id = NEW.item_id
               AND result.organization_id = NEW.organization_id
               AND result.edition_id = NEW.edition_id
               AND result.item_version = NEW.resulting_item_version
               AND result.actor_id = NEW.actor_id
               AND result.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'readiness_configure' THEN
        SELECT EXISTS (
            SELECT 1
              FROM public.programme_programmereadinessrequirementrevision AS result
              JOIN public.programme_programmereadinessrequirement AS requirement
                ON requirement.id = result.requirement_id
               AND requirement.item_id = result.item_id
               AND requirement.organization_id = result.organization_id
               AND requirement.edition_id = result.edition_id
               AND requirement.requirement_version = result.sequence
               AND requirement.item_version = result.item_version
               AND requirement.disposition = result.disposition
               AND requirement.last_modified_by_id = NEW.actor_id
             WHERE result.id = NEW.result_object_id
               AND result.item_id = NEW.item_id
               AND result.organization_id = NEW.organization_id
               AND result.edition_id = NEW.edition_id
               AND result.item_version = NEW.resulting_item_version
               AND result.actor_id = NEW.actor_id
               AND result.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'readiness_record' THEN
        SELECT EXISTS (
            SELECT 1
              FROM public.programme_programmereadinessevidence AS result
             WHERE result.id = NEW.result_object_id
               AND result.item_id = NEW.item_id
               AND result.organization_id = NEW.organization_id
               AND result.edition_id = NEW.edition_id
               AND result.item_version = NEW.resulting_item_version
               AND result.actor_id = NEW.actor_id
               AND result.reason = NEW.reason
        ) INTO result_matches;
    ELSIF NEW.operation = 'public_rendition_record' THEN
        SELECT EXISTS (
            SELECT 1
              FROM public.programme_programmepublicrendition AS result
             WHERE result.id = NEW.result_object_id
               AND result.item_id = NEW.item_id
               AND result.organization_id = NEW.organization_id
               AND result.edition_id = NEW.edition_id
               AND result.reviewed_by_id = NEW.actor_id
               AND result.review_reason = NEW.reason
        ) INTO result_matches;
    END IF;
    IF control_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR control_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.organization_id IS DISTINCT FROM NEW.organization_id
       OR item_row.edition_id IS DISTINCT FROM NEW.edition_id
       OR item_row.aggregate_version IS DISTINCT FROM NEW.resulting_item_version
       OR actor_active IS DISTINCT FROM TRUE
       OR NEW.operation NOT IN (
           'item_create', 'working_revise', 'delivery_revise',
           'discussion_append', 'readiness_configure', 'readiness_record',
           'public_rendition_record'
       )
       OR NEW.expected_version < 0
       OR NEW.resulting_item_version < 1
       OR btrim(NEW.reason) = ''
       OR btrim(NEW.source_channel) = ''
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.result_object_id IS NULL
       OR NOT result_matches
    THEN
        RAISE EXCEPTION 'Programme command receipt evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.operation = 'item_create' THEN
        IF item_row.aggregate_version <> 1
           OR item_row.lifecycle <> 'active'
           OR item_row.provenance_kind <> 'organizer_core'
           OR item_row.created_by_id IS DISTINCT FROM NEW.actor_id
           OR item_row.last_modified_by_id IS DISTINCT FROM NEW.actor_id
           OR NEW.result_object_id IS DISTINCT FROM NEW.item_id
           OR NEW.resulting_control_version IS DISTINCT FROM control_row.aggregate_version
           OR NEW.expected_version <> control_row.aggregate_version - 1
        THEN
            RAISE EXCEPTION 'Programme creation receipt does not match control and item state'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.operation = 'public_rendition_record' THEN
        IF NEW.resulting_control_version IS NOT NULL
           OR NEW.expected_version <> NEW.resulting_item_version
           OR item_row.lifecycle <> 'active'
        THEN
            RAISE EXCEPTION 'Programme public-copy receipt changed item state'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.resulting_control_version IS NOT NULL
       OR NEW.expected_version + 1 <> NEW.resulting_item_version
       OR item_row.lifecycle <> 'active'
       OR item_row.last_modified_by_id IS DISTINCT FROM NEW.actor_id
    THEN
        RAISE EXCEPTION 'Programme item mutation receipt does not match optimistic state'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$programme_receipt_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_item_evidence()
RETURNS trigger
AS $programme_item_evidence_guard$
DECLARE
    checked_id uuid;
    current_version bigint;
    matching_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'programme_programmeitem' THEN
        checked_id := NEW.id;
        current_version := NEW.aggregate_version;
        SELECT COUNT(*) INTO matching_count
          FROM public.programme_programmecommandreceipt AS receipt
         WHERE receipt.item_id = checked_id
           AND receipt.resulting_item_version = current_version
           AND receipt.operation <> 'public_rendition_record'
           AND (
               TG_OP <> 'INSERT'
               OR (
                   receipt.operation = 'item_create'
                   AND receipt.result_object_id = checked_id
               )
           );
    ELSIF TG_TABLE_NAME = 'programme_programmecommandreceipt' THEN
        IF NEW.operation = 'public_rendition_record' THEN
            RETURN NULL;
        END IF;
        checked_id := NEW.item_id;
        current_version := NEW.resulting_item_version;
        SELECT COUNT(*) INTO matching_count
          FROM public.programme_programmecommandreceipt AS receipt
         WHERE receipt.item_id = checked_id
           AND receipt.resulting_item_version = current_version
           AND receipt.operation <> 'public_rendition_record';
    ELSIF TG_TABLE_NAME = 'programme_programmeworkingrevision' THEN
        SELECT COUNT(*) INTO matching_count
         FROM public.programme_programmecommandreceipt AS receipt
         WHERE receipt.item_id = NEW.item_id
           AND receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_item_version = NEW.item_version
           AND receipt.actor_id = NEW.actor_id
           AND receipt.reason = NEW.reason
           AND (
               (
                   receipt.operation = 'working_revise'
                   AND receipt.result_object_id = NEW.id
               )
               OR (
                   receipt.operation = 'item_create'
                   AND receipt.result_object_id = NEW.item_id
                   AND NEW.sequence = 1
                   AND NEW.item_version = 1
               )
           );
    ELSIF TG_TABLE_NAME = 'programme_programmedeliveryrevision' THEN
        SELECT COUNT(*) INTO matching_count
          FROM public.programme_programmecommandreceipt AS receipt
         WHERE receipt.operation = 'delivery_revise'
           AND receipt.result_object_id = NEW.id
           AND receipt.item_id = NEW.item_id
           AND receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_item_version = NEW.item_version
           AND receipt.actor_id = NEW.actor_id
           AND receipt.reason = NEW.reason;
    ELSIF TG_TABLE_NAME = 'programme_programmedepartmentdiscussionentry' THEN
        SELECT COUNT(*) INTO matching_count
          FROM public.programme_programmecommandreceipt AS receipt
         WHERE receipt.operation = 'discussion_append'
           AND receipt.result_object_id = NEW.id
           AND receipt.item_id = NEW.item_id
           AND receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_item_version = NEW.item_version
           AND receipt.actor_id = NEW.actor_id
           AND receipt.reason = NEW.reason;
    ELSIF TG_TABLE_NAME = 'programme_programmereadinessrequirementrevision' THEN
        SELECT COUNT(*) INTO matching_count
          FROM public.programme_programmecommandreceipt AS receipt
         WHERE receipt.operation = 'readiness_configure'
           AND receipt.result_object_id = NEW.id
           AND receipt.item_id = NEW.item_id
           AND receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_item_version = NEW.item_version
           AND receipt.actor_id = NEW.actor_id
           AND receipt.reason = NEW.reason;
    ELSIF TG_TABLE_NAME = 'programme_programmereadinessevidence' THEN
        SELECT COUNT(*) INTO matching_count
          FROM public.programme_programmecommandreceipt AS receipt
         WHERE receipt.operation = 'readiness_record'
           AND receipt.result_object_id = NEW.id
           AND receipt.item_id = NEW.item_id
           AND receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_item_version = NEW.item_version
           AND receipt.actor_id = NEW.actor_id
           AND receipt.reason = NEW.reason;
    ELSIF TG_TABLE_NAME = 'programme_programmepublicrendition' THEN
        SELECT COUNT(*) INTO matching_count
          FROM public.programme_programmecommandreceipt AS receipt
          JOIN public.programme_programmeitem AS item
            ON item.id = NEW.item_id
           AND item.aggregate_version = receipt.resulting_item_version
         WHERE receipt.operation = 'public_rendition_record'
           AND receipt.result_object_id = NEW.id
           AND receipt.item_id = NEW.item_id
           AND receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.actor_id = NEW.reviewed_by_id
           AND receipt.reason = NEW.review_reason;
    ELSE
        RAISE EXCEPTION 'unsupported Programme command-evidence trigger target'
            USING ERRCODE = '23514';
    END IF;
    IF matching_count <> 1 THEN
        RAISE EXCEPTION 'Programme mutation lacks exact immutable command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$programme_item_evidence_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_control_evidence()
RETURNS trigger
AS $programme_control_evidence_guard$
DECLARE
    checked_id uuid;
    current_version bigint;
    matching_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'programme_programmeeditioncontrol' THEN
        checked_id := NEW.id;
        current_version := NEW.aggregate_version;
    ELSIF NEW.resulting_control_version IS NULL THEN
        RETURN NULL;
    ELSE
        checked_id := NEW.control_id;
        current_version := NEW.resulting_control_version;
    END IF;
    SELECT COUNT(*) INTO matching_count
      FROM public.programme_programmecommandreceipt
     WHERE control_id = checked_id
       AND resulting_control_version = current_version;
    IF matching_count <> 1 THEN
        RAISE EXCEPTION 'Programme control lacks exact immutable command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$programme_control_evidence_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_source_shape()
RETURNS trigger
AS $programme_source_shape_guard$
DECLARE
    checked_id uuid;
    item_provenance varchar;
    matching_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'programme_programmeitem' THEN
        checked_id := NEW.id;
    ELSE
        checked_id := NEW.item_id;
    END IF;
    SELECT provenance_kind INTO item_provenance
      FROM public.programme_programmeitem WHERE id = checked_id;
    SELECT COUNT(*) INTO matching_count
      FROM public.programme_programmeitemsourcebinding AS binding
     WHERE binding.item_id = checked_id
       AND (
           (item_provenance = 'organizer_core'
            AND binding.binding_code = 'programme.source.organizer-core@1'
            AND binding.source_object_id IS NULL
            AND binding.source_version IS NULL)
           OR
           (item_provenance = 'applications_accepted'
            AND binding.binding_code = 'programme.source.applications-accepted@1'
            AND binding.source_object_id IS NOT NULL
            AND binding.source_version > 0)
       );
    IF matching_count <> 1 THEN
        RAISE EXCEPTION 'Programme item requires one exact structural source binding'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$programme_source_shape_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_requirement_history()
RETURNS trigger
AS $programme_requirement_history_guard$
DECLARE
    checked_id uuid;
    requirement_row record;
    matching_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'programme_programmereadinessrequirement' THEN
        checked_id := NEW.id;
    ELSE
        checked_id := NEW.requirement_id;
    END IF;
    SELECT requirement_version, disposition
      INTO requirement_row
      FROM public.programme_programmereadinessrequirement
     WHERE id = checked_id;
    SELECT COUNT(*) INTO matching_count
      FROM public.programme_programmereadinessrequirementrevision
     WHERE requirement_id = checked_id
       AND sequence = requirement_row.requirement_version
       AND disposition = requirement_row.disposition;
    IF matching_count <> 1 THEN
        RAISE EXCEPTION 'Programme readiness requirement lacks exact revision history'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$programme_requirement_history_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_programme_dependency_cursors()
RETURNS trigger
AS $programme_dependency_cursor_guard$
DECLARE
    checked_item_id uuid;
    checked_item_version bigint;
    command_operation varchar;
    command_actor_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'programme_programmereadinessrequirement' THEN
        IF TG_OP <> 'UPDATE'
           OR NEW.dependency_version IS NOT DISTINCT FROM OLD.dependency_version
        THEN
            RETURN NULL;
        END IF;
        checked_item_id := NEW.item_id;
        checked_item_version := NEW.item_version;
    ELSE
        IF NEW.operation NOT IN ('working_revise', 'delivery_revise') THEN
            RETURN NULL;
        END IF;
        checked_item_id := NEW.item_id;
        checked_item_version := NEW.resulting_item_version;
    END IF;

    SELECT operation, actor_id
      INTO command_operation, command_actor_id
      FROM public.programme_programmecommandreceipt
     WHERE item_id = checked_item_id
       AND resulting_item_version = checked_item_version;
    IF command_operation IS NULL THEN
        RAISE EXCEPTION 'Programme dependency cursor lacks command evidence'
            USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'programme_programmereadinessrequirement' THEN
        IF NEW.last_modified_by_id IS DISTINCT FROM command_actor_id
           OR NOT (
               (command_operation = 'working_revise'
                AND NEW.concern = 'public_copy')
               OR
               (command_operation = 'delivery_revise'
                AND NEW.concern IN (
                    'technical_needs',
                    'accessibility_delivery',
                    'media_consent'
                ))
           )
        THEN
            RAISE EXCEPTION 'Programme dependency cursor changed outside its layer command'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF command_operation = 'working_revise' AND EXISTS (
        SELECT 1
          FROM public.programme_programmereadinessrequirement AS requirement
         WHERE requirement.item_id = checked_item_id
           AND requirement.concern = 'public_copy'
           AND (
               requirement.dependency_version <> checked_item_version
               OR requirement.item_version <> checked_item_version
               OR requirement.last_modified_by_id <> command_actor_id
           )
    ) THEN
        RAISE EXCEPTION 'Programme working change left public-copy readiness stale'
            USING ERRCODE = '23514';
    ELSIF command_operation = 'delivery_revise' AND EXISTS (
        SELECT 1
          FROM public.programme_programmereadinessrequirement AS requirement
         WHERE requirement.item_id = checked_item_id
           AND requirement.concern IN (
               'technical_needs',
               'accessibility_delivery',
               'media_consent'
           )
           AND (
               requirement.dependency_version <> checked_item_version
               OR requirement.item_version <> checked_item_version
               OR requirement.last_modified_by_id <> command_actor_id
           )
    ) THEN
        RAISE EXCEPTION 'Programme delivery change left readiness dependencies stale'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$programme_dependency_cursor_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_refuse_programme_truncate()
RETURNS trigger
AS $programme_truncate_guard$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Programme retained state cannot be truncated'
        USING ERRCODE = '23514';
END;
$programme_truncate_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER programme_control_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmeeditioncontrol
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_control();
CREATE TRIGGER programme_item_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmeitem
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_item();
CREATE TRIGGER programme_source_binding_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmeitemsourcebinding
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_source_binding();
CREATE TRIGGER programme_working_revision_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmeworkingrevision
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_layer_revision();
CREATE TRIGGER programme_delivery_revision_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmedeliveryrevision
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_layer_revision();
CREATE TRIGGER programme_discussion_entry_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmedepartmentdiscussionentry
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_layer_revision();
CREATE TRIGGER programme_requirement_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmereadinessrequirement
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_requirement();
CREATE TRIGGER programme_requirement_revision_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmereadinessrequirementrevision
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_requirement_revision();
CREATE TRIGGER programme_readiness_evidence_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmereadinessevidence
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_readiness_evidence();
CREATE TRIGGER programme_public_rendition_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmepublicrendition
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_public_rendition();
CREATE TRIGGER programme_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.programme_programmecommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_programme_receipt();

CREATE TRIGGER programme_control_no_truncate
BEFORE TRUNCATE ON public.programme_programmeeditioncontrol
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_item_no_truncate
BEFORE TRUNCATE ON public.programme_programmeitem
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_source_binding_no_truncate
BEFORE TRUNCATE ON public.programme_programmeitemsourcebinding
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_working_revision_no_truncate
BEFORE TRUNCATE ON public.programme_programmeworkingrevision
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_delivery_revision_no_truncate
BEFORE TRUNCATE ON public.programme_programmedeliveryrevision
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_discussion_entry_no_truncate
BEFORE TRUNCATE ON public.programme_programmedepartmentdiscussionentry
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_requirement_no_truncate
BEFORE TRUNCATE ON public.programme_programmereadinessrequirement
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_requirement_revision_no_truncate
BEFORE TRUNCATE ON public.programme_programmereadinessrequirementrevision
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_readiness_evidence_no_truncate
BEFORE TRUNCATE ON public.programme_programmereadinessevidence
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_public_rendition_no_truncate
BEFORE TRUNCATE ON public.programme_programmepublicrendition
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();
CREATE TRIGGER programme_receipt_no_truncate
BEFORE TRUNCATE ON public.programme_programmecommandreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_programme_truncate();

CREATE CONSTRAINT TRIGGER programme_item_evidence_guard
AFTER INSERT OR UPDATE ON public.programme_programmeitem
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_receipt_item_evidence_guard
AFTER INSERT ON public.programme_programmecommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_working_command_evidence_guard
AFTER INSERT ON public.programme_programmeworkingrevision
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_delivery_command_evidence_guard
AFTER INSERT ON public.programme_programmedeliveryrevision
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_discussion_command_evidence_guard
AFTER INSERT ON public.programme_programmedepartmentdiscussionentry
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_requirement_revision_command_evidence_guard
AFTER INSERT ON public.programme_programmereadinessrequirementrevision
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_readiness_evidence_command_evidence_guard
AFTER INSERT ON public.programme_programmereadinessevidence
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_public_rendition_command_evidence_guard
AFTER INSERT ON public.programme_programmepublicrendition
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_item_evidence();
CREATE CONSTRAINT TRIGGER programme_control_evidence_guard
AFTER INSERT OR UPDATE ON public.programme_programmeeditioncontrol
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_control_evidence();
CREATE CONSTRAINT TRIGGER programme_receipt_control_evidence_guard
AFTER INSERT ON public.programme_programmecommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_control_evidence();
CREATE CONSTRAINT TRIGGER programme_item_source_shape_guard
AFTER INSERT OR UPDATE ON public.programme_programmeitem
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_source_shape();
CREATE CONSTRAINT TRIGGER programme_binding_source_shape_guard
AFTER INSERT ON public.programme_programmeitemsourcebinding
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_source_shape();
CREATE CONSTRAINT TRIGGER programme_requirement_history_guard
AFTER INSERT OR UPDATE ON public.programme_programmereadinessrequirement
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_requirement_history();
CREATE CONSTRAINT TRIGGER programme_requirement_revision_history_guard
AFTER INSERT ON public.programme_programmereadinessrequirementrevision
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_requirement_history();
CREATE CONSTRAINT TRIGGER programme_requirement_dependency_cursor_guard
AFTER UPDATE ON public.programme_programmereadinessrequirement
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_dependency_cursors();
CREATE CONSTRAINT TRIGGER programme_receipt_dependency_cursor_guard
AFTER INSERT ON public.programme_programmecommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_validate_programme_dependency_cursors();

REVOKE ALL ON FUNCTION public.maru_guard_programme_control() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_item() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_source_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_layer_revision() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_requirement() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_requirement_revision() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_readiness_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_public_rendition() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_programme_receipt() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_validate_programme_item_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_validate_programme_control_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_validate_programme_source_shape() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_validate_programme_requirement_history() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_validate_programme_dependency_cursors() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_refuse_programme_truncate() FROM PUBLIC;
"""

REVERSE_SQL = r"""
LOCK TABLE
    public.programme_programmeeditioncontrol,
    public.programme_programmeitem,
    public.programme_programmeitemsourcebinding,
    public.programme_programmeworkingrevision,
    public.programme_programmedeliveryrevision,
    public.programme_programmedepartmentdiscussionentry,
    public.programme_programmereadinessrequirement,
    public.programme_programmereadinessrequirementrevision,
    public.programme_programmereadinessevidence,
    public.programme_programmepublicrendition,
    public.programme_programmecommandreceipt
IN ACCESS EXCLUSIVE MODE;

DO $programme_0002_reverse_preflight$
BEGIN
    IF EXISTS (SELECT 1 FROM public.programme_programmeeditioncontrol LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmeitem LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmeitemsourcebinding LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmeworkingrevision LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmedeliveryrevision LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmedepartmentdiscussionentry LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmereadinessrequirement LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmereadinessrequirementrevision LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmereadinessevidence LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmepublicrendition LIMIT 1)
       OR EXISTS (SELECT 1 FROM public.programme_programmecommandreceipt LIMIT 1)
    THEN
        RAISE EXCEPTION 'Cannot remove Programme integrity guards while Programme data exists'
            USING ERRCODE = '23514';
    END IF;
END;
$programme_0002_reverse_preflight$;

DROP TRIGGER IF EXISTS programme_receipt_no_truncate ON public.programme_programmecommandreceipt;
DROP TRIGGER IF EXISTS programme_public_rendition_no_truncate ON public.programme_programmepublicrendition;
DROP TRIGGER IF EXISTS programme_readiness_evidence_no_truncate ON public.programme_programmereadinessevidence;
DROP TRIGGER IF EXISTS programme_requirement_revision_no_truncate ON public.programme_programmereadinessrequirementrevision;
DROP TRIGGER IF EXISTS programme_requirement_no_truncate ON public.programme_programmereadinessrequirement;
DROP TRIGGER IF EXISTS programme_discussion_entry_no_truncate ON public.programme_programmedepartmentdiscussionentry;
DROP TRIGGER IF EXISTS programme_delivery_revision_no_truncate ON public.programme_programmedeliveryrevision;
DROP TRIGGER IF EXISTS programme_working_revision_no_truncate ON public.programme_programmeworkingrevision;
DROP TRIGGER IF EXISTS programme_source_binding_no_truncate ON public.programme_programmeitemsourcebinding;
DROP TRIGGER IF EXISTS programme_item_no_truncate ON public.programme_programmeitem;
DROP TRIGGER IF EXISTS programme_control_no_truncate ON public.programme_programmeeditioncontrol;
DROP TRIGGER IF EXISTS programme_receipt_dependency_cursor_guard ON public.programme_programmecommandreceipt;
DROP TRIGGER IF EXISTS programme_requirement_dependency_cursor_guard ON public.programme_programmereadinessrequirement;
DROP TRIGGER IF EXISTS programme_public_rendition_command_evidence_guard ON public.programme_programmepublicrendition;
DROP TRIGGER IF EXISTS programme_readiness_evidence_command_evidence_guard ON public.programme_programmereadinessevidence;
DROP TRIGGER IF EXISTS programme_requirement_revision_command_evidence_guard ON public.programme_programmereadinessrequirementrevision;
DROP TRIGGER IF EXISTS programme_discussion_command_evidence_guard ON public.programme_programmedepartmentdiscussionentry;
DROP TRIGGER IF EXISTS programme_delivery_command_evidence_guard ON public.programme_programmedeliveryrevision;
DROP TRIGGER IF EXISTS programme_working_command_evidence_guard ON public.programme_programmeworkingrevision;
DROP TRIGGER IF EXISTS programme_requirement_revision_history_guard ON public.programme_programmereadinessrequirementrevision;
DROP TRIGGER IF EXISTS programme_requirement_history_guard ON public.programme_programmereadinessrequirement;
DROP TRIGGER IF EXISTS programme_binding_source_shape_guard ON public.programme_programmeitemsourcebinding;
DROP TRIGGER IF EXISTS programme_item_source_shape_guard ON public.programme_programmeitem;
DROP TRIGGER IF EXISTS programme_receipt_control_evidence_guard ON public.programme_programmecommandreceipt;
DROP TRIGGER IF EXISTS programme_control_evidence_guard ON public.programme_programmeeditioncontrol;
DROP TRIGGER IF EXISTS programme_receipt_item_evidence_guard ON public.programme_programmecommandreceipt;
DROP TRIGGER IF EXISTS programme_item_evidence_guard ON public.programme_programmeitem;
DROP TRIGGER IF EXISTS programme_receipt_guard ON public.programme_programmecommandreceipt;
DROP TRIGGER IF EXISTS programme_public_rendition_guard ON public.programme_programmepublicrendition;
DROP TRIGGER IF EXISTS programme_readiness_evidence_guard ON public.programme_programmereadinessevidence;
DROP TRIGGER IF EXISTS programme_requirement_revision_guard ON public.programme_programmereadinessrequirementrevision;
DROP TRIGGER IF EXISTS programme_requirement_guard ON public.programme_programmereadinessrequirement;
DROP TRIGGER IF EXISTS programme_discussion_entry_guard ON public.programme_programmedepartmentdiscussionentry;
DROP TRIGGER IF EXISTS programme_delivery_revision_guard ON public.programme_programmedeliveryrevision;
DROP TRIGGER IF EXISTS programme_working_revision_guard ON public.programme_programmeworkingrevision;
DROP TRIGGER IF EXISTS programme_source_binding_guard ON public.programme_programmeitemsourcebinding;
DROP TRIGGER IF EXISTS programme_item_guard ON public.programme_programmeitem;
DROP TRIGGER IF EXISTS programme_control_guard ON public.programme_programmeeditioncontrol;
DROP FUNCTION IF EXISTS public.maru_validate_programme_requirement_history();
DROP FUNCTION IF EXISTS public.maru_validate_programme_dependency_cursors();
DROP FUNCTION IF EXISTS public.maru_refuse_programme_truncate();
DROP FUNCTION IF EXISTS public.maru_validate_programme_source_shape();
DROP FUNCTION IF EXISTS public.maru_validate_programme_control_evidence();
DROP FUNCTION IF EXISTS public.maru_validate_programme_item_evidence();
DROP FUNCTION IF EXISTS public.maru_guard_programme_receipt();
DROP FUNCTION IF EXISTS public.maru_guard_programme_public_rendition();
DROP FUNCTION IF EXISTS public.maru_guard_programme_readiness_evidence();
DROP FUNCTION IF EXISTS public.maru_guard_programme_requirement_revision();
DROP FUNCTION IF EXISTS public.maru_guard_programme_requirement();
DROP FUNCTION IF EXISTS public.maru_guard_programme_layer_revision();
DROP FUNCTION IF EXISTS public.maru_guard_programme_source_binding();
DROP FUNCTION IF EXISTS public.maru_guard_programme_item();
DROP FUNCTION IF EXISTS public.maru_guard_programme_control();
"""


class Migration(migrations.Migration):
    """Install Programme database-owned scope and evidence invariants."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0001_initial"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
