"""Install authoritative database integrity for preview-first Programme imports."""

# ruff: noqa: E501, FLY002 -- SQL contract text stays exact and reviewable.

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.applications.migrations.0005_programme_integrity_guards"
)

_GENERIC_PEER_CHECK = r"""    IF EXISTS (
        SELECT 1 FROM public.applications_programmecommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) THEN
        RAISE EXCEPTION 'Applications retry key is already retained by Programme'
            USING ERRCODE = '23505';
    END IF;"""

_GENERIC_PEER_CHECK_V2 = r"""    IF EXISTS (
        SELECT 1 FROM public.applications_programmecommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) OR EXISTS (
        SELECT 1 FROM public.applications_programmeimportcommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) THEN
        RAISE EXCEPTION 'Applications retry key is already retained by another Applications command family'
            USING ERRCODE = '23505';
    END IF;"""

_PROGRAMME_PEER_CHECK = r"""    IF EXISTS (
        SELECT 1 FROM public.applications_applicationcommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) THEN
        RAISE EXCEPTION 'Applications retry key is already retained by generic Applications'
            USING ERRCODE = '23505';
    END IF;"""

_PROGRAMME_PEER_CHECK_V2 = r"""    IF EXISTS (
        SELECT 1 FROM public.applications_applicationcommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) OR EXISTS (
        SELECT 1 FROM public.applications_programmeimportcommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) THEN
        RAISE EXCEPTION 'Applications retry key is already retained by another Applications command family'
            USING ERRCODE = '23505';
    END IF;"""

if _previous.GENERIC_RECEIPT_FUNCTION_SQL.count(_GENERIC_PEER_CHECK) != 1:
    raise RuntimeError("Generic Applications retry guard source is unrecognized.")
if _previous.PROGRAMME_RECEIPT_FUNCTION_SQL.count(_PROGRAMME_PEER_CHECK) != 1:
    raise RuntimeError("Programme retry guard source is unrecognized.")

GENERIC_RECEIPT_FUNCTION_SQL = _previous.GENERIC_RECEIPT_FUNCTION_SQL.replace(
    _GENERIC_PEER_CHECK,
    _GENERIC_PEER_CHECK_V2,
)
PROGRAMME_RECEIPT_FUNCTION_SQL = _previous.PROGRAMME_RECEIPT_FUNCTION_SQL.replace(
    _PROGRAMME_PEER_CHECK,
    _PROGRAMME_PEER_CHECK_V2,
)
PROGRAMME_INTEGRITY_FORWARD_SQL_V2 = _previous.FORWARD_SQL.replace(
    _previous.GENERIC_RECEIPT_FUNCTION_SQL.strip(),
    GENERIC_RECEIPT_FUNCTION_SQL.strip(),
).replace(
    _previous.PROGRAMME_RECEIPT_FUNCTION_SQL.strip(),
    PROGRAMME_RECEIPT_FUNCTION_SQL.strip(),
)
if PROGRAMME_INTEGRITY_FORWARD_SQL_V2 == _previous.FORWARD_SQL:
    raise RuntimeError("Programme integrity SQL was not extended for import retries.")

