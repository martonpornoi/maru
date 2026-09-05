"""Install exact-revision review invariants and receipt-backed transition guards."""

# ruff: noqa: E501 -- Keep auditable PostgreSQL contracts readable without wrapping literals.

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

REVIEW_TABLES = (
    ("policy", "applications_programmereviewpolicy"),
    ("case", "applications_programmereviewcase"),
    ("assignment", "applications_programmereviewassignment"),
    ("entry", "applications_programmereviewentry"),
    ("decision", "applications_programmereviewdecision"),
    ("ack", "applications_programmedecisionacknowledgement"),
    ("receipt", "applications_programmereviewreceipt"),
)
RETRY_TABLES = (
    "applications_applicationcommandreceipt",
    "applications_programmecommandreceipt",
    "applications_programmeimportcommandreceipt",
    "applications_programmereviewreceipt",
)

RETRY_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_review_retry_namespace()
RETURNS trigger AS $review_retry$
DECLARE
    relation_name text;
    collision boolean;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'maru:applications:retry:' || NEW.edition_id::text || ':' || NEW.actor_id::text || ':' || NEW.retry_key::text, 0
    ));
    FOREACH relation_name IN ARRAY ARRAY[
        'applications_applicationcommandreceipt', 'applications_programmecommandreceipt',
        'applications_programmeimportcommandreceipt', 'applications_programmereviewreceipt'
    ] LOOP
        IF relation_name <> TG_TABLE_NAME THEN
            EXECUTE pg_catalog.format('SELECT EXISTS (SELECT 1 FROM public.%I WHERE edition_id = $1 AND actor_id = $2 AND retry_key = $3)', relation_name)
              INTO collision USING NEW.edition_id, NEW.actor_id, NEW.retry_key;
            IF collision THEN
                RAISE EXCEPTION 'Applications retry identity already belongs to another workflow' USING ERRCODE = '23505';
            END IF;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$review_retry$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_review()
RETURNS trigger AS $review_guard$
DECLARE
    value jsonb := pg_catalog.to_jsonb(NEW);
    old_value jsonb;
    call_key uuid;
    case_key uuid;
    actor_key uuid;
    call_row record;
    case_row record;
    entry_row record;
    stage_value jsonb;
    criterion jsonb;
    template_value jsonb;
    codes text[] := ARRAY[]::text[];
    criterion_codes text[];
    outcome_codes text[] := ARRAY[]::text[];
    require_current boolean := false;
