"""Install race-safe Programme Department ownership integrity."""

# ruff: noqa: E501, FLY002 -- SQL contract text stays exact and reviewable.

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.applications.migrations.0008_programme_import_integrity_guards"
)
_programme = importlib.import_module(
    "maru.applications.migrations.0005_programme_integrity_guards"
)


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    """Return one exact SQL replacement or refuse an unknown predecessor."""
    if source.count(old) != 1:
        raise RuntimeError(f"Unrecognized Programme integrity SQL for {label}.")
    return source.replace(old, new)


_PROGRAMME_ALLOWED_ACTIONS = """                'call_created', 'call_configured', 'call_activated',
                'call_retired', 'call_successor_created'"""
_PROGRAMME_ALLOWED_ACTIONS_V2 = """                'call_created', 'call_configured', 'call_reassigned',
                'call_activated', 'call_retired', 'recovery_call_reassigned',
                'recovery_call_retired', 'call_successor_created'"""

PROGRAMME_RECEIPT_FUNCTION_SQL = _replace_once(
    _previous.PROGRAMME_RECEIPT_FUNCTION_SQL,
    _PROGRAMME_ALLOWED_ACTIONS,
    _PROGRAMME_ALLOWED_ACTIONS_V2,
    label="call receipt action catalog",
)

_PROGRAMME_SCOPE_END = """        RAISE EXCEPTION 'Programme command receipt scope, digest, or version mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_kind = 'call' THEN"""
_PROGRAMME_SCOPE_END_V2 = """        RAISE EXCEPTION 'Programme command receipt scope, digest, or version mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.action IN ('call_reassigned', 'recovery_call_reassigned') THEN
        IF NEW.source_department_id IS NULL
           OR NEW.destination_department_id IS NULL
           OR NEW.source_department_id = NEW.destination_department_id
           OR NOT EXISTS (
                SELECT 1 FROM public.workforce_department AS source_department
                 WHERE source_department.id = NEW.source_department_id
                   AND source_department.organization_id = NEW.organization_id
                   AND source_department.edition_id = NEW.edition_id
                   AND (
                       (NEW.action = 'call_reassigned'
                        AND source_department.retired_at IS NULL)
                       OR (NEW.action = 'recovery_call_reassigned'
                           AND source_department.retired_at IS NOT NULL)
                   )
           )
           OR NOT EXISTS (
                SELECT 1 FROM public.workforce_department AS destination_department
                 WHERE destination_department.id = NEW.destination_department_id
                   AND destination_department.organization_id = NEW.organization_id
                   AND destination_department.edition_id = NEW.edition_id
                   AND destination_department.retired_at IS NULL
           )
        THEN
            RAISE EXCEPTION 'Programme call Department transition evidence is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.action = 'recovery_call_retired' THEN
        IF NEW.source_department_id IS NULL
           OR NEW.destination_department_id IS NOT NULL
           OR NOT EXISTS (
                SELECT 1 FROM public.workforce_department AS source_department
                 WHERE source_department.id = NEW.source_department_id
                   AND source_department.organization_id = NEW.organization_id
                   AND source_department.edition_id = NEW.edition_id
                   AND source_department.retired_at IS NOT NULL
           )
        THEN
            RAISE EXCEPTION 'Programme call recovery-retirement evidence is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.source_department_id IS NOT NULL
          OR NEW.destination_department_id IS NOT NULL
    THEN
        RAISE EXCEPTION 'Ordinary Programme receipts cannot retain Department transitions'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_kind = 'call' THEN"""
PROGRAMME_RECEIPT_FUNCTION_SQL = _replace_once(
    PROGRAMME_RECEIPT_FUNCTION_SQL,
    _PROGRAMME_SCOPE_END,
    _PROGRAMME_SCOPE_END_V2,
    label="call Department receipt evidence",
)

_PROGRAMME_LIFECYCLE_BRANCH = """        ELSIF NEW.action IN ('call_activated', 'call_retired') THEN
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
        ELSIF NEW.action = 'call_configured' THEN"""