IMPORT_CURRENT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_import_current()
RETURNS trigger AS $applications_programme_import_current_guard$
DECLARE
    edition_organization uuid;
    parent_row record;
    actor_row record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Programme-import current records require governed retention'
            USING ERRCODE = '23514';
    END IF;
    IF pg_catalog.current_setting(
        'maru.applications_programme_import_writer', true
    ) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme-import records require the registered writer latch'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id INTO edition_organization
      FROM public.events_eventedition
     WHERE id = NEW.edition_id
     FOR KEY SHARE;
    IF edition_organization IS NULL
       OR edition_organization <> NEW.organization_id
    THEN
        RAISE EXCEPTION 'Programme-import edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF TG_TABLE_NAME = 'applications_programmeimportbatch' THEN
        PERFORM 1
          FROM public.workforce_department
         WHERE id = NEW.owner_department_id
           AND organization_id = NEW.organization_id
           AND edition_id = NEW.edition_id
         FOR KEY SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Programme-import owner Department scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        SELECT account_kind, is_active, email_verified_at INTO actor_row
          FROM public.identity_account
         WHERE id = CASE
             WHEN NEW.state = 'discarded' THEN NEW.discarded_by_id
             ELSE NEW.staged_by_id
         END
         FOR KEY SHARE;
        IF actor_row.account_kind IS DISTINCT FROM 'person'
           OR actor_row.is_active IS DISTINCT FROM TRUE
           OR actor_row.email_verified_at IS NULL
        THEN
            RAISE EXCEPTION 'Programme-import batch actor must be an active verified person'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.source_system !~ '^[a-z][a-z0-9_.:-]{0,79}$'
           OR NEW.source_digest !~ '^[0-9a-f]{64}$'
           OR NEW.retention_policy_code !~ '^[a-z][a-z0-9_.:-]{2,119}$'
           OR NEW.schema_version <> 1
           OR NEW.item_count NOT BETWEEN 1 AND 1000
           OR NEW.expires_at <= NEW.created_at
        THEN
            RAISE EXCEPTION 'Programme-import batch source or retention evidence is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' AND (
            NEW.state <> 'staged'
            OR NEW.aggregate_version <> 1
            OR NEW.discarded_by_id IS NOT NULL
            OR NEW.discarded_at IS NOT NULL
            OR NEW.discard_reason <> ''
        ) THEN
            RAISE EXCEPTION 'Programme-import batches must begin as version-one staged records'
                USING ERRCODE = '23514';
        ELSIF TG_OP = 'UPDATE' THEN
            IF ROW(
                NEW.id, NEW.organization_id, NEW.edition_id,
                NEW.owner_department_id, NEW.source_system, NEW.schema_version,
                NEW.source_digest, NEW.item_count, NEW.retention_policy_code,
                NEW.expires_at, NEW.staged_by_id, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.organization_id, OLD.edition_id,
                OLD.owner_department_id, OLD.source_system, OLD.schema_version,
                OLD.source_digest, OLD.item_count, OLD.retention_policy_code,
                OLD.expires_at, OLD.staged_by_id, OLD.created_at
            ) OR OLD.state <> 'staged'
              OR OLD.aggregate_version <> 1
              OR NEW.state <> 'discarded'
              OR NEW.aggregate_version <> 2
              OR NEW.discarded_by_id IS NULL
              OR NEW.discarded_at IS NULL
              OR NEW.discard_reason = ''
            THEN
                RAISE EXCEPTION 'Programme-import batch mutation is not the exact discard transition'
                    USING ERRCODE = '23514';
            END IF;
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeimportitem' THEN
        SELECT organization_id, edition_id, source_system, state, aggregate_version,
               item_count
          INTO parent_row
          FROM public.applications_programmeimportbatch
         WHERE id = NEW.batch_id
         FOR UPDATE;
        IF parent_row IS NULL
           OR parent_row.organization_id <> NEW.organization_id
           OR parent_row.edition_id <> NEW.edition_id
           OR NEW.sequence NOT BETWEEN 1 AND parent_row.item_count
           OR NEW.source_key !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'
           OR NEW.source_digest !~ '^[0-9a-f]{64}$'
           OR NEW.payload_size_bytes <= 0
        THEN
            RAISE EXCEPTION 'Programme-import item scope or source evidence mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF (NEW.kind = 'call' AND (
                NEW.dependency_source_system <> ''
                OR NEW.dependency_source_key <> ''
            )) OR (NEW.kind = 'proposal' AND (
                NEW.dependency_source_system !~ '^[a-z][a-z0-9_.:-]{0,79}$'
                OR NEW.dependency_source_system <> parent_row.source_system
                OR NEW.dependency_source_key !~
                   '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'
            )) OR NEW.kind NOT IN ('call', 'proposal')
        THEN
            RAISE EXCEPTION 'Programme-import item dependency shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF TG_OP = 'INSERT' THEN
            IF parent_row.state <> 'staged'
               OR parent_row.aggregate_version <> 1
               OR NEW.state <> 'staged'
               OR NEW.aggregate_version <> 1
               OR NEW.canonical_payload IS NULL
               OR pg_catalog.octet_length(NEW.canonical_payload) <> NEW.payload_size_bytes
               OR pg_catalog.encode(
                    pg_catalog.sha256(NEW.canonical_payload), 'hex'
                  ) <> NEW.source_digest
            THEN
                RAISE EXCEPTION 'Programme-import item canonical bytes do not match retained evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF TG_OP = 'UPDATE' THEN
            IF ROW(
                NEW.id, NEW.organization_id, NEW.edition_id, NEW.batch_id,
                NEW.sequence, NEW.kind, NEW.source_key, NEW.source_digest,
                NEW.payload_size_bytes, NEW.dependency_source_system,
                NEW.dependency_source_key, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.organization_id, OLD.edition_id, OLD.batch_id,
                OLD.sequence, OLD.kind, OLD.source_key, OLD.source_digest,
                OLD.payload_size_bytes, OLD.dependency_source_system,
                OLD.dependency_source_key, OLD.created_at
            ) OR parent_row.state <> 'staged'
              OR parent_row.aggregate_version <> 1
              OR OLD.state <> 'staged'
              OR OLD.aggregate_version <> 1
              OR NEW.state NOT IN ('applied', 'discarded')
              OR NEW.aggregate_version <> 2
              OR NEW.canonical_payload IS NOT NULL
            THEN
                RAISE EXCEPTION 'Programme-import item mutation is not an exact terminal scrub'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    ELSE
        RAISE EXCEPTION 'unregistered Programme-import current table'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_programme_import_current_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

