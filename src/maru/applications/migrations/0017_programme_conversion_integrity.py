"""Require atomic effective acceptance, reciprocal item, readiness and evidence."""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_review = importlib.import_module("maru.applications.migrations.0014_programme_review_integrity")
TABLE = "applications_programmeacceptedtransition"
RETRY_SQL = _review.RETRY_SQL.replace(
    "'applications_programmeimportcommandreceipt', 'applications_programmereviewreceipt'",
    "'applications_programmeimportcommandreceipt', 'applications_programmereviewreceipt', "
    "'applications_programmeacceptedtransition'",
)

GUARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_guard_programme_conversion()
RETURNS trigger AS $conversion_guard$
DECLARE
    source record;
    stage_index integer;
BEGIN
    IF TG_OP <> 'INSERT'
       OR pg_catalog.current_setting('maru.applications_programme_writer', true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION 'Programme conversion evidence requires its closed append-only writer' USING ERRCODE = '23514';
    END IF;
    PERFORM public.maru_workforce_page9_try_scope_mutex(pg_catalog.hashtextextended(
        'maru.workforce.department:' || NEW.organization_id::text || ':' || NEW.edition_id::text, 0
    ));
    SELECT c.id AS case_id, pg_catalog.jsonb_array_length(policy.stages) AS stage_count
      INTO source
      FROM public.applications_programmereviewdecision d
      JOIN public.applications_programmereviewentry entry ON entry.id = d.entry_id
      JOIN public.applications_programmereviewcase c ON c.id = entry.case_id
      JOIN public.applications_programmereviewpolicy policy ON policy.id = c.policy_id
      JOIN public.applications_programmeproposal p ON p.id = c.proposal_id
      JOIN public.applications_programmeproposalrevision r ON r.id = c.revision_id AND r.proposal_id = p.id
      JOIN public.applications_programmecall call ON call.id = p.call_id
      JOIN public.workforce_department owner ON owner.id = call.owner_department_id
      JOIN public.events_eventedition e ON e.id = call.edition_id
      JOIN public.organizations_organization o ON o.id = e.organization_id
     WHERE d.id = NEW.decision_id AND d.outcome = 'accepted' AND d.revision_id = NEW.revision_id
       AND entry.action = 'decided' AND entry.version <= NEW.review_version
       AND c.state = 'accepted' AND c.version = NEW.review_version AND c.revision_id = NEW.revision_id
       AND p.state = 'submitted' AND p.submitted_revision_id = r.id AND p.sealed_revision_id = r.id
       AND r.organization_id = NEW.organization_id AND r.edition_id = NEW.edition_id
       AND p.organization_id = NEW.organization_id AND p.edition_id = NEW.edition_id
       AND call.organization_id = NEW.organization_id AND call.edition_id = NEW.edition_id
       AND owner.organization_id = NEW.organization_id AND owner.edition_id = NEW.edition_id
       AND owner.retired_at IS NULL AND e.organization_id = NEW.organization_id
       AND e.lifecycle IN ('draft', 'preparing') AND o.lifecycle IN ('draft', 'active');
    IF source IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.identity_account a WHERE a.id = NEW.actor_id
          AND a.account_kind = 'person' AND a.is_active AND a.email_verified_at IS NOT NULL
    ) OR NEW.request_digest !~ '^[0-9a-f]{64}$'
      OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
      OR pg_catalog.length(pg_catalog.btrim(NEW.reason)) NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'Programme conversion requires exact current accepted source and planning scope' USING ERRCODE = '23514';
    END IF;
    FOR stage_index IN 0..source.stage_count - 1 LOOP
        IF NOT public.maru_applications_review_stage_ready(source.case_id, stage_index, NEW.review_version) THEN
            RAISE EXCEPTION 'Programme conversion requires effective moderated acceptance' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$conversion_guard$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

EVIDENCE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_applications_validate_programme_conversion()
RETURNS trigger AS $conversion_evidence$
DECLARE
    item_row record;
    target_receipt record;
    concern_count integer;
