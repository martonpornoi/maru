"""Add governed Shift demand, claims, confirmation, and retained evidence."""

from __future__ import annotations

from typing import Any, ClassVar

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_guard_workforce_shift_demand()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_demand_guard$
DECLARE
    edition_organization uuid;
    edition_starts_on date;
    edition_ends_on date;
    edition_time_zone varchar;
    position_organization uuid;
    position_edition uuid;
    position_status varchar;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce Shift demand cannot be deleted normally'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, starts_on, ends_on, time_zone
      INTO edition_organization, edition_starts_on, edition_ends_on, edition_time_zone
      FROM public.events_eventedition
     WHERE id = NEW.edition_id
     FOR KEY SHARE;
    SELECT organization_id, edition_id, status
      INTO position_organization, position_edition, position_status
      FROM public.workforce_position
     WHERE id = NEW.position_id
     FOR UPDATE;
    IF edition_organization IS DISTINCT FROM NEW.organization_id
       OR position_organization IS DISTINCT FROM NEW.organization_id
       OR position_edition IS DISTINCT FROM NEW.edition_id
       OR position_status = 'closed'
    THEN
        RAISE EXCEPTION 'workforce Shift demand scope or Position is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.starts_at < (edition_starts_on::timestamp AT TIME ZONE edition_time_zone)
       OR NEW.ends_at > ((edition_ends_on + 1)::timestamp AT TIME ZONE edition_time_zone)
       OR NEW.ends_at <= NEW.starts_at
       OR NEW.break_minutes * interval '1 minute' >= NEW.ends_at - NEW.starts_at
       OR btrim(NEW.title) = ''
       OR btrim(NEW.location_label) = ''
       OR btrim(NEW.briefing) = ''
    THEN
        RAISE EXCEPTION 'workforce Shift demand planning values are invalid'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.command_version <> 1 OR NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'workforce Shift demand must begin as version-one draft'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.position_id IS DISTINCT FROM OLD.position_id
           OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'workforce Shift demand identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.command_version <> OLD.command_version + 1 THEN
            RAISE EXCEPTION 'workforce Shift demand version did not advance once'
                USING ERRCODE = '23514';
        END IF;
        IF ROW(NEW.title, NEW.location_label, NEW.briefing, NEW.supervision_note,
               NEW.starts_at, NEW.ends_at, NEW.required_headcount,
               NEW.break_minutes, NEW.minimum_rest_minutes)
           IS DISTINCT FROM
           ROW(OLD.title, OLD.location_label, OLD.briefing, OLD.supervision_note,
               OLD.starts_at, OLD.ends_at, OLD.required_headcount,
               OLD.break_minutes, OLD.minimum_rest_minutes)
           AND NOT (OLD.status = 'draft' AND NEW.status = 'draft')
        THEN
            RAISE EXCEPTION 'published workforce Shift planning is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NOT (
            (OLD.status = 'draft' AND NEW.status IN ('draft', 'open', 'cancelled'))
            OR (OLD.status = 'open' AND NEW.status IN ('locked', 'cancelled'))
            OR (OLD.status = 'locked' AND NEW.status IN ('open', 'completed', 'cancelled'))
        )
        THEN
            RAISE EXCEPTION 'workforce Shift demand transition is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF (NEW.published_at IS NULL) <> (NEW.published_by_id IS NULL)
       OR (NEW.locked_at IS NULL) <> (NEW.locked_by_id IS NULL)
       OR (NEW.locked_at IS NULL) <> (NEW.locked_headcount IS NULL)
       OR (NEW.locked_at IS NULL) <> (btrim(NEW.lock_reason) = '')
       OR (NEW.completed_at IS NULL) <> (NEW.completed_by_id IS NULL)
       OR (NEW.completed_at IS NULL) <> (btrim(NEW.completion_reason) = '')
       OR (NEW.cancelled_at IS NULL) <> (NEW.cancelled_by_id IS NULL)
       OR (NEW.cancelled_at IS NULL) <> (btrim(NEW.cancellation_reason) = '')
       OR (NEW.locked_headcount IS NOT NULL
           AND NEW.locked_headcount > NEW.required_headcount)
    THEN
        RAISE EXCEPTION 'workforce Shift demand evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;
    IF (NEW.status = 'draft' AND (
            NEW.published_at IS NOT NULL OR NEW.locked_at IS NOT NULL
            OR NEW.completed_at IS NOT NULL OR NEW.cancelled_at IS NOT NULL))
       OR (NEW.status = 'open' AND (
            NEW.published_at IS NULL OR NEW.locked_at IS NOT NULL
            OR NEW.completed_at IS NOT NULL OR NEW.cancelled_at IS NOT NULL))
       OR (NEW.status = 'locked' AND (
            NEW.published_at IS NULL OR NEW.locked_at IS NULL
            OR NEW.completed_at IS NOT NULL OR NEW.cancelled_at IS NOT NULL))
       OR (NEW.status = 'completed' AND (
            NEW.published_at IS NULL OR NEW.locked_at IS NULL
            OR NEW.completed_at IS NULL OR NEW.cancelled_at IS NOT NULL))
       OR (NEW.status = 'cancelled' AND (
            NEW.cancelled_at IS NULL OR NEW.completed_at IS NOT NULL))
    THEN
        RAISE EXCEPTION 'workforce Shift demand state evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$shift_demand_guard$;