IMPORT_EVIDENCE_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_import_evidence()
RETURNS trigger AS $applications_programme_import_evidence_guard$
DECLARE
    batch_row record;
    item_row record;
    preview_row record;
    binding_row record;
    import_receipt_row record;
    programme_receipt_row record;
    target_row record;
    expected_action text;
    expected_retry_key uuid;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme-import evidence is append-only'
            USING ERRCODE = '23514';
    END IF;
    IF pg_catalog.current_setting(
        'maru.applications_programme_import_writer', true
    ) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme-import evidence requires the registered writer latch'
            USING ERRCODE = '23514';
    END IF;
    NEW.updated_at := NEW.created_at;

    IF TG_TABLE_NAME = 'applications_programmeimportpreviewrevision' THEN
        SELECT organization_id, edition_id, state, aggregate_version, item_count
          INTO batch_row
          FROM public.applications_programmeimportbatch
         WHERE id = NEW.batch_id
         FOR UPDATE;
        IF batch_row IS NULL
           OR batch_row.organization_id <> NEW.organization_id
           OR batch_row.edition_id <> NEW.edition_id
           OR batch_row.state <> 'staged'
           OR NEW.source_batch_version <> batch_row.aggregate_version
           OR NEW.source_batch_version <> 1
           OR NEW.item_count <> batch_row.item_count
           OR NEW.preview_digest !~ '^[0-9a-f]{64}$'
           OR NEW.revision_number <> COALESCE((
                SELECT pg_catalog.max(revision_number) + 1
                  FROM public.applications_programmeimportpreviewrevision
                 WHERE batch_id = NEW.batch_id
           ), 1)
        THEN
            RAISE EXCEPTION 'Programme-import preview scope, batch version, or sequence mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeimportpreviewitemresult' THEN
        SELECT batch_id, organization_id, edition_id, item_count
          INTO preview_row
          FROM public.applications_programmeimportpreviewrevision
         WHERE id = NEW.preview_id
         FOR KEY SHARE;
        SELECT batch_id, organization_id, edition_id, kind, aggregate_version
          INTO item_row
          FROM public.applications_programmeimportitem
         WHERE id = NEW.item_id
         FOR KEY SHARE;
        IF preview_row IS NULL OR item_row IS NULL
           OR preview_row.batch_id <> item_row.batch_id
           OR preview_row.organization_id <> NEW.organization_id
           OR preview_row.edition_id <> NEW.edition_id
           OR item_row.organization_id <> NEW.organization_id
           OR item_row.edition_id <> NEW.edition_id
           OR NEW.item_version <> item_row.aggregate_version
           OR NEW.result_digest !~ '^[0-9a-f]{64}$'
           OR pg_catalog.jsonb_typeof(NEW.safe_field_keys) <> 'array'
           OR pg_catalog.jsonb_typeof(NEW.reason_codes) <> 'array'
           OR EXISTS (
                SELECT 1 FROM pg_catalog.jsonb_array_elements(NEW.safe_field_keys) AS value
                 WHERE pg_catalog.jsonb_typeof(value) <> 'string'
           ) OR EXISTS (
                SELECT 1 FROM pg_catalog.jsonb_array_elements(NEW.reason_codes) AS value
                 WHERE pg_catalog.jsonb_typeof(value) <> 'string'
           )
           OR NEW.safe_field_keys <> COALESCE((
                SELECT pg_catalog.jsonb_agg(
                           allowed.key ORDER BY allowed.ordinal
                       )
                  FROM pg_catalog.unnest(ARRAY[
                           'configuration',
                           'definition',
                           'answers',
                           'lead_action_required',
                           'selection'
                       ]::text[]) WITH ORDINALITY AS allowed(key, ordinal)
                 WHERE NEW.safe_field_keys ? allowed.key
           ), '[]'::jsonb)
           OR NEW.reason_codes <> COALESCE((
                SELECT pg_catalog.jsonb_agg(
                           allowed.code ORDER BY allowed.ordinal
                       )
                  FROM pg_catalog.unnest(ARRAY[
                           'source_already_applied',
                           'source_digest_conflict',
                           'definition_code_conflict',
                           'call_dependency_unavailable',
                           'call_dependency_not_active',
                           'proposal_mapping_invalid'
                       ]::text[]) WITH ORDINALITY AS allowed(code, ordinal)
                 WHERE NEW.reason_codes ? allowed.code
           ), '[]'::jsonb)
        THEN
            RAISE EXCEPTION 'Programme-import preview item scope or sanitized shape mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF (NEW.dependency_state IN ('none', 'missing') AND (
                NEW.dependency_digest <> '' OR NEW.dependency_version IS NOT NULL
            )) OR (NEW.dependency_state IN ('draft', 'active', 'retired') AND (
                NEW.dependency_digest !~ '^[0-9a-f]{64}$'
                OR NEW.dependency_version IS NULL
                OR NEW.dependency_version <= 0
            )) OR NEW.dependency_state NOT IN (
                'none', 'missing', 'draft', 'active', 'retired'
            )
        THEN
            RAISE EXCEPTION 'Programme-import dependency evidence shape is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF (NEW.status = 'ready' AND (
                (item_row.kind = 'call'
                 AND (NEW.action <> 'commit_call' OR NEW.dependency_state <> 'none'))
                OR (item_row.kind = 'proposal'
                    AND (NEW.action <> 'claim_proposal'
                         OR NEW.dependency_state <> 'active'))
            )) OR (NEW.status <> 'ready' AND NEW.action <> 'none')
               OR NEW.status NOT IN ('ready', 'blocked', 'no_op', 'conflict')
        THEN
            RAISE EXCEPTION 'Programme-import preview status and action mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeimportsourcebinding' THEN
        SELECT item.batch_id, item.organization_id, item.edition_id, item.kind,
               item.source_key, item.source_digest, item.state,
               item.dependency_source_system, item.dependency_source_key,
               batch.source_system, batch.owner_department_id
          INTO item_row
          FROM public.applications_programmeimportitem AS item
          JOIN public.applications_programmeimportbatch AS batch
            ON batch.id = item.batch_id
         WHERE item.id = NEW.item_id
         FOR KEY SHARE OF item, batch;
        IF item_row IS NULL
           OR item_row.organization_id <> NEW.organization_id
           OR item_row.edition_id <> NEW.edition_id
           OR item_row.kind <> NEW.kind
           OR item_row.source_system <> NEW.source_system
           OR item_row.source_key <> NEW.source_key
           OR item_row.source_digest <> NEW.source_digest
           OR item_row.state <> 'applied'
           OR NEW.source_key !~ '^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$'
        THEN
            RAISE EXCEPTION 'Programme-import source binding does not match its applied item'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'call' THEN
            SELECT organization_id, edition_id, owner_department_id,
                   definition_id, NULL::uuid AS proposal_call_id,
                   NULL::uuid AS submission_definition_id,
                   NULL::uuid AS call_definition_id
              INTO target_row
              FROM public.applications_programmecall
             WHERE id = NEW.call_id
             FOR KEY SHARE;
            IF NEW.call_id IS NULL OR NEW.proposal_id IS NOT NULL THEN
                RAISE EXCEPTION 'Programme-import call binding target shape is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.kind = 'proposal' THEN
            SELECT proposal.organization_id, proposal.edition_id,
                   NULL::uuid AS owner_department_id,
                   call_row.definition_id AS definition_id,
                   proposal.call_id AS proposal_call_id,
                   submission.definition_id AS submission_definition_id,
                   call_row.definition_id AS call_definition_id
              INTO target_row
              FROM public.applications_programmeproposal AS proposal
              JOIN public.applications_applicationsubmission AS submission
                ON submission.id = proposal.submission_id
              JOIN public.applications_programmecall AS call_row
                ON call_row.id = proposal.call_id
             WHERE proposal.id = NEW.proposal_id
             FOR KEY SHARE OF proposal, submission, call_row;
            IF NEW.call_id IS NOT NULL OR NEW.proposal_id IS NULL THEN
                RAISE EXCEPTION 'Programme-import proposal binding target shape is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            RAISE EXCEPTION 'Programme-import source binding kind is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF target_row IS NULL
           OR target_row.organization_id <> NEW.organization_id
           OR target_row.edition_id <> NEW.edition_id
        THEN
            RAISE EXCEPTION 'Programme-import source binding target scope mismatch'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'call' AND (
            target_row.owner_department_id <> item_row.owner_department_id
        ) THEN
            RAISE EXCEPTION 'Programme-import call binding owner mismatch'
                USING ERRCODE = '23514';
        ELSIF NEW.kind = 'proposal' AND (
            target_row.submission_definition_id <> target_row.call_definition_id
            OR target_row.proposal_call_id IS DISTINCT FROM (
                SELECT dependency_binding.call_id
                  FROM public.applications_programmeimportsourcebinding
                       AS dependency_binding
                 WHERE dependency_binding.organization_id = NEW.organization_id
                   AND dependency_binding.edition_id = NEW.edition_id
                   AND dependency_binding.source_system =
                       item_row.dependency_source_system
                   AND dependency_binding.kind = 'call'
                   AND dependency_binding.source_key = item_row.dependency_source_key
            )
        ) THEN
            RAISE EXCEPTION 'Programme-import proposal binding dependency mismatch'
                USING ERRCODE = '23514';
        END IF;

    ELSIF TG_TABLE_NAME = 'applications_programmeimportappliedcommand' THEN
        SELECT binding.organization_id, binding.edition_id, binding.kind,
               binding.call_id, binding.proposal_id, binding.item_id
          INTO binding_row
          FROM public.applications_programmeimportsourcebinding AS binding
         WHERE binding.id = NEW.binding_id
         FOR KEY SHARE;
        SELECT receipt.organization_id, receipt.edition_id, receipt.actor_id,
               receipt.action, receipt.retry_key, receipt.correlation_id,
               receipt.reason,
               receipt.source_binding_id, receipt.item_id,
               receipt.applied_command_count
          INTO import_receipt_row
          FROM public.applications_programmeimportcommandreceipt AS receipt
         WHERE receipt.id = NEW.import_receipt_id
         FOR KEY SHARE;
        SELECT receipt.organization_id, receipt.edition_id, receipt.actor_id,
               receipt.action, receipt.retry_key, receipt.correlation_id,
               receipt.reason,
               receipt.definition_id, receipt.submission_id, receipt.target_id,
               receipt.result_kind, receipt.expected_version,
               receipt.resulting_version
          INTO programme_receipt_row
          FROM public.applications_programmecommandreceipt AS receipt
         WHERE receipt.id = NEW.programme_receipt_id
         FOR KEY SHARE;
        IF binding_row IS NULL OR import_receipt_row IS NULL
           OR programme_receipt_row IS NULL
           OR NEW.sequence <= 0
           OR binding_row.organization_id <> NEW.organization_id
           OR binding_row.edition_id <> NEW.edition_id
           OR import_receipt_row.organization_id <> NEW.organization_id
           OR import_receipt_row.edition_id <> NEW.edition_id
           OR programme_receipt_row.organization_id <> NEW.organization_id
           OR programme_receipt_row.edition_id <> NEW.edition_id
           OR import_receipt_row.source_binding_id <> NEW.binding_id
           OR import_receipt_row.item_id <> binding_row.item_id
           OR programme_receipt_row.actor_id <> import_receipt_row.actor_id
           OR programme_receipt_row.correlation_id <> import_receipt_row.correlation_id
           OR programme_receipt_row.reason <> import_receipt_row.reason
           OR NEW.sequence > import_receipt_row.applied_command_count
           OR programme_receipt_row.expected_version <> NEW.sequence - 1
           OR programme_receipt_row.resulting_version <> NEW.sequence
        THEN
            RAISE EXCEPTION 'Programme-import nested command scope, actor, correlation, or version mismatch'
                USING ERRCODE = '23514';
        END IF;
        expected_action := CASE
            WHEN binding_row.kind = 'call' THEN 'call_created'
            WHEN NEW.sequence = 1 THEN 'proposal_started'
            ELSE 'proposal_answer_revised'
        END;
        expected_retry_key := pg_catalog.md5(
            'maru:applications:programme-import:nested:v1:'
            || pg_catalog.lower(import_receipt_row.retry_key::text) || ':'
            || pg_catalog.lower(binding_row.item_id::text) || ':'
            || NEW.sequence::text || ':' || expected_action
        )::uuid;
        IF programme_receipt_row.action <> expected_action
           OR programme_receipt_row.retry_key <> expected_retry_key
           OR (binding_row.kind = 'call' AND (
                NEW.sequence <> 1
                OR import_receipt_row.action <> 'call_committed'
                OR programme_receipt_row.submission_id IS NOT NULL
                OR programme_receipt_row.result_kind <> 'call'
                OR programme_receipt_row.target_id <> binding_row.call_id
                OR programme_receipt_row.definition_id <> (
                    SELECT definition_id
                      FROM public.applications_programmecall
                     WHERE id = binding_row.call_id
                )
           )) OR (binding_row.kind = 'proposal' AND (
                import_receipt_row.action <> 'proposal_claimed'
                OR programme_receipt_row.submission_id <> (
                    SELECT submission_id
                      FROM public.applications_programmeproposal
                     WHERE id = binding_row.proposal_id
                )
                OR (NEW.sequence = 1 AND (
                    programme_receipt_row.result_kind <> 'proposal'
                    OR programme_receipt_row.target_id <> binding_row.proposal_id
                ))
                OR (NEW.sequence > 1 AND (
                    programme_receipt_row.result_kind <> 'answer_revision'
                    OR programme_receipt_row.definition_id <> (
                        SELECT call_row.definition_id
                          FROM public.applications_programmeproposal AS proposal
                          JOIN public.applications_programmecall AS call_row
                            ON call_row.id = proposal.call_id
                         WHERE proposal.id = binding_row.proposal_id
                    )
                    OR NOT EXISTS (
                        SELECT 1
                          FROM public.applications_applicationanswerrevision AS answer
                          JOIN public.applications_programmeproposal AS proposal
                            ON proposal.submission_id = answer.submission_id
                          JOIN public.applications_applicationquestion AS question
                            ON question.id = answer.question_id
                          JOIN public.applications_applicationsection AS section
                            ON section.id = question.section_id
                          JOIN public.applications_programmecall AS call_row
                            ON call_row.id = proposal.call_id
                         WHERE answer.id = programme_receipt_row.target_id
                           AND proposal.id = binding_row.proposal_id
                           AND section.definition_id = call_row.definition_id
                    )
                    OR (NEW.sequence > 2 AND NOT EXISTS (
                        SELECT 1
                          FROM public.applications_programmeimportappliedcommand
                               AS previous_link
                          JOIN public.applications_programmecommandreceipt
                               AS previous_receipt
                            ON previous_receipt.id =
                               previous_link.programme_receipt_id
                          JOIN public.applications_applicationanswerrevision
                               AS previous_answer
                            ON previous_answer.id = previous_receipt.target_id
                          JOIN public.applications_applicationquestion
                               AS previous_question
                            ON previous_question.id = previous_answer.question_id
                          JOIN public.applications_applicationsection
                               AS previous_section
                            ON previous_section.id = previous_question.section_id
                          JOIN public.applications_applicationanswerrevision
                               AS current_answer
                            ON current_answer.id = programme_receipt_row.target_id
                          JOIN public.applications_applicationquestion
                               AS current_question
                            ON current_question.id = current_answer.question_id
                          JOIN public.applications_applicationsection
                               AS current_section
                            ON current_section.id = current_question.section_id
                         WHERE previous_link.import_receipt_id =
                               NEW.import_receipt_id
                           AND previous_link.sequence = NEW.sequence - 1
                           AND ROW(
                               previous_section.position,
                               previous_question.position,
                               previous_question.id
                           ) < ROW(
                               current_section.position,
                               current_question.position,
                               current_question.id
                           )
                    ))
                ))
           ))
        THEN
            RAISE EXCEPTION 'Programme-import nested receipt topology or retry derivation mismatch'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'unregistered Programme-import evidence table'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_programme_import_evidence_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

