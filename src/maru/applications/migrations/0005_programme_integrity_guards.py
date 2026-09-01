"""Install authoritative integrity for Applications-owned Programme calls."""

# ruff: noqa: E501, FLY002 -- SQL contract text stays reviewable and exact.

from __future__ import annotations

import importlib
import re
from typing import ClassVar

from django.db import migrations

_legacy = importlib.import_module("maru.applications.migrations.0002_integrity_guards")
_legacy_acl = importlib.import_module(
    "maru.applications.migrations.0003_integrity_function_execute_boundary"
)


def _replace_function(source: str, name: str, replacement: str) -> str:
    pattern = re.compile(
        rf"CREATE OR REPLACE FUNCTION public\.{re.escape(name)}\(\).*?"
        r"\$\$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;",
        re.DOTALL,
    )
    updated, count = pattern.subn(replacement.strip(), source, count=1)
    if count != 1:
        raise RuntimeError(f"Legacy Applications function unavailable: {name}")
    return updated


LEGACY_TRIGGER_DROP_SQL = r"""
DROP TRIGGER IF EXISTS applications_file_guard
    ON public.applications_applicationfilereceipt;
DROP TRIGGER IF EXISTS applications_receipt_guard
    ON public.applications_applicationcommandreceipt;
DROP TRIGGER IF EXISTS applications_target_guard
    ON public.applications_applicationtargetrecord;
DROP TRIGGER IF EXISTS applications_review_guard
    ON public.applications_applicationreviewdecision;
DROP TRIGGER IF EXISTS applications_answer_guard
    ON public.applications_applicationanswerrevision;
DROP TRIGGER IF EXISTS applications_submission_guard
    ON public.applications_applicationsubmission;
DROP TRIGGER IF EXISTS applications_question_guard
    ON public.applications_applicationquestion;
DROP TRIGGER IF EXISTS applications_section_guard
    ON public.applications_applicationsection;
DROP TRIGGER IF EXISTS applications_reviewer_person_guard
    ON public.applications_applicationreviewerperson;
DROP TRIGGER IF EXISTS applications_reviewer_role_guard
    ON public.applications_applicationreviewerrole;
DROP TRIGGER IF EXISTS applications_owner_guard
    ON public.applications_applicationownerdepartment;
DROP TRIGGER IF EXISTS applications_definition_guard
    ON public.applications_applicationdefinition;
"""

DEFINITION_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_definition()
RETURNS trigger AS $applications_definition_guard$
DECLARE
    edition_organization uuid;
    programme_call_count integer;
    programme_owner_count integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'application definitions require governed retention'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.target_adapter_kind = 'programme_item'
       AND pg_catalog.current_setting(
           'maru.applications_programme_writer', true
       ) IS DISTINCT FROM 'on'
    THEN
        RAISE EXCEPTION 'Programme definitions require the registered writer latch'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id INTO edition_organization
      FROM public.events_eventedition
     WHERE id = NEW.edition_id
     FOR KEY SHARE;
    IF edition_organization IS NULL
       OR edition_organization <> NEW.organization_id
    THEN
        RAISE EXCEPTION 'application definition scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.target_adapter_kind NOT IN (
        'merch_submission', 'dj_set', 'fursuit_dance_competition',
        'maid_cafe', 'adult_fursuit_striptease', 'volunteer', 'feedback',
        'idea', 'damage_report', 'helper', 'programme_item'
    ) THEN
        RAISE EXCEPTION 'application target adapter kind is unsupported'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' AND (
        NEW.status <> 'draft' OR NEW.aggregate_version <> 1
    ) THEN
        RAISE EXCEPTION 'application definitions must begin as version-one drafts'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW.id <> OLD.id
           OR NEW.organization_id <> OLD.organization_id
           OR NEW.edition_id <> OLD.edition_id
           OR NEW.code <> OLD.code
           OR NEW.version <> OLD.version
           OR NEW.target_adapter_kind <> OLD.target_adapter_kind
           OR NEW.created_by_id <> OLD.created_by_id
           OR NEW.created_at <> OLD.created_at
        THEN
            RAISE EXCEPTION 'application definition identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'application definition version must advance exactly once'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.status = 'active' AND NEW.status = 'retired' THEN
            IF ROW(
                NEW.name, NEW.description, NEW.purpose, NEW.classification,
                NEW.eligibility_kind, NEW.max_submissions_per_person,
                NEW.opens_at, NEW.closes_at, NEW.applicant_edit_until,
                NEW.minimum_age, NEW.audience_policy_code,
                NEW.retention_policy_code, NEW.age_policy_code,
                NEW.activated_at, NEW.activated_by_id
            ) IS DISTINCT FROM ROW(
                OLD.name, OLD.description, OLD.purpose, OLD.classification,
                OLD.eligibility_kind, OLD.max_submissions_per_person,
                OLD.opens_at, OLD.closes_at, OLD.applicant_edit_until,
                OLD.minimum_age, OLD.audience_policy_code,
                OLD.retention_policy_code, OLD.age_policy_code,
                OLD.activated_at, OLD.activated_by_id
            ) THEN
                RAISE EXCEPTION 'retirement cannot rewrite active definition meaning'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'active and retired application definitions are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.status IN ('active', 'retired') AND (
        (
            NEW.classification IN ('C3', 'C4')
            OR NEW.target_adapter_kind IN (
                'adult_fursuit_striptease', 'damage_report'
            )
        ) AND (
            NEW.audience_policy_code IN ('', 'default', 'generic', 'standard')
            OR NEW.retention_policy_code IN ('', 'default', 'generic', 'standard')
        )
    ) THEN
        RAISE EXCEPTION 'sensitive application policies must be explicit'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status IN ('active', 'retired')
       AND NEW.target_adapter_kind = 'adult_fursuit_striptease'
       AND (
           NEW.minimum_age < 18
           OR NEW.age_policy_code IN ('', 'default', 'generic', 'standard')
       )
    THEN
        RAISE EXCEPTION 'adult application age policy must be explicit'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'active' AND (
        NOT EXISTS (
            SELECT 1
              FROM public.applications_applicationownerdepartment
             WHERE definition_id = NEW.id
        )
        OR NOT EXISTS (
            SELECT 1
              FROM public.applications_applicationsection
             WHERE definition_id = NEW.id
        )
        OR NOT EXISTS (
            SELECT 1
              FROM public.applications_applicationquestion
             WHERE definition_id = NEW.id
        )
        OR (
            NEW.target_adapter_kind <> 'programme_item'
            AND NOT (
                EXISTS (
                    SELECT 1
                      FROM public.applications_applicationreviewerrole
                     WHERE definition_id = NEW.id
                )
                OR EXISTS (
                    SELECT 1
                      FROM public.applications_applicationreviewerperson
                     WHERE definition_id = NEW.id
                )
            )
        )
    ) THEN
        RAISE EXCEPTION 'active application definition graph is incomplete'
            USING ERRCODE = '23514';
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
               OR (
                   NEW.target_adapter_kind = 'programme_item'
                   AND NOT (
                       question.applicant_visible
                       AND question.applicant_writable
                       AND question.source_binding = ''
                       AND NOT question.staff_visible
                       AND NOT question.staff_writable
                       AND NOT question.reviewer_visible
                       AND NOT question.public_after_approval
                       AND NOT question.api_projection
                   )
               )
           )
    ) THEN
        RAISE EXCEPTION 'active application question policy is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status = 'active' AND NEW.target_adapter_kind = 'programme_item' THEN
        IF NEW.classification NOT IN ('C1', 'C2', 'C3')
           OR NEW.eligibility_kind <> 'authenticated_person'
           OR NEW.max_submissions_per_person NOT BETWEEN 1 AND 100
           OR NEW.minimum_age <> 0
           OR NOT (
               NEW.opens_at <= NEW.applicant_edit_until
               AND NEW.applicant_edit_until <= NEW.closes_at
               AND NEW.opens_at < NEW.closes_at
           )
           OR EXISTS (
                SELECT 1
                  FROM public.applications_applicationreviewerrole
                 WHERE definition_id = NEW.id
           )
           OR EXISTS (
                SELECT 1
                  FROM public.applications_applicationreviewerperson
                 WHERE definition_id = NEW.id
           )
        THEN
            RAISE EXCEPTION 'active Programme definition shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        SELECT COUNT(*) INTO programme_call_count
          FROM public.applications_programmecall AS call
         WHERE call.definition_id = NEW.id;
        SELECT COUNT(*) INTO programme_owner_count
          FROM public.applications_programmecall AS call
          JOIN public.applications_applicationownerdepartment AS owner
            ON owner.definition_id = call.definition_id
           AND owner.department_id = call.owner_department_id
          JOIN public.workforce_department AS department
            ON department.id = call.owner_department_id
           AND department.organization_id = call.organization_id
           AND department.edition_id = call.edition_id
         WHERE call.definition_id = NEW.id;
        IF programme_call_count <> 1 OR programme_owner_count <> 1
           OR (
                SELECT COUNT(*)
                  FROM public.applications_applicationownerdepartment
                 WHERE definition_id = NEW.id
           ) <> 1
           OR EXISTS (
                SELECT 1
                  FROM public.applications_programmecall AS call
                  JOIN public.workforce_department AS department
                    ON department.id = call.owner_department_id
                 WHERE call.definition_id = NEW.id
                   AND department.retired_at IS NOT NULL
           )
        THEN
            RAISE EXCEPTION 'active Programme call ownership is incomplete'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.applications_programmecalltrack AS track
             WHERE track.call_id = (
                 SELECT id FROM public.applications_programmecall
                  WHERE definition_id = NEW.id
             )
        ) OR NOT EXISTS (
            SELECT 1 FROM public.applications_programmecallformat AS format
             WHERE format.call_id = (
                 SELECT id FROM public.applications_programmecall
                  WHERE definition_id = NEW.id
             )
        ) THEN
            RAISE EXCEPTION 'active Programme call requires tracks and formats'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM public.applications_programmecallcontributorfield AS field
             WHERE field.call_id = (
                 SELECT id FROM public.applications_programmecall
                  WHERE definition_id = NEW.id
             )
               AND field.field_code = 'public_name'
               AND field.lead_requirement = 'required'
        ) THEN
            RAISE EXCEPTION 'active Programme call requires the lead public name'
                USING ERRCODE = '23514';
        END IF;
        IF (SELECT COUNT(*)
              FROM public.applications_applicationsection
             WHERE definition_id = NEW.id) NOT BETWEEN 1 AND 100
           OR (SELECT COUNT(*)
                 FROM public.applications_applicationquestion
                WHERE definition_id = NEW.id) NOT BETWEEN 1 AND 500
           OR EXISTS (
                SELECT 1
                  FROM public.applications_applicationsection AS section
                 WHERE section.definition_id = NEW.id
                   AND (
                       section.key !~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'
                       OR pg_catalog.btrim(section.title) = ''
                       OR pg_catalog.char_length(section.help_text) > 2000
                       OR NOT EXISTS (
                            SELECT 1
                              FROM public.applications_applicationquestion
                             WHERE section_id = section.id
                       )
                       OR (SELECT MIN(question.position)
                             FROM public.applications_applicationquestion AS question
                            WHERE question.section_id = section.id) <> 1
                       OR (SELECT MAX(question.position)
                             FROM public.applications_applicationquestion AS question
                            WHERE question.section_id = section.id) <>
                          (SELECT COUNT(*)
                             FROM public.applications_applicationquestion AS question
                            WHERE question.section_id = section.id)
                   )
           )
           OR (SELECT MIN(section.position)
                 FROM public.applications_applicationsection AS section
                WHERE section.definition_id = NEW.id) <> 1
           OR (SELECT MAX(section.position)
                 FROM public.applications_applicationsection AS section
                WHERE section.definition_id = NEW.id) <>
              (SELECT COUNT(*)
                 FROM public.applications_applicationsection AS section
                WHERE section.definition_id = NEW.id)
           OR EXISTS (
                SELECT 1
                  FROM public.applications_applicationquestion AS question
                 WHERE question.definition_id = NEW.id
                   AND (
                       question.key !~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'
                       OR question.field_type NOT IN (
                           'short_text', 'long_text', 'integer', 'decimal',
                           'boolean', 'single_choice', 'multiple_choice',
                           'date', 'time', 'instant', 'email', 'phone', 'url',
                           'address', 'person_reference', 'domain_reference',
                           'safe_file'
                       )
                       OR question.classification NOT IN ('C1', 'C2', 'C3')
                       OR pg_catalog.btrim(question.label) = ''
                       OR pg_catalog.btrim(question.purpose) = ''
                       OR pg_catalog.char_length(question.help_text) > 2000
                       OR NOT (
                           question.applicant_visible
                           AND question.applicant_writable
                           AND question.source_binding = ''
                           AND NOT question.staff_visible
                           AND NOT question.staff_writable
                           AND NOT question.reviewer_visible
                           AND NOT question.public_after_approval
                           AND NOT question.api_projection
                       )
                       OR pg_catalog.jsonb_typeof(question.options) <> 'array'
                       OR CASE
                            WHEN question.field_type IN (
                                'single_choice', 'multiple_choice'
                            ) THEN pg_catalog.jsonb_array_length(
                                CASE
                                  WHEN pg_catalog.jsonb_typeof(question.options) =
                                       'array'
                                  THEN question.options
                                  ELSE '[]'::jsonb
                                END
                            ) NOT BETWEEN 2 AND 100
                            ELSE pg_catalog.jsonb_array_length(
                                CASE
                                  WHEN pg_catalog.jsonb_typeof(question.options) =
                                       'array'
                                  THEN question.options
                                  ELSE '[]'::jsonb
                                END
                            ) <> 0
                          END
                       OR EXISTS (
                            SELECT 1
                              FROM pg_catalog.jsonb_array_elements(
                                  CASE
                                    WHEN pg_catalog.jsonb_typeof(question.options) =
                                         'array'
                                    THEN question.options
                                    ELSE '[]'::jsonb
                                  END
                              ) AS option
                             WHERE pg_catalog.jsonb_typeof(option) <> 'object'
                                OR (
                                    SELECT COUNT(*)
                                      FROM pg_catalog.jsonb_object_keys(
                                          CASE
                                            WHEN pg_catalog.jsonb_typeof(option) =
                                                 'object'
                                            THEN option
                                            ELSE '{}'::jsonb
                                          END
                                      )
                                ) <> 2
                                OR NOT option ?& ARRAY['code', 'label']
                                OR pg_catalog.jsonb_typeof(option->'code') <>
                                   'string'
                                OR option->>'code' !~
                                   '^[a-z0-9]+(?:-[a-z0-9]+)*$'
                                OR pg_catalog.char_length(option->>'code') > 80
                                OR pg_catalog.jsonb_typeof(option->'label') <>
                                   'string'
                                OR pg_catalog.btrim(option->>'label') = ''
                                OR pg_catalog.char_length(option->>'label') > 160
                       )
                       OR (SELECT COUNT(*)
                             FROM pg_catalog.jsonb_array_elements(
                                 CASE
                                   WHEN pg_catalog.jsonb_typeof(question.options) =
                                        'array'
                                   THEN question.options
                                   ELSE '[]'::jsonb
                                 END
                             ) AS option) <>
                          (SELECT COUNT(DISTINCT option->>'code')
                             FROM pg_catalog.jsonb_array_elements(
                                 CASE
                                   WHEN pg_catalog.jsonb_typeof(question.options) =
                                        'array'
                                   THEN question.options
                                   ELSE '[]'::jsonb
                                 END
                             ) AS option)
                       OR CASE
                            WHEN question.field_type = 'multiple_choice' THEN
                                question.maximum_choices IS NULL
                                OR question.maximum_choices < 1
                                OR question.maximum_choices >
                                   pg_catalog.jsonb_array_length(
                                       CASE
                                         WHEN pg_catalog.jsonb_typeof(
                                             question.options
                                         ) = 'array'
                                         THEN question.options
                                         ELSE '[]'::jsonb
                                       END
                                   )
                            ELSE question.maximum_choices IS NOT NULL
                          END
                       OR CASE
                            WHEN question.field_type IN (
                                'short_text', 'long_text', 'email', 'phone', 'url'
                            ) THEN
                                COALESCE(question.minimum_length, 0) > 65536
                                OR COALESCE(question.maximum_length, 0) > 65536
                            ELSE question.minimum_length IS NOT NULL
                                 OR question.maximum_length IS NOT NULL
                          END
                       OR CASE
                            WHEN question.field_type IN ('integer', 'decimal')
                            THEN FALSE
                            ELSE question.minimum_value IS NOT NULL
                                 OR question.maximum_value IS NOT NULL
                          END
                       OR CASE
                            WHEN question.field_type IN (
                                'person_reference', 'domain_reference'
                            ) THEN question.reference_kind = ''
                                 OR question.reference_kind !~
                                    '^[a-z][a-z0-9_.:-]{0,79}$'
                            ELSE question.reference_kind <> ''
                          END
                   )
           )
        THEN
            RAISE EXCEPTION 'active Programme question graph shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM public.applications_applicationquestion AS question
              JOIN public.applications_applicationsection AS question_section
                ON question_section.id = question.section_id
              LEFT JOIN public.applications_applicationquestion AS source
                ON source.definition_id = question.definition_id
               AND source.key = question.condition->>'question_key'
              LEFT JOIN public.applications_applicationsection AS source_section
                ON source_section.id = source.section_id
             WHERE question.definition_id = NEW.id
               AND question.condition <> '{}'::jsonb
               AND CASE
                    WHEN pg_catalog.jsonb_typeof(question.condition) <> 'object'
                      OR (
                          SELECT COUNT(*)
                            FROM pg_catalog.jsonb_object_keys(
                                CASE
                                  WHEN pg_catalog.jsonb_typeof(
                                      question.condition
                                  ) = 'object'
                                  THEN question.condition
                                  ELSE '{}'::jsonb
                                END
                            )
                      ) <> 3
                      OR NOT question.condition ?&
                         ARRAY['question_key', 'operator', 'value']
                    THEN TRUE
                    WHEN question.condition->>'operator' NOT IN (
                        'equals', 'not_equals', 'contains'
                    ) THEN TRUE
                    WHEN source.id IS NULL THEN TRUE
                    WHEN NOT (
                        source_section.position < question_section.position
                        OR (
                            source_section.position = question_section.position
                            AND source.position < question.position
                        )
                    ) THEN TRUE
                    WHEN question.condition->>'operator' = 'contains' THEN NOT (
                        source.field_type = 'multiple_choice'
                        AND pg_catalog.jsonb_typeof(
                            question.condition->'value'
                        ) = 'string'
                        AND EXISTS (
                            SELECT 1
                              FROM pg_catalog.jsonb_array_elements(
                                  CASE
                                    WHEN pg_catalog.jsonb_typeof(source.options) =
                                         'array'
                                    THEN source.options
                                    ELSE '[]'::jsonb
                                  END
                              ) AS option
                             WHERE option->>'code' =
                                   question.condition->>'value'
                        )
                    )
                    WHEN source.field_type = 'boolean' THEN
                        pg_catalog.jsonb_typeof(question.condition->'value') <>
                        'boolean'
                    WHEN source.field_type = 'integer' THEN NOT (
                        pg_catalog.jsonb_typeof(question.condition->'value') =
                        'number'
                        AND question.condition->>'value' ~
                            '^-?(0|[1-9][0-9]*)$'
                        AND (question.condition->>'value')::numeric BETWEEN
                            -2147483648 AND 2147483647
                    )
                    WHEN source.field_type = 'single_choice' THEN NOT (
                        pg_catalog.jsonb_typeof(
                            question.condition->'value'
                        ) = 'string'
                        AND EXISTS (
                            SELECT 1
                              FROM pg_catalog.jsonb_array_elements(
                                  CASE
                                    WHEN pg_catalog.jsonb_typeof(source.options) =
                                         'array'
                                    THEN source.options
                                    ELSE '[]'::jsonb
                                  END
                              ) AS option
                             WHERE option->>'code' =
                                   question.condition->>'value'
                        )
                    )
                    WHEN source.field_type IN (
                        'short_text', 'long_text', 'email', 'phone', 'url'
                    ) THEN pg_catalog.jsonb_typeof(
                        question.condition->'value'
                    ) <> 'string'
                    ELSE TRUE
                   END
        ) THEN
            RAISE EXCEPTION 'active Programme condition graph is invalid'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$applications_definition_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