CREATE TRIGGER workforce_shift_demand_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.workforce_shiftdemand
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_shift_demand();
REVOKE ALL ON FUNCTION public.maru_guard_workforce_shift_demand() FROM PUBLIC;

CREATE FUNCTION public.maru_guard_workforce_shift_position_dependency()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_position_dependency_guard$
BEGIN
    IF OLD.status IS DISTINCT FROM 'closed'
       AND NEW.status = 'closed'
       AND EXISTS (
           SELECT 1
             FROM public.workforce_shiftdemand
            WHERE position_id = NEW.id
              AND status IN ('draft', 'open', 'locked')
       )
    THEN
        RAISE EXCEPTION 'unfinished Workforce Shifts protect this Position'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$shift_position_dependency_guard$;

CREATE TRIGGER aa0_workforce_shift_position_dependency_guard
BEFORE UPDATE OF status ON public.workforce_position
FOR EACH ROW
EXECUTE FUNCTION public.maru_guard_workforce_shift_position_dependency();
REVOKE ALL ON FUNCTION public.maru_guard_workforce_shift_position_dependency()
FROM PUBLIC;

CREATE FUNCTION public.maru_guard_workforce_shift_demand_receipt()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_demand_receipt_guard$
DECLARE
    demand_organization uuid;
    demand_edition uuid;
    demand_version bigint;
    demand_status varchar;
    actor_active boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'workforce Shift demand receipts are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, command_version, status
      INTO demand_organization, demand_edition, demand_version, demand_status
      FROM public.workforce_shiftdemand
     WHERE id = NEW.demand_id
     FOR KEY SHARE;
    SELECT is_active INTO actor_active
      FROM public.identity_account WHERE id = NEW.actor_id FOR KEY SHARE;
    IF demand_organization IS DISTINCT FROM NEW.organization_id
       OR demand_edition IS DISTINCT FROM NEW.edition_id
       OR demand_version IS DISTINCT FROM NEW.resulting_version
       OR demand_status IS DISTINCT FROM NEW.resulting_status
       OR actor_active IS DISTINCT FROM TRUE
       OR btrim(NEW.reason) = ''
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR NOT (
           (NEW.action IN ('created', 'updated') AND NEW.resulting_status = 'draft')
           OR (NEW.action IN ('opened', 'reopened') AND NEW.resulting_status = 'open')
           OR (NEW.action = 'locked' AND NEW.resulting_status = 'locked')
           OR (NEW.action = 'completed' AND NEW.resulting_status = 'completed')
           OR (NEW.action = 'cancelled' AND NEW.resulting_status = 'cancelled')
       )
    THEN
        RAISE EXCEPTION 'workforce Shift demand receipt evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$shift_demand_receipt_guard$;

CREATE TRIGGER workforce_shift_demand_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_shiftdemandcommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_shift_demand_receipt();
REVOKE ALL ON FUNCTION public.maru_guard_workforce_shift_demand_receipt() FROM PUBLIC;