IMPORT_RECEIPT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_import_receipt()
RETURNS trigger AS $applications_programme_import_receipt_guard$
DECLARE
    retry_namespace text;
    batch_row record;
    item_row record;
    preview_row record;
    result_row record;
    binding_row record;
    actor_row record;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme-import command receipts are append-only'
            USING ERRCODE = '23514';
    END IF;
    IF pg_catalog.current_setting(
        'maru.applications_programme_import_writer', true
    ) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme-import receipts require the registered writer latch'
            USING ERRCODE = '23514';
    END IF;
    NEW.updated_at := NEW.created_at;
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
    ) OR EXISTS (
        SELECT 1 FROM public.applications_programmecommandreceipt
         WHERE edition_id = NEW.edition_id
           AND actor_id = NEW.actor_id
           AND retry_key = NEW.retry_key
    ) THEN
        RAISE EXCEPTION 'Applications retry key is already retained by another Applications command family'
            USING ERRCODE = '23505';
    END IF;
    SELECT account_kind, is_active, email_verified_at INTO actor_row
      FROM public.identity_account
     WHERE id = NEW.actor_id
     FOR KEY SHARE;
    SELECT organization_id, edition_id, state, aggregate_version, source_digest,
           staged_by_id, discarded_by_id, discard_reason
      INTO batch_row
      FROM public.applications_programmeimportbatch
     WHERE id = NEW.batch_id
     FOR KEY SHARE;
    IF actor_row.account_kind IS DISTINCT FROM 'person'
       OR actor_row.is_active IS DISTINCT FROM TRUE
       OR actor_row.email_verified_at IS NULL
       OR batch_row IS NULL
       OR batch_row.organization_id <> NEW.organization_id
       OR batch_row.edition_id <> NEW.edition_id
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.reason = ''
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]*$'
       OR NEW.resulting_version <> NEW.expected_version + 1
    THEN
        RAISE EXCEPTION 'Programme-import receipt actor, scope, digest, or version mismatch'
            USING ERRCODE = '23514';
    END IF;
    SELECT batch_id, organization_id, edition_id, kind, state,
           aggregate_version, source_digest
      INTO item_row
      FROM public.applications_programmeimportitem
     WHERE id = NEW.item_id
     FOR KEY SHARE;
    SELECT batch_id, organization_id, edition_id, preview_digest,
           revision_number, actor_id
      INTO preview_row
      FROM public.applications_programmeimportpreviewrevision
     WHERE id = NEW.preview_revision_id
     FOR KEY SHARE;
    SELECT preview_id, item_id, organization_id, edition_id, status, action,
           result_digest
      INTO result_row
      FROM public.applications_programmeimportpreviewitemresult
     WHERE id = NEW.preview_item_result_id
     FOR KEY SHARE;
    SELECT item_id, organization_id, edition_id, kind, source_digest,
           created_by_id
      INTO binding_row
      FROM public.applications_programmeimportsourcebinding
     WHERE id = NEW.source_binding_id
     FOR KEY SHARE;

    IF NEW.action = 'batch_staged' THEN
        IF NEW.aggregate_kind <> 'batch'
           OR NEW.item_id IS NOT NULL
           OR NEW.preview_revision_id IS NOT NULL
           OR NEW.preview_item_result_id IS NOT NULL
           OR NEW.source_binding_id IS NOT NULL
           OR NEW.adopted_preview_digest <> ''
           OR NEW.applied_command_count <> 0
           OR NEW.result_kind <> 'batch'
           OR NEW.expected_version <> 0 OR NEW.resulting_version <> 1
           OR batch_row.state <> 'staged' OR batch_row.aggregate_version <> 1
           OR NEW.actor_id <> batch_row.staged_by_id
        THEN
            RAISE EXCEPTION 'Programme-import batch-staged receipt shape is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.action = 'batch_previewed' THEN
        IF NEW.aggregate_kind <> 'preview'
           OR NEW.item_id IS NOT NULL
           OR preview_row IS NULL OR preview_row.batch_id <> NEW.batch_id
           OR preview_row.organization_id <> NEW.organization_id
           OR preview_row.edition_id <> NEW.edition_id
           OR NEW.preview_item_result_id IS NOT NULL
           OR NEW.source_binding_id IS NOT NULL
           OR NEW.adopted_preview_digest <> ''
           OR NEW.applied_command_count <> 0
           OR NEW.result_kind <> 'preview'
           OR NEW.expected_version <> preview_row.revision_number - 1
           OR NEW.resulting_version <> preview_row.revision_number
           OR NEW.actor_id <> preview_row.actor_id
        THEN
            RAISE EXCEPTION 'Programme-import preview receipt shape is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.action IN ('call_committed', 'proposal_claimed') THEN
        IF NEW.aggregate_kind <> 'item'
           OR item_row IS NULL OR item_row.batch_id <> NEW.batch_id
           OR item_row.organization_id <> NEW.organization_id
           OR item_row.edition_id <> NEW.edition_id
           OR item_row.state <> 'applied'
           OR item_row.aggregate_version <> 2
           OR binding_row IS NULL OR binding_row.item_id <> NEW.item_id
           OR binding_row.organization_id <> NEW.organization_id
           OR binding_row.edition_id <> NEW.edition_id
           OR binding_row.source_digest <> item_row.source_digest
           OR NEW.actor_id <> binding_row.created_by_id
           OR NEW.expected_version <> 1 OR NEW.resulting_version <> 2
           OR (item_row.kind = 'call' AND (
                NEW.action <> 'call_committed'
                OR NEW.applied_command_count <> 1
                OR preview_row IS NULL OR preview_row.batch_id <> NEW.batch_id
                OR result_row IS NULL
                OR result_row.preview_id <> NEW.preview_revision_id
                OR result_row.item_id <> NEW.item_id
                OR result_row.status <> 'ready'
                OR result_row.action <> 'commit_call'
                OR binding_row.kind <> 'call'
                OR NEW.adopted_preview_digest <> result_row.result_digest
                OR NEW.result_kind <> 'call_binding'
           )) OR (item_row.kind = 'proposal' AND (
                NEW.action <> 'proposal_claimed'
                OR NEW.applied_command_count NOT BETWEEN 1 AND 1001
                OR NEW.preview_revision_id IS NOT NULL
                OR NEW.preview_item_result_id IS NOT NULL
                OR binding_row.kind <> 'proposal'
                OR NEW.adopted_preview_digest !~ '^[0-9a-f]{64}$'
                OR NEW.result_kind <> 'proposal_binding'
           ))
        THEN
            RAISE EXCEPTION 'Programme-import commit receipt does not adopt one exact ready preview result'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.action = 'batch_discarded' THEN
        IF NEW.aggregate_kind <> 'batch'
           OR NEW.item_id IS NOT NULL
           OR NEW.preview_revision_id IS NOT NULL
           OR NEW.preview_item_result_id IS NOT NULL
           OR NEW.source_binding_id IS NOT NULL
           OR NEW.adopted_preview_digest <> ''
           OR NEW.applied_command_count <> 0
           OR NEW.result_kind <> 'discard'
           OR NEW.expected_version <> 1 OR NEW.resulting_version <> 2
           OR NEW.reason = ''
           OR batch_row.state <> 'discarded' OR batch_row.aggregate_version <> 2
           OR NEW.actor_id <> batch_row.discarded_by_id
           OR NEW.reason <> batch_row.discard_reason
        THEN
            RAISE EXCEPTION 'Programme-import discard receipt shape is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'Programme-import command action is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$applications_programme_import_receipt_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