_PROGRAMME_LIFECYCLE_BRANCH_V2 = """        ELSIF NEW.action IN ('call_activated', 'call_retired') THEN
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
        ELSIF NEW.action IN ('call_reassigned', 'recovery_call_reassigned') THEN
            IF definition_row.status <> 'draft'
               OR NEW.result_kind <> 'call'
               OR NOT EXISTS (
                    SELECT 1 FROM public.applications_programmecall
                     WHERE id = NEW.target_id
                       AND definition_id = NEW.definition_id
                       AND owner_department_id = NEW.destination_department_id
               )
            THEN
                RAISE EXCEPTION 'Programme call reassignment receipt target is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.action = 'recovery_call_retired' THEN
            IF definition_row.status <> 'retired'
               OR NEW.result_kind <> 'call'
               OR NOT EXISTS (
                    SELECT 1 FROM public.applications_programmecall
                     WHERE id = NEW.target_id
                       AND definition_id = NEW.definition_id
                       AND owner_department_id = NEW.source_department_id
               )
            THEN
                RAISE EXCEPTION 'Programme call recovery-retirement target is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.action = 'call_configured' THEN"""
PROGRAMME_RECEIPT_FUNCTION_SQL = _replace_once(
    PROGRAMME_RECEIPT_FUNCTION_SQL,
    _PROGRAMME_LIFECYCLE_BRANCH,
    _PROGRAMME_LIFECYCLE_BRANCH_V2,
    label="call transition receipt targets",
)

_RETIRED_OWNER_CHECK = """    IF submission_id_value IS NULL AND EXISTS (
        SELECT 1
          FROM public.applications_programmecall AS call
          JOIN public.workforce_department AS department
            ON department.id = call.owner_department_id
         WHERE call.definition_id = definition_id_value
           AND department.retired_at IS NOT NULL
    ) THEN"""
_RETIRED_OWNER_CHECK_V2 = """    IF submission_id_value IS NULL
       AND definition_row.status <> 'retired'
       AND EXISTS (
        SELECT 1
          FROM public.applications_programmecall AS call
          JOIN public.workforce_department AS department
            ON department.id = call.owner_department_id
         WHERE call.definition_id = definition_id_value
           AND department.retired_at IS NOT NULL
    ) THEN"""
PROGRAMME_CONTRACT_FUNCTION_SQL = _replace_once(
    _programme.PROGRAMME_CONTRACT_FUNCTION_SQL,
    _RETIRED_OWNER_CHECK,
    _RETIRED_OWNER_CHECK_V2,
    label="retired call history",
)

_CONTRACT_BEGIN = """BEGIN
    IF TG_TABLE_NAME = 'applications_applicationdefinition' THEN"""
_CONTRACT_BEGIN_V2 = """BEGIN
    IF TG_TABLE_NAME = 'applications_programmecall' THEN
        IF TG_OP = 'UPDATE'
           AND (pg_catalog.to_jsonb(NEW)->>'owner_department_id')::uuid
               IS DISTINCT FROM
               (pg_catalog.to_jsonb(OLD)->>'owner_department_id')::uuid
           AND (
            SELECT pg_catalog.count(*)
              FROM public.applications_programmecommandreceipt AS receipt
             WHERE receipt.definition_id =
                   (pg_catalog.to_jsonb(NEW)->>'definition_id')::uuid
               AND receipt.submission_id IS NULL
               AND receipt.resulting_version = (
                    SELECT aggregate_version
                      FROM public.applications_applicationdefinition
                     WHERE id =
                           (pg_catalog.to_jsonb(NEW)->>'definition_id')::uuid
               )
               AND receipt.action IN (
                    'call_reassigned', 'recovery_call_reassigned'
               )
               AND receipt.source_department_id =
                   (pg_catalog.to_jsonb(OLD)->>'owner_department_id')::uuid
               AND receipt.destination_department_id =
                   (pg_catalog.to_jsonb(NEW)->>'owner_department_id')::uuid
           ) <> 1
        THEN
            RAISE EXCEPTION 'Programme call ownership mutation lacks exact transition evidence'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'applications_applicationdefinition' THEN"""
PROGRAMME_CONTRACT_FUNCTION_SQL = _replace_once(
    PROGRAMME_CONTRACT_FUNCTION_SQL,
    _CONTRACT_BEGIN,
    _CONTRACT_BEGIN_V2,
    label="call owner transition contract",
)