DEFINITION_CHILD_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_definition_child()
RETURNS trigger AS $applications_definition_child_guard$
DECLARE
    definition_id_value uuid;
    definition_status text;
    target_kind text;
BEGIN
    definition_id_value := CASE
        WHEN TG_OP = 'DELETE' THEN OLD.definition_id
        ELSE NEW.definition_id
    END;
    SELECT status, target_adapter_kind
      INTO definition_status, target_kind
      FROM public.applications_applicationdefinition
     WHERE id = definition_id_value
     FOR UPDATE;
    IF definition_status IS NULL THEN
        RAISE EXCEPTION 'application definition unavailable'
            USING ERRCODE = '23514';
    END IF;
    IF target_kind = 'programme_item'
       AND pg_catalog.current_setting(
           'maru.applications_programme_writer', true
       ) IS DISTINCT FROM 'on'
    THEN
        RAISE EXCEPTION 'Programme definition children require the writer latch'
            USING ERRCODE = '23514';
    END IF;
    IF definition_status <> 'draft' THEN
        RAISE EXCEPTION 'active application definition children are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$applications_definition_child_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

SUBMISSION_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_submission()
RETURNS trigger AS $applications_submission_guard$
DECLARE
    definition_row record;
    account_row record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'application submissions require governed retention'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, status, target_adapter_kind
      INTO definition_row
      FROM public.applications_applicationdefinition
     WHERE id = NEW.definition_id
     FOR UPDATE;
    SELECT account_kind, is_active, email_verified_at
      INTO account_row
      FROM public.identity_account
     WHERE id = NEW.account_id
     FOR KEY SHARE;
    IF definition_row IS NULL
       OR definition_row.organization_id <> NEW.organization_id
       OR definition_row.edition_id <> NEW.edition_id
    THEN
        RAISE EXCEPTION 'application submission scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF account_row.account_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION 'platform administrators cannot become application subjects'
            USING ERRCODE = '23514';
    END IF;
    IF definition_row.target_adapter_kind = 'programme_item' AND (
        pg_catalog.current_setting(
            'maru.applications_programme_writer', true
        ) IS DISTINCT FROM 'on'
        OR account_row.is_active IS DISTINCT FROM TRUE
        OR account_row.email_verified_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Programme proposals require an active verified person and writer latch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' AND (
        definition_row.status <> 'active'
        OR NEW.aggregate_version <> 1
        OR NEW.state <> 'draft'
    ) THEN
        RAISE EXCEPTION 'application submissions require an active definition and version-one draft'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF ROW(
            NEW.id, NEW.organization_id, NEW.edition_id, NEW.definition_id,
            NEW.account_id, NEW.ordinal, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.organization_id, OLD.edition_id, OLD.definition_id,
            OLD.account_id, OLD.ordinal, OLD.created_at
        ) THEN
            RAISE EXCEPTION 'application submission identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'application submission version must advance exactly once'
                USING ERRCODE = '23514';
        END IF;
        IF definition_row.target_adapter_kind = 'programme_item' THEN
            IF OLD.state = 'withdrawn'
               OR NOT (
                   (OLD.state = 'draft' AND NEW.state IN ('draft', 'submitted', 'withdrawn'))
                   OR (OLD.state = 'submitted' AND NEW.state IN (
                       'submitted', 'draft', 'withdrawn'
                   ))
               )
            THEN
                RAISE EXCEPTION 'invalid Programme proposal submission transition'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            IF OLD.state IN ('accepted', 'rejected', 'withdrawn') THEN
                RAISE EXCEPTION 'terminal application submissions are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.state <> OLD.state AND NOT (
                (OLD.state = 'draft' AND NEW.state IN ('submitted', 'withdrawn'))
                OR (
                    OLD.state = 'submitted'
                    AND NEW.state IN (
                        'under_review', 'changes_requested', 'accepted',
                        'rejected', 'withdrawn'
                    )
                )
                OR (
                    OLD.state = 'under_review'
                    AND NEW.state IN (
                        'changes_requested', 'accepted', 'rejected', 'withdrawn'
                    )
                )
                OR (
                    OLD.state = 'changes_requested'
                    AND NEW.state IN ('submitted', 'accepted', 'rejected', 'withdrawn')
                )
            ) THEN
                RAISE EXCEPTION 'invalid application submission transition'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$applications_submission_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

ANSWER_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_answer()
RETURNS trigger AS $applications_answer_guard$
DECLARE
    submission_row record;
    question_row record;
    actor_row record;
    prior_sequence integer;
    actor_is_collaborator boolean := FALSE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'application answer revisions are append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT submission.definition_id, submission.account_id,
           submission.organization_id, submission.edition_id,
           submission.aggregate_version, definition.target_adapter_kind
      INTO submission_row
      FROM public.applications_applicationsubmission AS submission
      JOIN public.applications_applicationdefinition AS definition
        ON definition.id = submission.definition_id
     WHERE submission.id = NEW.submission_id
     FOR UPDATE OF submission;
    SELECT definition_id, key, field_type, classification,
           applicant_visible, applicant_writable, source_binding,
           staff_visible, staff_writable, reviewer_visible,
           public_after_approval, api_projection
      INTO question_row
      FROM public.applications_applicationquestion
     WHERE id = NEW.question_id
     FOR KEY SHARE;
    IF submission_row.definition_id IS NULL
       OR question_row.definition_id IS NULL
       OR submission_row.definition_id <> question_row.definition_id
    THEN
        RAISE EXCEPTION 'application answer question scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF ROW(NEW.question_key, NEW.question_type, NEW.classification)
       IS DISTINCT FROM ROW(
           question_row.key, question_row.field_type, question_row.classification
       )
    THEN
        RAISE EXCEPTION 'application answer snapshots must match the question'
            USING ERRCODE = '23514';
    END IF;
    IF submission_row.target_adapter_kind = 'programme_item' THEN
        IF pg_catalog.current_setting(
            'maru.applications_programme_writer', true
        ) IS DISTINCT FROM 'on' THEN
            RAISE EXCEPTION 'Programme answers require the writer latch'
                USING ERRCODE = '23514';
        END IF;
        SELECT account_kind, is_active, email_verified_at
          INTO actor_row
          FROM public.identity_account
         WHERE id = NEW.actor_id
         FOR KEY SHARE;
        SELECT EXISTS (
            SELECT 1
              FROM public.applications_programmeproposal AS proposal
              JOIN public.applications_programmeproposalcollaborator AS collaborator
                ON collaborator.proposal_id = proposal.id
             WHERE proposal.submission_id = NEW.submission_id
               AND collaborator.account_id = NEW.actor_id
               AND collaborator.state = 'accepted'
        ) INTO actor_is_collaborator;
        IF actor_row.account_kind IS DISTINCT FROM 'person'
           OR actor_row.is_active IS DISTINCT FROM TRUE
           OR actor_row.email_verified_at IS NULL
           OR NOT (
               NEW.actor_id = submission_row.account_id OR actor_is_collaborator
           )
           OR NEW.source <> 'applicant'
           OR NOT (
               question_row.applicant_visible AND question_row.applicant_writable
           )
           OR question_row.source_binding <> ''
           OR question_row.staff_visible
           OR question_row.staff_writable
           OR question_row.reviewer_visible
           OR question_row.public_after_approval
           OR question_row.api_projection
           OR NEW.source_version IS DISTINCT FROM submission_row.aggregate_version
           OR NEW.resulting_version IS DISTINCT FROM NEW.source_version + 1
        THEN
            RAISE EXCEPTION 'Programme answer writer or version evidence mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM public.applications_programmeproposal AS proposal
             WHERE proposal.submission_id = NEW.submission_id
               AND proposal.organization_id = submission_row.organization_id
               AND proposal.edition_id = submission_row.edition_id
               AND proposal.state = 'draft'
        ) THEN
            RAISE EXCEPTION 'Programme answers are writable only in draft proposals'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.source IN ('applicant', 'system_source')
           AND NEW.actor_id <> submission_row.account_id
        THEN
            RAISE EXCEPTION 'applicant answer actor must own the submission'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.source = 'applicant'
           AND NOT (
               question_row.applicant_visible AND question_row.applicant_writable
           )
        THEN
            RAISE EXCEPTION 'applicant cannot write this application question'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.source = 'system_source' AND question_row.source_binding = '' THEN
            RAISE EXCEPTION 'system answer requires an authoritative source binding'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.source_version IS NOT NULL OR NEW.resulting_version IS NOT NULL THEN
            RAISE EXCEPTION 'legacy application answers cannot claim Programme versions'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT COALESCE(MAX(sequence), 0)
      INTO prior_sequence
      FROM public.applications_applicationanswerrevision
     WHERE submission_id = NEW.submission_id
       AND question_id = NEW.question_id;
    IF NEW.sequence <> prior_sequence + 1 THEN
        RAISE EXCEPTION 'application answer revision history must be contiguous'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_answer_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