IMPORT_CONTRACT_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_validate_programme_import_contract()
RETURNS trigger AS $applications_programme_import_contract_guard$
DECLARE
    batch_id_value uuid;
    batch_row record;
    item_total integer;
    preview_total integer;
    target_version bigint;
BEGIN
    IF TG_TABLE_NAME = 'applications_programmeimportbatch' THEN
        batch_id_value := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
    ELSIF TG_TABLE_NAME = 'applications_programmeimportitem' THEN
        batch_id_value := CASE WHEN TG_OP = 'DELETE' THEN OLD.batch_id ELSE NEW.batch_id END;
    ELSIF TG_TABLE_NAME = 'applications_programmeimportpreviewrevision' THEN
        batch_id_value := CASE WHEN TG_OP = 'DELETE' THEN OLD.batch_id ELSE NEW.batch_id END;
    ELSIF TG_TABLE_NAME = 'applications_programmeimportpreviewitemresult' THEN
        SELECT batch_id INTO batch_id_value
          FROM public.applications_programmeimportpreviewrevision
         WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.preview_id ELSE NEW.preview_id END;
    ELSIF TG_TABLE_NAME = 'applications_programmeimportsourcebinding' THEN
        SELECT batch_id INTO batch_id_value
          FROM public.applications_programmeimportitem
         WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.item_id ELSE NEW.item_id END;
    ELSIF TG_TABLE_NAME = 'applications_programmeimportcommandreceipt' THEN
        batch_id_value := CASE WHEN TG_OP = 'DELETE' THEN OLD.batch_id ELSE NEW.batch_id END;
    ELSIF TG_TABLE_NAME = 'applications_programmeimportappliedcommand' THEN
        SELECT batch_id INTO batch_id_value
          FROM public.applications_programmeimportcommandreceipt
         WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.import_receipt_id ELSE NEW.import_receipt_id END;
    ELSE
        RAISE EXCEPTION 'unregistered Programme-import contract table'
            USING ERRCODE = '23514';
    END IF;
    IF batch_id_value IS NULL THEN RETURN NULL; END IF;
    SELECT organization_id, edition_id, item_count, state, aggregate_version
      INTO batch_row
      FROM public.applications_programmeimportbatch
     WHERE id = batch_id_value
     FOR KEY SHARE;
    IF batch_row IS NULL THEN RETURN NULL; END IF;
    SELECT pg_catalog.count(*), COALESCE(pg_catalog.max(sequence), 0)
      INTO item_total, preview_total
      FROM public.applications_programmeimportitem
     WHERE batch_id = batch_id_value;
    IF item_total <> batch_row.item_count
       OR preview_total <> batch_row.item_count
       OR EXISTS (
            SELECT 1
              FROM pg_catalog.generate_series(1, batch_row.item_count) AS expected(sequence)
             WHERE NOT EXISTS (
                 SELECT 1 FROM public.applications_programmeimportitem AS item
                  WHERE item.batch_id = batch_id_value
                    AND item.sequence = expected.sequence
             )
       )
    THEN
        RAISE EXCEPTION 'Programme-import batch item count or contiguous order mismatch'
            USING ERRCODE = '23514';
    END IF;
    SELECT pg_catalog.count(*), COALESCE(pg_catalog.max(revision_number), 0)
      INTO item_total, preview_total
      FROM public.applications_programmeimportpreviewrevision
     WHERE batch_id = batch_id_value;
    IF item_total <> preview_total
       OR EXISTS (
            SELECT 1
              FROM public.applications_programmeimportpreviewrevision AS preview
             WHERE preview.batch_id = batch_id_value
               AND (
                   preview.organization_id <> batch_row.organization_id
                   OR preview.edition_id <> batch_row.edition_id
                   OR preview.item_count <> batch_row.item_count
                   OR preview.source_batch_version <> 1
                   OR (
                       SELECT pg_catalog.count(*)
                         FROM public.applications_programmeimportpreviewitemresult AS result
                        WHERE result.preview_id = preview.id
                   ) <> batch_row.item_count
                   OR EXISTS (
                       SELECT 1
                         FROM public.applications_programmeimportitem AS item
                        WHERE item.batch_id = batch_id_value
                          AND NOT EXISTS (
                              SELECT 1
                                FROM public.applications_programmeimportpreviewitemresult AS result
                               WHERE result.preview_id = preview.id
                                 AND result.item_id = item.id
                          )
                   )
               )
       )
    THEN
        RAISE EXCEPTION 'Programme-import preview revisions or result coverage are not exact'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.applications_programmeimportcommandreceipt
         WHERE batch_id = batch_id_value AND action = 'batch_staged'
    ) OR EXISTS (
        SELECT 1
          FROM public.applications_programmeimportpreviewrevision AS preview
         WHERE preview.batch_id = batch_id_value
           AND NOT EXISTS (
               SELECT 1 FROM public.applications_programmeimportcommandreceipt AS receipt
                WHERE receipt.preview_revision_id = preview.id
                  AND receipt.action = 'batch_previewed'
           )
    ) THEN
        RAISE EXCEPTION 'Programme-import batch or preview receipt evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;
    IF batch_row.state = 'discarded' AND (
        EXISTS (
            SELECT 1 FROM public.applications_programmeimportitem
             WHERE batch_id = batch_id_value
               AND (
                   state NOT IN ('applied', 'discarded')
                   OR canonical_payload IS NOT NULL
               )
        ) OR NOT EXISTS (
            SELECT 1 FROM public.applications_programmeimportcommandreceipt
             WHERE batch_id = batch_id_value AND action = 'batch_discarded'
        )
    ) THEN
        RAISE EXCEPTION 'Discarded Programme-import batches require exact item scrubs and receipt evidence'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.applications_programmeimportitem AS discarded_item
         WHERE discarded_item.batch_id = batch_id_value
           AND discarded_item.state = 'discarded'
    ) AND (
        batch_row.state <> 'discarded'
        OR NOT EXISTS (
            SELECT 1
              FROM public.applications_programmeimportcommandreceipt AS receipt
             WHERE receipt.batch_id = batch_id_value
               AND receipt.action = 'batch_discarded'
        )
    ) THEN
        RAISE EXCEPTION 'Discarded Programme-import items require batch receipt evidence'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.applications_programmeimportitem AS item
         WHERE item.batch_id = batch_id_value
           AND (
               (item.state = 'applied' AND (
                    (SELECT pg_catalog.count(*)
                       FROM public.applications_programmeimportsourcebinding AS binding
                      WHERE binding.item_id = item.id) <> 1
                    OR NOT EXISTS (
                        SELECT 1
                          FROM public.applications_programmeimportcommandreceipt AS receipt
                         WHERE receipt.item_id = item.id
                           AND receipt.action IN ('call_committed', 'proposal_claimed')
                    )
               )) OR (item.state <> 'applied' AND EXISTS (
                    SELECT 1 FROM public.applications_programmeimportsourcebinding AS binding
                     WHERE binding.item_id = item.id
               ))
           )
    ) THEN
        RAISE EXCEPTION 'Programme-import item terminal state and binding evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM public.applications_programmeimportsourcebinding AS binding
          JOIN public.applications_programmeimportcommandreceipt AS receipt
            ON receipt.source_binding_id = binding.id
         WHERE receipt.batch_id = batch_id_value
           AND (
               NOT EXISTS (
                   SELECT 1 FROM public.applications_programmeimportappliedcommand AS applied
                    WHERE applied.import_receipt_id = receipt.id
               )
               OR (
                   SELECT pg_catalog.count(*)
                     FROM public.applications_programmeimportappliedcommand AS applied
                    WHERE applied.import_receipt_id = receipt.id
               ) <> receipt.applied_command_count
               OR (
                   SELECT COALESCE(pg_catalog.max(sequence), 0)
                     FROM public.applications_programmeimportappliedcommand AS applied
                    WHERE applied.import_receipt_id = receipt.id
               ) <> receipt.applied_command_count
           )
    ) THEN
        RAISE EXCEPTION 'Programme-import nested command evidence is missing or non-contiguous'
            USING ERRCODE = '23514';
    END IF;
    IF TG_TABLE_NAME = 'applications_programmeimportappliedcommand'
       AND TG_OP = 'INSERT'
    THEN
        SELECT receipt.applied_command_count
          INTO target_version
          FROM public.applications_programmeimportcommandreceipt AS receipt
         WHERE receipt.id = NEW.import_receipt_id
           AND receipt.source_binding_id = NEW.binding_id;
        SELECT pg_catalog.count(*), COALESCE(pg_catalog.max(sequence), 0)
          INTO item_total, preview_total
          FROM public.applications_programmeimportappliedcommand
         WHERE import_receipt_id = NEW.import_receipt_id;
        IF target_version IS NULL
           OR target_version <= 0
           OR item_total <> target_version
           OR preview_total <> target_version
        THEN
            RAISE EXCEPTION 'Programme-import nested command links do not cover the sealed imported command count'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NULL;