PROGRAMME_INTEGRITY_FORWARD_SQL = _previous.PROGRAMME_INTEGRITY_FORWARD_SQL_V2
PROGRAMME_INTEGRITY_FORWARD_SQL = _replace_once(
    PROGRAMME_INTEGRITY_FORWARD_SQL,
    _previous.PROGRAMME_RECEIPT_FUNCTION_SQL,
    PROGRAMME_RECEIPT_FUNCTION_SQL,
    label="consolidated call receipt function",
)
PROGRAMME_INTEGRITY_FORWARD_SQL = _replace_once(
    PROGRAMME_INTEGRITY_FORWARD_SQL,
    _programme.PROGRAMME_CONTRACT_FUNCTION_SQL,
    PROGRAMME_CONTRACT_FUNCTION_SQL,
    label="consolidated call contract function",
)

_BATCH_UPDATE = """        ELSIF TG_OP = 'UPDATE' THEN
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
        END IF;"""
_BATCH_UPDATE_V2 = """        ELSIF TG_OP = 'UPDATE' THEN
            IF ROW(
                NEW.id, NEW.organization_id, NEW.edition_id,
                NEW.source_system, NEW.schema_version, NEW.source_digest,
                NEW.item_count, NEW.retention_policy_code, NEW.expires_at,
                NEW.staged_by_id, NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id, OLD.organization_id, OLD.edition_id,
                OLD.source_system, OLD.schema_version, OLD.source_digest,
                OLD.item_count, OLD.retention_policy_code, OLD.expires_at,
                OLD.staged_by_id, OLD.created_at
            ) OR OLD.state <> 'staged'
              OR OLD.aggregate_version <= 0
              OR NEW.aggregate_version <> OLD.aggregate_version + 1
              OR NOT (
                  (
                    NEW.state = 'staged'
                    AND NEW.owner_department_id <> OLD.owner_department_id
                    AND NEW.discarded_by_id IS NULL
                    AND NEW.discarded_at IS NULL
                    AND NEW.discard_reason = ''
                    AND NOT EXISTS (
                        SELECT 1
                          FROM public.applications_programmeimportitem AS item
                         WHERE item.batch_id = NEW.id
                           AND (
                               item.state <> 'staged'
                               OR item.aggregate_version <> 1
                               OR item.canonical_payload IS NULL
                               OR pg_catalog.octet_length(item.canonical_payload)
                                  <> item.payload_size_bytes
                           )
                    )
                    AND NOT EXISTS (
                        SELECT 1
                          FROM public.applications_programmeimportsourcebinding AS binding
                          JOIN public.applications_programmeimportitem AS item
                            ON item.id = binding.item_id
                         WHERE item.batch_id = NEW.id
                    )
                  )
                  OR (
                    NEW.state = 'discarded'
                    AND NEW.owner_department_id = OLD.owner_department_id
                    AND NEW.discarded_by_id IS NOT NULL
                    AND NEW.discarded_at IS NOT NULL
                    AND NEW.discard_reason <> ''
                  )
              )
            THEN
                RAISE EXCEPTION 'Programme-import batch mutation is not an exact reassign or discard transition'
                    USING ERRCODE = '23514';
            END IF;
        END IF;"""
IMPORT_CURRENT_FUNCTION_SQL = _replace_once(
    _previous.IMPORT_CURRENT_FUNCTION_SQL,
    _BATCH_UPDATE,
    _BATCH_UPDATE_V2,
    label="batch reassign or discard transition",
)
IMPORT_CURRENT_FUNCTION_SQL = _replace_once(
    IMPORT_CURRENT_FUNCTION_SQL,
    """OR parent_row.aggregate_version <> 1
              OR OLD.state <> 'staged'""",
    """OR parent_row.aggregate_version <= 0
              OR OLD.state <> 'staged'""",
    label="item terminal parent version",
)

IMPORT_EVIDENCE_FUNCTION_SQL = _replace_once(
    _previous.IMPORT_EVIDENCE_FUNCTION_SQL,
    """           OR NEW.source_batch_version <> batch_row.aggregate_version
           OR NEW.source_batch_version <> 1
           OR NEW.item_count <> batch_row.item_count""",
    """           OR NEW.source_batch_version <> batch_row.aggregate_version
           OR NEW.source_batch_version <= 0
           OR NEW.item_count <> batch_row.item_count""",
    label="preview positive batch version",
)

