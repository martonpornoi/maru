"""Bind private supporting bytes to exact Programme answer provenance."""

from typing import ClassVar

from django.db import migrations

PREFLIGHT_SQL = """
DO $file_preflight$ BEGIN
    IF EXISTS (
        SELECT 1 FROM public.applications_applicationanswerrevision a
        JOIN public.applications_applicationsubmission s ON s.id = a.submission_id
        JOIN public.applications_applicationdefinition d ON d.id = s.definition_id
        WHERE d.target_adapter_kind = 'programme_item' AND a.question_type = 'safe_file'
          AND a.value IS NOT NULL AND a.value <> 'null'::jsonb
    ) OR EXISTS (
        SELECT 1 FROM public.applications_applicationfilereceipt
        WHERE storage_key LIKE 'programme-db/%'
    ) THEN
        RAISE EXCEPTION 'Unproven Programme files require explicit reconciliation before custody migration';
    END IF;
END; $file_preflight$;
"""

INTAKE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_file_intake()
RETURNS trigger AS $file_intake$
DECLARE
    source record;
    receipt record;
    condition_value jsonb;
    retained_count bigint;
    retained_bytes bigint;
BEGIN
    IF TG_OP <> 'INSERT'
       OR pg_catalog.current_setting('maru.applications_programme_writer', true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme file intake requires its closed append-only writer' USING ERRCODE = '23514';
    END IF;
    PERFORM public.maru_workforce_page9_try_scope_mutex(pg_catalog.hashtextextended(
        'maru.workforce.department:' || NEW.organization_id::text || ':' || NEW.edition_id::text, 0
    ));
    SELECT p.submission_id, s.definition_id, s.aggregate_version, s.account_id,
           d.aggregate_version AS call_version, d.version AS definition_version,
           q.condition, d.opens_at, d.applicant_edit_until
      INTO source
      FROM public.applications_programmeproposal p
      JOIN public.applications_applicationsubmission s ON s.id = p.submission_id
      JOIN public.applications_programmecall c ON c.id = p.call_id
      JOIN public.applications_applicationdefinition d ON d.id = c.definition_id AND d.id = s.definition_id
      JOIN public.applications_applicationquestion q ON q.id = NEW.question_id AND q.definition_id = d.id
      JOIN public.workforce_department owner ON owner.id = c.owner_department_id
      JOIN public.events_eventedition e ON e.id = p.edition_id
      JOIN public.organizations_organization o ON o.id = p.organization_id
     WHERE p.id = NEW.proposal_id AND p.organization_id = NEW.organization_id AND p.edition_id = NEW.edition_id
       AND s.organization_id = NEW.organization_id AND s.edition_id = NEW.edition_id
       AND c.organization_id = NEW.organization_id AND c.edition_id = NEW.edition_id
       AND d.organization_id = NEW.organization_id AND d.edition_id = NEW.edition_id
       AND owner.organization_id = NEW.organization_id AND owner.edition_id = NEW.edition_id
       AND owner.retired_at IS NULL AND e.organization_id = NEW.organization_id
       AND e.lifecycle IN ('draft', 'preparing') AND o.lifecycle IN ('draft', 'active')
       AND p.state = 'draft' AND d.status = 'active' AND d.target_adapter_kind = 'programme_item'
       AND q.field_type = 'safe_file' AND q.applicant_visible AND q.applicant_writable
       AND q.source_binding = '' AND NOT q.staff_visible AND NOT q.staff_writable
       AND NOT q.reviewer_visible AND NOT q.public_after_approval AND NOT q.api_projection
     FOR UPDATE OF d, s;
    SELECT * INTO receipt FROM public.applications_applicationfilereceipt WHERE id = NEW.file_receipt_id;
    IF source IS NULL OR receipt IS NULL
       OR NEW.source_version IS DISTINCT FROM source.aggregate_version
       OR NEW.call_version IS DISTINCT FROM source.call_version
       OR NEW.definition_version IS DISTINCT FROM source.definition_version
       OR NOT pg_catalog.isfinite(NEW.scanned_at)
       OR NEW.scanned_at < source.opens_at OR NEW.scanned_at > source.applicant_edit_until
       OR NEW.scanned_at > pg_catalog.clock_timestamp()
       OR pg_catalog.statement_timestamp() < source.opens_at
       OR pg_catalog.statement_timestamp() > source.applicant_edit_until
       OR receipt.organization_id IS DISTINCT FROM NEW.organization_id
       OR receipt.edition_id IS DISTINCT FROM NEW.edition_id
       OR receipt.account_id IS DISTINCT FROM NEW.actor_id
       OR receipt.status IS DISTINCT FROM 'clean'
       OR receipt.media_type IS DISTINCT FROM 'application/pdf'
       OR receipt.scanner_receipt IS DISTINCT FROM 'clamav-instream@1'
       OR receipt.storage_key IS DISTINCT FROM 'programme-db/' || NEW.id::text
       OR receipt.sha256 !~ '^[0-9a-f]{64}$' OR receipt.size_bytes NOT BETWEEN 1 AND 10485760
       OR NOT EXISTS (SELECT 1 FROM public.identity_account a WHERE a.id = NEW.actor_id
                      AND a.account_kind = 'person' AND a.is_active AND a.email_verified_at IS NOT NULL)
       OR NOT (NEW.actor_id = source.account_id OR EXISTS (
           SELECT 1 FROM public.applications_programmeproposalcollaborator co
           WHERE co.proposal_id = NEW.proposal_id AND co.account_id = NEW.actor_id AND co.state = 'accepted'
       )) THEN
        RAISE EXCEPTION 'Programme file intake requires exact current private purpose, uploader and scan evidence' USING ERRCODE = '23514';
    END IF;
    IF source.condition <> '{}'::jsonb THEN
        SELECT a.value INTO condition_value
          FROM public.applications_applicationanswerrevision a
          JOIN public.applications_applicationquestion q ON q.id = a.question_id
         WHERE a.submission_id = source.submission_id AND q.definition_id = source.definition_id
           AND q.key = source.condition->>'question_key' AND a.resulting_version <= NEW.source_version
         ORDER BY a.sequence DESC LIMIT 1;
        condition_value := COALESCE(condition_value, 'null'::jsonb);
        IF (CASE source.condition->>'operator'
            WHEN 'equals' THEN condition_value = source.condition->'value'
            WHEN 'not_equals' THEN condition_value <> source.condition->'value'
            WHEN 'contains' THEN pg_catalog.jsonb_typeof(condition_value) = 'array'
                AND condition_value @> pg_catalog.jsonb_build_array(source.condition->'value')
            ELSE FALSE END) IS DISTINCT FROM TRUE THEN
            RAISE EXCEPTION 'Programme file question is not applicable' USING ERRCODE = '23514';
        END IF;
    END IF;
    SELECT count(*), COALESCE(sum(r.size_bytes), 0) INTO retained_count, retained_bytes
      FROM public.applications_programmefileintake i
      JOIN public.applications_applicationfilereceipt r ON r.id = i.file_receipt_id
     WHERE i.proposal_id = NEW.proposal_id;
    IF retained_count >= 64 OR retained_bytes + receipt.size_bytes > 67108864 THEN
        RAISE EXCEPTION 'Programme supporting file retention quota exceeded' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$file_intake$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

CONTENT_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_file_content()
RETURNS trigger AS $file_content$
BEGIN
    IF TG_OP <> 'INSERT'
       OR pg_catalog.current_setting('maru.applications_programme_writer', true) IS DISTINCT FROM 'on'
       OR NOT EXISTS (
           SELECT 1 FROM public.applications_programmefileintake i
           JOIN public.applications_applicationfilereceipt r ON r.id = i.file_receipt_id
           WHERE i.id = NEW.intake_id AND pg_catalog.octet_length(NEW.payload) = r.size_bytes
             AND pg_catalog.octet_length(NEW.payload) BETWEEN 1 AND 10485760
             AND pg_catalog.encode(pg_catalog.sha256(NEW.payload), 'hex') = r.sha256
             AND pg_catalog.substr(NEW.payload, 1, 5) = pg_catalog.decode('255044462d', 'hex')
       ) THEN
        RAISE EXCEPTION 'Programme private bytes require immutable exact receipt evidence' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$file_content$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

EVIDENCE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_validate_programme_file_intake()
RETURNS trigger AS $file_evidence$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.applications_programmefilecontent b WHERE b.intake_id = NEW.id)
       OR NOT EXISTS (
           SELECT 1 FROM public.applications_programmeproposal p
           JOIN public.applications_applicationsubmission s ON s.id = p.submission_id
           JOIN public.applications_applicationanswerrevision a ON a.submission_id = s.id
           JOIN public.applications_programmecommandreceipt r ON r.target_id = a.id
           WHERE p.id = NEW.proposal_id AND a.question_id = NEW.question_id AND a.actor_id = NEW.actor_id
             AND a.question_type = 'safe_file' AND a.source = 'applicant'
             AND a.value = pg_catalog.to_jsonb(NEW.file_receipt_id::text)
             AND a.source_version = NEW.source_version AND a.resulting_version = NEW.source_version + 1
             AND r.organization_id = NEW.organization_id AND r.edition_id = NEW.edition_id
             AND r.actor_id = NEW.actor_id AND r.retry_key = NEW.retry_key
             AND r.aggregate_kind = 'proposal' AND r.action = 'proposal_answer_revised'
             AND r.result_kind = 'answer_revision' AND r.submission_id = s.id AND r.definition_id = s.definition_id
             AND r.expected_version = NEW.source_version AND r.resulting_version = NEW.source_version + 1
       ) THEN
        RAISE EXCEPTION 'Programme file custody requires atomic content, first answer and canonical success receipt' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$file_evidence$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