END;
$applications_programme_import_contract_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

IMPORT_TRUNCATE_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_refuse_programme_import_truncate()
RETURNS trigger AS $applications_programme_import_truncate_guard$
BEGIN
    IF pg_catalog.current_database() LIKE 'test\_%' ESCAPE '\'
       AND pg_catalog.current_setting(
           'maru.authority_provenance_test_reset', true
       ) = 'on'
    THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Programme-import relations cannot be truncated'
        USING ERRCODE = '23514';
END;
$applications_programme_import_truncate_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

_CURRENT_TABLES = (
    ("batch", "applications_programmeimportbatch"),
    ("item", "applications_programmeimportitem"),
)
_EVIDENCE_TABLES = (
    ("preview", "applications_programmeimportpreviewrevision"),
    ("result", "applications_programmeimportpreviewitemresult"),
    ("binding", "applications_programmeimportsourcebinding"),
    ("applied", "applications_programmeimportappliedcommand"),
)
_RECEIPT_TABLE = ("receipt", "applications_programmeimportcommandreceipt")
_IMPORT_TABLES = (*_CURRENT_TABLES, *_EVIDENCE_TABLES, _RECEIPT_TABLE)
_FUNCTION_IDENTITIES = (
    "maru_applications_guard_programme_import_current",
    "maru_applications_guard_programme_import_evidence",
    "maru_applications_guard_programme_import_receipt",
    "maru_applications_validate_programme_import_contract",
    "maru_applications_refuse_programme_import_truncate",
)