IMPORT_RECEIPT_FUNCTION_SQL = _previous.IMPORT_RECEIPT_FUNCTION_SQL
IMPORT_RECEIPT_FUNCTION_SQL = _replace_once(
    IMPORT_RECEIPT_FUNCTION_SQL,
    """    SELECT organization_id, edition_id, state, aggregate_version, source_digest,
           staged_by_id, discarded_by_id, discard_reason""",
    """    SELECT organization_id, edition_id, owner_department_id, state,
           aggregate_version, source_digest, staged_by_id, discarded_by_id,
           discard_reason""",
    label="batch receipt owner projection",
)
_IMPORT_STAGED_BRANCH = """    ELSIF NEW.action = 'batch_previewed' THEN"""
_IMPORT_REASSIGNED_BRANCH = """    ELSIF NEW.action = 'batch_reassigned' THEN
        IF NEW.aggregate_kind <> 'batch'
           OR NEW.item_id IS NOT NULL
           OR NEW.preview_revision_id IS NOT NULL
           OR NEW.preview_item_result_id IS NOT NULL
           OR NEW.source_binding_id IS NOT NULL
           OR NEW.adopted_preview_digest <> ''
           OR NEW.applied_command_count <> 0
           OR NEW.result_kind <> 'batch'
           OR NEW.expected_version <= 0
           OR batch_row.state <> 'staged'
           OR batch_row.aggregate_version <> NEW.resulting_version
           OR batch_row.owner_department_id <> NEW.destination_department_id
           OR NEW.source_department_id IS NULL
           OR NEW.destination_department_id IS NULL
           OR NEW.source_department_id = NEW.destination_department_id
           OR NOT EXISTS (
                SELECT 1 FROM public.workforce_department AS source_department
                 WHERE source_department.id = NEW.source_department_id
                   AND source_department.organization_id = NEW.organization_id
                   AND source_department.edition_id = NEW.edition_id
                   AND source_department.retired_at IS NULL
           )
           OR NOT EXISTS (
                SELECT 1 FROM public.workforce_department AS destination_department
                 WHERE destination_department.id = NEW.destination_department_id
                   AND destination_department.organization_id = NEW.organization_id
                   AND destination_department.edition_id = NEW.edition_id
                   AND destination_department.retired_at IS NULL
           )
        THEN
            RAISE EXCEPTION 'Programme-import batch reassignment receipt is invalid'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.action = 'batch_previewed' THEN"""
IMPORT_RECEIPT_FUNCTION_SQL = _replace_once(
    IMPORT_RECEIPT_FUNCTION_SQL,
    _IMPORT_STAGED_BRANCH,
    _IMPORT_REASSIGNED_BRANCH,
    label="batch reassignment receipt",
)
IMPORT_RECEIPT_FUNCTION_SQL = _replace_once(
    IMPORT_RECEIPT_FUNCTION_SQL,
    """           OR NEW.expected_version <> 1 OR NEW.resulting_version <> 2
           OR NEW.reason = ''
           OR batch_row.state <> 'discarded' OR batch_row.aggregate_version <> 2""",
    """           OR NEW.expected_version <= 0
           OR NEW.reason = ''
           OR batch_row.state <> 'discarded'
           OR batch_row.aggregate_version <> NEW.resulting_version""",
    label="monotonic discard receipt",
)
_IMPORT_RECEIPT_RETURN = """    ELSE
        RAISE EXCEPTION 'Programme-import command action is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;"""
_IMPORT_RECEIPT_RETURN_V2 = """    ELSE
        RAISE EXCEPTION 'Programme-import command action is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.action = 'batch_reassigned' THEN
        IF NEW.source_department_id IS NULL
           OR NEW.destination_department_id IS NULL
        THEN
            RAISE EXCEPTION 'Programme-import transition Department evidence is missing'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.source_department_id IS NOT NULL
          OR NEW.destination_department_id IS NOT NULL
    THEN
        RAISE EXCEPTION 'Ordinary Programme-import receipts cannot retain Department transitions'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;"""