REVIEW_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_review()
RETURNS trigger AS $applications_review_guard$
DECLARE
    submission_state text;
    submission_definition uuid;
    target_kind text;
    prior_sequence integer;
    prior_state text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'application review decisions are append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT submission.state, submission.definition_id,
           definition.target_adapter_kind
      INTO submission_state, submission_definition, target_kind
      FROM public.applications_applicationsubmission AS submission
      JOIN public.applications_applicationdefinition AS definition
        ON definition.id = submission.definition_id
     WHERE submission.id = NEW.submission_id
     FOR UPDATE OF submission;
    IF target_kind = 'programme_item' THEN
        RAISE EXCEPTION 'Programme proposals cannot enter generic review'
            USING ERRCODE = '23514';
    END IF;
    IF submission_state IS NULL OR submission_state <> NEW.to_state THEN
        RAISE EXCEPTION 'review decision must describe the locked submission transition'
            USING ERRCODE = '23514';
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
    ) OR NEW.decision NOT IN (
        'start_review', 'request_changes', 'accept', 'reject'
    ) THEN
        RAISE EXCEPTION 'review decision transition is invalid'
            USING ERRCODE = '23514';
    END IF;
    SELECT sequence, to_state INTO prior_sequence, prior_state
      FROM public.applications_applicationreviewdecision
     WHERE submission_id = NEW.submission_id
     ORDER BY sequence DESC, id DESC
     LIMIT 1;
    IF prior_sequence IS NULL THEN
        IF NEW.sequence <> 1 OR NEW.from_state <> 'submitted' THEN
            RAISE EXCEPTION 'first review decision must start from submitted'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.sequence <> prior_sequence + 1 OR NOT (
        NEW.from_state = prior_state
        OR (prior_state = 'changes_requested' AND NEW.from_state = 'submitted')
    ) THEN
        RAISE EXCEPTION 'review decision history must be contiguous'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.reviewer_basis = 'named_person' AND NOT EXISTS (
        SELECT 1 FROM public.applications_applicationreviewerperson
         WHERE definition_id = submission_definition
           AND account_id = NEW.reviewer_id
    ) THEN
        RAISE EXCEPTION 'named reviewer is outside the configured queue'
            USING ERRCODE = '23514';
    ELSIF NEW.reviewer_basis = 'immutable_role' AND NOT EXISTS (
        SELECT 1 FROM public.applications_applicationreviewerrole
         WHERE definition_id = submission_definition
           AND role_bundle_id = NEW.reviewer_role_bundle_id
    ) THEN
        RAISE EXCEPTION 'reviewer role version is outside the configured queue'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_review_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

TARGET_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_target()
RETURNS trigger AS $applications_target_guard$
DECLARE
    submission_row record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'typed application targets are append-only'
            USING ERRCODE = '23514';
    END IF;
    SELECT submission.state, definition.target_adapter_kind
      INTO submission_row
      FROM public.applications_applicationsubmission AS submission
      JOIN public.applications_applicationdefinition AS definition
        ON definition.id = submission.definition_id
     WHERE submission.id = NEW.submission_id
     FOR UPDATE OF submission;
    IF submission_row.target_adapter_kind = 'programme_item' THEN
        RAISE EXCEPTION 'Programme proposal acceptance targets are a later adapter'
            USING ERRCODE = '23514';
    END IF;
    IF submission_row IS NULL OR submission_row.state <> 'accepted'
       OR submission_row.target_adapter_kind <> NEW.adapter_kind
    THEN
        RAISE EXCEPTION 'typed target must match an accepted application adapter'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_target_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

GENERIC_RECEIPT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_receipt()
RETURNS trigger AS $applications_receipt_guard$
DECLARE
    retry_namespace text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'application command receipts are append-only'
            USING ERRCODE = '23514';
    END IF;
    retry_namespace := 'maru:applications:retry:'
        || pg_catalog.lower(NEW.edition_id::text) || ':'
        || pg_catalog.lower(NEW.actor_id::text) || ':'
        || pg_catalog.lower(NEW.retry_key::text);
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(retry_namespace, 0)
    );
    IF EXISTS (
        SELECT 1 FROM public.applications_programmecommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) THEN
        RAISE EXCEPTION 'Applications retry key is already retained by Programme'
            USING ERRCODE = '23505';
    END IF;
    RETURN NEW;
END;
$applications_receipt_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

PROGRAMME_CURRENT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_current()
RETURNS trigger AS $applications_programme_current_guard$
DECLARE
    scope_row record;
    definition_status text;
    subject_row record;
BEGIN
    IF pg_catalog.current_setting(
        'maru.applications_programme_writer', true
    ) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme current records require the writer latch'
            USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'applications_programmecall' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Programme call roots require governed retention'
                USING ERRCODE = '23514';
        END IF;
        SELECT definition.organization_id, definition.edition_id,
               definition.target_adapter_kind, definition.status,
               department.organization_id AS department_organization_id,
               department.edition_id AS department_edition_id,
               department.retired_at
          INTO scope_row
          FROM public.applications_applicationdefinition AS definition
          JOIN public.workforce_department AS department
            ON department.id = (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.owner_department_id
                ELSE NEW.owner_department_id
            END)
         WHERE definition.id = (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.definition_id
                ELSE NEW.definition_id
            END)
         FOR UPDATE OF definition;
        IF scope_row IS NULL
           OR scope_row.target_adapter_kind <> 'programme_item'
           OR scope_row.organization_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.organization_id
                ELSE NEW.organization_id
              END)
           OR scope_row.edition_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.edition_id
                ELSE NEW.edition_id
              END)
           OR scope_row.department_organization_id <> scope_row.organization_id
           OR scope_row.department_edition_id <> scope_row.edition_id
           OR scope_row.retired_at IS NOT NULL
        THEN
            RAISE EXCEPTION 'Programme call scope or owner mismatch'
                USING ERRCODE = '23514';
        END IF;
        definition_status := scope_row.status;
        IF TG_OP = 'UPDATE' AND ROW(
            NEW.id, NEW.organization_id, NEW.edition_id, NEW.definition_id,
            NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.organization_id, OLD.edition_id, OLD.definition_id,
            OLD.created_at
        ) THEN
            RAISE EXCEPTION 'Programme call identity is immutable'
                USING ERRCODE = '23514';
        END IF;
    ELSIF TG_TABLE_NAME IN (
        'applications_programmecalltrack',
        'applications_programmecallformat',
        'applications_programmecallcontributorfield'
    ) THEN
        SELECT call.organization_id, call.edition_id,
               definition.status, definition.target_adapter_kind
          INTO scope_row
          FROM public.applications_programmecall AS call
          JOIN public.applications_applicationdefinition AS definition
            ON definition.id = call.definition_id
         WHERE call.id = (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.call_id ELSE NEW.call_id
            END)
         FOR UPDATE OF definition;
        IF scope_row IS NULL
           OR scope_row.target_adapter_kind <> 'programme_item'
           OR scope_row.organization_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.organization_id
                ELSE NEW.organization_id
              END)
           OR scope_row.edition_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.edition_id ELSE NEW.edition_id
              END)
        THEN
            RAISE EXCEPTION 'Programme call configuration scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        definition_status := scope_row.status;
        IF TG_OP = 'UPDATE' AND ROW(
            NEW.id, NEW.organization_id, NEW.edition_id, NEW.call_id,
            NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.organization_id, OLD.edition_id, OLD.call_id,
            OLD.created_at
        ) THEN
            RAISE EXCEPTION 'Programme call configuration identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT'
           AND TG_TABLE_NAME = 'applications_programmecalltrack'
           AND (
                SELECT COUNT(*)
                  FROM public.applications_programmecalltrack
                 WHERE call_id = NEW.call_id
           ) >= 64
        THEN
            RAISE EXCEPTION 'Programme calls support at most 64 tracks'
                USING ERRCODE = '23514';
        ELSIF TG_OP = 'INSERT'
              AND TG_TABLE_NAME = 'applications_programmecallformat'
              AND (
                   SELECT COUNT(*)
                     FROM public.applications_programmecallformat
                    WHERE call_id = NEW.call_id
              ) >= 32
        THEN
            RAISE EXCEPTION 'Programme calls support at most 32 formats'
                USING ERRCODE = '23514';
        ELSIF TG_OP = 'INSERT'
              AND TG_TABLE_NAME = 'applications_programmecallcontributorfield'
              AND (
                   SELECT COUNT(*)
                     FROM public.applications_programmecallcontributorfield
                    WHERE call_id = NEW.call_id
              ) >= 4
        THEN
            RAISE EXCEPTION 'Programme calls support at most 4 contributor fields'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP <> 'DELETE'
           AND TG_TABLE_NAME = 'applications_programmecallformat'
        THEN
            IF (
                NEW.min_duration_minutes < 1
                OR NEW.max_duration_minutes > 1440
                OR NEW.default_duration_minutes < NEW.min_duration_minutes
                OR NEW.default_duration_minutes > NEW.max_duration_minutes
            ) THEN
                RAISE EXCEPTION 'Programme format durations must remain within 1..1440 minutes'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'applications_programmeproposal' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Programme proposal roots require governed retention'
                USING ERRCODE = '23514';
        END IF;
        SELECT submission.organization_id, submission.edition_id,
               submission.definition_id, submission.account_id,
               definition.target_adapter_kind, call.id AS call_id,
               call.organization_id AS call_organization_id,
               call.edition_id AS call_edition_id,
               call.definition_id AS call_definition_id
          INTO scope_row
          FROM public.applications_applicationsubmission AS submission
          JOIN public.applications_applicationdefinition AS definition
            ON definition.id = submission.definition_id
          JOIN public.applications_programmecall AS call
            ON call.id = (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.call_id ELSE NEW.call_id
            END)
         WHERE submission.id = (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.submission_id ELSE NEW.submission_id
            END)
         FOR UPDATE OF submission;
        IF scope_row IS NULL
           OR scope_row.target_adapter_kind <> 'programme_item'
           OR scope_row.definition_id <> scope_row.call_definition_id
           OR scope_row.organization_id <> scope_row.call_organization_id
           OR scope_row.edition_id <> scope_row.call_edition_id
           OR scope_row.organization_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.organization_id
                ELSE NEW.organization_id
              END)
           OR scope_row.edition_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.edition_id ELSE NEW.edition_id
              END)
        THEN
            RAISE EXCEPTION 'Programme proposal scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' AND NEW.state <> 'draft' THEN
            RAISE EXCEPTION 'Programme proposals must begin as drafts'
                USING ERRCODE = '23514';
        ELSIF TG_OP = 'UPDATE' THEN
            IF ROW(
                NEW.id, NEW.organization_id, NEW.edition_id,
                NEW.submission_id, NEW.call_id, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.organization_id, OLD.edition_id,
                OLD.submission_id, OLD.call_id, OLD.created_at
            ) THEN
                RAISE EXCEPTION 'Programme proposal identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT (
                (OLD.state = 'draft' AND NEW.state IN (
                    'draft', 'sealed', 'withdrawn'
                ))
                OR (OLD.state = 'sealed' AND NEW.state IN (
                    'sealed', 'draft', 'submitted', 'withdrawn'
                ))
                OR (OLD.state = 'submitted' AND NEW.state IN (
                    'submitted', 'draft', 'withdrawn'
                ))
                OR (OLD.state = 'withdrawn' AND NEW.state = 'withdrawn')
            ) THEN
                RAISE EXCEPTION 'invalid Programme proposal transition'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'applications_programmeproposalcollaborator' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Programme collaborator projections require governed retention'
                USING ERRCODE = '23514';
        END IF;
        SELECT proposal.organization_id, proposal.edition_id,
               submission.account_id AS lead_id,
               call.max_collaborators, definition.applicant_edit_until
          INTO scope_row
          FROM public.applications_programmeproposal AS proposal
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
          JOIN public.applications_programmecall AS call
            ON call.id = proposal.call_id
          JOIN public.applications_applicationdefinition AS definition
            ON definition.id = call.definition_id
         WHERE proposal.id = (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.proposal_id ELSE NEW.proposal_id
            END)
         FOR UPDATE OF proposal;
        IF scope_row IS NULL
           OR scope_row.organization_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.organization_id
                ELSE NEW.organization_id
              END)
           OR scope_row.edition_id <> (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.edition_id ELSE NEW.edition_id
              END)
           OR scope_row.lead_id = (CASE
                WHEN TG_OP = 'DELETE' THEN OLD.account_id ELSE NEW.account_id
              END)
        THEN
            RAISE EXCEPTION 'Programme collaborator scope or lead exclusion mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP <> 'DELETE' THEN
            SELECT account_kind, is_active, email_verified_at
              INTO subject_row
              FROM public.identity_account
             WHERE id = NEW.account_id
             FOR KEY SHARE;
            IF subject_row.account_kind IS DISTINCT FROM 'person'
               OR subject_row.is_active IS DISTINCT FROM TRUE
               OR subject_row.email_verified_at IS NULL
            THEN
                RAISE EXCEPTION 'Programme collaborators must be active verified people'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        IF TG_OP <> 'DELETE' AND NEW.state = 'invited'
           AND NEW.invite_expires_at <= pg_catalog.transaction_timestamp()
        THEN
            RAISE EXCEPTION 'Programme invitations require a future expiry'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP <> 'DELETE'
           AND NEW.invite_expires_at > scope_row.applicant_edit_until
        THEN
            RAISE EXCEPTION 'Programme invitation expiry exceeds the applicant edit deadline'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP <> 'DELETE'
           AND NEW.state IN ('invited', 'accepted')
           AND (
                SELECT COUNT(*)
                  FROM public.applications_programmeproposalcollaborator
                 WHERE proposal_id = NEW.proposal_id
                   AND id <> NEW.id
                   AND (
                        state = 'accepted'
                        OR (
                            state = 'invited'
                            AND invite_expires_at >
                                pg_catalog.transaction_timestamp()
                        )
                   )
           ) >= scope_row.max_collaborators
        THEN
            RAISE EXCEPTION 'Programme current collaborator limit exceeded'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'UPDATE' AND ROW(
            NEW.id, NEW.organization_id, NEW.edition_id,
            NEW.proposal_id, NEW.account_id, NEW.created_at
        ) IS DISTINCT FROM ROW(
            OLD.id, OLD.organization_id, OLD.edition_id,
            OLD.proposal_id, OLD.account_id, OLD.created_at
        ) THEN
            RAISE EXCEPTION 'Programme collaborator identity is immutable'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unregistered Programme current projection table'
            USING ERRCODE = '23514';
    END IF;

    IF definition_status IS NOT NULL AND definition_status <> 'draft' THEN
        RAISE EXCEPTION 'active Programme call configuration is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$applications_programme_current_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