BEGIN
    IF TG_OP = 'DELETE' OR pg_catalog.current_setting('maru.applications_programme_writer', true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme review requires its closed writer and governed retention' USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        old_value := pg_catalog.to_jsonb(OLD);
        IF TG_TABLE_NAME = 'applications_programmereviewcase' THEN
            IF value - ARRAY['updated_at', 'version', 'stage', 'state'] <> old_value - ARRAY['updated_at', 'version', 'stage', 'state']
               OR NEW.version <> OLD.version + 1 THEN
                RAISE EXCEPTION 'Review case binding is immutable and versions are contiguous' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'applications_programmereviewassignment' THEN
            IF value - ARRAY['updated_at', 'version', 'state'] <> old_value - ARRAY['updated_at', 'version', 'state']
               OR NEW.version <= OLD.version OR OLD.state NOT IN ('pending', 'active')
               OR NOT ((OLD.state = 'pending' AND NEW.state IN ('active', 'recused', 'removed'))
                       OR (OLD.state = 'active' AND NEW.state IN ('recused', 'removed'))) THEN
                RAISE EXCEPTION 'Review assignment cannot change identity or reactivate' USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Programme review evidence is append-only' USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_TABLE_NAME = 'applications_programmereviewpolicy' THEN
        call_key := NEW.call_id;
        actor_key := NEW.actor_id;
        require_current := true;
    ELSIF TG_TABLE_NAME = 'applications_programmereviewcase' THEN
        case_key := NEW.id;
        actor_key := NEW.created_by_id;
        SELECT * INTO case_row FROM public.applications_programmeproposal WHERE id = NEW.proposal_id;
        call_key := case_row.call_id;
        IF NOT EXISTS (
            SELECT 1 FROM public.applications_programmeproposalrevision r
            JOIN public.applications_programmereviewpolicy p ON p.id = NEW.policy_id AND p.call_id = call_key
            WHERE r.id = NEW.revision_id AND r.proposal_id = NEW.proposal_id
              AND r.organization_id = case_row.organization_id AND r.edition_id = case_row.edition_id
              AND NEW.stage < pg_catalog.jsonb_array_length(p.stages)
        ) OR (TG_OP = 'INSERT' AND (NEW.version <> 1 OR NEW.stage <> 0 OR NEW.state <> 'open')) THEN
            RAISE EXCEPTION 'Review case must pin one coherent revision and policy' USING ERRCODE = '23514';
        END IF;
        -- Current actor proof is attached to each entry, not the historical opener.
        actor_key := NULL;
    ELSIF TG_TABLE_NAME IN ('applications_programmereviewdecision', 'applications_programmedecisionacknowledgement') THEN
        SELECT * INTO entry_row FROM public.applications_programmereviewentry WHERE id = (value->>'entry_id')::uuid;
        case_key := entry_row.case_id;
        actor_key := entry_row.actor_id;
    ELSE
        case_key := (value->>'case_id')::uuid;
        actor_key := COALESCE((value->>'actor_id')::uuid, (value->>'account_id')::uuid);
        IF case_key IS NULL AND TG_TABLE_NAME = 'applications_programmereviewreceipt' THEN
            SELECT call_id INTO call_key FROM public.applications_programmereviewpolicy WHERE id = NEW.policy_id;
        END IF;
    END IF;
    IF case_key IS NOT NULL AND call_key IS NULL THEN
        SELECT p.call_id INTO call_key FROM public.applications_programmereviewcase c
        JOIN public.applications_programmeproposal p ON p.id = c.proposal_id WHERE c.id = case_key;
    END IF;
    SELECT * INTO call_row FROM public.applications_programmecall WHERE id = call_key;
    IF call_row IS NULL THEN
        RAISE EXCEPTION 'Programme review owner scope unavailable' USING ERRCODE = '23514';
    END IF;
    PERFORM public.maru_workforce_page9_try_scope_mutex(pg_catalog.hashtextextended(
        'maru.workforce.department:' || call_row.organization_id::text || ':' || call_row.edition_id::text, 0
    ));
    IF actor_key IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.identity_account WHERE id = actor_key AND account_kind = 'person'
          AND is_active AND email_verified_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Programme review actor must be an active verified person' USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME IN ('applications_programmereviewentry', 'applications_programmereviewreceipt') THEN
        require_current := NEW.action <> 'acknowledged';
    ELSIF TG_TABLE_NAME = 'applications_programmereviewassignment' THEN
        require_current := true;
    END IF;
    IF require_current AND NOT EXISTS (
        SELECT 1 FROM public.workforce_department d
        JOIN public.events_eventedition e ON e.id = d.edition_id AND e.organization_id = d.organization_id
        JOIN public.organizations_organization o ON o.id = e.organization_id
        WHERE d.id = call_row.owner_department_id AND d.organization_id = call_row.organization_id
          AND d.edition_id = call_row.edition_id AND d.retired_at IS NULL
          AND e.lifecycle IN ('draft', 'preparing') AND o.lifecycle IN ('draft', 'active')
    ) THEN
        RAISE EXCEPTION 'Programme review requires current private planning ownership' USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'applications_programmereviewpolicy' THEN
        IF NEW.version <> 1 + COALESCE((SELECT max(version) FROM public.applications_programmereviewpolicy WHERE call_id = NEW.call_id), 0)
           OR NEW.digest !~ '^[0-9a-f]{64}$' OR pg_catalog.length(pg_catalog.btrim(NEW.reason)) NOT BETWEEN 1 AND 2000
           OR pg_catalog.jsonb_typeof(NEW.stages) IS DISTINCT FROM 'array'
           OR pg_catalog.jsonb_typeof(NEW.templates) IS DISTINCT FROM 'array'
           OR pg_catalog.jsonb_array_length(NEW.stages) NOT BETWEEN 1 AND 8
           OR pg_catalog.jsonb_array_length(NEW.templates) <> 4 THEN
            RAISE EXCEPTION 'Programme review policy is not bounded and contiguous' USING ERRCODE = '23514';
        END IF;
        FOR stage_value IN SELECT * FROM pg_catalog.jsonb_array_elements(NEW.stages) LOOP
            IF pg_catalog.jsonb_typeof(stage_value) IS DISTINCT FROM 'object'
               OR stage_value - ARRAY['code', 'required_reviews', 'criteria', 'question_keys', 'anonymous', 'discussion'] <> '{}'::jsonb
               OR NOT stage_value ?& ARRAY['code', 'required_reviews', 'criteria', 'question_keys', 'anonymous', 'discussion']
               OR pg_catalog.jsonb_typeof(stage_value->'code') IS DISTINCT FROM 'string'
               OR pg_catalog.jsonb_typeof(stage_value->'required_reviews') IS DISTINCT FROM 'number'
               OR stage_value->>'code' !~ '^[a-z][a-z0-9_-]{0,39}$' OR stage_value->>'code' = ANY(codes)
               OR stage_value->>'required_reviews' !~ '^[0-9]+$' OR (stage_value->>'required_reviews')::numeric NOT BETWEEN 1 AND 16
               OR pg_catalog.jsonb_typeof(stage_value->'anonymous') IS DISTINCT FROM 'boolean'
               OR pg_catalog.jsonb_typeof(stage_value->'discussion') IS DISTINCT FROM 'boolean'
               OR pg_catalog.jsonb_typeof(stage_value->'criteria') IS DISTINCT FROM 'array'
               OR pg_catalog.jsonb_array_length(stage_value->'criteria') NOT BETWEEN 1 AND 16
               OR pg_catalog.jsonb_typeof(stage_value->'question_keys') IS DISTINCT FROM 'array'
               OR pg_catalog.jsonb_array_length(stage_value->'question_keys') NOT BETWEEN 1 AND 500
               OR EXISTS (
                   SELECT 1 FROM pg_catalog.jsonb_array_elements(stage_value->'question_keys') k
                   WHERE pg_catalog.jsonb_typeof(k) <> 'string' OR k #>> '{}' !~ '^[a-z][a-z0-9_-]{0,79}$'
                     OR NOT EXISTS (SELECT 1 FROM public.applications_applicationquestion q
                         WHERE q.definition_id = call_row.definition_id AND q.key = k #>> '{}')
               )
               OR (SELECT count(DISTINCT k) FROM pg_catalog.jsonb_array_elements(stage_value->'question_keys') k)
                   <> pg_catalog.jsonb_array_length(stage_value->'question_keys') THEN
                RAISE EXCEPTION 'Programme review stage shape is invalid' USING ERRCODE = '23514';
            END IF;
            codes := pg_catalog.array_append(codes, stage_value->>'code');
            criterion_codes := ARRAY[]::text[];
            FOR criterion IN SELECT * FROM pg_catalog.jsonb_array_elements(stage_value->'criteria') LOOP
                IF pg_catalog.jsonb_typeof(criterion) IS DISTINCT FROM 'object'
                   OR criterion - ARRAY['code', 'label', 'minimum', 'maximum'] <> '{}'::jsonb
                   OR NOT criterion ?& ARRAY['code', 'label', 'minimum', 'maximum']
                   OR pg_catalog.jsonb_typeof(criterion->'code') IS DISTINCT FROM 'string'
                   OR pg_catalog.jsonb_typeof(criterion->'label') IS DISTINCT FROM 'string'
                   OR pg_catalog.jsonb_typeof(criterion->'minimum') IS DISTINCT FROM 'number'
                   OR pg_catalog.jsonb_typeof(criterion->'maximum') IS DISTINCT FROM 'number'
                   OR criterion->>'code' !~ '^[a-z][a-z0-9_-]{0,39}$' OR criterion->>'code' = ANY(criterion_codes)
                   OR pg_catalog.length(pg_catalog.btrim(criterion->>'label')) NOT BETWEEN 1 AND 200
                   OR criterion->>'minimum' !~ '^[0-9]+$' OR criterion->>'maximum' !~ '^[0-9]+$'
                   OR (criterion->>'minimum')::numeric NOT BETWEEN 0 AND 10000
                   OR (criterion->>'maximum')::numeric NOT BETWEEN (criterion->>'minimum')::numeric AND 10000 THEN
                    RAISE EXCEPTION 'Programme review rubric shape is invalid' USING ERRCODE = '23514';
                END IF;
                criterion_codes := pg_catalog.array_append(criterion_codes, criterion->>'code');
            END LOOP;
        END LOOP;
        FOR template_value IN SELECT * FROM pg_catalog.jsonb_array_elements(NEW.templates) LOOP
            IF pg_catalog.jsonb_typeof(template_value) IS DISTINCT FROM 'object'
               OR template_value - ARRAY['outcome', 'text', 'acknowledgement_required'] <> '{}'::jsonb
               OR NOT template_value ?& ARRAY['outcome', 'text', 'acknowledgement_required']
               OR pg_catalog.jsonb_typeof(template_value->'outcome') IS DISTINCT FROM 'string'
               OR pg_catalog.jsonb_typeof(template_value->'text') IS DISTINCT FROM 'string'
               OR template_value->>'outcome' NOT IN ('accepted', 'rejected', 'waitlisted', 'revision_requested')
               OR template_value->>'outcome' = ANY(outcome_codes)
               OR pg_catalog.length(pg_catalog.btrim(template_value->>'text')) NOT BETWEEN 1 AND 3000
               OR pg_catalog.jsonb_typeof(template_value->'acknowledgement_required') IS DISTINCT FROM 'boolean' THEN
                RAISE EXCEPTION 'Programme review decision templates are incomplete' USING ERRCODE = '23514';
            END IF;
            outcome_codes := pg_catalog.array_append(outcome_codes, template_value->>'outcome');
        END LOOP;
    END IF;
    RETURN NEW;
END;
$review_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""


STAGE_READY_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_review_stage_ready(case_key uuid, stage_index integer, evidence_version bigint)
RETURNS boolean AS $review_ready$
DECLARE
    moderation_version bigint;
    required_count integer;
    score_count integer;
BEGIN
    SELECT (p.stages->stage_index->>'required_reviews')::integer INTO required_count
      FROM public.applications_programmereviewcase c
      JOIN public.applications_programmereviewpolicy p ON p.id = c.policy_id WHERE c.id = case_key;
    SELECT max(version) INTO moderation_version FROM public.applications_programmereviewentry
      WHERE case_id = case_key AND stage = stage_index AND action = 'moderated' AND version <= evidence_version;
    IF moderation_version IS NULL OR required_count IS NULL OR EXISTS (
        SELECT 1 FROM public.applications_programmereviewentry
        WHERE case_id = case_key AND version > moderation_version AND version <= evidence_version
          AND ((stage = stage_index AND action IN ('reviewer_assigned', 'conflict_cleared', 'reviewer_recused', 'reviewer_removed', 'scored', 'discussed'))
               OR (stage <= stage_index AND action = 'stage_reopened'))
    ) THEN RETURN false; END IF;
    WITH states AS (
        SELECT DISTINCT ON (assignment_id) assignment_id, action FROM public.applications_programmereviewentry
        WHERE case_id = case_key AND stage = stage_index AND version <= evidence_version
          AND action IN ('reviewer_assigned', 'conflict_cleared', 'reviewer_recused', 'reviewer_removed')
        ORDER BY assignment_id, version DESC
    ), scores AS (
        SELECT DISTINCT ON (assignment_id) assignment_id, actor_id FROM public.applications_programmereviewentry
        WHERE case_id = case_key AND stage = stage_index AND action = 'scored' AND version <= evidence_version
        ORDER BY assignment_id, version DESC
    ) SELECT count(*) INTO score_count FROM scores
      JOIN states USING (assignment_id)
      JOIN public.identity_account a ON a.id = scores.actor_id
      WHERE states.action = 'conflict_cleared' AND a.account_kind = 'person' AND a.is_active AND a.email_verified_at IS NOT NULL;
    RETURN score_count >= required_count;
END;
$review_ready$
LANGUAGE plpgsql STABLE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

EVIDENCE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_validate_programme_review()
RETURNS trigger AS $review_evidence$
DECLARE
    data jsonb := pg_catalog.to_jsonb(NEW);
    policy_row record;
    case_row record;
    proposal_row record;
    call_row record;
    entry_row record;
    prior_entry record;
    assignment_row record;
    receipt_row record;
    decision_row record;
    ack_row record;
    case_key uuid;
    entry_version bigint;
    expected_target uuid;
    expected_aggregate uuid;
    expected_actor uuid;
    stage_value jsonb;
    criterion jsonb;
    template_value jsonb;
    prior_assignment_action text;
    previous_state text;
    previous_stage integer;
    stage_index integer;
    expected_fields text[];
BEGIN
    IF TG_TABLE_NAME = 'applications_programmereviewpolicy' THEN
        SELECT * INTO policy_row FROM public.applications_programmereviewpolicy WHERE id = NEW.id;
    ELSIF TG_TABLE_NAME = 'applications_programmereviewreceipt' AND data->>'case_id' IS NULL THEN
        SELECT * INTO policy_row FROM public.applications_programmereviewpolicy WHERE id = NEW.policy_id;
    ELSE
        IF TG_TABLE_NAME = 'applications_programmereviewcase' THEN
            case_key := NEW.id; entry_version := NEW.version;
        ELSIF TG_TABLE_NAME IN ('applications_programmereviewassignment', 'applications_programmereviewentry') THEN
            case_key := NEW.case_id; entry_version := NEW.version;
        ELSIF TG_TABLE_NAME = 'applications_programmereviewreceipt' THEN
            case_key := NEW.case_id; entry_version := NEW.resulting_version;
        ELSE
            SELECT * INTO entry_row FROM public.applications_programmereviewentry WHERE id = (data->>'entry_id')::uuid;
            case_key := entry_row.case_id; entry_version := entry_row.version;
        END IF;
        SELECT * INTO case_row FROM public.applications_programmereviewcase WHERE id = case_key;
        SELECT * INTO entry_row FROM public.applications_programmereviewentry WHERE case_id = case_key AND version = entry_version;
        SELECT * INTO policy_row FROM public.applications_programmereviewpolicy WHERE id = case_row.policy_id;
        SELECT * INTO proposal_row FROM public.applications_programmeproposal WHERE id = case_row.proposal_id;
        IF case_row IS NULL OR entry_row IS NULL OR entry_version > case_row.version THEN
            RAISE EXCEPTION 'Review transition lacks exact immutable evidence' USING ERRCODE = '23514';
        END IF;
        IF (TG_TABLE_NAME = 'applications_programmereviewdecision' AND entry_row.action <> 'decided')
           OR (TG_TABLE_NAME = 'applications_programmedecisionacknowledgement' AND entry_row.action <> 'acknowledged') THEN
            RAISE EXCEPTION 'Decision and acknowledgement rows require their own action evidence' USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT * INTO call_row FROM public.applications_programmecall WHERE id = policy_row.call_id;
    expected_aggregate := COALESCE(case_key, call_row.id);
    entry_version := COALESCE(entry_version, policy_row.version);
    SELECT * INTO receipt_row FROM public.applications_programmereviewreceipt
      WHERE aggregate_id = expected_aggregate AND resulting_version = entry_version;
    IF receipt_row IS NULL OR receipt_row.policy_id <> policy_row.id
       OR receipt_row.case_id IS DISTINCT FROM case_key
       OR receipt_row.organization_id <> call_row.organization_id OR receipt_row.edition_id <> call_row.edition_id
       OR receipt_row.expected_version <> entry_version - 1
       OR receipt_row.request_digest !~ '^[0-9a-f]{64}$'
       OR receipt_row.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$' THEN
        RAISE EXCEPTION 'Programme review receipt is absent or incoherent' USING ERRCODE = '23514';
    END IF;
    IF case_key IS NULL THEN
        expected_target := policy_row.id; expected_actor := policy_row.actor_id;
        IF receipt_row.action <> 'policy_created' THEN
            RAISE EXCEPTION 'Review policy needs its own creation receipt' USING ERRCODE = '23514';
        END IF;
    ELSE
        expected_actor := entry_row.actor_id;
        IF receipt_row.action <> entry_row.action OR entry_row.stage >= pg_catalog.jsonb_array_length(policy_row.stages)
           OR pg_catalog.jsonb_typeof(entry_row.payload) IS DISTINCT FROM 'object'
           OR pg_catalog.length(entry_row.reason) > 2000
           OR (entry_row.action NOT IN ('conflict_cleared', 'reviewer_recused', 'acknowledged') AND pg_catalog.length(pg_catalog.btrim(entry_row.reason)) = 0) THEN
            RAISE EXCEPTION 'Review evidence action, stage, or reason is invalid' USING ERRCODE = '23514';
        END IF;
        SELECT * INTO prior_entry FROM public.applications_programmereviewentry WHERE case_id = case_key AND version = entry_version - 1;
        IF (entry_version = 1 AND entry_row.action <> 'case_opened') OR (entry_version > 1 AND prior_entry IS NULL)
           OR (entry_row.action = 'case_opened' AND entry_version <> 1) THEN
            RAISE EXCEPTION 'Review evidence versions must start once and remain contiguous' USING ERRCODE = '23514';
        END IF;
        stage_value := policy_row.stages->entry_row.stage;
        expected_target := entry_row.id;
        previous_state := COALESCE((
            SELECT CASE WHEN action = 'stage_reopened' THEN 'open' ELSE payload->>'outcome' END
            FROM public.applications_programmereviewentry WHERE case_id = case_key AND version < entry_version
              AND action IN ('decided', 'stage_reopened') ORDER BY version DESC LIMIT 1
        ), 'open');
        previous_stage := COALESCE((
            SELECT (payload->>'to_stage')::integer FROM public.applications_programmereviewentry
            WHERE case_id = case_key AND version < entry_version AND action IN ('stage_advanced', 'stage_reopened')
            ORDER BY version DESC LIMIT 1
        ), 0);
        IF entry_row.action NOT IN ('acknowledged', 'reviewer_recused', 'reviewer_removed')
           AND previous_state <> 'open'
           AND NOT (previous_state = 'waitlisted' AND entry_row.action IN ('decided', 'stage_reopened')) THEN
            RAISE EXCEPTION 'Final review evidence cannot be silently replaced' USING ERRCODE = '23514';
        END IF;
        IF entry_row.action NOT IN ('reviewer_recused', 'reviewer_removed', 'stage_reopened') AND entry_row.stage <> previous_stage THEN
            RAISE EXCEPTION 'Review evidence must use its current stage' USING ERRCODE = '23514';
        END IF;
        IF entry_row.action <> 'acknowledged' AND (
            proposal_row.state <> 'submitted' OR proposal_row.sealed_revision_id IS DISTINCT FROM case_row.revision_id
            OR proposal_row.submitted_revision_id IS DISTINCT FROM case_row.revision_id
        ) THEN
            RAISE EXCEPTION 'Fresh review evidence requires the exact submitted seal' USING ERRCODE = '23514';
        END IF;

        IF entry_row.action = 'case_opened' THEN
            expected_fields := ARRAY['policy_id']; expected_target := case_key;
            IF entry_row.payload->>'policy_id' IS DISTINCT FROM case_row.policy_id::text OR entry_row.actor_id <> case_row.created_by_id
               OR EXISTS (SELECT 1 FROM public.applications_applicationsubmission WHERE id = proposal_row.submission_id AND account_id = entry_row.actor_id)
               OR EXISTS (SELECT 1 FROM public.applications_programmeproposalcollaborator WHERE proposal_id = case_row.proposal_id AND account_id = entry_row.actor_id) THEN
                RAISE EXCEPTION 'Review case opener or policy is conflicting' USING ERRCODE = '23514';
            END IF;
        ELSIF entry_row.action IN ('reviewer_assigned', 'conflict_cleared', 'reviewer_recused', 'reviewer_removed', 'scored', 'discussed') THEN
            SELECT * INTO assignment_row FROM public.applications_programmereviewassignment WHERE id = entry_row.assignment_id;
            IF assignment_row IS NULL OR assignment_row.case_id <> case_key OR assignment_row.stage <> entry_row.stage THEN
                RAISE EXCEPTION 'Review evidence assignment scope mismatch' USING ERRCODE = '23514';
            END IF;
            expected_target := assignment_row.id;
            SELECT action INTO prior_assignment_action FROM public.applications_programmereviewentry
              WHERE assignment_id = assignment_row.id AND version < entry_version
                AND action IN ('reviewer_assigned', 'conflict_cleared', 'reviewer_recused', 'reviewer_removed')
              ORDER BY version DESC LIMIT 1;
            IF entry_row.action = 'reviewer_assigned' THEN
                expected_fields := ARRAY['reviewer_id', 'state'];
                IF prior_assignment_action IS NOT NULL OR entry_row.payload->>'state' IS DISTINCT FROM 'pending'
                   OR entry_row.payload->>'reviewer_id' IS DISTINCT FROM assignment_row.account_id::text
                   OR assignment_row.account_id = case_row.created_by_id
                   OR EXISTS (SELECT 1 FROM public.applications_applicationsubmission WHERE id = proposal_row.submission_id AND account_id = assignment_row.account_id)
                   OR EXISTS (SELECT 1 FROM public.applications_programmeproposalcollaborator WHERE proposal_id = case_row.proposal_id AND account_id = assignment_row.account_id)
                   OR EXISTS (SELECT 1 FROM public.applications_programmereviewentry WHERE case_id = case_key AND actor_id = assignment_row.account_id AND action IN ('moderated', 'decided'))
                   OR (SELECT count(*) FROM public.applications_programmereviewassignment WHERE case_id = case_key AND stage = entry_row.stage) > 16 THEN
                    RAISE EXCEPTION 'Review assignment lacks independence or exceeds bounds' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF entry_row.action <> 'reviewer_removed' AND assignment_row.account_id <> entry_row.actor_id THEN
                    RAISE EXCEPTION 'Only the assigned reviewer can declare, score, or discuss' USING ERRCODE = '23514';
                END IF;
                IF entry_row.action IN ('conflict_cleared', 'reviewer_recused', 'reviewer_removed') THEN
                    expected_fields := ARRAY['state'];
                    IF prior_assignment_action IS NULL OR prior_assignment_action NOT IN ('reviewer_assigned', 'conflict_cleared')
                       OR (entry_row.action = 'conflict_cleared' AND prior_assignment_action <> 'reviewer_assigned')
                       OR entry_row.payload->>'state' IS DISTINCT FROM (CASE entry_row.action WHEN 'conflict_cleared' THEN 'active' WHEN 'reviewer_recused' THEN 'recused' ELSE 'removed' END) THEN
                        RAISE EXCEPTION 'Reviewer conflict response is stale or not a one-way transition' USING ERRCODE = '23514';
                    END IF;
                ELSE
                    IF prior_assignment_action IS DISTINCT FROM 'conflict_cleared' THEN
                        RAISE EXCEPTION 'Review content work requires explicit no-conflict evidence' USING ERRCODE = '23514';
                    END IF;
                    IF entry_row.action = 'scored' THEN
                        expected_fields := ARRAY['scores'];
                        IF pg_catalog.jsonb_typeof(entry_row.payload->'scores') IS DISTINCT FROM 'object'
                           OR (SELECT count(*) FROM pg_catalog.jsonb_object_keys(entry_row.payload->'scores')) <> pg_catalog.jsonb_array_length(stage_value->'criteria') THEN
                            RAISE EXCEPTION 'Review scores must cover the complete pinned rubric' USING ERRCODE = '23514';
                        END IF;
                        FOR criterion IN SELECT * FROM pg_catalog.jsonb_array_elements(stage_value->'criteria') LOOP
                            IF pg_catalog.jsonb_typeof(entry_row.payload->'scores'->(criterion->>'code')) IS DISTINCT FROM 'number'
                               OR entry_row.payload->'scores'->>(criterion->>'code') !~ '^[0-9]+$'
                               OR (entry_row.payload->'scores'->>(criterion->>'code'))::numeric NOT BETWEEN (criterion->>'minimum')::numeric AND (criterion->>'maximum')::numeric THEN
                                RAISE EXCEPTION 'Review score falls outside the exact pinned rubric' USING ERRCODE = '23514';
                            END IF;
                        END LOOP;
                    ELSE
                        expected_fields := ARRAY['text'];
                        IF NOT (stage_value->>'discussion')::boolean
                           OR pg_catalog.jsonb_typeof(entry_row.payload->'text') IS DISTINCT FROM 'string'
                           OR pg_catalog.length(pg_catalog.btrim(entry_row.payload->>'text')) NOT BETWEEN 1 AND 3000
                           OR NOT EXISTS (SELECT 1 FROM public.applications_programmereviewentry WHERE assignment_id = assignment_row.id AND action = 'scored' AND version < entry_version) THEN
                            RAISE EXCEPTION 'Peer discussion requires an independent score and explicit policy' USING ERRCODE = '23514';
                        END IF;
                    END IF;
                END IF;
            END IF;
        ELSIF entry_row.action IN ('moderated', 'stage_advanced', 'stage_reopened', 'decided') THEN
            IF EXISTS (SELECT 1 FROM public.applications_applicationsubmission WHERE id = proposal_row.submission_id AND account_id = entry_row.actor_id)
               OR EXISTS (SELECT 1 FROM public.applications_programmeproposalcollaborator WHERE proposal_id = case_row.proposal_id AND account_id = entry_row.actor_id)
               OR EXISTS (SELECT 1 FROM public.applications_programmereviewassignment WHERE case_id = case_key AND account_id = entry_row.actor_id)
               OR (entry_row.action = 'decided' AND EXISTS (SELECT 1 FROM public.applications_programmereviewentry WHERE case_id = case_key AND actor_id = entry_row.actor_id AND action = 'moderated')) THEN
                RAISE EXCEPTION 'Review moderation and decision require independent actors' USING ERRCODE = '23514';
            END IF;
            IF entry_row.action = 'moderated' THEN
                expected_fields := ARRAY['evidence_version'];
                IF entry_row.payload->'evidence_version' IS DISTINCT FROM pg_catalog.to_jsonb(entry_version - 1) THEN
                    RAISE EXCEPTION 'Moderation must pin the exact preceding evidence version' USING ERRCODE = '23514';
                END IF;
            ELSIF entry_row.action = 'stage_advanced' THEN
                expected_fields := ARRAY['to_stage'];
                IF entry_row.payload->'to_stage' IS DISTINCT FROM pg_catalog.to_jsonb(previous_stage + 1)
                   OR previous_stage + 1 >= pg_catalog.jsonb_array_length(policy_row.stages)
                   OR NOT public.maru_applications_review_stage_ready(case_key, previous_stage, entry_version - 1) THEN
                    RAISE EXCEPTION 'Review stage advancement needs fresh sufficient evidence' USING ERRCODE = '23514';
                END IF;
            ELSIF entry_row.action = 'stage_reopened' THEN
                expected_fields := ARRAY['from_stage', 'to_stage'];
                IF entry_row.stage > previous_stage OR entry_row.payload->'from_stage' IS DISTINCT FROM pg_catalog.to_jsonb(previous_stage)
                   OR entry_row.payload->'to_stage' IS DISTINCT FROM pg_catalog.to_jsonb(entry_row.stage) THEN
                    RAISE EXCEPTION 'Stage reopening must name an exact earlier stage' USING ERRCODE = '23514';
                END IF;
            ELSE
                expected_fields := ARRAY['outcome'];
                SELECT * INTO decision_row FROM public.applications_programmereviewdecision WHERE entry_id = entry_row.id;
                expected_target := decision_row.id;
                IF decision_row IS NULL OR decision_row.revision_id <> case_row.revision_id
                   OR entry_row.payload->>'outcome' IS DISTINCT FROM decision_row.outcome
                   OR (previous_state = 'waitlisted' AND decision_row.outcome = 'waitlisted')
                   OR previous_stage <> pg_catalog.jsonb_array_length(policy_row.stages) - 1 THEN
                    RAISE EXCEPTION 'Review decision lacks its exact final-stage outcome' USING ERRCODE = '23514';
                END IF;
                FOR stage_index IN 0..pg_catalog.jsonb_array_length(policy_row.stages) - 1 LOOP
                    IF NOT public.maru_applications_review_stage_ready(case_key, stage_index, entry_version - 1) THEN
                        RAISE EXCEPTION 'Review decision requires all current score and moderation gates' USING ERRCODE = '23514';
                    END IF;
                END LOOP;
                SELECT v INTO template_value FROM pg_catalog.jsonb_array_elements(policy_row.templates) v WHERE v->>'outcome' = decision_row.outcome;
                IF decision_row.acknowledgement_required IS DISTINCT FROM (template_value->>'acknowledgement_required')::boolean
                   OR pg_catalog.left(decision_row.message, pg_catalog.length(template_value->>'text') + 2) IS DISTINCT FROM (template_value->>'text') || E'\n\n'
                   OR pg_catalog.length(pg_catalog.btrim(pg_catalog.substr(decision_row.message, pg_catalog.length(template_value->>'text') + 3))) NOT BETWEEN 1 AND 3000 THEN
                    RAISE EXCEPTION 'Decision message must use the pinned template and deliberate recipient text' USING ERRCODE = '23514';
                END IF;
            END IF;
        ELSIF entry_row.action = 'acknowledged' THEN
            expected_fields := ARRAY['decision_id'];
            SELECT * INTO ack_row FROM public.applications_programmedecisionacknowledgement WHERE entry_id = entry_row.id;
            SELECT * INTO decision_row FROM public.applications_programmereviewdecision WHERE id = ack_row.decision_id;
            expected_target := ack_row.id;
            IF ack_row IS NULL OR ack_row.account_id <> entry_row.actor_id OR decision_row.revision_id <> case_row.revision_id
               OR NOT decision_row.acknowledgement_required OR entry_row.payload->>'decision_id' IS DISTINCT FROM decision_row.id::text
               OR NOT EXISTS (SELECT 1 FROM public.applications_programmereviewentry WHERE id = decision_row.entry_id AND case_id = case_key AND version < entry_version)
               OR NOT EXISTS (SELECT 1 FROM public.applications_programmeproposalrevisioncontributor WHERE revision_id = case_row.revision_id AND account_id = entry_row.actor_id AND organization_id = call_row.organization_id AND edition_id = call_row.edition_id) THEN
                RAISE EXCEPTION 'Only an exact addressed recipient can acknowledge their own decision' USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Unknown Programme review action' USING ERRCODE = '23514';
        END IF;
        IF entry_row.payload - expected_fields <> '{}'::jsonb OR NOT entry_row.payload ?& expected_fields
           OR (entry_row.action NOT IN ('reviewer_assigned', 'conflict_cleared', 'reviewer_recused', 'reviewer_removed', 'scored', 'discussed') AND entry_row.assignment_id IS NOT NULL) THEN
            RAISE EXCEPTION 'Review action payload is not closed' USING ERRCODE = '23514';
        END IF;
        IF TG_TABLE_NAME = 'applications_programmereviewcase' AND (
            data->>'state' IS DISTINCT FROM (CASE WHEN entry_row.action = 'decided' THEN entry_row.payload->>'outcome' WHEN entry_row.action = 'stage_reopened' THEN 'open' ELSE previous_state END)
            OR (data->>'stage')::integer IS DISTINCT FROM (CASE WHEN entry_row.action IN ('stage_advanced', 'stage_reopened') THEN (entry_row.payload->>'to_stage')::integer ELSE previous_stage END)
        ) THEN
            RAISE EXCEPTION 'Review case state must match its exact transition evidence' USING ERRCODE = '23514';
        END IF;
        IF TG_TABLE_NAME = 'applications_programmereviewassignment' AND (
            NEW.id IS DISTINCT FROM entry_row.assignment_id OR data->>'state' IS DISTINCT FROM entry_row.payload->>'state'
            OR entry_row.action NOT IN ('reviewer_assigned', 'conflict_cleared', 'reviewer_recused', 'reviewer_removed')
        ) THEN
            RAISE EXCEPTION 'Assignment state must match its own transition evidence' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF receipt_row.target_id IS DISTINCT FROM expected_target OR receipt_row.actor_id IS DISTINCT FROM expected_actor
       OR NOT EXISTS (
           SELECT 1 FROM public.audit_auditevent a JOIN public.effects_domainevent e ON e.id = receipt_row.domain_event_id
           WHERE a.id = receipt_row.audit_event_id AND a.principal_kind = 'account' AND a.principal_id = expected_actor
             AND a.organization_id = call_row.organization_id AND a.event_edition_id = call_row.edition_id
             AND a.operation = 'applications.programme_review.command.' || receipt_row.action AND a.outcome = 'allow'
             AND a.capability_code = CASE
                 WHEN receipt_row.action IN ('policy_created', 'case_opened', 'reviewer_assigned', 'reviewer_removed') THEN 'applications.manage_programme_review'
                 WHEN receipt_row.action IN ('conflict_cleared', 'reviewer_recused', 'scored', 'discussed') THEN 'applications.review_programme'
                 WHEN receipt_row.action IN ('moderated', 'stage_advanced', 'stage_reopened') THEN 'applications.moderate_programme_review'
                 WHEN receipt_row.action = 'decided' THEN 'applications.decide_programme'
                 ELSE 'applications.acknowledge_programme_decision_self' END
             AND a.target_type = 'applications.programme_review' AND a.target_id = expected_aggregate
             AND a.correlation_id = receipt_row.correlation_id AND a.source_channel = receipt_row.source_channel
             AND e.causation_id = a.id AND e.actor_kind = 'account' AND e.actor_id = expected_actor
             AND e.organization_id = call_row.organization_id AND e.event_edition_id = call_row.edition_id
             AND e.aggregate_type = 'applications.programme_review' AND e.aggregate_id = expected_aggregate
             AND e.aggregate_version = entry_version AND e.correlation_id = receipt_row.correlation_id
             AND e.event_name = 'applications.programme_review.changed.v1' AND e.schema_version = 1
             AND e.payload = pg_catalog.jsonb_build_object('action', receipt_row.action, 'aggregate_id', expected_aggregate::text, 'resulting_version', entry_version::text)
             AND a.retention_class = 'applications-programme-restricted' AND e.retention_class = a.retention_class
             AND EXISTS (SELECT 1 FROM public.effects_outboxmessage b WHERE b.event_id = e.id AND b.organization_id = e.organization_id)
       ) THEN
        RAISE EXCEPTION 'Review receipt must bind exact actor, target, audit, and minimized event' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$review_evidence$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""


def _trigger_sql() -> str:
    statements = []
    for suffix, table in REVIEW_TABLES:
        statements.extend(
            (
                f"CREATE TRIGGER aa_applications_review_{suffix}_barrier BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();",
                f"CREATE TRIGGER applications_review_{suffix}_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_programme_review();",
                f"CREATE TRIGGER applications_review_{suffix}_truncate BEFORE TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.maru_applications_refuse_programme_truncate();",
                f"CREATE CONSTRAINT TRIGGER applications_review_{suffix}_evidence AFTER INSERT OR UPDATE ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_applications_validate_programme_review();",
            )
        )
    for table in RETRY_TABLES:
        statements.append(
            f"CREATE TRIGGER applications_review_retry_{table.removeprefix('applications_')} BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.maru_applications_review_retry_namespace();"
        )
    return "\n".join(statements)


def _drop_sql() -> str:
    statements = [
        f"DROP TRIGGER IF EXISTS applications_review_retry_{table.removeprefix('applications_')} ON public.{table};"
        for table in RETRY_TABLES
    ]
    for suffix, table in reversed(REVIEW_TABLES):
        statements.extend(
            f"DROP TRIGGER IF EXISTS {name} ON public.{table};"
            for name in (
                f"aa_applications_review_{suffix}_barrier",
                f"applications_review_{suffix}_guard",
                f"applications_review_{suffix}_truncate",
                f"applications_review_{suffix}_evidence",
            )
        )
    statements.extend(
        (
            "DROP FUNCTION IF EXISTS public.maru_applications_guard_programme_review();",
            "DROP FUNCTION IF EXISTS public.maru_applications_review_retry_namespace();",
            "DROP FUNCTION IF EXISTS public.maru_applications_validate_programme_review();",
            "DROP FUNCTION IF EXISTS public.maru_applications_review_stage_ready(uuid, integer, bigint);",
        )
    )
    return "\n".join(statements)


FORWARD_SQL = "\n".join(
    (
        RETRY_SQL,
        GUARD_SQL,
        STAGE_READY_SQL,
        EVIDENCE_SQL,
        _trigger_sql(),
        "REVOKE ALL ON FUNCTION public.maru_applications_guard_programme_review(), public.maru_applications_review_retry_namespace(), public.maru_applications_validate_programme_review(), public.maru_applications_review_stage_ready(uuid, integer, bigint) FROM PUBLIC;",
    )
)
REVERSE_SQL = _drop_sql()


class Migration(migrations.Migration):
    """Install review safeguards only after persistence and dormant vocabulary."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0013_programme_review_persistence"),
        ("authorization", "0024_programme_review_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)
    ]