IMPORT_RECEIPT_FUNCTION_SQL = _replace_once(
    IMPORT_RECEIPT_FUNCTION_SQL,
    _IMPORT_RECEIPT_RETURN,
    _IMPORT_RECEIPT_RETURN_V2,
    label="import transition evidence shape",
)

_IMPORT_CONTRACT_BEGIN = """BEGIN
    IF TG_TABLE_NAME = 'applications_programmeimportbatch' THEN"""
_IMPORT_CONTRACT_BEGIN_V2 = """BEGIN
    IF TG_TABLE_NAME = 'applications_programmeimportbatch' AND TG_OP = 'UPDATE' THEN
        IF (pg_catalog.to_jsonb(NEW)->>'owner_department_id')::uuid
               IS DISTINCT FROM
               (pg_catalog.to_jsonb(OLD)->>'owner_department_id')::uuid
           AND (
               SELECT pg_catalog.count(*)
                 FROM public.applications_programmeimportcommandreceipt AS receipt
                WHERE receipt.batch_id = (pg_catalog.to_jsonb(NEW)->>'id')::uuid
                  AND receipt.action = 'batch_reassigned'
                  AND receipt.expected_version =
                      (pg_catalog.to_jsonb(OLD)->>'aggregate_version')::bigint
                  AND receipt.resulting_version =
                      (pg_catalog.to_jsonb(NEW)->>'aggregate_version')::bigint
                  AND receipt.source_department_id =
                      (pg_catalog.to_jsonb(OLD)->>'owner_department_id')::uuid
                  AND receipt.destination_department_id =
                      (pg_catalog.to_jsonb(NEW)->>'owner_department_id')::uuid
           ) <> 1
        THEN
            RAISE EXCEPTION 'Programme-import owner change requires exact transition evidence'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'applications_programmeimportbatch' THEN"""
IMPORT_CONTRACT_FUNCTION_SQL = _replace_once(
    _previous.IMPORT_CONTRACT_FUNCTION_SQL,
    _IMPORT_CONTRACT_BEGIN,
    _IMPORT_CONTRACT_BEGIN_V2,
    label="batch exact old and new owner evidence",
)
IMPORT_CONTRACT_FUNCTION_SQL = _replace_once(
    IMPORT_CONTRACT_FUNCTION_SQL,
    """                   OR preview.source_batch_version <> 1
                   OR (""",
    """                   OR preview.source_batch_version <= 0
                   OR preview.source_batch_version > batch_row.aggregate_version
                   OR (""",
    label="historical preview batch versions",
)
_IMPORT_STAGED_RECEIPT_CHECK = """    IF NOT EXISTS (
        SELECT 1 FROM public.applications_programmeimportcommandreceipt
         WHERE batch_id = batch_id_value AND action = 'batch_staged'
    ) OR EXISTS ("""
_IMPORT_STAGED_RECEIPT_CHECK_V2 = """    IF (
        SELECT pg_catalog.count(*)
          FROM public.applications_programmeimportcommandreceipt AS receipt
         WHERE receipt.batch_id = batch_id_value
           AND receipt.aggregate_kind = 'batch'
           AND receipt.action IN (
                'batch_staged', 'batch_reassigned', 'batch_discarded'
           )
    ) <> batch_row.aggregate_version
       OR EXISTS (
            SELECT 1
              FROM pg_catalog.generate_series(
                   1, batch_row.aggregate_version
              ) AS expected(version)
             WHERE NOT EXISTS (
                 SELECT 1
                   FROM public.applications_programmeimportcommandreceipt AS receipt
                  WHERE receipt.batch_id = batch_id_value
                    AND receipt.aggregate_kind = 'batch'
                    AND receipt.resulting_version = expected.version
                    AND receipt.expected_version = expected.version - 1
                    AND (
                        (expected.version = 1 AND receipt.action = 'batch_staged')
                        OR (expected.version > 1 AND receipt.action IN (
                            'batch_reassigned', 'batch_discarded'
                        ))
                    )
             )
       )
       OR EXISTS ("""
IMPORT_CONTRACT_FUNCTION_SQL = _replace_once(
    IMPORT_CONTRACT_FUNCTION_SQL,
    _IMPORT_STAGED_RECEIPT_CHECK,
    _IMPORT_STAGED_RECEIPT_CHECK_V2,
    label="batch transition receipt chain",
)