PROGRAMME_EVIDENCE_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_evidence()
RETURNS trigger AS $applications_programme_evidence_guard$
DECLARE
    proposal_row record;
    prior_row record;
    selected_row record;
    actor_row record;
    actor_id_value uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme proposal evidence is append-only'
            USING ERRCODE = '23514';
    END IF;
    IF pg_catalog.current_setting(
        'maru.applications_programme_writer', true
    ) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme proposal evidence requires the writer latch'
            USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'applications_programmeproposalrevision' THEN
        actor_id_value := NEW.created_by_id;
    ELSIF TG_TABLE_NAME IN (
        'applications_programmeproposalselectionrevision',
        'applications_programmeproposalcollaboratortransition',
        'applications_programmeproposalcontributorprofilerevision',
        'applications_programmeproposalrevisionresponse'
    ) THEN
        actor_id_value := NEW.actor_id;
    END IF;
    IF actor_id_value IS NOT NULL THEN
        SELECT account_kind, is_active, email_verified_at
          INTO actor_row
          FROM public.identity_account
         WHERE id = actor_id_value
         FOR KEY SHARE;
        IF actor_row.account_kind IS DISTINCT FROM 'person'
           OR actor_row.is_active IS DISTINCT FROM TRUE
           OR actor_row.email_verified_at IS NULL
        THEN
            RAISE EXCEPTION 'Programme subject operations require an active verified person'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_TABLE_NAME = 'applications_programmeproposalselectionrevision' THEN
        SELECT proposal.organization_id, proposal.edition_id, proposal.call_id,
               proposal.state, submission.account_id AS lead_id,
               submission.aggregate_version
          INTO proposal_row
          FROM public.applications_programmeproposal AS proposal
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
         WHERE proposal.id = NEW.proposal_id
         FOR UPDATE OF submission;
        SELECT track.call_id AS track_call_id, format.call_id AS format_call_id,
               format.min_duration_minutes, format.max_duration_minutes
          INTO selected_row
          FROM public.applications_programmecalltrack AS track
          JOIN public.applications_programmecallformat AS format
            ON format.id = NEW.format_id
         WHERE track.id = NEW.track_id;
        SELECT sequence INTO prior_row
          FROM public.applications_programmeproposalselectionrevision
         WHERE proposal_id = NEW.proposal_id
         ORDER BY sequence DESC, id DESC LIMIT 1;
        IF proposal_row IS NULL
           OR selected_row IS NULL
           OR proposal_row.organization_id <> NEW.organization_id
           OR proposal_row.edition_id <> NEW.edition_id
           OR selected_row.track_call_id <> proposal_row.call_id
           OR selected_row.format_call_id <> proposal_row.call_id
           OR NEW.requested_duration_minutes NOT BETWEEN
                selected_row.min_duration_minutes
                AND selected_row.max_duration_minutes
           OR proposal_row.state <> 'draft'
           OR NEW.actor_id <> proposal_row.lead_id
           OR NEW.sequence <> COALESCE(prior_row.sequence, 0) + 1
           OR NEW.resulting_version <> NEW.source_version + 1
           OR proposal_row.aggregate_version NOT IN (
                NEW.source_version, NEW.resulting_version
           )
        THEN
            RAISE EXCEPTION 'Programme selection scope, duration, chain, actor, or version mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeproposalcollaboratortransition' THEN
        SELECT proposal.organization_id, proposal.edition_id,
               proposal.state AS proposal_state,
               submission.account_id AS lead_id,
               submission.aggregate_version,
               collaborator.proposal_id AS collaborator_proposal_id,
               collaborator.account_id,
               collaborator.state AS collaborator_state,
               collaborator.generation, collaborator.invite_expires_at,
               definition.applicant_edit_until
          INTO proposal_row
          FROM public.applications_programmeproposal AS proposal
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
          JOIN public.applications_programmeproposalcollaborator AS collaborator
            ON collaborator.id = NEW.collaborator_id
          JOIN public.applications_programmecall AS call
            ON call.id = proposal.call_id
          JOIN public.applications_applicationdefinition AS definition
            ON definition.id = call.definition_id
         WHERE proposal.id = NEW.proposal_id
         FOR UPDATE OF submission, collaborator;
        SELECT sequence, generation, to_state
          INTO prior_row
          FROM public.applications_programmeproposalcollaboratortransition
         WHERE collaborator_id = NEW.collaborator_id
         ORDER BY sequence DESC, id DESC LIMIT 1;
        IF proposal_row IS NULL
           OR proposal_row.organization_id <> NEW.organization_id
           OR proposal_row.edition_id <> NEW.edition_id
           OR proposal_row.collaborator_proposal_id <> NEW.proposal_id
           OR proposal_row.proposal_state <> 'draft'
           OR NEW.sequence <> COALESCE(prior_row.sequence, 0) + 1
           OR NEW.resulting_version <> NEW.source_version + 1
           OR proposal_row.aggregate_version NOT IN (
                NEW.source_version, NEW.resulting_version
           )
           OR NEW.from_state IS DISTINCT FROM prior_row.to_state
        THEN
            RAISE EXCEPTION 'Programme collaborator transition scope, chain, or version mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.to_state = 'invited'
           AND NEW.invite_expires_at > proposal_row.applicant_edit_until
        THEN
            RAISE EXCEPTION 'Programme invitation expiry exceeds the applicant edit deadline'
                USING ERRCODE = '23514';
        END IF;
        IF prior_row.sequence IS NULL THEN
            IF NEW.from_state IS NOT NULL
               OR NEW.to_state <> 'invited'
               OR NEW.generation <> 1
               OR NEW.actor_id <> proposal_row.lead_id
            THEN
                RAISE EXCEPTION 'Programme collaboration must begin with a lead invitation'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.to_state = 'invited' THEN
            IF NEW.actor_id <> proposal_row.lead_id
               OR NEW.generation <> prior_row.generation + 1
               OR NEW.from_state NOT IN ('invited', 'declined', 'left', 'removed')
               OR NEW.reason = ''
            THEN
                RAISE EXCEPTION 'Programme reinvitation requires lead authority, reason, and new generation'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.to_state IN ('accepted', 'declined') THEN
            IF NEW.actor_id <> proposal_row.account_id
               OR NEW.from_state <> 'invited'
               OR NEW.generation <> prior_row.generation
               OR prior_row.to_state <> 'invited'
               OR proposal_row.invite_expires_at <= pg_catalog.transaction_timestamp()
            THEN
                RAISE EXCEPTION 'Programme invitation response is unavailable or expired'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.to_state = 'left' THEN
            IF NEW.actor_id <> proposal_row.account_id
               OR NEW.from_state <> 'accepted'
               OR NEW.generation <> prior_row.generation
            THEN
                RAISE EXCEPTION 'Programme collaborator leave transition is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.to_state = 'removed' THEN
            IF NEW.actor_id <> proposal_row.lead_id
               OR NEW.from_state NOT IN ('invited', 'accepted')
               OR NEW.generation <> prior_row.generation
               OR NEW.reason = ''
            THEN
                RAISE EXCEPTION 'Programme collaborator removal requires lead authority and reason'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Programme collaborator transition is outside the closed graph'
                USING ERRCODE = '23514';
        END IF;
        IF ROW(
            proposal_row.collaborator_state, proposal_row.generation,
            proposal_row.invite_expires_at
        ) IS DISTINCT FROM ROW(
            NEW.to_state, NEW.generation,
            COALESCE(NEW.invite_expires_at, proposal_row.invite_expires_at)
        ) AND NOT (
            NEW.to_state <> 'invited'
            AND proposal_row.collaborator_state = NEW.to_state
            AND proposal_row.generation = NEW.generation
        ) THEN
            RAISE EXCEPTION 'Programme collaborator projection must match its transition'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeproposalcontributorprofilerevision' THEN
        SELECT proposal.organization_id, proposal.edition_id, proposal.state,
               submission.account_id AS lead_id,
               submission.aggregate_version,
               call.id AS call_id,
               call.contributor_consent_policy_code
          INTO proposal_row
          FROM public.applications_programmeproposal AS proposal
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
          JOIN public.applications_programmecall AS call
            ON call.id = proposal.call_id
         WHERE proposal.id = NEW.proposal_id
         FOR UPDATE OF submission;
        SELECT id, sequence INTO prior_row
          FROM public.applications_programmeproposalcontributorprofilerevision
         WHERE proposal_id = NEW.proposal_id AND account_id = NEW.account_id
         ORDER BY sequence DESC, id DESC LIMIT 1;
        IF proposal_row IS NULL
           OR proposal_row.organization_id <> NEW.organization_id
           OR proposal_row.edition_id <> NEW.edition_id
           OR proposal_row.state <> 'draft'
           OR NEW.actor_id <> NEW.account_id
           OR NOT (
                NEW.account_id = proposal_row.lead_id
                OR EXISTS (
                    SELECT 1
                      FROM public.applications_programmeproposalcollaborator
                     WHERE proposal_id = NEW.proposal_id
                       AND account_id = NEW.account_id
                       AND state = 'accepted'
                )
           )
           OR NEW.consent_policy_code <>
                proposal_row.contributor_consent_policy_code
           OR NEW.sequence <> COALESCE(prior_row.sequence, 0) + 1
           OR NEW.predecessor_id IS DISTINCT FROM prior_row.id
           OR NEW.resulting_version <> NEW.source_version + 1
           OR proposal_row.aggregate_version NOT IN (
                NEW.source_version, NEW.resulting_version
           )
           OR NEW.digest !~ '^[0-9a-f]{64}$'
        THEN
            RAISE EXCEPTION 'Programme contributor profile scope, self-authorship, policy, chain, or version mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM (VALUES
                    ('public_name'::text, NEW.public_name::text),
                    ('biography'::text, NEW.biography::text),
                    ('pronouns'::text, NEW.pronouns::text),
                    ('website'::text, NEW.website::text)
              ) AS supplied(field_code, field_value)
             WHERE supplied.field_value <> ''
               AND NOT EXISTS (
                    SELECT 1
                      FROM public.applications_programmecallcontributorfield AS field
                     WHERE field.call_id = proposal_row.call_id
                       AND field.field_code = supplied.field_code
                       AND CASE
                            WHEN NEW.account_id = proposal_row.lead_id
                            THEN field.lead_requirement
                            ELSE field.collaborator_requirement
                           END <> 'hidden'
               )
        ) THEN
            RAISE EXCEPTION 'Programme profile contains a field not collected for this role'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeproposalrevision' THEN
        SELECT proposal.organization_id, proposal.edition_id, proposal.state,
               proposal.call_id, submission.account_id AS lead_id,
               submission.aggregate_version, submission.definition_id,
               definition.version AS definition_version
          INTO proposal_row
          FROM public.applications_programmeproposal AS proposal
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
          JOIN public.applications_applicationdefinition AS definition
            ON definition.id = submission.definition_id
         WHERE proposal.id = NEW.proposal_id
         FOR UPDATE OF submission;
        SELECT id, sequence INTO prior_row
          FROM public.applications_programmeproposalrevision
         WHERE proposal_id = NEW.proposal_id
         ORDER BY sequence DESC, id DESC LIMIT 1;
        SELECT proposal_id, track_id, format_id, requested_duration_minutes,
               resulting_version
          INTO selected_row
          FROM public.applications_programmeproposalselectionrevision
         WHERE id = NEW.selection_revision_id;
        IF proposal_row IS NULL
           OR proposal_row.organization_id <> NEW.organization_id
           OR proposal_row.edition_id <> NEW.edition_id
           OR proposal_row.state <> 'draft'
           OR NEW.created_by_id <> proposal_row.lead_id
           OR NEW.definition_version <> proposal_row.definition_version
           OR NEW.sequence <> COALESCE(prior_row.sequence, 0) + 1
           OR NEW.predecessor_id IS DISTINCT FROM prior_row.id
           OR selected_row.proposal_id <> NEW.proposal_id
           OR selected_row.resulting_version > NEW.source_version
           OR NEW.resulting_version <> NEW.source_version + 1
           OR proposal_row.aggregate_version NOT IN (
                NEW.source_version, NEW.resulting_version
           )
           OR NEW.digest !~ '^[0-9a-f]{64}$'
        THEN
            RAISE EXCEPTION 'Programme proposal revision scope, selection, chain, actor, or version mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.selection_revision_id IS DISTINCT FROM (
            SELECT selection.id
              FROM public.applications_programmeproposalselectionrevision AS selection
             WHERE selection.proposal_id = NEW.proposal_id
               AND selection.resulting_version <= NEW.source_version
             ORDER BY selection.resulting_version DESC, selection.sequence DESC
             LIMIT 1
        ) THEN
            RAISE EXCEPTION 'Programme proposal revision must snapshot the latest selection including requested duration'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeproposalrevisionanswer' THEN
        SELECT revision.organization_id, revision.edition_id,
               revision.proposal_id, revision.source_version,
               submission.id AS submission_id,
               submission.definition_id
          INTO proposal_row
          FROM public.applications_programmeproposalrevision AS revision
          JOIN public.applications_programmeproposal AS proposal
            ON proposal.id = revision.proposal_id
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
         WHERE revision.id = NEW.revision_id
         FOR KEY SHARE OF revision;
        SELECT definition_id, key, field_type, classification
          INTO selected_row
          FROM public.applications_applicationquestion
         WHERE id = NEW.question_id
         FOR KEY SHARE;
        IF proposal_row IS NULL
           OR proposal_row.organization_id <> NEW.organization_id
           OR proposal_row.edition_id <> NEW.edition_id
           OR selected_row.definition_id <> proposal_row.definition_id
           OR ROW(
                NEW.question_key, NEW.question_type, NEW.classification
           ) IS DISTINCT FROM ROW(
                selected_row.key, selected_row.field_type,
                selected_row.classification
           )
        THEN
            RAISE EXCEPTION 'Programme revision answer scope or question snapshot mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.answer_revision_id IS NULL THEN
            IF EXISTS (
                SELECT 1
                  FROM public.applications_applicationanswerrevision AS answer
                 WHERE answer.submission_id = proposal_row.submission_id
                   AND answer.question_id = NEW.question_id
                   AND answer.resulting_version <= proposal_row.source_version
            ) THEN
                RAISE EXCEPTION 'Programme revision explicit absence cannot hide an answer'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.answer_revision_id IS DISTINCT FROM (
            SELECT answer.id
              FROM public.applications_applicationanswerrevision AS answer
             WHERE answer.submission_id = proposal_row.submission_id
               AND answer.question_id = NEW.question_id
               AND answer.resulting_version <= proposal_row.source_version
             ORDER BY answer.resulting_version DESC, answer.sequence DESC
             LIMIT 1
        ) THEN
            RAISE EXCEPTION 'Programme revision must snapshot the exact latest answer'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeproposalrevisioncontributor' THEN
        SELECT revision.organization_id, revision.edition_id,
               revision.proposal_id, revision.source_version,
               submission.account_id AS lead_id
          INTO proposal_row
          FROM public.applications_programmeproposalrevision AS revision
          JOIN public.applications_programmeproposal AS proposal
            ON proposal.id = revision.proposal_id
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
         WHERE revision.id = NEW.revision_id
         FOR KEY SHARE OF revision;
        SELECT proposal_id, account_id, resulting_version
          INTO selected_row
          FROM public.applications_programmeproposalcontributorprofilerevision
         WHERE id = NEW.profile_revision_id;
        IF proposal_row IS NULL
           OR proposal_row.organization_id <> NEW.organization_id
           OR proposal_row.edition_id <> NEW.edition_id
           OR selected_row.proposal_id <> proposal_row.proposal_id
           OR selected_row.account_id <> NEW.account_id
           OR selected_row.resulting_version > proposal_row.source_version
           OR NEW.profile_revision_id IS DISTINCT FROM (
                SELECT profile.id
                  FROM public.applications_programmeproposalcontributorprofilerevision
                       AS profile
                 WHERE profile.proposal_id = proposal_row.proposal_id
                   AND profile.account_id = NEW.account_id
                   AND profile.resulting_version <= proposal_row.source_version
                 ORDER BY profile.resulting_version DESC, profile.sequence DESC
                 LIMIT 1
           )
        THEN
            RAISE EXCEPTION 'Programme revision contributor scope or profile snapshot mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.role = 'lead' THEN
            IF NEW.account_id <> proposal_row.lead_id
               OR NEW.accepted_transition_id IS NOT NULL
            THEN
                RAISE EXCEPTION 'Programme revision lead snapshot is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.role = 'collaborator' THEN
            IF NEW.account_id = proposal_row.lead_id
               OR NEW.accepted_transition_id IS DISTINCT FROM (
                    SELECT transition.id
                      FROM public.applications_programmeproposalcollaborator AS collaborator
                      JOIN public.applications_programmeproposalcollaboratortransition
                           AS transition
                        ON transition.collaborator_id = collaborator.id
                     WHERE collaborator.proposal_id = proposal_row.proposal_id
                       AND collaborator.account_id = NEW.account_id
                       AND transition.resulting_version <= proposal_row.source_version
                     ORDER BY transition.resulting_version DESC,
                              transition.sequence DESC
                     LIMIT 1
               )
               OR NOT EXISTS (
                    SELECT 1
                      FROM public.applications_programmeproposalcollaboratortransition
                     WHERE id = NEW.accepted_transition_id
                       AND to_state = 'accepted'
               )
            THEN
                RAISE EXCEPTION 'Programme revision collaborator snapshot is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Programme revision contributor role is invalid'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeproposalrevisionresponse' THEN
        SELECT revision.organization_id, revision.edition_id,
               revision.proposal_id, contributor.account_id,
               contributor.role, contributor.profile_revision_id,
               proposal.submission_id, submission.aggregate_version
          INTO proposal_row
          FROM public.applications_programmeproposalrevision AS revision
          JOIN public.applications_programmeproposalrevisioncontributor AS contributor
            ON contributor.id = NEW.contributor_id
           AND contributor.revision_id = revision.id
          JOIN public.applications_programmeproposal AS proposal
            ON proposal.id = revision.proposal_id
          JOIN public.applications_applicationsubmission AS submission
            ON submission.id = proposal.submission_id
         WHERE revision.id = NEW.revision_id
         FOR UPDATE OF submission;
        IF proposal_row IS NULL
           OR proposal_row.organization_id <> NEW.organization_id
           OR proposal_row.edition_id <> NEW.edition_id
           OR proposal_row.role <> 'collaborator'
           OR NEW.account_id <> proposal_row.account_id
           OR NEW.actor_id <> NEW.account_id
           OR NEW.profile_revision_id <> proposal_row.profile_revision_id
           OR NEW.resulting_version <> NEW.source_version + 1
           OR proposal_row.aggregate_version NOT IN (
                NEW.source_version, NEW.resulting_version
           )
        THEN
            RAISE EXCEPTION 'Programme revision response scope, self-authorship, profile, or version mismatch'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unregistered Programme evidence table'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_programme_evidence_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