CREATE FUNCTION public.maru_guard_workforce_shift_commitment()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_commitment_guard$
DECLARE
    demand_organization uuid;
    demand_edition uuid;
    demand_position uuid;
    demand_start timestamptz;
    demand_end timestamptz;
    demand_rest integer;
    demand_status varchar;
    assignment_organization uuid;
    assignment_edition uuid;
    assignment_position uuid;
    assignment_account uuid;
    assignment_status varchar;
    assignment_start timestamptz;
    assignment_end timestamptz;
    plan_organization uuid;
    plan_edition uuid;
    plan_account uuid;
    plan_status varchar;
    plan_version bigint;
    subject_kind varchar;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce Shift commitments cannot be deleted normally'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, position_id, starts_at, ends_at,
           minimum_rest_minutes, status
      INTO demand_organization, demand_edition, demand_position, demand_start,
           demand_end, demand_rest, demand_status
      FROM public.workforce_shiftdemand
     WHERE id = NEW.demand_id
     FOR KEY SHARE;
    SELECT organization_id, edition_id, position_id, account_id, status,
           effective_from, expires_at
      INTO assignment_organization, assignment_edition, assignment_position,
           assignment_account, assignment_status, assignment_start, assignment_end
      FROM public.workforce_positionassignment
     WHERE id = NEW.position_assignment_id
     FOR KEY SHARE;
    SELECT organization_id, edition_id, account_id, status, command_version
      INTO plan_organization, plan_edition, plan_account, plan_status, plan_version
      FROM public.workforce_personavailabilityplan
     WHERE id = NEW.availability_plan_id
     FOR KEY SHARE;
    SELECT account_kind INTO subject_kind
      FROM public.identity_account WHERE id = NEW.account_id FOR KEY SHARE;
    IF demand_organization IS DISTINCT FROM NEW.organization_id
       OR demand_edition IS DISTINCT FROM NEW.edition_id
       OR assignment_organization IS DISTINCT FROM NEW.organization_id
       OR assignment_edition IS DISTINCT FROM NEW.edition_id
       OR assignment_position IS DISTINCT FROM demand_position
       OR assignment_account IS DISTINCT FROM NEW.account_id
       OR plan_organization IS DISTINCT FROM NEW.organization_id
       OR plan_edition IS DISTINCT FROM NEW.edition_id
       OR plan_account IS DISTINCT FROM NEW.account_id
       OR subject_kind IS DISTINCT FROM 'person'
       OR NEW.starts_at IS DISTINCT FROM demand_start
       OR NEW.ends_at IS DISTINCT FROM demand_end
       OR NEW.rest_ends_at IS DISTINCT FROM
          demand_end + make_interval(mins => demand_rest)
    THEN
        RAISE EXCEPTION 'workforce Shift commitment scope or snapshot mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.command_version <> 1 OR NEW.status <> 'claimed'
           OR demand_status <> 'open'
        THEN
            RAISE EXCEPTION 'workforce Shift commitment must begin as an open claim'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.demand_id IS DISTINCT FROM OLD.demand_id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.position_assignment_id IS DISTINCT FROM OLD.position_assignment_id
           OR NEW.account_id IS DISTINCT FROM OLD.account_id
           OR NEW.starts_at IS DISTINCT FROM OLD.starts_at
           OR NEW.ends_at IS DISTINCT FROM OLD.ends_at
           OR NEW.rest_ends_at IS DISTINCT FROM OLD.rest_ends_at
           OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'workforce Shift commitment identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.command_version <> OLD.command_version + 1
           OR NOT (
               (OLD.status = 'claimed' AND NEW.status IN ('confirmed', 'removed'))
               OR (OLD.status = 'confirmed'
                   AND NEW.status IN ('confirmed', 'removed', 'completed'))
           )
        THEN
            RAISE EXCEPTION 'workforce Shift commitment transition is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.status IN ('claimed', 'confirmed') AND (
        demand_status <> 'open'
        OR assignment_status <> 'active'
        OR assignment_start > demand_start
        OR (assignment_end IS NOT NULL AND assignment_end < demand_end)
        OR plan_status <> 'submitted'
        OR plan_version IS DISTINCT FROM NEW.availability_version
        OR NOT EXISTS (
            SELECT 1 FROM public.workforce_personavailabilitywindow
             WHERE plan_id = NEW.availability_plan_id
               AND created_by_version = NEW.availability_version
               AND starts_at <= demand_start
               AND ends_at >= demand_end
        )
    )
    THEN
        RAISE EXCEPTION 'workforce Shift commitment is not currently suitable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.claimed_at IS NULL
       OR (NEW.confirmed_at IS NULL) <> (NEW.confirmed_by_id IS NULL)
       OR (NEW.confirmed_at IS NULL) <> (btrim(NEW.confirmation_reason) = '')
       OR (NEW.removed_at IS NULL) <> (NEW.removed_by_id IS NULL)
       OR (NEW.removed_at IS NULL) <> (btrim(NEW.removal_kind) = '')
       OR (NEW.removed_at IS NULL) <> (btrim(NEW.removal_reason) = '')
       OR (NEW.completed_at IS NULL) <> (NEW.completed_by_id IS NULL)
       OR (NEW.completed_at IS NULL) <> (btrim(NEW.completion_reason) = '')
       OR (NEW.status = 'claimed' AND (
            NEW.confirmed_at IS NOT NULL OR NEW.removed_at IS NOT NULL
            OR NEW.completed_at IS NOT NULL))
       OR (NEW.status = 'confirmed' AND (
            NEW.confirmed_at IS NULL OR NEW.removed_at IS NOT NULL
            OR NEW.completed_at IS NOT NULL))
       OR (NEW.status = 'removed' AND (
            NEW.removed_at IS NULL OR NEW.completed_at IS NOT NULL))
       OR (NEW.status = 'completed' AND (
            NEW.confirmed_at IS NULL OR NEW.removed_at IS NOT NULL
            OR NEW.completed_at IS NULL))
    THEN
        RAISE EXCEPTION 'workforce Shift commitment state evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$shift_commitment_guard$;