PROGRAMME_IMPORT_OWNER_CHAIN_FUNCTION_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_validate_programme_import_call_owner_chain()
RETURNS trigger AS $applications_programme_import_owner_chain_guard$
DECLARE
    call_id_value uuid;
    call_row record;
    anchor_department_id uuid;
    terminal_department_id uuid;
    transition_total bigint;
    covered_total bigint;
BEGIN
    IF TG_TABLE_NAME = 'applications_programmecall' THEN
        call_id_value := CASE WHEN TG_OP = 'DELETE' THEN OLD.id ELSE NEW.id END;
    ELSIF TG_TABLE_NAME = 'applications_programmecommandreceipt' THEN
        IF NEW.aggregate_kind <> 'call' THEN RETURN NULL; END IF;
        SELECT id INTO call_id_value
          FROM public.applications_programmecall
         WHERE definition_id = NEW.definition_id;
    ELSIF TG_TABLE_NAME = 'applications_programmeimportsourcebinding' THEN
        call_id_value := CASE WHEN TG_OP = 'DELETE' THEN OLD.call_id ELSE NEW.call_id END;
    ELSE
        RAISE EXCEPTION 'unregistered Programme import owner-chain table'
            USING ERRCODE = '23514';
    END IF;
    IF call_id_value IS NULL THEN RETURN NULL; END IF;

    SELECT call.id, call.organization_id, call.edition_id, call.definition_id,
           call.owner_department_id
      INTO call_row
      FROM public.applications_programmecall AS call
     WHERE call.id = call_id_value;
    IF call_row IS NULL THEN RETURN NULL; END IF;

    SELECT batch.owner_department_id
      INTO anchor_department_id
      FROM public.applications_programmeimportsourcebinding AS binding
      JOIN public.applications_programmeimportitem AS item ON item.id = binding.item_id
      JOIN public.applications_programmeimportbatch AS batch ON batch.id = item.batch_id
     WHERE binding.call_id = call_id_value
       AND binding.kind = 'call';
    IF anchor_department_id IS NULL THEN RETURN NULL; END IF;

    WITH RECURSIVE ordered_transition AS (
        SELECT receipt.source_department_id,
               receipt.destination_department_id,
               pg_catalog.row_number() OVER (
                   ORDER BY receipt.resulting_version, receipt.id
               ) AS ordinal
          FROM public.applications_programmecommandreceipt AS receipt
         WHERE receipt.definition_id = call_row.definition_id
           AND receipt.submission_id IS NULL
           AND receipt.action IN (
                'call_reassigned', 'recovery_call_reassigned'
           )
    ), owner_chain AS (
        SELECT 0::bigint AS ordinal, anchor_department_id AS department_id
        UNION ALL
        SELECT transition.ordinal, transition.destination_department_id
          FROM owner_chain AS prior
          JOIN ordered_transition AS transition
            ON transition.ordinal = prior.ordinal + 1
           AND transition.source_department_id = prior.department_id
    )
    SELECT (SELECT pg_catalog.count(*) FROM ordered_transition),
           pg_catalog.max(owner_chain.ordinal),
           (pg_catalog.array_agg(
                owner_chain.department_id ORDER BY owner_chain.ordinal DESC
            ))[1]
      INTO transition_total, covered_total, terminal_department_id
      FROM owner_chain;
    IF transition_total <> covered_total
       OR terminal_department_id IS DISTINCT FROM call_row.owner_department_id
    THEN
        RAISE EXCEPTION 'Imported Programme call owner transition chain is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$applications_programme_import_owner_chain_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

_OWNER_CHAIN_TABLES = (
    ("call", "applications_programmecall"),
    ("receipt", "applications_programmecommandreceipt"),
    ("binding", "applications_programmeimportsourcebinding"),
)


def _owner_chain_trigger_sql() -> str:
    return "\n".join(
        f"""CREATE CONSTRAINT TRIGGER applications_prg_imp_owner_chain_{suffix}
AFTER INSERT OR UPDATE OR DELETE ON public.{table}
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION
public.maru_applications_validate_programme_import_call_owner_chain();"""
        for suffix, table in _OWNER_CHAIN_TABLES
    )