PROGRAMME_RECEIPT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_receipt()
RETURNS trigger AS $applications_programme_receipt_guard$
DECLARE
    retry_namespace text;
    definition_row record;
    submission_row record;
    actor_row record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme command receipts are append-only'
            USING ERRCODE = '23514';
    END IF;
    IF pg_catalog.current_setting(
        'maru.applications_programme_writer', true
    ) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme command receipts require the writer latch'
            USING ERRCODE = '23514';
    END IF;
    retry_namespace := 'maru:applications:retry:'
        || pg_catalog.lower(NEW.edition_id::text) || ':'
        || pg_catalog.lower(NEW.actor_id::text) || ':'
        || pg_catalog.lower(NEW.retry_key::text);
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(retry_namespace, 0)
    );
    IF EXISTS (
        SELECT 1 FROM public.applications_applicationcommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) THEN
        RAISE EXCEPTION 'Applications retry key is already retained by generic Applications'
            USING ERRCODE = '23505';
    END IF;
    SELECT account_kind, is_active, email_verified_at
      INTO actor_row
      FROM public.identity_account
     WHERE id = NEW.actor_id
     FOR KEY SHARE;
    IF actor_row.account_kind IS DISTINCT FROM 'person'
       OR actor_row.is_active IS DISTINCT FROM TRUE
       OR actor_row.email_verified_at IS NULL
    THEN
        RAISE EXCEPTION 'Programme commands require an active verified person actor'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, code, version, status,
           target_adapter_kind, aggregate_version, opens_at,
           applicant_edit_until
      INTO definition_row
      FROM public.applications_applicationdefinition
     WHERE id = NEW.definition_id
     FOR KEY SHARE;
    IF definition_row IS NULL
       OR definition_row.target_adapter_kind <> 'programme_item'
       OR definition_row.organization_id <> NEW.organization_id
       OR definition_row.edition_id <> NEW.edition_id
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.resulting_version <> NEW.expected_version + 1
    THEN
        RAISE EXCEPTION 'Programme command receipt scope, digest, or version mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_kind = 'call' THEN
        IF NEW.submission_id IS NOT NULL
           OR NEW.action NOT IN (
                'call_created', 'call_configured', 'call_activated',
                'call_retired', 'call_successor_created'
           )
           OR definition_row.aggregate_version <> NEW.resulting_version
        THEN
            RAISE EXCEPTION 'Programme call receipt aggregate mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.action = 'call_created' THEN
            IF definition_row.version <> 1
               OR definition_row.status <> 'draft'
               OR NEW.result_kind <> 'call'
               OR NOT EXISTS (
                    SELECT 1 FROM public.applications_programmecall
                     WHERE id = NEW.target_id
                       AND definition_id = NEW.definition_id
               )
               OR EXISTS (
                    SELECT 1
                      FROM public.applications_applicationdefinition
                     WHERE edition_id = NEW.edition_id
                       AND code = definition_row.code
                       AND id <> NEW.definition_id
               )
            THEN
                RAISE EXCEPTION 'Programme call creation must begin one unbranched version chain'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.action = 'call_successor_created' THEN
            PERFORM 1
              FROM public.applications_applicationdefinition AS predecessor
              JOIN public.applications_programmecall AS predecessor_call
                ON predecessor_call.definition_id = predecessor.id
             WHERE predecessor.edition_id = NEW.edition_id
               AND predecessor.code = definition_row.code
               AND predecessor.version = definition_row.version - 1
               AND predecessor.status = 'retired'
             FOR KEY SHARE OF predecessor;
            IF NOT FOUND
               OR definition_row.version <= 1
               OR definition_row.status <> 'draft'
               OR NEW.result_kind <> 'call'
               OR NOT EXISTS (
                    SELECT 1 FROM public.applications_programmecall
                     WHERE id = NEW.target_id
                       AND definition_id = NEW.definition_id
               )
            THEN
                RAISE EXCEPTION 'Programme call successor must extend the exact retired version chain'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.action IN ('call_activated', 'call_retired') THEN
            IF NEW.result_kind <> 'call'
               OR NOT EXISTS (
                    SELECT 1 FROM public.applications_programmecall
                     WHERE id = NEW.target_id
                       AND definition_id = NEW.definition_id
               )
            THEN
                RAISE EXCEPTION 'Programme call lifecycle receipt must target its call'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.action = 'call_configured' THEN
            IF NOT (
                (NEW.result_kind = 'call' AND EXISTS (
                    SELECT 1 FROM public.applications_programmecall
                     WHERE id = NEW.target_id
                       AND definition_id = NEW.definition_id
                ))
                OR (NEW.result_kind = 'track' AND EXISTS (
                    SELECT 1 FROM public.applications_programmecalltrack AS track
                    JOIN public.applications_programmecall AS call
                      ON call.id = track.call_id
                    WHERE track.id = NEW.target_id
                      AND call.definition_id = NEW.definition_id
                ))
                OR (NEW.result_kind = 'format' AND EXISTS (
                    SELECT 1 FROM public.applications_programmecallformat AS format
                    JOIN public.applications_programmecall AS call
                      ON call.id = format.call_id
                    WHERE format.id = NEW.target_id
                      AND call.definition_id = NEW.definition_id
                ))
                OR (NEW.result_kind = 'contributor_field' AND EXISTS (
                    SELECT 1
                      FROM public.applications_programmecallcontributorfield AS field
                      JOIN public.applications_programmecall AS call
                        ON call.id = field.call_id
                     WHERE field.id = NEW.target_id
                       AND call.definition_id = NEW.definition_id
                ))
            ) THEN
                RAISE EXCEPTION 'Programme call configuration receipt target is invalid'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSIF NEW.aggregate_kind = 'proposal' THEN
        SELECT organization_id, edition_id, definition_id, aggregate_version
          INTO submission_row
          FROM public.applications_applicationsubmission
         WHERE id = NEW.submission_id
         FOR KEY SHARE;
        IF submission_row IS NULL
           OR submission_row.organization_id <> NEW.organization_id
           OR submission_row.edition_id <> NEW.edition_id
           OR submission_row.definition_id <> NEW.definition_id
           OR submission_row.aggregate_version <> NEW.resulting_version
           OR NEW.action NOT IN (
                'proposal_started', 'proposal_selection_revised',
                'proposal_answer_revised', 'collaborator_invited',
                'collaborator_accepted', 'collaborator_declined',
                'collaborator_left', 'collaborator_removed',
                'collaborator_reinvited', 'contributor_profile_revised',
                'proposal_sealed', 'proposal_reopened',
                'revision_acknowledged', 'revision_declined',
                'proposal_submitted', 'proposal_withdrawn'
           )
        THEN
            RAISE EXCEPTION 'Programme proposal receipt aggregate mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.action IN ('proposal_started', 'proposal_reopened') AND (
            definition_row.status <> 'active'
            OR pg_catalog.transaction_timestamp() < definition_row.opens_at
            OR pg_catalog.transaction_timestamp() >
               definition_row.applicant_edit_until
        ) THEN
            RAISE EXCEPTION 'Programme proposal draft lifecycle is outside its edit window'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.action IN (
            'proposal_started', 'proposal_selection_revised',
            'collaborator_invited', 'collaborator_removed',
            'collaborator_reinvited', 'proposal_sealed',
            'proposal_reopened', 'proposal_submitted',
            'proposal_withdrawn'
        ) AND NEW.actor_id <> (
            SELECT account_id
              FROM public.applications_applicationsubmission
             WHERE id = NEW.submission_id
        ) THEN
            RAISE EXCEPTION 'Programme proposal action requires the accountable lead'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'Programme command receipt aggregate kind is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_programme_receipt_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