BEGIN
    SELECT i.* INTO item_row FROM public.programme_programmeitem i
      JOIN public.programme_programmeitemsourcebinding b ON b.item_id = i.id
     WHERE i.id = NEW.programme_item_id AND i.organization_id = NEW.organization_id
       AND i.edition_id = NEW.edition_id AND i.kind = 'accepted_proposal'
       AND i.provenance_kind = 'applications_accepted' AND i.created_by_id = NEW.actor_id
       AND b.organization_id = NEW.organization_id AND b.edition_id = NEW.edition_id
       AND b.binding_code = 'programme.source.applications-accepted@1'
       AND b.source_object_id = NEW.id AND b.source_version = 1;
    SELECT * INTO target_receipt FROM public.programme_programmecommandreceipt t
     WHERE t.item_id = NEW.programme_item_id AND t.operation = 'item_accept'
       AND t.organization_id = NEW.organization_id AND t.edition_id = NEW.edition_id
       AND t.actor_id = NEW.actor_id AND t.idempotency_key = NEW.id
       AND t.reason = NEW.reason AND t.correlation_id = NEW.correlation_id
       AND t.source_channel = NEW.source_channel AND t.resulting_item_version = 1
       AND t.expected_version = NEW.expected_programme_version
       AND t.resulting_control_version = NEW.resulting_programme_version;
    SELECT count(*) INTO concern_count FROM public.programme_programmereadinessrequirement r
      JOIN public.programme_programmereadinessrequirementrevision v ON v.requirement_id = r.id
     WHERE r.item_id = NEW.programme_item_id AND v.sequence = 1 AND v.item_version = 1
       AND v.disposition = 'required' AND v.actor_id = NEW.actor_id AND v.reason = NEW.reason
       AND r.organization_id = NEW.organization_id AND r.edition_id = NEW.edition_id;
    IF item_row IS NULL OR target_receipt IS NULL OR concern_count <> 7 THEN
        RAISE EXCEPTION 'Programme conversion lacks reciprocal item, creation receipt or seven required concerns' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a JOIN public.effects_domainevent e ON e.id = NEW.domain_event_id
         WHERE a.id = NEW.audit_event_id AND a.principal_kind = 'account' AND a.principal_id = NEW.actor_id
           AND a.organization_id = NEW.organization_id AND a.event_edition_id = NEW.edition_id
           AND a.operation = 'applications.programme_conversion.completed' AND a.outcome = 'allow'
           AND a.capability_code = 'applications.convert_programme_acceptance'
           AND a.target_type = 'applications.programme_conversion' AND a.target_id = NEW.id
           AND a.correlation_id = NEW.correlation_id AND a.source_channel = NEW.source_channel
           AND e.causation_id = a.id AND e.actor_kind = 'account' AND e.actor_id = NEW.actor_id
           AND e.organization_id = NEW.organization_id AND e.event_edition_id = NEW.edition_id
           AND e.aggregate_type = 'applications.programme_conversion' AND e.aggregate_id = NEW.id
           AND e.aggregate_version = 1 AND e.correlation_id = NEW.correlation_id
           AND e.event_name = 'applications.programme_conversion.completed.v1' AND e.schema_version = 1
           AND e.payload = pg_catalog.jsonb_build_object('transition_id', NEW.id::text, 'programme_item_id', NEW.programme_item_id::text)
           AND a.retention_class = 'applications-programme-restricted' AND e.retention_class = a.retention_class
           AND EXISTS (SELECT 1 FROM public.effects_outboxmessage b WHERE b.event_id = e.id AND b.organization_id = e.organization_id)
    ) OR NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent a JOIN public.effects_domainevent e ON e.causation_id = a.id
         WHERE a.principal_kind = 'account' AND a.principal_id = NEW.actor_id
           AND a.organization_id = NEW.organization_id AND a.event_edition_id = NEW.edition_id
           AND a.operation = 'programme.command.item_accept' AND a.outcome = 'allow'
           AND a.capability_code = 'programme.manage_items' AND a.target_type = 'programme.item'
           AND a.target_id = NEW.programme_item_id AND a.correlation_id = NEW.correlation_id
           AND a.source_channel = NEW.source_channel AND a.retention_class = 'programme-restricted'
           AND e.actor_kind = 'account' AND e.actor_id = NEW.actor_id
           AND e.organization_id = NEW.organization_id AND e.event_edition_id = NEW.edition_id
           AND e.aggregate_type = 'programme.item' AND e.aggregate_id = NEW.programme_item_id
           AND e.aggregate_version = 1 AND e.correlation_id = NEW.correlation_id
           AND e.event_name = 'programme.item.changed.v1' AND e.schema_version = 1
           AND e.payload = pg_catalog.jsonb_build_object('action', 'accept_application_item', 'item_kind', 'accepted_proposal',
               'provenance', 'applications_accepted', 'lifecycle', 'active', 'concern', 'none', 'layer', 'item')
           AND e.retention_class = a.retention_class
           AND EXISTS (SELECT 1 FROM public.effects_outboxmessage b WHERE b.event_id = e.id AND b.organization_id = e.organization_id)
    ) THEN
        RAISE EXCEPTION 'Programme conversion lacks both owners minimized success evidence and outboxes' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$conversion_evidence$
LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp;
"""

TRIGGER_SQL = f"""
CREATE TRIGGER aa_applications_conversion_barrier BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON public.{TABLE}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();
CREATE TRIGGER applications_conversion_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{TABLE}
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_guard_programme_conversion();
CREATE TRIGGER applications_conversion_truncate BEFORE TRUNCATE ON public.{TABLE}
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_applications_refuse_programme_truncate();
CREATE TRIGGER applications_conversion_retry BEFORE INSERT ON public.{TABLE}
FOR EACH ROW EXECUTE FUNCTION public.maru_applications_review_retry_namespace();
CREATE CONSTRAINT TRIGGER applications_conversion_evidence AFTER INSERT ON public.{TABLE}
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.maru_applications_validate_programme_conversion();
REVOKE ALL ON FUNCTION public.maru_applications_guard_programme_conversion(),
public.maru_applications_validate_programme_conversion(), public.maru_applications_review_retry_namespace() FROM PUBLIC;
"""
FORWARD_SQL = "\n".join((RETRY_SQL, GUARD_SQL, EVIDENCE_SQL, TRIGGER_SQL))
REVERSE_SQL = "\n".join((
    *(f"DROP TRIGGER IF EXISTS {name} ON public.{TABLE};" for name in (
        "aa_applications_conversion_barrier", "applications_conversion_guard",
        "applications_conversion_truncate", "applications_conversion_retry", "applications_conversion_evidence",
    )),
    "DROP FUNCTION public.maru_applications_guard_programme_conversion();",
    "DROP FUNCTION public.maru_applications_validate_programme_conversion();",
    _review.RETRY_SQL,
))


class Migration(migrations.Migration):
    """Install reciprocal guards after both owned schemas and Programme rules."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0016_programmeacceptedtransition"),
        ("programme", "0005_accepted_item_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