_MUTEX_TABLES = (
    ("call", "applications_programmecall"),
    ("call_receipt", "applications_programmecommandreceipt"),
    ("import_batch", "applications_programmeimportbatch"),
    ("import_item", "applications_programmeimportitem"),
    ("import_receipt", "applications_programmeimportcommandreceipt"),
)


def _mutex_trigger_sql() -> str:
    statements = [
        """CREATE TRIGGER aa_applications_definition_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.applications_applicationdefinition
FOR EACH STATEMENT EXECUTE FUNCTION
public.maru_workforce_page9_writer_barrier();""",
        """CREATE TRIGGER ab_applications_definition_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.applications_applicationdefinition
FOR EACH ROW EXECUTE FUNCTION
public.maru_workforce_page9_scope_mutex();""",
    ]
    for suffix, table in _MUTEX_TABLES:
        statements.extend(
            (
                f"""CREATE TRIGGER aa_applications_{suffix}_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{table}
FOR EACH STATEMENT EXECUTE FUNCTION
public.maru_workforce_page9_writer_barrier();""",
                f"""CREATE TRIGGER ab_applications_{suffix}_scope
BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
FOR EACH ROW EXECUTE FUNCTION
public.maru_workforce_page9_scope_mutex();""",
            )
        )
    return "\n".join(statements)


def _drop_owner_chain_sql() -> str:
    statements = [
        f"DROP TRIGGER IF EXISTS applications_prg_imp_owner_chain_{suffix} ON public.{table};"
        for suffix, table in reversed(_OWNER_CHAIN_TABLES)
    ]
    statements.append(
        "DROP FUNCTION IF EXISTS "
        "public.maru_applications_validate_programme_import_call_owner_chain();"
    )
    return "\n".join(statements)


def _drop_mutex_trigger_sql() -> str:
    statements = [
        "DROP TRIGGER IF EXISTS ab_applications_definition_scope "
        "ON public.applications_applicationdefinition;",
        "DROP TRIGGER IF EXISTS aa_applications_definition_barrier "
        "ON public.applications_applicationdefinition;",
    ]
    for suffix, table in reversed(_MUTEX_TABLES):
        statements.extend(
            (
                f"DROP TRIGGER IF EXISTS ab_applications_{suffix}_scope ON public.{table};",
                f"DROP TRIGGER IF EXISTS aa_applications_{suffix}_barrier ON public.{table};",
            )
        )
    return "\n".join(statements)


FORWARD_SQL = "\n\n".join(
    (
        _drop_mutex_trigger_sql(),
        _drop_owner_chain_sql(),
        _previous._drop_sql(),  # noqa: SLF001
        _programme._drop_trigger_sql(),  # noqa: SLF001
        _programme._drop_function_sql(),  # noqa: SLF001
        PROGRAMME_INTEGRITY_FORWARD_SQL.strip(),
        IMPORT_CURRENT_FUNCTION_SQL.strip(),
        IMPORT_EVIDENCE_FUNCTION_SQL.strip(),
        IMPORT_RECEIPT_FUNCTION_SQL.strip(),
        IMPORT_CONTRACT_FUNCTION_SQL.strip(),
        _previous.IMPORT_TRUNCATE_FUNCTION_SQL.strip(),
        _previous._trigger_sql(),  # noqa: SLF001
        _previous._revoke_sql(),  # noqa: SLF001
        PROGRAMME_IMPORT_OWNER_CHAIN_FUNCTION_SQL.strip(),
        _owner_chain_trigger_sql(),
        "REVOKE ALL ON FUNCTION public."
        "maru_applications_validate_programme_import_call_owner_chain() FROM PUBLIC;",
        _mutex_trigger_sql(),
    )
)

REVERSE_SQL = "\n\n".join(
    (
        _drop_mutex_trigger_sql(),
        _drop_owner_chain_sql(),
        _previous._drop_sql(),  # noqa: SLF001
        _previous.FORWARD_SQL.strip(),
    )
)


class Migration(migrations.Migration):
    """Install ownership transitions, shared mutexes, and exact evidence."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0010_programme_department_ownership_persistence"),
        ("authorization", "0023_programme_department_ownership_recovery"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