PROGRAMME_CONTRACT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_validate_programme_contract()
RETURNS trigger AS $applications_programme_contract_guard$
DECLARE
    definition_id_value uuid;
    submission_id_value uuid;
    proposal_id_value uuid;
    definition_row record;
    submission_row record;
    proposal_row record;
    receipt_row record;
    revision_row record;
    receipt_count integer;
BEGIN
    IF TG_TABLE_NAME = 'applications_applicationdefinition' THEN
        definition_id_value := NEW.id;
        IF NEW.target_adapter_kind <> 'programme_item' THEN RETURN NULL; END IF;
    ELSIF TG_TABLE_NAME IN (
        'applications_applicationownerdepartment',
        'applications_applicationreviewerrole',
        'applications_applicationreviewerperson',
        'applications_applicationsection',
        'applications_applicationquestion'
    ) THEN
        definition_id_value := CASE
            WHEN TG_OP = 'DELETE' THEN OLD.definition_id ELSE NEW.definition_id
        END;
    ELSIF TG_TABLE_NAME = 'applications_programmecall' THEN
        definition_id_value := CASE
            WHEN TG_OP = 'DELETE' THEN OLD.definition_id ELSE NEW.definition_id
        END;
    ELSIF TG_TABLE_NAME IN (
        'applications_programmecalltrack',
        'applications_programmecallformat',
        'applications_programmecallcontributorfield'
    ) THEN
        SELECT definition_id INTO definition_id_value
          FROM public.applications_programmecall
         WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.call_id ELSE NEW.call_id END;
    ELSIF TG_TABLE_NAME = 'applications_applicationsubmission' THEN
        submission_id_value := NEW.id;
        definition_id_value := NEW.definition_id;
    ELSIF TG_TABLE_NAME = 'applications_applicationanswerrevision' THEN
        submission_id_value := NEW.submission_id;
    ELSIF TG_TABLE_NAME = 'applications_programmeproposal' THEN
        proposal_id_value := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
        submission_id_value := CASE
            WHEN TG_OP = 'DELETE' THEN OLD.submission_id ELSE NEW.submission_id
        END;
    ELSIF TG_TABLE_NAME IN (
        'applications_programmeproposalselectionrevision',
        'applications_programmeproposalcollaborator',
        'applications_programmeproposalcollaboratortransition',
        'applications_programmeproposalcontributorprofilerevision',
        'applications_programmeproposalrevision'
    ) THEN
        proposal_id_value := CASE
            WHEN TG_OP = 'DELETE' THEN OLD.proposal_id ELSE NEW.proposal_id
        END;
    ELSIF TG_TABLE_NAME IN (
        'applications_programmeproposalrevisionanswer',
        'applications_programmeproposalrevisioncontributor',
        'applications_programmeproposalrevisionresponse'
    ) THEN
        SELECT proposal_id INTO proposal_id_value
          FROM public.applications_programmeproposalrevision
         WHERE id = CASE
            WHEN TG_OP = 'DELETE' THEN OLD.revision_id ELSE NEW.revision_id
         END;
    ELSIF TG_TABLE_NAME = 'applications_programmecommandreceipt' THEN
        definition_id_value := NEW.definition_id;
        submission_id_value := NEW.submission_id;
    END IF;

    IF proposal_id_value IS NOT NULL AND submission_id_value IS NULL THEN
        SELECT submission_id INTO submission_id_value
          FROM public.applications_programmeproposal
         WHERE id = proposal_id_value;
    END IF;
    IF submission_id_value IS NOT NULL AND definition_id_value IS NULL THEN
        SELECT definition_id INTO definition_id_value
          FROM public.applications_applicationsubmission
         WHERE id = submission_id_value;
    END IF;
    IF definition_id_value IS NULL THEN RETURN NULL; END IF;

    SELECT id, organization_id, edition_id, target_adapter_kind,
           status, aggregate_version, opens_at, applicant_edit_until
      INTO definition_row
      FROM public.applications_applicationdefinition
     WHERE id = definition_id_value;
    IF definition_row.target_adapter_kind IS DISTINCT FROM 'programme_item' THEN
        RETURN NULL;
    END IF;

    SELECT COUNT(*) INTO receipt_count
      FROM public.applications_programmecommandreceipt AS receipt
     WHERE receipt.definition_id = definition_id_value
       AND receipt.submission_id IS NULL
       AND receipt.resulting_version = definition_row.aggregate_version;
    IF receipt_count <> 1 THEN
        RAISE EXCEPTION 'Programme call mutation lacks one exact command receipt'
            USING ERRCODE = '23514';
    END IF;
    SELECT receipt.id, receipt.action, receipt.target_id,
           receipt.result_kind, receipt.actor_id
      INTO receipt_row
      FROM public.applications_programmecommandreceipt AS receipt
     WHERE receipt.definition_id = definition_id_value
       AND receipt.submission_id IS NULL
       AND receipt.resulting_version = definition_row.aggregate_version
     LIMIT 1;
    IF NOT EXISTS (
        SELECT 1
          FROM public.applications_programmecall AS call
          JOIN public.applications_applicationownerdepartment AS owner
            ON owner.definition_id = call.definition_id
           AND owner.department_id = call.owner_department_id
          JOIN public.workforce_department AS department
            ON department.id = call.owner_department_id
           AND department.organization_id = call.organization_id
           AND department.edition_id = call.edition_id
         WHERE call.definition_id = definition_id_value
           AND call.organization_id = definition_row.organization_id
           AND call.edition_id = definition_row.edition_id
    ) THEN
        RAISE EXCEPTION 'Programme call graph lacks its exact Department owner'
            USING ERRCODE = '23514';
    END IF;
    IF submission_id_value IS NULL AND EXISTS (
        SELECT 1
          FROM public.applications_programmecall AS call
          JOIN public.workforce_department AS department
            ON department.id = call.owner_department_id
         WHERE call.definition_id = definition_id_value
           AND department.retired_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Programme call management requires a current Department owner'
            USING ERRCODE = '23514';
    END IF;
    IF receipt_row.action = 'call_created' AND NOT EXISTS (
        SELECT 1 FROM public.applications_programmecall
         WHERE definition_id = definition_id_value
           AND id = receipt_row.target_id
    ) THEN
        RAISE EXCEPTION 'Programme call creation receipt lacks its call proof'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'call_activated'
          AND definition_row.status <> 'active' THEN
        RAISE EXCEPTION 'Programme call activation receipt lacks active state'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'call_retired'
          AND definition_row.status <> 'retired' THEN
        RAISE EXCEPTION 'Programme call retirement receipt lacks retired state'
            USING ERRCODE = '23514';
    END IF;
    IF definition_row.status IN ('active', 'retired') AND (
        NOT EXISTS (
            SELECT 1 FROM public.applications_programmecalltrack AS track
            JOIN public.applications_programmecall AS call ON call.id = track.call_id
            WHERE call.definition_id = definition_id_value
        ) OR NOT EXISTS (
            SELECT 1 FROM public.applications_programmecallformat AS format
            JOIN public.applications_programmecall AS call ON call.id = format.call_id
            WHERE call.definition_id = definition_id_value
        )
    ) THEN
        RAISE EXCEPTION 'active Programme call graph is incomplete'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.applications_programmecall AS call
         WHERE call.definition_id = definition_id_value
           AND (
                (SELECT COUNT(*)
                   FROM public.applications_programmecalltrack
                  WHERE call_id = call.id) > 64
                OR (SELECT COUNT(*)
                      FROM public.applications_programmecallformat
                     WHERE call_id = call.id) > 32
                OR (SELECT COUNT(*)
                      FROM public.applications_programmecallcontributorfield
                     WHERE call_id = call.id) > 4
                OR EXISTS (
                    SELECT 1
                      FROM public.applications_programmecallformat AS format
                     WHERE format.call_id = call.id
                       AND (
                            format.min_duration_minutes < 1
                            OR format.max_duration_minutes > 1440
                       )
                )
           )
    ) THEN
        RAISE EXCEPTION 'Programme call configuration exceeds its closed bounds'
            USING ERRCODE = '23514';
    END IF;
    IF definition_row.status IN ('active', 'retired') AND NOT EXISTS (
        SELECT 1
          FROM public.applications_programmecallcontributorfield AS field
          JOIN public.applications_programmecall AS call
            ON call.id = field.call_id
         WHERE call.definition_id = definition_id_value
           AND field.field_code = 'public_name'
           AND field.lead_requirement = 'required'
    ) THEN
        RAISE EXCEPTION 'active Programme call lacks its required lead public name'
            USING ERRCODE = '23514';
    END IF;
    IF definition_row.status IN ('active', 'retired') AND EXISTS (
        SELECT 1
          FROM public.applications_applicationquestion AS question
          JOIN public.applications_applicationsection AS question_section
            ON question_section.id = question.section_id
          LEFT JOIN public.applications_applicationquestion AS source
            ON source.definition_id = question.definition_id
           AND source.key = question.condition->>'question_key'
          LEFT JOIN public.applications_applicationsection AS source_section
            ON source_section.id = source.section_id
         WHERE question.definition_id = definition_id_value
           AND question.condition <> '{}'::jsonb
           AND CASE
                WHEN pg_catalog.jsonb_typeof(question.condition) <> 'object'
                  OR (
                      SELECT COUNT(*)
                        FROM pg_catalog.jsonb_object_keys(
                            CASE
                              WHEN pg_catalog.jsonb_typeof(
                                  question.condition
                              ) = 'object'
                              THEN question.condition
                              ELSE '{}'::jsonb
                            END
                        )
                  ) <> 3
                  OR NOT question.condition ?&
                     ARRAY['question_key', 'operator', 'value']
                THEN TRUE
                WHEN question.condition->>'operator' NOT IN (
                    'equals', 'not_equals', 'contains'
                ) THEN TRUE
                WHEN source.id IS NULL THEN TRUE
                WHEN NOT (
                    source_section.position < question_section.position
                    OR (
                        source_section.position = question_section.position
                        AND source.position < question.position
                    )
                ) THEN TRUE
                WHEN question.condition->>'operator' = 'contains' THEN NOT (
                    source.field_type = 'multiple_choice'
                    AND pg_catalog.jsonb_typeof(
                        question.condition->'value'
                    ) = 'string'
                    AND EXISTS (
                        SELECT 1
                          FROM pg_catalog.jsonb_array_elements(
                              CASE
                                WHEN pg_catalog.jsonb_typeof(source.options) =
                                     'array'
                                THEN source.options
                                ELSE '[]'::jsonb
                              END
                          ) AS option
                         WHERE option->>'code' =
                               question.condition->>'value'
                    )
                )
                WHEN source.field_type = 'boolean' THEN
                    pg_catalog.jsonb_typeof(question.condition->'value') <>
                    'boolean'
                WHEN source.field_type = 'integer' THEN NOT (
                    pg_catalog.jsonb_typeof(question.condition->'value') =
                    'number'
                    AND question.condition->>'value' ~
                        '^-?(0|[1-9][0-9]*)$'
                    AND (question.condition->>'value')::numeric BETWEEN
                        -2147483648 AND 2147483647
                )
                WHEN source.field_type = 'single_choice' THEN NOT (
                    pg_catalog.jsonb_typeof(question.condition->'value') =
                    'string'
                    AND EXISTS (
                        SELECT 1
                          FROM pg_catalog.jsonb_array_elements(
                              CASE
                                WHEN pg_catalog.jsonb_typeof(source.options) =
                                     'array'
                                THEN source.options
                                ELSE '[]'::jsonb
                              END
                          ) AS option
                         WHERE option->>'code' =
                               question.condition->>'value'
                    )
                )
                WHEN source.field_type IN (
                    'short_text', 'long_text', 'email', 'phone', 'url'
                ) THEN pg_catalog.jsonb_typeof(
                    question.condition->'value'
                ) <> 'string'
                ELSE TRUE
               END
    ) THEN
        RAISE EXCEPTION 'active Programme condition graph is invalid'
            USING ERRCODE = '23514';
    END IF;

    IF submission_id_value IS NULL THEN RETURN NULL; END IF;
    SELECT id, organization_id, edition_id, definition_id, account_id,
           state, aggregate_version, submitted_at, withdrawn_at
      INTO submission_row
      FROM public.applications_applicationsubmission
     WHERE id = submission_id_value;
    SELECT id, organization_id, edition_id, call_id, state,
           sealed_revision_id, submitted_revision_id
      INTO proposal_row
      FROM public.applications_programmeproposal
     WHERE submission_id = submission_id_value;
    IF submission_row IS NULL OR proposal_row IS NULL
       OR submission_row.definition_id <> definition_id_value
       OR proposal_row.organization_id <> submission_row.organization_id
       OR proposal_row.edition_id <> submission_row.edition_id
    THEN
        RAISE EXCEPTION 'Programme proposal projection is missing or cross-scoped'
            USING ERRCODE = '23514';
    END IF;

    SELECT COUNT(*) INTO receipt_count
      FROM public.applications_programmecommandreceipt AS receipt
     WHERE receipt.submission_id = submission_id_value
       AND receipt.resulting_version = submission_row.aggregate_version;
    IF receipt_count <> 1 THEN
        RAISE EXCEPTION 'Programme proposal mutation lacks one exact command receipt'
            USING ERRCODE = '23514';
    END IF;
    SELECT receipt.id, receipt.action, receipt.target_id,
           receipt.result_kind, receipt.actor_id
      INTO receipt_row
      FROM public.applications_programmecommandreceipt AS receipt
     WHERE receipt.submission_id = submission_id_value
       AND receipt.resulting_version = submission_row.aggregate_version
     LIMIT 1;
    IF receipt_row.action = 'proposal_started' THEN
        IF submission_row.aggregate_version <> 1
           OR definition_row.status <> 'active'
           OR pg_catalog.transaction_timestamp() < definition_row.opens_at
           OR pg_catalog.transaction_timestamp() >
              definition_row.applicant_edit_until
           OR proposal_row.state <> 'draft'
           OR receipt_row.target_id <> proposal_row.id
           OR receipt_row.result_kind <> 'proposal'
           OR NOT EXISTS (
                SELECT 1
                  FROM public.applications_programmecall AS call
                  JOIN public.workforce_department AS department
                    ON department.id = call.owner_department_id
                   AND department.organization_id = call.organization_id
                   AND department.edition_id = call.edition_id
                   AND department.retired_at IS NULL
                 WHERE call.id = proposal_row.call_id
           )
           OR NOT EXISTS (
                SELECT 1
                  FROM public.applications_programmeproposalselectionrevision
                 WHERE proposal_id = proposal_row.id
                   AND source_version = 0 AND resulting_version = 1
           )
           OR NOT EXISTS (
                SELECT 1
                  FROM public.applications_programmeproposalcontributorprofilerevision
                 WHERE proposal_id = proposal_row.id
                   AND account_id = submission_row.account_id
                   AND source_version = 0 AND resulting_version = 1
           )
        THEN
            RAISE EXCEPTION 'Programme proposal start lacks initial selection and lead profile proof'
                USING ERRCODE = '23514';
        END IF;
    ELSIF receipt_row.action = 'proposal_selection_revised' AND (
        receipt_row.result_kind <> 'selection_revision'
        OR NOT EXISTS (
            SELECT 1
              FROM public.applications_programmeproposalselectionrevision
             WHERE id = receipt_row.target_id
               AND proposal_id = proposal_row.id
               AND actor_id = receipt_row.actor_id
               AND resulting_version = submission_row.aggregate_version
        )
    ) THEN
        RAISE EXCEPTION 'Programme selection receipt lacks exact revision proof'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'proposal_answer_revised' AND (
        receipt_row.result_kind <> 'answer_revision'
        OR NOT EXISTS (
            SELECT 1 FROM public.applications_applicationanswerrevision
             WHERE id = receipt_row.target_id
               AND submission_id = submission_row.id
               AND actor_id = receipt_row.actor_id
               AND resulting_version = submission_row.aggregate_version
        )
    ) THEN
        RAISE EXCEPTION 'Programme answer receipt lacks exact revision proof'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action IN (
        'collaborator_invited', 'collaborator_accepted',
        'collaborator_declined', 'collaborator_left',
        'collaborator_removed', 'collaborator_reinvited'
    ) AND (
        receipt_row.result_kind <> 'collaborator_transition'
        OR NOT EXISTS (
            SELECT 1
              FROM public.applications_programmeproposalcollaboratortransition
             WHERE id = receipt_row.target_id
               AND proposal_id = proposal_row.id
               AND actor_id = receipt_row.actor_id
               AND resulting_version = submission_row.aggregate_version
               AND to_state = CASE receipt_row.action
                    WHEN 'collaborator_invited' THEN 'invited'
                    WHEN 'collaborator_reinvited' THEN 'invited'
                    WHEN 'collaborator_accepted' THEN 'accepted'
                    WHEN 'collaborator_declined' THEN 'declined'
                    WHEN 'collaborator_left' THEN 'left'
                    WHEN 'collaborator_removed' THEN 'removed'
                   END
        )
    ) THEN
        RAISE EXCEPTION 'Programme collaborator receipt lacks exact transition proof'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'contributor_profile_revised' AND (
        receipt_row.result_kind <> 'profile_revision'
        OR NOT EXISTS (
            SELECT 1
              FROM public.applications_programmeproposalcontributorprofilerevision
             WHERE id = receipt_row.target_id
               AND proposal_id = proposal_row.id
               AND actor_id = receipt_row.actor_id
               AND account_id = receipt_row.actor_id
               AND resulting_version = submission_row.aggregate_version
        )
    ) THEN
        RAISE EXCEPTION 'Programme contributor receipt lacks exact profile proof'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'proposal_sealed' AND (
        receipt_row.result_kind <> 'proposal_revision'
        OR proposal_row.state <> 'sealed'
        OR proposal_row.sealed_revision_id <> receipt_row.target_id
        OR NOT EXISTS (
            SELECT 1 FROM public.applications_programmeproposalrevision
             WHERE id = receipt_row.target_id
               AND proposal_id = proposal_row.id
               AND created_by_id = receipt_row.actor_id
               AND resulting_version = submission_row.aggregate_version
        )
    ) THEN
        RAISE EXCEPTION 'Programme seal receipt lacks exact revision proof'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action IN (
        'revision_acknowledged', 'revision_declined'
    ) AND (
        receipt_row.result_kind <> 'revision_response'
        OR NOT EXISTS (
            SELECT 1
              FROM public.applications_programmeproposalrevisionresponse AS response
              JOIN public.applications_programmeproposalrevisioncontributor
                   AS contributor
                ON contributor.id = response.contributor_id
             WHERE response.id = receipt_row.target_id
               AND response.revision_id = proposal_row.sealed_revision_id
               AND response.account_id = receipt_row.actor_id
               AND response.actor_id = receipt_row.actor_id
               AND response.resulting_version = submission_row.aggregate_version
               AND contributor.revision_id = response.revision_id
               AND contributor.account_id = response.account_id
               AND contributor.role = 'collaborator'
               AND response.response = CASE receipt_row.action
                    WHEN 'revision_acknowledged' THEN 'acknowledged'
                    ELSE 'declined' END
        )
    ) THEN
        RAISE EXCEPTION 'Programme response receipt lacks exact response proof'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'proposal_reopened' AND (
        receipt_row.result_kind <> 'proposal'
        OR receipt_row.target_id <> proposal_row.id
        OR definition_row.status <> 'active'
        OR pg_catalog.transaction_timestamp() < definition_row.opens_at
        OR pg_catalog.transaction_timestamp() >
           definition_row.applicant_edit_until
        OR proposal_row.state <> 'draft'
        OR proposal_row.sealed_revision_id IS NOT NULL
        OR proposal_row.submitted_revision_id IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Programme reopen receipt lacks a cleared draft projection'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'proposal_submitted' AND (
        receipt_row.result_kind <> 'proposal_revision'
        OR receipt_row.target_id IS DISTINCT FROM
           proposal_row.submitted_revision_id
        OR proposal_row.state <> 'submitted'
        OR proposal_row.sealed_revision_id IS NULL
        OR proposal_row.submitted_revision_id IS DISTINCT FROM
           proposal_row.sealed_revision_id
    ) THEN
        RAISE EXCEPTION 'Programme submit receipt lacks one exact submitted revision'
            USING ERRCODE = '23514';
    ELSIF receipt_row.action = 'proposal_withdrawn' AND (
        receipt_row.result_kind <> 'proposal'
        OR receipt_row.target_id <> proposal_row.id
        OR proposal_row.state <> 'withdrawn'
    ) THEN
        RAISE EXCEPTION 'Programme withdrawal receipt lacks withdrawn state'
            USING ERRCODE = '23514';
    END IF;

    IF proposal_row.state IN ('draft', 'sealed') AND (
        submission_row.state <> 'draft'
        OR submission_row.submitted_at IS NOT NULL
        OR submission_row.withdrawn_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Programme draft or sealed projection must retain a draft submission'
            USING ERRCODE = '23514';
    ELSIF proposal_row.state = 'submitted' AND (
        submission_row.state <> 'submitted'
        OR submission_row.submitted_at IS NULL
        OR submission_row.withdrawn_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Programme submitted projection must match its submission'
            USING ERRCODE = '23514';
    ELSIF proposal_row.state = 'withdrawn' AND (
        submission_row.state <> 'withdrawn'
        OR submission_row.withdrawn_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Programme withdrawn projection must match its submission'
            USING ERRCODE = '23514';
    END IF;

    IF proposal_row.state = 'draft' THEN
        IF proposal_row.sealed_revision_id IS NOT NULL
           OR proposal_row.submitted_revision_id IS NOT NULL
        THEN
            RAISE EXCEPTION 'Programme draft projection cannot retain revision pointers'
                USING ERRCODE = '23514';
        END IF;
        RETURN NULL;
    ELSIF proposal_row.state = 'withdrawn' THEN
        RETURN NULL;
    END IF;

    SELECT id, proposal_id, sequence, definition_version,
           selection_revision_id, source_version, resulting_version,
           created_by_id
      INTO revision_row
      FROM public.applications_programmeproposalrevision
     WHERE id = proposal_row.sealed_revision_id;
    IF revision_row IS NULL
       OR revision_row.proposal_id <> proposal_row.id
       OR revision_row.created_by_id <> submission_row.account_id
       OR revision_row.definition_version IS DISTINCT FROM (
            SELECT version FROM public.applications_applicationdefinition
             WHERE id = submission_row.definition_id
       )
       OR revision_row.selection_revision_id IS DISTINCT FROM (
            SELECT selection.id
              FROM public.applications_programmeproposalselectionrevision AS selection
             WHERE selection.proposal_id = proposal_row.id
               AND selection.resulting_version <= revision_row.source_version
             ORDER BY selection.resulting_version DESC, selection.sequence DESC
             LIMIT 1
       )
    THEN
        RAISE EXCEPTION 'Programme sealed projection points to an incoherent revision'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        WITH latest_answers AS (
            SELECT DISTINCT ON (answer.question_id)
                   answer.question_id, answer.id, answer.value,
                   answer.resulting_version
              FROM public.applications_applicationanswerrevision AS answer
             WHERE answer.submission_id = submission_row.id
               AND answer.resulting_version <= revision_row.source_version
             ORDER BY answer.question_id, answer.resulting_version DESC,
                      answer.sequence DESC
        ), applicable_questions AS (
            SELECT question.id
              FROM public.applications_applicationquestion AS question
             WHERE question.definition_id = submission_row.definition_id
               AND (
                    question.condition = '{}'::jsonb
                    OR CASE question.condition->>'operator'
                        WHEN 'equals' THEN COALESCE(
                            (
                                SELECT source_answer.value
                                  FROM public.applications_applicationquestion
                                       AS source_question
                                  LEFT JOIN latest_answers AS source_answer
                                    ON source_answer.question_id = source_question.id
                                 WHERE source_question.definition_id =
                                       question.definition_id
                                   AND source_question.key =
                                       question.condition->>'question_key'
                                 LIMIT 1
                            ),
                            'null'::jsonb
                        ) = question.condition->'value'
                        WHEN 'not_equals' THEN COALESCE(
                            (
                                SELECT source_answer.value
                                  FROM public.applications_applicationquestion
                                       AS source_question
                                  LEFT JOIN latest_answers AS source_answer
                                    ON source_answer.question_id = source_question.id
                                 WHERE source_question.definition_id =
                                       question.definition_id
                                   AND source_question.key =
                                       question.condition->>'question_key'
                                 LIMIT 1
                            ),
                            'null'::jsonb
                        ) <> question.condition->'value'
                        WHEN 'contains' THEN
                            pg_catalog.jsonb_typeof(COALESCE(
                                (
                                    SELECT source_answer.value
                                      FROM public.applications_applicationquestion
                                           AS source_question
                                      LEFT JOIN latest_answers AS source_answer
                                        ON source_answer.question_id = source_question.id
                                     WHERE source_question.definition_id =
                                           question.definition_id
                                       AND source_question.key =
                                           question.condition->>'question_key'
                                     LIMIT 1
                                ),
                                'null'::jsonb
                            )) = 'array'
                            AND COALESCE(
                                (
                                    SELECT source_answer.value
                                      FROM public.applications_applicationquestion
                                           AS source_question
                                      LEFT JOIN latest_answers AS source_answer
                                        ON source_answer.question_id = source_question.id
                                     WHERE source_question.definition_id =
                                           question.definition_id
                                       AND source_question.key =
                                           question.condition->>'question_key'
                                     LIMIT 1
                                ),
                                'null'::jsonb
                            ) @> pg_catalog.jsonb_build_array(
                                question.condition->'value'
                            )
                        ELSE FALSE
                       END
               )
        ), expected AS (
            SELECT applicable.id AS question_id,
                   latest.id AS answer_id
              FROM applicable_questions AS applicable
              LEFT JOIN latest_answers AS latest
                ON latest.question_id = applicable.id
        ), actual AS (
            SELECT answer.question_id, answer.answer_revision_id AS answer_id
              FROM public.applications_programmeproposalrevisionanswer AS answer
             WHERE answer.revision_id = revision_row.id
        )
        (SELECT * FROM expected EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM expected)
    ) THEN
        RAISE EXCEPTION 'Programme revision must contain exactly every applicable latest answer or explicit absence'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.applications_programmeproposalrevisionanswer AS snapshot
          JOIN public.applications_applicationquestion AS question
            ON question.id = snapshot.question_id
         WHERE snapshot.revision_id = revision_row.id
           AND question.required
           AND (
                snapshot.answer_revision_id IS NULL
                OR EXISTS (
                    SELECT 1
                      FROM public.applications_applicationanswerrevision AS answer
                     WHERE answer.id = snapshot.answer_revision_id
                       AND (
                            answer.value IS NULL
                            OR answer.value IN (
                                'null'::jsonb,
                                '""'::jsonb,
                                '[]'::jsonb,
                                '{}'::jsonb
                            )
                       )
                )
           )
    ) THEN
        RAISE EXCEPTION 'Programme revision has an unanswered required question'
            USING ERRCODE = '23514';
    END IF;

    IF EXISTS (
        WITH latest_transitions AS (
            SELECT DISTINCT ON (collaborator.id)
                   collaborator.account_id, transition.id AS transition_id,
                   transition.to_state
              FROM public.applications_programmeproposalcollaborator AS collaborator
              JOIN public.applications_programmeproposalcollaboratortransition
                   AS transition
                ON transition.collaborator_id = collaborator.id
             WHERE collaborator.proposal_id = proposal_row.id
               AND transition.resulting_version <= revision_row.source_version
             ORDER BY collaborator.id, transition.resulting_version DESC,
                      transition.sequence DESC
        ), expected AS (
            SELECT submission_row.account_id AS account_id,
                   'lead'::text AS role, NULL::uuid AS transition_id
            UNION ALL
            SELECT account_id, 'collaborator'::text, transition_id
              FROM latest_transitions
             WHERE to_state = 'accepted'
        ), actual AS (
            SELECT contributor.account_id, contributor.role::text,
                   contributor.accepted_transition_id
              FROM public.applications_programmeproposalrevisioncontributor
                   AS contributor
             WHERE contributor.revision_id = revision_row.id
        )
        (SELECT * FROM expected EXCEPT SELECT * FROM actual)
        UNION ALL
        (SELECT * FROM actual EXCEPT SELECT * FROM expected)
    ) THEN
        RAISE EXCEPTION 'Programme revision contributor roster is not the exact accepted roster'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.applications_programmeproposalrevisioncontributor AS contributor
          JOIN public.applications_programmeproposalcontributorprofilerevision AS profile
            ON profile.id = contributor.profile_revision_id
          JOIN public.applications_programmecallcontributorfield AS field
            ON field.call_id = proposal_row.call_id
         WHERE contributor.revision_id = revision_row.id
           AND (
                CASE contributor.role
                  WHEN 'lead' THEN field.lead_requirement
                  ELSE field.collaborator_requirement
                END = 'required'
           )
           AND CASE field.field_code
                WHEN 'public_name' THEN profile.public_name = ''
                WHEN 'biography' THEN profile.biography = ''
                WHEN 'pronouns' THEN profile.pronouns = ''
                WHEN 'website' THEN profile.website = ''
                ELSE TRUE
               END
    ) THEN
        RAISE EXCEPTION 'Programme revision lacks a required contributor profile field'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.applications_programmeproposalrevisioncontributor AS contributor
          JOIN public.applications_programmeproposalcontributorprofilerevision AS profile
            ON profile.id = contributor.profile_revision_id
          CROSS JOIN LATERAL (VALUES
                ('public_name'::text, profile.public_name::text),
                ('biography'::text, profile.biography::text),
                ('pronouns'::text, profile.pronouns::text),
                ('website'::text, profile.website::text)
          ) AS supplied(field_code, field_value)
          LEFT JOIN public.applications_programmecallcontributorfield AS field
            ON field.call_id = proposal_row.call_id
           AND field.field_code = supplied.field_code
         WHERE contributor.revision_id = revision_row.id
           AND supplied.field_value <> ''
           AND (
                field.id IS NULL
                OR CASE contributor.role
                    WHEN 'lead' THEN field.lead_requirement
                    ELSE field.collaborator_requirement
                   END = 'hidden'
           )
    ) THEN
        RAISE EXCEPTION 'Programme revision exposes a contributor field not collected for that role'
            USING ERRCODE = '23514';
    END IF;

    IF proposal_row.state IN ('sealed', 'submitted') AND EXISTS (
        SELECT 1
          FROM public.applications_programmeproposalcollaborator
         WHERE proposal_id = proposal_row.id
           AND state = 'invited'
           AND invite_expires_at > pg_catalog.transaction_timestamp()
    ) THEN
        RAISE EXCEPTION 'Programme proposal has an unresolved collaborator invitation'
            USING ERRCODE = '23514';
    END IF;

    IF proposal_row.state = 'submitted' THEN
        IF proposal_row.submitted_revision_id IS DISTINCT FROM
           proposal_row.sealed_revision_id THEN
            RAISE EXCEPTION 'Programme submitted pointer must equal the sealed revision'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM public.applications_programmeproposalrevisioncontributor AS contributor
              LEFT JOIN public.applications_programmeproposalrevisionresponse AS response
                ON response.revision_id = contributor.revision_id
               AND response.contributor_id = contributor.id
               AND response.account_id = contributor.account_id
               AND response.profile_revision_id = contributor.profile_revision_id
               AND response.response = 'acknowledged'
             WHERE contributor.revision_id = revision_row.id
               AND contributor.role = 'collaborator'
               AND response.id IS NULL
        ) THEN
            RAISE EXCEPTION 'Programme collaborators must acknowledge the exact revision before submit'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$applications_programme_contract_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

