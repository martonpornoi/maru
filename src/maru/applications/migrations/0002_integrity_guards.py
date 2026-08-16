"""Install database enforcement for typed application provenance."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_definition()
RETURNS trigger AS $$
DECLARE edition_organization uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'application definitions require governed retention';
    END IF;
    SELECT organization_id INTO edition_organization
      FROM public.events_eventedition WHERE id = NEW.edition_id FOR KEY SHARE;
    IF edition_organization IS NULL OR edition_organization <> NEW.organization_id THEN
        RAISE EXCEPTION 'application definition scope mismatch';
    END IF;
    IF TG_OP = 'INSERT' AND NEW.status <> 'draft' THEN
        RAISE EXCEPTION 'application definitions must begin as drafts';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.id <> OLD.id OR NEW.organization_id <> OLD.organization_id
           OR NEW.edition_id <> OLD.edition_id OR NEW.code <> OLD.code
           OR NEW.version <> OLD.version OR NEW.target_adapter_kind <> OLD.target_adapter_kind
           OR NEW.created_by_id <> OLD.created_by_id OR NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'application definition identity is immutable';
        END IF;
        IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'application definition version must advance exactly once';
        END IF;
        IF OLD.status = 'active' AND NEW.status = 'retired' THEN
            IF ROW(NEW.name, NEW.description, NEW.purpose, NEW.classification,
                   NEW.eligibility_kind, NEW.max_submissions_per_person,
                   NEW.opens_at, NEW.closes_at, NEW.applicant_edit_until,
                   NEW.minimum_age, NEW.audience_policy_code,
                   NEW.retention_policy_code, NEW.age_policy_code,
                   NEW.activated_at, NEW.activated_by_id)
               IS DISTINCT FROM
               ROW(OLD.name, OLD.description, OLD.purpose, OLD.classification,
                   OLD.eligibility_kind, OLD.max_submissions_per_person,
                   OLD.opens_at, OLD.closes_at, OLD.applicant_edit_until,
                   OLD.minimum_age, OLD.audience_policy_code,
                   OLD.retention_policy_code, OLD.age_policy_code,
                   OLD.activated_at, OLD.activated_by_id) THEN
                RAISE EXCEPTION 'retirement cannot rewrite active definition meaning';
            END IF;
        ELSIF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'active and retired application definitions are immutable';
        END IF;
    END IF;
    IF NEW.status IN ('active', 'retired') AND (
        (NEW.classification IN ('C3', 'C4') OR NEW.target_adapter_kind IN ('adult_fursuit_striptease', 'damage_report'))
        AND (
            NEW.audience_policy_code IN ('', 'default', 'generic', 'standard')
            OR NEW.retention_policy_code IN ('', 'default', 'generic', 'standard')
        )
    ) THEN
        RAISE EXCEPTION 'sensitive application policies must be explicit';
    END IF;
    IF NEW.status IN ('active', 'retired') AND NEW.target_adapter_kind = 'adult_fursuit_striptease'
       AND (
           NEW.minimum_age < 18
           OR NEW.age_policy_code IN ('', 'default', 'generic', 'standard')
       ) THEN
        RAISE EXCEPTION 'adult application age policy must be explicit';
    END IF;
    IF NEW.status = 'active' AND (
        NOT EXISTS (
            SELECT 1 FROM public.applications_applicationownerdepartment
            WHERE definition_id = NEW.id
        )
        OR NOT EXISTS (
            SELECT 1 FROM public.applications_applicationsection
            WHERE definition_id = NEW.id
        )
        OR NOT EXISTS (
            SELECT 1 FROM public.applications_applicationquestion
            WHERE definition_id = NEW.id
        )
        OR NOT (
            EXISTS (
                SELECT 1 FROM public.applications_applicationreviewerrole
                WHERE definition_id = NEW.id
            )
            OR EXISTS (
                SELECT 1 FROM public.applications_applicationreviewerperson
                WHERE definition_id = NEW.id
            )
        )
    ) THEN
        RAISE EXCEPTION 'active application definition graph is incomplete';
    END IF;
    IF NEW.status = 'active' AND EXISTS (
        SELECT 1
        FROM public.applications_applicationquestion AS question
        WHERE question.definition_id = NEW.id
          AND (
              (question.required AND NOT question.applicant_visible)
              OR (
                  question.classification IN ('C3', 'C4')
                  AND question.retention_policy_code = ''
                  AND NEW.retention_policy_code = ''
              )
              OR CASE question.classification
                    WHEN 'C1' THEN 1 WHEN 'C2' THEN 2
                    WHEN 'C3' THEN 3 WHEN 'C4' THEN 4 ELSE 99
                 END > CASE NEW.classification
                    WHEN 'C1' THEN 1 WHEN 'C2' THEN 2
                    WHEN 'C3' THEN 3 WHEN 'C4' THEN 4 ELSE 0
                 END
          )
    ) THEN
        RAISE EXCEPTION 'active application question policy is invalid';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_applications_guard_definition_child()
RETURNS trigger AS $$
DECLARE definition_id_value uuid;
DECLARE definition_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN definition_id_value := OLD.definition_id;
    ELSE definition_id_value := NEW.definition_id; END IF;
    SELECT status INTO definition_status
      FROM public.applications_applicationdefinition
      WHERE id = definition_id_value FOR UPDATE;
    IF definition_status IS NULL THEN RAISE EXCEPTION 'application definition unavailable'; END IF;
    IF definition_status <> 'draft' THEN
        RAISE EXCEPTION 'active application definition children are immutable';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_applications_guard_submission()
RETURNS trigger AS $$
DECLARE definition_row record;
DECLARE account_kind_value text;
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'application submissions require governed retention'; END IF;
    SELECT organization_id, edition_id, status INTO definition_row
      FROM public.applications_applicationdefinition
      WHERE id = NEW.definition_id FOR UPDATE;
    SELECT account_kind INTO account_kind_value
      FROM public.identity_account WHERE id = NEW.account_id FOR KEY SHARE;
    IF definition_row IS NULL OR definition_row.organization_id <> NEW.organization_id
       OR definition_row.edition_id <> NEW.edition_id THEN
        RAISE EXCEPTION 'application submission scope mismatch';
    END IF;
    IF account_kind_value IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION 'platform administrators cannot become application subjects';
    END IF;
    IF TG_OP = 'INSERT' AND definition_row.status <> 'active' THEN
        RAISE EXCEPTION 'application submissions require an active definition';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(NEW.id, NEW.organization_id, NEW.edition_id, NEW.definition_id,
               NEW.account_id, NEW.ordinal, NEW.created_at)
           IS DISTINCT FROM
           ROW(OLD.id, OLD.organization_id, OLD.edition_id, OLD.definition_id,
               OLD.account_id, OLD.ordinal, OLD.created_at) THEN
            RAISE EXCEPTION 'application submission identity is immutable';
        END IF;
        IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'application submission version must advance exactly once';
        END IF;
        IF OLD.state IN ('accepted', 'rejected', 'withdrawn') THEN
            RAISE EXCEPTION 'terminal application submissions are immutable';
        END IF;
        IF NEW.state <> OLD.state AND NOT (
            (OLD.state = 'draft' AND NEW.state IN ('submitted', 'withdrawn'))
            OR (OLD.state = 'submitted' AND NEW.state IN ('under_review', 'changes_requested', 'accepted', 'rejected', 'withdrawn'))
            OR (OLD.state = 'under_review' AND NEW.state IN ('changes_requested', 'accepted', 'rejected', 'withdrawn'))
            OR (OLD.state = 'changes_requested' AND NEW.state IN ('submitted', 'accepted', 'rejected', 'withdrawn'))
        ) THEN
            RAISE EXCEPTION 'invalid application submission transition';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_applications_guard_answer()
RETURNS trigger AS $$
DECLARE submission_definition uuid;
DECLARE submission_account uuid;
DECLARE question_row record;
DECLARE prior_sequence integer;
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'application answer revisions are append-only'; END IF;
    SELECT definition_id, account_id INTO submission_definition, submission_account
      FROM public.applications_applicationsubmission WHERE id = NEW.submission_id FOR UPDATE;
    SELECT definition_id, key, field_type, classification,
           applicant_visible, applicant_writable, source_binding
      INTO question_row
      FROM public.applications_applicationquestion WHERE id = NEW.question_id FOR KEY SHARE;
    IF submission_definition IS NULL OR question_row.definition_id IS NULL
       OR submission_definition <> question_row.definition_id THEN
        RAISE EXCEPTION 'application answer question scope mismatch';
    END IF;
    IF ROW(NEW.question_key, NEW.question_type, NEW.classification)
       IS DISTINCT FROM
       ROW(question_row.key, question_row.field_type, question_row.classification) THEN
        RAISE EXCEPTION 'application answer snapshots must match the question';
    END IF;
    IF NEW.source IN ('applicant', 'system_source')
       AND NEW.actor_id <> submission_account THEN
        RAISE EXCEPTION 'applicant answer actor must own the submission';
    END IF;
    IF NEW.source = 'applicant'
       AND NOT (question_row.applicant_visible AND question_row.applicant_writable) THEN
        RAISE EXCEPTION 'applicant cannot write this application question';
    END IF;
    IF NEW.source = 'system_source' AND question_row.source_binding = '' THEN
        RAISE EXCEPTION 'system answer requires an authoritative source binding';
    END IF;
    SELECT COALESCE(MAX(sequence), 0) INTO prior_sequence
      FROM public.applications_applicationanswerrevision
      WHERE submission_id = NEW.submission_id AND question_id = NEW.question_id;
    IF NEW.sequence <> prior_sequence + 1 THEN
        RAISE EXCEPTION 'application answer revision history must be contiguous';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_applications_guard_review()
RETURNS trigger AS $$
DECLARE submission_state text;
DECLARE submission_definition uuid;
DECLARE prior_sequence integer;
DECLARE prior_state text;
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'application review decisions are append-only'; END IF;
    SELECT state, definition_id INTO submission_state, submission_definition
      FROM public.applications_applicationsubmission WHERE id = NEW.submission_id FOR UPDATE;
    IF submission_state IS NULL OR submission_state <> NEW.to_state THEN
        RAISE EXCEPTION 'review decision must describe the locked submission transition';
    END IF;
    IF (
        NEW.decision = 'start_review'
        AND (NEW.from_state <> 'submitted' OR NEW.to_state <> 'under_review')
    ) OR (
        NEW.decision = 'request_changes'
        AND (
            NEW.from_state NOT IN ('submitted', 'under_review')
            OR NEW.to_state <> 'changes_requested'
        )
    ) OR (
        NEW.decision IN ('accept', 'reject')
        AND (
            NEW.from_state NOT IN ('submitted', 'under_review', 'changes_requested')
            OR NEW.to_state <> CASE NEW.decision
                WHEN 'accept' THEN 'accepted' ELSE 'rejected'
            END
        )
    ) OR NEW.decision NOT IN ('start_review', 'request_changes', 'accept', 'reject') THEN
        RAISE EXCEPTION 'review decision transition is invalid';
    END IF;
    SELECT sequence, to_state INTO prior_sequence, prior_state
      FROM public.applications_applicationreviewdecision
      WHERE submission_id = NEW.submission_id
      ORDER BY sequence DESC, id DESC LIMIT 1;
    IF prior_sequence IS NULL THEN
        IF NEW.sequence <> 1 OR NEW.from_state <> 'submitted' THEN
            RAISE EXCEPTION 'first review decision must start from submitted';
        END IF;
    ELSIF NEW.sequence <> prior_sequence + 1 OR NOT (
        NEW.from_state = prior_state
        OR (prior_state = 'changes_requested' AND NEW.from_state = 'submitted')
    ) THEN
        RAISE EXCEPTION 'review decision history must be contiguous';
    END IF;
    IF NEW.reviewer_basis = 'named_person' AND NOT EXISTS (
        SELECT 1 FROM public.applications_applicationreviewerperson
        WHERE definition_id = submission_definition AND account_id = NEW.reviewer_id
    ) THEN
        RAISE EXCEPTION 'named reviewer is outside the configured queue';
    ELSIF NEW.reviewer_basis = 'immutable_role' AND NOT EXISTS (
        SELECT 1 FROM public.applications_applicationreviewerrole
        WHERE definition_id = submission_definition
          AND role_bundle_id = NEW.reviewer_role_bundle_id
    ) THEN
        RAISE EXCEPTION 'reviewer role version is outside the configured queue';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_applications_guard_target()
RETURNS trigger AS $$
DECLARE submission_row record;
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'typed application targets are append-only'; END IF;
    SELECT submission.state, definition.target_adapter_kind
      INTO submission_row
      FROM public.applications_applicationsubmission AS submission
      JOIN public.applications_applicationdefinition AS definition
        ON definition.id = submission.definition_id
      WHERE submission.id = NEW.submission_id FOR UPDATE OF submission;
    IF submission_row IS NULL OR submission_row.state <> 'accepted'
       OR submission_row.target_adapter_kind <> NEW.adapter_kind THEN
        RAISE EXCEPTION 'typed target must match an accepted application adapter';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE OR REPLACE FUNCTION public.maru_applications_append_only()
RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN RAISE EXCEPTION 'application evidence is append-only'; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER applications_definition_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationdefinition
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_definition();
CREATE TRIGGER applications_owner_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationownerdepartment FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_definition_child();
CREATE TRIGGER applications_reviewer_role_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationreviewerrole FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_definition_child();
CREATE TRIGGER applications_reviewer_person_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationreviewerperson FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_definition_child();
CREATE TRIGGER applications_section_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationsection FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_definition_child();
CREATE TRIGGER applications_question_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationquestion FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_definition_child();
CREATE TRIGGER applications_submission_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationsubmission FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_submission();
CREATE TRIGGER applications_answer_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationanswerrevision FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_answer();
CREATE TRIGGER applications_review_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationreviewdecision FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_review();
CREATE TRIGGER applications_target_guard BEFORE INSERT OR UPDATE OR DELETE ON public.applications_applicationtargetrecord FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_target();
CREATE TRIGGER applications_receipt_guard BEFORE UPDATE OR DELETE ON public.applications_applicationcommandreceipt FOR EACH ROW EXECUTE FUNCTION public.maru_applications_append_only();
CREATE TRIGGER applications_file_guard BEFORE UPDATE OR DELETE ON public.applications_applicationfilereceipt FOR EACH ROW EXECUTE FUNCTION public.maru_applications_append_only();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS applications_file_guard ON public.applications_applicationfilereceipt;
DROP TRIGGER IF EXISTS applications_receipt_guard ON public.applications_applicationcommandreceipt;
DROP TRIGGER IF EXISTS applications_target_guard ON public.applications_applicationtargetrecord;
DROP TRIGGER IF EXISTS applications_review_guard ON public.applications_applicationreviewdecision;
DROP TRIGGER IF EXISTS applications_answer_guard ON public.applications_applicationanswerrevision;
DROP TRIGGER IF EXISTS applications_submission_guard ON public.applications_applicationsubmission;
DROP TRIGGER IF EXISTS applications_question_guard ON public.applications_applicationquestion;
DROP TRIGGER IF EXISTS applications_section_guard ON public.applications_applicationsection;
DROP TRIGGER IF EXISTS applications_reviewer_person_guard ON public.applications_applicationreviewerperson;
DROP TRIGGER IF EXISTS applications_reviewer_role_guard ON public.applications_applicationreviewerrole;
DROP TRIGGER IF EXISTS applications_owner_guard ON public.applications_applicationownerdepartment;
DROP TRIGGER IF EXISTS applications_definition_guard ON public.applications_applicationdefinition;
DROP FUNCTION IF EXISTS public.maru_applications_append_only();
DROP FUNCTION IF EXISTS public.maru_applications_guard_target();
DROP FUNCTION IF EXISTS public.maru_applications_guard_review();
DROP FUNCTION IF EXISTS public.maru_applications_guard_answer();
DROP FUNCTION IF EXISTS public.maru_applications_guard_submission();
DROP FUNCTION IF EXISTS public.maru_applications_guard_definition_child();
DROP FUNCTION IF EXISTS public.maru_applications_guard_definition();
"""


class Migration(migrations.Migration):
    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0001_initial"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