def _trigger_sql() -> str:
    statements = []
    statements.extend(
        f"""CREATE TRIGGER applications_prg_imp_{suffix}_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_programme_import_current();"""
        for suffix, table in _CURRENT_TABLES
    )
    statements.extend(
        f"""CREATE TRIGGER applications_prg_imp_{suffix}_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_programme_import_evidence();"""
        for suffix, table in _EVIDENCE_TABLES
    )
    statements.append(
        f"""CREATE TRIGGER applications_prg_imp_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.{_RECEIPT_TABLE[1]}
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_programme_import_receipt();"""
    )
    statements.extend(
        f"""CREATE CONSTRAINT TRIGGER applications_prg_imp_{suffix}_contract
AFTER INSERT OR UPDATE OR DELETE ON public.{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_validate_programme_import_contract();"""
        for suffix, table in _IMPORT_TABLES
    )
    statements.extend(
        f"""CREATE TRIGGER applications_prg_imp_{suffix}_truncate
BEFORE TRUNCATE ON public.{table}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_applications_refuse_programme_import_truncate();"""
        for suffix, table in _IMPORT_TABLES
    )
    return "\n".join(statements)


def _revoke_sql() -> str:
    return "\n".join(
        f"REVOKE ALL ON FUNCTION public.{identity}() FROM PUBLIC;"
        for identity in _FUNCTION_IDENTITIES
    )