PROGRAMME_TRUNCATE_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_refuse_programme_truncate()
RETURNS trigger AS $applications_programme_truncate_guard$
BEGIN
    IF pg_catalog.current_database() LIKE 'test\_%' ESCAPE '\'
       AND pg_catalog.current_setting(
           'maru.authority_provenance_test_reset', true
       ) = 'on'
    THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Programme Applications records require governed retention'
        USING ERRCODE = '23514';
END;
$applications_programme_truncate_guard$
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

_PATCHED_LEGACY_SQL = _legacy.FORWARD_SQL
for _function_name, _replacement in (
    ("maru_applications_guard_definition", DEFINITION_FUNCTION_SQL),
    ("maru_applications_guard_definition_child", DEFINITION_CHILD_FUNCTION_SQL),
    ("maru_applications_guard_submission", SUBMISSION_FUNCTION_SQL),
    ("maru_applications_guard_answer", ANSWER_FUNCTION_SQL),
    ("maru_applications_guard_review", REVIEW_FUNCTION_SQL),
    ("maru_applications_guard_target", TARGET_FUNCTION_SQL),
):
    _PATCHED_LEGACY_SQL = _replace_function(
        _PATCHED_LEGACY_SQL,
        _function_name,
        _replacement,
    )

_legacy_receipt_trigger = (
    "CREATE TRIGGER applications_receipt_guard BEFORE UPDATE OR DELETE ON "
    "public.applications_applicationcommandreceipt FOR EACH ROW EXECUTE FUNCTION "
    "public.maru_applications_append_only();"
)
_programme_aware_receipt_trigger = (
    "CREATE TRIGGER applications_receipt_guard BEFORE INSERT OR UPDATE OR DELETE ON "
    "public.applications_applicationcommandreceipt FOR EACH ROW EXECUTE FUNCTION "
    "public.maru_applications_guard_receipt();"
)
if _PATCHED_LEGACY_SQL.count(_legacy_receipt_trigger) != 1:
    raise RuntimeError("Legacy Applications receipt trigger unavailable")