CREATE TRIGGER workforce_shift_commitment_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.workforce_shiftcommitment
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_shift_commitment();
REVOKE ALL ON FUNCTION public.maru_guard_workforce_shift_commitment() FROM PUBLIC;

CREATE TRIGGER workforce_idn011_shift_subject_guard
BEFORE INSERT OR UPDATE ON public.workforce_shiftcommitment
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_idn011_subject();

CREATE FUNCTION public.maru_guard_workforce_shift_commitment_receipt()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_commitment_receipt_guard$
DECLARE
    commitment_demand uuid;
    commitment_organization uuid;
    commitment_edition uuid;
    commitment_version bigint;
    commitment_status varchar;
    actor_active boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'workforce Shift commitment receipts are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT demand_id, organization_id, edition_id, command_version, status
      INTO commitment_demand, commitment_organization, commitment_edition,
           commitment_version, commitment_status
      FROM public.workforce_shiftcommitment
     WHERE id = NEW.commitment_id
     FOR KEY SHARE;
    SELECT is_active INTO actor_active
      FROM public.identity_account WHERE id = NEW.actor_id FOR KEY SHARE;
    IF commitment_demand IS DISTINCT FROM NEW.demand_id
       OR commitment_organization IS DISTINCT FROM NEW.organization_id
       OR commitment_edition IS DISTINCT FROM NEW.edition_id
       OR commitment_version IS DISTINCT FROM NEW.resulting_version
       OR commitment_status IS DISTINCT FROM NEW.resulting_status
       OR actor_active IS DISTINCT FROM TRUE
       OR btrim(NEW.reason) = ''
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR NOT (
           (NEW.action = 'claimed' AND NEW.resulting_status = 'claimed')
           OR (NEW.action = 'confirmed' AND NEW.resulting_status = 'confirmed')
           OR (NEW.action IN ('withdrawn', 'removed', 'cancelled')
               AND NEW.resulting_status = 'removed')
           OR (NEW.action = 'completed' AND NEW.resulting_status = 'completed')
       )
    THEN
        RAISE EXCEPTION 'workforce Shift commitment receipt evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$shift_commitment_receipt_guard$;

CREATE TRIGGER workforce_shift_commitment_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_shiftcommitmentcommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_shift_commitment_receipt();
REVOKE ALL ON FUNCTION public.maru_guard_workforce_shift_commitment_receipt()
FROM PUBLIC;