FORWARD_SQL = "\n\n".join(
    (
        _previous._drop_trigger_sql(),  # noqa: SLF001
        _previous._drop_function_sql(),  # noqa: SLF001
        PROGRAMME_INTEGRITY_FORWARD_SQL_V2.strip(),
        IMPORT_CURRENT_FUNCTION_SQL.strip(),
        IMPORT_EVIDENCE_FUNCTION_SQL.strip(),
        IMPORT_RECEIPT_FUNCTION_SQL.strip(),
        IMPORT_CONTRACT_FUNCTION_SQL.strip(),
        IMPORT_TRUNCATE_FUNCTION_SQL.strip(),
        _trigger_sql(),
        _revoke_sql(),
    )
)


def _drop_sql() -> str:
    statements = [
        f"DROP TRIGGER IF EXISTS applications_prg_imp_{suffix}_contract ON public.{table};"
        for suffix, table in reversed(_IMPORT_TABLES)
    ]
    statements.extend(
        f"DROP TRIGGER IF EXISTS applications_prg_imp_{suffix}_truncate ON public.{table};"
        for suffix, table in reversed(_IMPORT_TABLES)
    )
    statements.extend(
        f"DROP TRIGGER IF EXISTS applications_prg_imp_{suffix}_guard ON public.{table};"
        for suffix, table in reversed(_IMPORT_TABLES)
    )
    statements.extend(
        f"DROP FUNCTION IF EXISTS public.{identity}();"
        for identity in reversed(_FUNCTION_IDENTITIES)
    )
    return "\n".join(statements)


REVERSE_SQL = "\n\n".join(
    (
        _drop_sql(),
        _previous.REVERSE_SQL.strip(),
        _previous.FORWARD_SQL.strip(),
    )
)


class Migration(migrations.Migration):
    """Install import guards after schema and exact capability authority."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0007_programme_import_persistence"),
        ("authorization", "0022_programme_import_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