_PATCHED_LEGACY_SQL = _PATCHED_LEGACY_SQL.replace(
    _legacy_receipt_trigger,
    _programme_aware_receipt_trigger,
)
_legacy_trigger_marker = "CREATE TRIGGER applications_definition_guard"
if _PATCHED_LEGACY_SQL.count(_legacy_trigger_marker) != 1:
    raise RuntimeError("Legacy Applications trigger block unavailable")
_LEGACY_FUNCTION_SQL, _LEGACY_TRIGGER_SQL = _PATCHED_LEGACY_SQL.split(
    _legacy_trigger_marker,
    maxsplit=1,
)
_LEGACY_TRIGGER_SQL = _legacy_trigger_marker + _LEGACY_TRIGGER_SQL

_CURRENT_TABLES = (
    ("call", "applications_programmecall"),
    ("track", "applications_programmecalltrack"),
    ("format", "applications_programmecallformat"),
    ("field", "applications_programmecallcontributorfield"),
    ("proposal", "applications_programmeproposal"),
    ("collaborator", "applications_programmeproposalcollaborator"),
)
_EVIDENCE_TABLES = (
    ("selection", "applications_programmeproposalselectionrevision"),
    ("transition", "applications_programmeproposalcollaboratortransition"),
    ("profile", "applications_programmeproposalcontributorprofilerevision"),
    ("revision", "applications_programmeproposalrevision"),
    ("answer", "applications_programmeproposalrevisionanswer"),
    ("contributor", "applications_programmeproposalrevisioncontributor"),
    ("response", "applications_programmeproposalrevisionresponse"),
)
_PROGRAMME_TABLES = (
    *_CURRENT_TABLES,
    *_EVIDENCE_TABLES,
    ("receipt", "applications_programmecommandreceipt"),
)
_CONTRACT_TABLES = (
    ("definition", "applications_applicationdefinition"),
    ("owner", "applications_applicationownerdepartment"),
    ("reviewrole", "applications_applicationreviewerrole"),
    ("reviewperson", "applications_applicationreviewerperson"),
    ("section", "applications_applicationsection"),
    ("question", "applications_applicationquestion"),
    ("submission", "applications_applicationsubmission"),
    ("genericanswer", "applications_applicationanswerrevision"),
    *_PROGRAMME_TABLES,
)


def _trigger_sql() -> str:
    statements: list[str] = []
    for suffix, table in _CURRENT_TABLES:
        statements.append(
            f"""CREATE TRIGGER applications_prg_{suffix}_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION
public.maru_applications_guard_programme_current();"""
        )
    for suffix, table in _EVIDENCE_TABLES:
        statements.append(
            f"""CREATE TRIGGER applications_prg_{suffix}_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION
public.maru_applications_guard_programme_evidence();"""
        )
    statements.append(
        """CREATE TRIGGER applications_prg_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.applications_programmecommandreceipt
FOR EACH ROW EXECUTE FUNCTION
public.maru_applications_guard_programme_receipt();"""
    )
    for suffix, table in _PROGRAMME_TABLES:
        statements.append(
            f"""CREATE TRIGGER applications_prg_{suffix}_truncate
BEFORE TRUNCATE ON public.{table}
FOR EACH STATEMENT EXECUTE FUNCTION
public.maru_applications_refuse_programme_truncate();"""
        )
    for suffix, table in _CONTRACT_TABLES:
        statements.append(
            f"""CREATE CONSTRAINT TRIGGER applications_prg_{suffix}_contract
AFTER INSERT OR UPDATE OR DELETE ON public.{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
public.maru_applications_validate_programme_contract();"""
        )
    return "\n\n".join(statements)


_FUNCTION_IDENTITIES = (
    "maru_applications_guard_definition",
    "maru_applications_guard_definition_child",
    "maru_applications_guard_submission",
    "maru_applications_guard_answer",
    "maru_applications_guard_review",
    "maru_applications_guard_target",
    "maru_applications_append_only",
    "maru_applications_guard_receipt",
    "maru_applications_guard_programme_current",
    "maru_applications_guard_programme_evidence",
    "maru_applications_guard_programme_receipt",
    "maru_applications_validate_programme_contract",
    "maru_applications_refuse_programme_truncate",
)


def _revoke_sql() -> str:
    return "\n".join(
        f"REVOKE ALL ON FUNCTION public.{identity}() FROM PUBLIC;"
        for identity in _FUNCTION_IDENTITIES
    )


FORWARD_SQL = "\n\n".join(
    (
        LEGACY_TRIGGER_DROP_SQL.strip(),
        _LEGACY_FUNCTION_SQL.strip(),
        GENERIC_RECEIPT_FUNCTION_SQL.strip(),
        PROGRAMME_CURRENT_FUNCTION_SQL.strip(),
        PROGRAMME_EVIDENCE_FUNCTION_SQL.strip(),
        PROGRAMME_RECEIPT_FUNCTION_SQL.strip(),
        PROGRAMME_CONTRACT_FUNCTION_SQL.strip(),
        PROGRAMME_TRUNCATE_FUNCTION_SQL.strip(),
        _LEGACY_TRIGGER_SQL.strip(),
        _trigger_sql(),
        _revoke_sql(),
    )
)


def _drop_trigger_sql() -> str:
    statements = [
        f"DROP TRIGGER IF EXISTS applications_prg_{suffix}_contract ON public.{table};"
        for suffix, table in reversed(_CONTRACT_TABLES)
    ]
    statements.extend(
        f"DROP TRIGGER IF EXISTS applications_prg_{suffix}_truncate ON public.{table};"
        for suffix, table in reversed(_PROGRAMME_TABLES)
    )
    statements.append(
        "DROP TRIGGER IF EXISTS applications_prg_receipt_guard "
        "ON public.applications_programmecommandreceipt;"
    )
    statements.extend(
        f"DROP TRIGGER IF EXISTS applications_prg_{suffix}_guard ON public.{table};"
        for suffix, table in reversed(_EVIDENCE_TABLES)
    )
    statements.extend(
        f"DROP TRIGGER IF EXISTS applications_prg_{suffix}_guard ON public.{table};"
        for suffix, table in reversed(_CURRENT_TABLES)
    )
    statements.append(LEGACY_TRIGGER_DROP_SQL.strip())
    return "\n".join(statements)


def _drop_function_sql() -> str:
    return "\n".join(
        f"DROP FUNCTION IF EXISTS public.{identity}();"
        for identity in reversed(_FUNCTION_IDENTITIES)
    )


REVERSE_SQL = "\n\n".join(
    (
        _drop_trigger_sql(),
        _drop_function_sql(),
        _legacy.FORWARD_SQL.strip(),
        _legacy_acl.FORWARD_SQL.strip(),
    )
)


class Migration(migrations.Migration):
    """Install Programme call and collaborative proposal database integrity."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0004_programme_calls_and_proposals"),
        ("identity", "0020_programme_proposal_person_guard"),
        ("authorization", "0021_applications_programme_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