CREATE FUNCTION public.maru_deferred_validate_workforce_shift_demand()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_demand_evidence_guard$
DECLARE
    checked_id uuid;
    current_version bigint;
    current_status varchar;
    matching_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'workforce_shiftdemand' THEN
        checked_id := NEW.id;
    ELSE
        checked_id := NEW.demand_id;
    END IF;
    SELECT command_version, status INTO current_version, current_status
      FROM public.workforce_shiftdemand WHERE id = checked_id;
    SELECT COUNT(*) INTO matching_count
      FROM public.workforce_shiftdemandcommandreceipt
     WHERE demand_id = checked_id
       AND resulting_version = current_version
       AND resulting_status = current_status;
    IF matching_count <> 1 THEN
        RAISE EXCEPTION 'workforce Shift demand lacks exact command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$shift_demand_evidence_guard$;

CREATE CONSTRAINT TRIGGER workforce_shift_demand_evidence_guard
AFTER INSERT OR UPDATE ON public.workforce_shiftdemand
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_workforce_shift_demand();
CREATE CONSTRAINT TRIGGER workforce_shift_demand_receipt_evidence_guard
AFTER INSERT ON public.workforce_shiftdemandcommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_workforce_shift_demand();
REVOKE ALL ON FUNCTION public.maru_deferred_validate_workforce_shift_demand()
FROM PUBLIC;

CREATE FUNCTION public.maru_deferred_validate_workforce_shift_commitment()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_commitment_evidence_guard$
DECLARE
    checked_id uuid;
    current_version bigint;
    current_status varchar;
    matching_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'workforce_shiftcommitment' THEN
        checked_id := NEW.id;
    ELSE
        checked_id := NEW.commitment_id;
    END IF;
    SELECT command_version, status INTO current_version, current_status
      FROM public.workforce_shiftcommitment WHERE id = checked_id;
    SELECT COUNT(*) INTO matching_count
      FROM public.workforce_shiftcommitmentcommandreceipt
     WHERE commitment_id = checked_id
       AND resulting_version = current_version
       AND resulting_status = current_status;
    IF matching_count <> 1 THEN
        RAISE EXCEPTION 'workforce Shift commitment lacks exact command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$shift_commitment_evidence_guard$;

CREATE CONSTRAINT TRIGGER workforce_shift_commitment_evidence_guard
AFTER INSERT OR UPDATE ON public.workforce_shiftcommitment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_workforce_shift_commitment();
CREATE CONSTRAINT TRIGGER workforce_shift_commitment_receipt_evidence_guard
AFTER INSERT ON public.workforce_shiftcommitmentcommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_workforce_shift_commitment();
REVOKE ALL ON FUNCTION public.maru_deferred_validate_workforce_shift_commitment()
FROM PUBLIC;

CREATE FUNCTION public.maru_refuse_workforce_shift_truncate()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY DEFINER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $shift_truncate_guard$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN RETURN NULL; END IF;
    RAISE EXCEPTION 'workforce Shift tables cannot be truncated'
        USING ERRCODE = '23514';
END;
$shift_truncate_guard$;

CREATE TRIGGER workforce_shift_demand_truncate_guard
BEFORE TRUNCATE ON public.workforce_shiftdemand
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_workforce_shift_truncate();
CREATE TRIGGER workforce_shift_demand_receipt_truncate_guard
BEFORE TRUNCATE ON public.workforce_shiftdemandcommandreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_workforce_shift_truncate();
CREATE TRIGGER workforce_shift_commitment_truncate_guard
BEFORE TRUNCATE ON public.workforce_shiftcommitment
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_workforce_shift_truncate();
CREATE TRIGGER workforce_shift_commitment_receipt_truncate_guard
BEFORE TRUNCATE ON public.workforce_shiftcommitmentcommandreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_refuse_workforce_shift_truncate();
REVOKE ALL ON FUNCTION public.maru_refuse_workforce_shift_truncate() FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.maru_deferred_validate_workforce_idn011_account()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $workforce_subject_guard$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (SELECT 1 FROM public.workforce_volunteerapplication
                    WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM public.workforce_onboardingdocumentrequest
                      WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM public.workforce_positionassignment
                      WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM public.workforce_personavailabilityplan
                      WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM public.workforce_shiftcommitment
                      WHERE account_id = NEW.id)
       )
    THEN
        RAISE EXCEPTION 'platform account cannot retain workforce subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$workforce_subject_guard$;
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS aa0_workforce_shift_position_dependency_guard
    ON public.workforce_position;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_shift_position_dependency();
DROP TRIGGER IF EXISTS workforce_shift_commitment_receipt_truncate_guard
    ON public.workforce_shiftcommitmentcommandreceipt;