RECEIPT_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_validate_programme_file_receipt()
RETURNS trigger AS $file_receipt$
BEGIN
    IF NEW.storage_key LIKE 'programme-db/%' AND NOT EXISTS (
        SELECT 1 FROM public.applications_programmefileintake i WHERE i.file_receipt_id = NEW.id
          AND NEW.storage_key = 'programme-db/' || i.id::text
    ) THEN
        RAISE EXCEPTION 'Programme storage references require exact private custody' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$file_receipt$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

ANSWER_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_file_answer()
RETURNS trigger AS $file_answer$
BEGIN
    IF NEW.question_type = 'safe_file' AND NEW.value IS NOT NULL AND NEW.value <> 'null'::jsonb
       AND EXISTS (
           SELECT 1 FROM public.applications_applicationsubmission s
           JOIN public.applications_applicationdefinition d ON d.id = s.definition_id
           WHERE s.id = NEW.submission_id AND d.target_adapter_kind = 'programme_item'
       ) AND NOT EXISTS (
           SELECT 1 FROM public.applications_programmefileintake i
           JOIN public.applications_programmeproposal p ON p.id = i.proposal_id
           JOIN public.applications_applicationfilereceipt r ON r.id = i.file_receipt_id
           WHERE p.submission_id = NEW.submission_id AND i.question_id = NEW.question_id
             AND i.actor_id = NEW.actor_id AND r.account_id = NEW.actor_id AND r.status = 'clean'
             AND i.organization_id = p.organization_id AND i.edition_id = p.edition_id
             AND r.organization_id = p.organization_id AND r.edition_id = p.edition_id
             AND NEW.value = pg_catalog.to_jsonb(r.id::text)
       ) THEN
        RAISE EXCEPTION 'Programme file answers require exact proposal, question and uploader custody' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$file_answer$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

TRIGGER_SQL = (
    "\n".join(
        f"""
CREATE TRIGGER aa_applications_file_{kind}_barrier BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.applications_programmefile{kind} FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();
CREATE TRIGGER applications_file_{kind}_guard BEFORE INSERT OR UPDATE OR DELETE
ON public.applications_programmefile{kind} FOR EACH ROW
EXECUTE FUNCTION public.maru_applications_guard_programme_file_{kind}();
CREATE TRIGGER applications_file_{kind}_truncate BEFORE TRUNCATE
ON public.applications_programmefile{kind} FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_applications_refuse_programme_truncate();
"""
        for kind in ("intake", "content")
    )
    + """
CREATE CONSTRAINT TRIGGER applications_file_intake_evidence AFTER INSERT
ON public.applications_programmefileintake DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_validate_programme_file_intake();
CREATE CONSTRAINT TRIGGER applications_file_receipt_custody AFTER INSERT
ON public.applications_applicationfilereceipt DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_validate_programme_file_receipt();
CREATE TRIGGER applications_file_answer_custody BEFORE INSERT ON public.applications_applicationanswerrevision
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_programme_file_answer();
REVOKE ALL ON FUNCTION public.maru_applications_guard_programme_file_intake(),
public.maru_applications_guard_programme_file_content(), public.maru_applications_validate_programme_file_intake(),
public.maru_applications_validate_programme_file_receipt(), public.maru_applications_guard_programme_file_answer() FROM PUBLIC;
"""
)
FORWARD_SQL = "\n".join(
    (
        PREFLIGHT_SQL,
        INTAKE_SQL,
        CONTENT_SQL,
        EVIDENCE_SQL,
        RECEIPT_SQL,
        ANSWER_SQL,
        TRIGGER_SQL,
    )
)
REVERSE_SQL = "\n".join(
    (
        *(
            f"DROP TRIGGER applications_file_{kind}_{suffix} ON public.applications_programmefile{kind};"
            for kind in ("intake", "content")
            for suffix in ("guard", "truncate")
        ),
        *(
            f"DROP TRIGGER aa_applications_file_{kind}_barrier ON public.applications_programmefile{kind};"
            for kind in ("intake", "content")
        ),
        "DROP TRIGGER applications_file_intake_evidence ON public.applications_programmefileintake;",
        "DROP TRIGGER applications_file_receipt_custody ON public.applications_applicationfilereceipt;",
        "DROP TRIGGER applications_file_answer_custody ON public.applications_applicationanswerrevision;",
        *(
            f"DROP FUNCTION public.maru_applications_{name}_programme_file_{kind}();"
            for name, kind in (
                ("guard", "intake"),
                ("guard", "content"),
                ("validate", "intake"),
                ("validate", "receipt"),
                ("guard", "answer"),
            )
        ),
    )
)


class Migration(migrations.Migration):
    """Install closed custody guards without activating an upload route."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0019_programme_file_custody"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)
    ]