DROP TRIGGER IF EXISTS workforce_shift_commitment_truncate_guard
    ON public.workforce_shiftcommitment;
DROP TRIGGER IF EXISTS workforce_shift_demand_receipt_truncate_guard
    ON public.workforce_shiftdemandcommandreceipt;
DROP TRIGGER IF EXISTS workforce_shift_demand_truncate_guard
    ON public.workforce_shiftdemand;
DROP FUNCTION IF EXISTS public.maru_refuse_workforce_shift_truncate();
DROP TRIGGER IF EXISTS workforce_shift_commitment_receipt_evidence_guard
    ON public.workforce_shiftcommitmentcommandreceipt;
DROP TRIGGER IF EXISTS workforce_shift_commitment_evidence_guard
    ON public.workforce_shiftcommitment;
DROP FUNCTION IF EXISTS public.maru_deferred_validate_workforce_shift_commitment();
DROP TRIGGER IF EXISTS workforce_shift_demand_receipt_evidence_guard
    ON public.workforce_shiftdemandcommandreceipt;
DROP TRIGGER IF EXISTS workforce_shift_demand_evidence_guard
    ON public.workforce_shiftdemand;
DROP FUNCTION IF EXISTS public.maru_deferred_validate_workforce_shift_demand();
DROP TRIGGER IF EXISTS workforce_shift_commitment_receipt_guard
    ON public.workforce_shiftcommitmentcommandreceipt;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_shift_commitment_receipt();
DROP TRIGGER IF EXISTS workforce_idn011_shift_subject_guard
    ON public.workforce_shiftcommitment;
DROP TRIGGER IF EXISTS workforce_shift_commitment_guard
    ON public.workforce_shiftcommitment;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_shift_commitment();
DROP TRIGGER IF EXISTS workforce_shift_demand_receipt_guard
    ON public.workforce_shiftdemandcommandreceipt;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_shift_demand_receipt();
DROP TRIGGER IF EXISTS workforce_shift_demand_guard ON public.workforce_shiftdemand;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_shift_demand();

CREATE OR REPLACE FUNCTION public.maru_deferred_validate_workforce_idn011_account()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $workforce_subject_guard$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (SELECT 1 FROM public.workforce_volunteerapplication
                    WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM public.workforce_onboardingdocumentrequest
                      WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM public.workforce_positionassignment
                      WHERE account_id = NEW.id)
           OR EXISTS (SELECT 1 FROM public.workforce_personavailabilityplan
                      WHERE account_id = NEW.id)
       )
    THEN
        RAISE EXCEPTION 'platform account cannot retain workforce subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$workforce_subject_guard$;
"""


def refuse_used_shift_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep Shift demand and command evidence fix-forward once created."""
    model_names = (
        "ShiftDemand",
        "ShiftDemandCommandReceipt",
        "ShiftCommitment",
        "ShiftCommitmentCommandReceipt",
    )
    schema_editor.execute(
        "LOCK TABLE public.workforce_shiftdemand, "
        "public.workforce_shiftdemandcommandreceipt, "
        "public.workforce_shiftcommitment, "
        "public.workforce_shiftcommitmentcommandreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if any(apps.get_model("workforce", name).objects.exists() for name in model_names):
        raise RuntimeError(
            "Cannot remove Workforce Shifts after durable demand, commitments, or "
            "command evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Create Shift aggregates and install their database-owned invariants."""

    dependencies: ClassVar[list[tuple[str, str] | object]] = [
        ("authorization", "0018_workforce_shift_capabilities"),
        ("events", "0009_edition_workspace_downgrade_fence"),
        ("organizations", "0013_runtime_executable_function_hardening"),
        ("workforce", "0012_person_owned_availability"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="ShiftCommitment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("claimed", "Claimed"),
                            ("confirmed", "Confirmed"),
                            ("removed", "Removed"),
                            ("completed", "Completed"),
                        ],
                        max_length=16,
                    ),
                ),
                ("starts_at", models.DateTimeField(editable=False)),
                ("ends_at", models.DateTimeField(editable=False)),
                ("rest_ends_at", models.DateTimeField(editable=False)),
                (
                    "availability_version",
                    models.PositiveBigIntegerField(editable=False),
                ),
                ("command_version", models.PositiveBigIntegerField(editable=False)),
                ("claimed_at", models.DateTimeField(editable=False)),
                (
                    "confirmed_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "confirmation_reason",
                    models.CharField(blank=True, editable=False, max_length=240),
                ),
                (
                    "removed_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "removal_kind",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("withdrawn", "Withdrawn by person"),
                            ("organizer", "Removed by organizer"),
                            ("cancelled", "Removed when Shift was cancelled"),
                        ],
                        editable=False,
                        max_length=16,
                    ),
                ),
                (
                    "removal_reason",
                    models.CharField(blank=True, editable=False, max_length=240),
                ),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "completion_reason",
                    models.CharField(blank=True, editable=False, max_length=240),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "availability_plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shift_commitments",
                        to="workforce.personavailabilityplan",
                    ),
                ),
                (
                    "completed_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitments_completed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitments_confirmed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitments",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitments",
                        to="organizations.organization",
                    ),
                ),
                (
                    "position_assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shift_commitments",
                        to="workforce.positionassignment",
                    ),
                ),
                (
                    "removed_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitments_removed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("edition_id", "starts_at", "account_id", "id"),
            },
        ),
        migrations.CreateModel(
            name="ShiftDemand",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(max_length=160)),
                ("location_label", models.CharField(max_length=160)),
                ("briefing", models.CharField(max_length=1000)),
                ("supervision_note", models.CharField(blank=True, max_length=500)),
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                (
                    "required_headcount",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(1024),
                        ]
                    ),
                ),
                (
                    "break_minutes",
                    models.PositiveSmallIntegerField(
                        default=0,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(1440),
                        ],
                    ),
                ),
                (
                    "minimum_rest_minutes",
                    models.PositiveSmallIntegerField(
                        default=0,
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(2880),
                        ],
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("open", "Open for claims"),
                            ("locked", "Coverage locked"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("command_version", models.PositiveBigIntegerField(editable=False)),
                (
                    "published_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "locked_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "locked_headcount",
                    models.PositiveSmallIntegerField(
                        blank=True, editable=False, null=True
                    ),
                ),
                (
                    "lock_reason",
                    models.CharField(blank=True, editable=False, max_length=240),
                ),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "completion_reason",
                    models.CharField(blank=True, editable=False, max_length=240),
                ),
                (
                    "cancelled_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "cancellation_reason",
                    models.CharField(blank=True, editable=False, max_length=240),
                ),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demands_cancelled",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "completed_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demands_completed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demands_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demands",
                        to="events.eventedition",
                    ),
                ),
                (
                    "locked_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demands_locked",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demands",
                        to="organizations.organization",
                    ),
                ),
                (
                    "position",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="shift_demands",
                        to="workforce.position",
                    ),
                ),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demands_published",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("edition_id", "starts_at", "title", "id"),
            },
        ),
        migrations.CreateModel(
            name="ShiftCommitmentCommandReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("claimed", "Shift claimed"),
                            ("confirmed", "Claim confirmed"),
                            ("withdrawn", "Claim withdrawn"),
                            ("removed", "Claim removed"),
                            ("completed", "Commitment completed"),
                            ("cancelled", "Removed by cancellation"),
                        ],
                        max_length=16,
                    ),
                ),
                ("resulting_version", models.PositiveBigIntegerField()),
                (
                    "resulting_status",
                    models.CharField(
                        choices=[
                            ("claimed", "Claimed"),
                            ("confirmed", "Confirmed"),
                            ("removed", "Removed"),
                            ("completed", "Completed"),
                        ],
                        max_length=16,
                    ),
                ),
                ("reason", models.CharField(max_length=240)),
                ("retry_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_structure_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitment_commands_acted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "commitment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="workforce.shiftcommitment",
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitment_receipts",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_commitment_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "demand",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="commitment_command_receipts",
                        to="workforce.shiftdemand",
                    ),
                ),
            ],
            options={
                "ordering": ("commitment_id", "resulting_version", "id"),
            },
        ),
        migrations.AddField(
            model_name="shiftcommitment",
            name="demand",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="commitments",
                to="workforce.shiftdemand",
            ),
        ),
        migrations.CreateModel(
            name="ShiftDemandCommandReceipt",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("created", "Shift created"),
                            ("updated", "Draft updated"),
                            ("opened", "Claims opened"),
                            ("locked", "Coverage locked"),
                            ("reopened", "Coverage reopened"),
                            ("completed", "Shift completed"),
                            ("cancelled", "Shift cancelled"),
                        ],
                        max_length=16,
                    ),
                ),
                ("resulting_version", models.PositiveBigIntegerField()),
                (
                    "resulting_status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("open", "Open for claims"),
                            ("locked", "Coverage locked"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                        ],
                        max_length=16,
                    ),
                ),
                ("reason", models.CharField(max_length=240)),
                ("retry_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_structure_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demand_commands_acted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "demand",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="workforce.shiftdemand",
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demand_receipts",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_shift_demand_receipts",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={
                "ordering": ("demand_id", "resulting_version", "id"),
            },
        ),
        migrations.AddIndex(
            model_name="shiftdemand",
            index=models.Index(
                fields=["organization", "edition", "status", "starts_at"],
                name="wrk_shift_demand_state_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="shiftdemand",
            index=models.Index(
                fields=["position", "starts_at"], name="wrk_shift_demand_pos_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemand",
            constraint=models.CheckConstraint(
                condition=models.Q(("ends_at__gt", models.F("starts_at"))),
                name="workforce_shift_time_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemand",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("required_headcount__gte", 1), ("required_headcount__lte", 1024)
                ),
                name="workforce_shift_headcount_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemand",
            constraint=models.CheckConstraint(
                condition=models.Q(("break_minutes__lte", 1440)),
                name="workforce_shift_break_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemand",
            constraint=models.CheckConstraint(
                condition=models.Q(("minimum_rest_minutes__lte", 2880)),
                name="workforce_shift_rest_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemand",
            constraint=models.CheckConstraint(
                condition=models.Q(("command_version__gt", 0)),
                name="workforce_shift_version_pos",
            ),
        ),
        migrations.AddIndex(
            model_name="shiftcommitmentcommandreceipt",
            index=models.Index(
                fields=["organization", "edition", "action", "created_at"],
                name="wrk_shift_commit_action_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitmentcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("commitment", "resulting_version"),
                name="workforce_shift_commit_receipt_ver",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitmentcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_shift_commit_retry_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitmentcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("resulting_version__gt", 0)),
                name="workforce_shift_commit_receipt_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitmentcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("reason", ""), _negated=True),
                    models.Q(("source_channel", ""), _negated=True),
                ),
                name="workforce_shift_commit_evidence_set",
            ),
        ),
        migrations.AddIndex(
            model_name="shiftcommitment",
            index=models.Index(
                fields=["organization", "edition", "status", "starts_at"],
                name="wrk_shift_commit_state_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="shiftcommitment",
            index=models.Index(
                fields=["account", "status", "starts_at"],
                name="wrk_shift_commit_person_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ("claimed", "confirmed"))),
                fields=("demand", "account"),
                name="workforce_shift_one_active_claim",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitment",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                condition=models.Q(("status__in", ("claimed", "confirmed"))),
                expressions=(
                    ("account", "="),
                    (
                        models.Func(
                            models.F("starts_at"),
                            models.F("rest_ends_at"),
                            models.Value("[)"),
                            function="TSTZRANGE",
                            output_field=django.contrib.postgres.fields.ranges.DateTimeRangeField(),
                        ),
                        "&&",
                    ),
                ),
                name="workforce_shift_no_active_overlap",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("ends_at__gt", models.F("starts_at")),
                    ("rest_ends_at__gte", models.F("ends_at")),
                ),
                name="workforce_shift_commitment_time_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftcommitment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("availability_version__gt", 0), ("command_version__gt", 0)
                ),
                name="workforce_shift_commitment_versions_pos",
            ),
        ),
        migrations.AddIndex(
            model_name="shiftdemandcommandreceipt",
            index=models.Index(
                fields=["organization", "edition", "action", "created_at"],
                name="wrk_shift_demand_action_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemandcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("demand", "resulting_version"),
                name="workforce_shift_demand_receipt_ver",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemandcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_shift_demand_retry_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemandcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("resulting_version__gt", 0)),
                name="workforce_shift_demand_receipt_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="shiftdemandcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("reason", ""), _negated=True),
                    models.Q(("source_channel", ""), _negated=True),
                ),
                name="workforce_shift_demand_evidence_set",
            ),
        ),
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_shift_downgrade,
        ),
    ]
