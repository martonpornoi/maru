# ruff: noqa: E501

from collections.abc import Sequence
from typing import ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_assert_registration_template_publication_v1(
    template_pk uuid
)
RETURNS void AS $$
DECLARE
    evidence_count bigint;
    incomplete_children bigint;
BEGIN
    SELECT count(*)
      INTO evidence_count
      FROM public.registration_registrationtemplate AS template
      JOIN public.registration_registrationtemplatecatalogcontrol AS catalog
        ON catalog.organization_id = template.organization_id
       AND catalog.provenance_status = 'complete'
       AND catalog.aggregate_version >= template.last_changed_in_catalog_version
      JOIN public.registration_registrationtemplatecatalogcommandreceipt AS receipt
        ON receipt.catalog_id = catalog.id
       AND receipt.organization_id = template.organization_id
       AND receipt.action = 'template_published'
       AND receipt.resulting_version = template.last_changed_in_catalog_version
       AND receipt.retry_key IS NOT NULL
       AND receipt.request_digest ~ '^[0-9a-f]{64}$'
      JOIN public.registration_registrationtemplatecatalogcommandtarget AS target
        ON target.receipt_id = receipt.id
       AND target.target_kind = 'template'
       AND target.target_id = template.id
       AND target.change_kind = 'published'
       AND target.target_schema_version = template.version
       AND target.content_digest = template.content_digest
      JOIN public.audit_auditevent AS audit
        ON audit.schema_version = 1
       AND audit.organization_id = template.organization_id
       AND audit.event_edition_id IS NOT NULL
       AND audit.principal_kind = 'account'
       AND audit.principal_id = receipt.actor_id
       AND audit.capability_code = 'registration.manage_configuration'
       AND audit.operation = 'registration.template.published'
       AND audit.target_type = 'registration.template'
       AND audit.target_id = template.id
       AND audit.outcome = 'allow'
       AND audit.correlation_id = receipt.correlation_id
       AND audit.source_channel = receipt.source_channel
       AND audit.changed_fields = ARRAY[
            'catalog_versions', 'content_digest', 'provenance', 'status'
       ]::varchar[]
       AND audit.idempotency_key_hash = pg_catalog.encode(
            pg_catalog.sha256(
                pg_catalog.convert_to(
                    '{"retry_key":"' || receipt.retry_key::text || '"}',
                    'UTF8'
                )
            ),
            'hex'
       )
       AND audit.reason_code != ''
       AND audit.request_id IS NOT NULL
       AND audit.retention_class = 'registration-restricted'
       AND audit.safe_metadata->>'contract_version' =
            'registration-template-publication-v1'
       AND audit.safe_metadata->>'policy_version' ~
            '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[1-9][0-9]*$'
       AND audit.safe_metadata->'target_count' = '1'::jsonb
       AND (SELECT count(*) FROM pg_catalog.jsonb_object_keys(audit.safe_metadata)) = 3
       AND audit.occurred_at = template.published_at
      JOIN public.events_eventedition AS authority_edition
        ON authority_edition.id = audit.event_edition_id
       AND authority_edition.organization_id = template.organization_id
       AND (
            template.series_id IS NULL
            OR authority_edition.series_id = template.series_id
       )
      JOIN public.identity_account AS actor
        ON actor.id = receipt.actor_id
       AND (
            template.series_id IS NOT NULL
            OR actor.account_kind = 'platform_administrator'
       )
      JOIN public.effects_domainevent AS event
        ON event.event_name = 'registration.template.published.v1'
       AND event.schema_version = 1
       AND event.occurred_at = audit.occurred_at
       AND event.organization_id = template.organization_id
       AND event.event_edition_id = audit.event_edition_id
       AND event.aggregate_type = 'registration.template_catalog'
       AND event.aggregate_id = catalog.id
       AND event.aggregate_version = receipt.resulting_version
       AND event.payload = pg_catalog.jsonb_build_object(
            'template_code', template.code,
            'template_version', template.version::text
       )
       AND event.correlation_id = receipt.correlation_id
       AND event.causation_id = audit.id
       AND event.actor_kind = 'account'
       AND event.actor_id = receipt.actor_id
       AND event.retention_class = 'registration-restricted'
      JOIN public.effects_outboxmessage AS outbox
        ON outbox.event_id = event.id
       AND outbox.organization_id = template.organization_id
       AND outbox.destination = 'internal'
       AND outbox.workload_pool = 'default'
     WHERE template.id = template_pk
       AND template.status IN ('published', 'retired')
       AND template.provenance_status = 'complete'
       AND template.published_at IS NOT NULL
       AND template.content_digest ~ '^[0-9a-f]{64}$'
       AND template.created_in_catalog_version = template.last_changed_in_catalog_version
       AND NOT EXISTS (
            SELECT 1
              FROM public.registration_registrationtemplatecatalogcommandtarget AS extra
             WHERE extra.receipt_id = receipt.id
               AND extra.id != target.id
       );
    IF evidence_count != 1 THEN
        RAISE EXCEPTION 'registration template publication evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;

    SELECT
        (SELECT count(*)
           FROM public.registration_registrationtemplatesection AS child
          WHERE child.template_id = template.id
            AND (
                child.created_in_catalog_version != template.last_changed_in_catalog_version
                OR child.last_changed_in_catalog_version != template.last_changed_in_catalog_version
            ))
      + (SELECT count(*)
           FROM public.registration_registrationtemplatequestion AS child
          WHERE child.template_id = template.id
            AND (
                child.created_in_catalog_version != template.last_changed_in_catalog_version
                OR child.last_changed_in_catalog_version != template.last_changed_in_catalog_version
            ))
      + (SELECT count(*)
           FROM public.registration_registrationtemplateproduct AS child
          WHERE child.template_id = template.id
            AND (
                child.created_in_catalog_version != template.last_changed_in_catalog_version
                OR child.last_changed_in_catalog_version != template.last_changed_in_catalog_version
            ))
      INTO incomplete_children
      FROM public.registration_registrationtemplate AS template
     WHERE template.id = template_pk;
    IF incomplete_children != 0 THEN
        RAISE EXCEPTION 'registration template child provenance is incomplete'
            USING ERRCODE = '23514';
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
SET TimeZone = 'UTC';

REVOKE ALL ON FUNCTION
public.maru_assert_registration_template_publication_v1(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.maru_guard_registration_template_catalog_v2()
RETURNS trigger AS $$
DECLARE
    template_pk uuid;
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        IF public.maru_authority_provenance_test_reset_allowed() THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'registration template catalog evidence cannot be truncated'
            USING ERRCODE = '23514';
    END IF;

    IF TG_WHEN = 'BEFORE' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'registration template catalog evidence is retained'
                USING ERRCODE = '23514';
        END IF;
        IF TG_TABLE_NAME = 'registration_registrationtemplatecatalogcontrol' THEN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.aggregate_version != OLD.aggregate_version + 1
               OR NOT (
                    NEW.provenance_status = OLD.provenance_status
                    OR (
                        OLD.provenance_status = 'legacy_unknown'
                        AND NEW.provenance_status = 'complete'
                    )
               )
            THEN
                RAISE EXCEPTION 'registration template catalog movement is invalid'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'registration_registrationtemplate' THEN
            IF OLD.provenance_status = 'complete'
               AND OLD.status IN ('published', 'retired')
            THEN
                RAISE EXCEPTION 'published registration templates are immutable'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME IN (
            'registration_registrationtemplatecatalogcommandreceipt',
            'registration_registrationtemplatecatalogcommandtarget'
        ) THEN
            RAISE EXCEPTION 'registration template catalog evidence is immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF TG_TABLE_NAME = 'registration_registrationtemplate' THEN
        IF NEW.provenance_status = 'complete'
           AND NEW.status IN ('published', 'retired')
        THEN
            PERFORM public.maru_assert_registration_template_publication_v1(NEW.id);
        END IF;
    ELSIF TG_TABLE_NAME = 'registration_registrationtemplatecatalogcommandreceipt' THEN
        IF NEW.action = 'template_published' THEN
            SELECT target_id
              INTO template_pk
              FROM public.registration_registrationtemplatecatalogcommandtarget
             WHERE receipt_id = NEW.id
               AND target_kind = 'template'
               AND change_kind = 'published';
            PERFORM public.maru_assert_registration_template_publication_v1(template_pk);
        END IF;
    ELSIF TG_TABLE_NAME = 'registration_registrationtemplatecatalogcommandtarget' THEN
        IF NEW.target_kind = 'template' AND NEW.change_kind = 'published' THEN
            PERFORM public.maru_assert_registration_template_publication_v1(NEW.target_id);
        END IF;
    ELSIF TG_TABLE_NAME = 'registration_registrationtemplatecatalogcontrol' THEN
        IF NEW.provenance_status = 'complete' THEN
            SELECT target.target_id
              INTO template_pk
              FROM public.registration_registrationtemplatecatalogcommandreceipt AS receipt
              JOIN public.registration_registrationtemplatecatalogcommandtarget AS target
                ON target.receipt_id = receipt.id
               AND target.target_kind = 'template'
               AND target.change_kind = 'published'
             WHERE receipt.catalog_id = NEW.id
               AND receipt.resulting_version = NEW.aggregate_version;
            PERFORM public.maru_assert_registration_template_publication_v1(template_pk);
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
SET TimeZone = 'UTC';

REVOKE ALL ON FUNCTION public.maru_guard_registration_template_catalog_v2()
FROM PUBLIC;

CREATE TRIGGER registration_template_catalog_control_v2_immutable
BEFORE UPDATE OR DELETE
ON public.registration_registrationtemplatecatalogcontrol
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE TRIGGER registration_template_catalog_control_v2_no_truncate
BEFORE TRUNCATE
ON public.registration_registrationtemplatecatalogcontrol
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE CONSTRAINT TRIGGER registration_template_catalog_control_v2_exact
AFTER INSERT OR UPDATE
ON public.registration_registrationtemplatecatalogcontrol
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();

CREATE TRIGGER registration_template_publication_v2_immutable
BEFORE UPDATE OR DELETE
ON public.registration_registrationtemplate
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE TRIGGER registration_template_publication_v2_no_truncate
BEFORE TRUNCATE
ON public.registration_registrationtemplate
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE CONSTRAINT TRIGGER registration_template_publication_v2_exact
AFTER INSERT OR UPDATE
ON public.registration_registrationtemplate
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();

CREATE TRIGGER registration_template_catalog_receipt_v2_immutable
BEFORE UPDATE OR DELETE
ON public.registration_registrationtemplatecatalogcommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE TRIGGER registration_template_catalog_receipt_v2_no_truncate
BEFORE TRUNCATE
ON public.registration_registrationtemplatecatalogcommandreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE CONSTRAINT TRIGGER registration_template_catalog_receipt_v2_exact
AFTER INSERT
ON public.registration_registrationtemplatecatalogcommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();

CREATE TRIGGER registration_template_catalog_target_v2_immutable
BEFORE UPDATE OR DELETE
ON public.registration_registrationtemplatecatalogcommandtarget
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE TRIGGER registration_template_catalog_target_v2_no_truncate
BEFORE TRUNCATE
ON public.registration_registrationtemplatecatalogcommandtarget
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();
CREATE CONSTRAINT TRIGGER registration_template_catalog_target_v2_exact
AFTER INSERT
ON public.registration_registrationtemplatecatalogcommandtarget
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_template_catalog_v2();

CREATE OR REPLACE FUNCTION public.maru_guard_registration_configuration_activation_v2()
RETURNS trigger AS $$
DECLARE
    evidence_count bigint;
BEGIN
    IF NEW.status != 'active' OR NEW.provenance_status != 'complete' THEN
        RETURN NEW;
    END IF;
    SELECT count(*)
      INTO evidence_count
      FROM public.registration_registrationsetupcontrol AS control
      JOIN public.registration_registrationsetupcommandreceipt AS activation
        ON activation.setup_id = control.id
       AND activation.organization_id = NEW.organization_id
       AND activation.edition_id = NEW.edition_id
       AND activation.action = 'configuration_activated'
       AND activation.resulting_version = NEW.last_changed_in_setup_version
       AND activation.retry_key IS NOT NULL
       AND activation.request_digest ~ '^[0-9a-f]{64}$'
      JOIN public.registration_registrationsetupcommandtarget AS activation_target
        ON activation_target.receipt_id = activation.id
       AND activation_target.target_kind = 'configuration'
       AND activation_target.target_id = NEW.id
       AND activation_target.change_kind = 'activated'
       AND activation_target.target_schema_version = NEW.version
       AND activation_target.content_digest = NEW.content_digest
      JOIN public.registration_registrationsetupcommandreceipt AS review
        ON review.setup_id = control.id
       AND review.organization_id = NEW.organization_id
       AND review.edition_id = NEW.edition_id
       AND review.action = 'configuration_reviewed'
       AND review.resulting_version = activation.resulting_version - 1
       AND review.retry_key IS NOT NULL
       AND review.request_digest ~ '^[0-9a-f]{64}$'
      JOIN public.registration_registrationsetupcommandtarget AS review_target
        ON review_target.receipt_id = review.id
       AND review_target.target_kind = 'configuration'
       AND review_target.target_id = NEW.id
       AND review_target.change_kind = 'reviewed'
       AND review_target.target_schema_version = NEW.version
       AND review_target.content_digest = NEW.content_digest
      JOIN public.audit_auditevent AS activation_audit
        ON activation_audit.schema_version = 1
       AND activation_audit.organization_id = NEW.organization_id
       AND activation_audit.event_edition_id = NEW.edition_id
       AND activation_audit.principal_kind = 'account'
       AND activation_audit.principal_id = activation.actor_id
       AND activation_audit.capability_code = 'registration.manage_configuration'
       AND activation_audit.operation = 'registration.setup.configuration_activated'
       AND activation_audit.target_type = 'registration.configuration'
       AND activation_audit.target_id = NEW.id
       AND activation_audit.outcome = 'allow'
       AND activation_audit.correlation_id = activation.correlation_id
       AND activation_audit.source_channel = activation.source_channel
       AND activation_audit.changed_fields = ARRAY['status', 'activated_at']::varchar[]
       AND activation_audit.idempotency_key_hash = pg_catalog.encode(
            pg_catalog.sha256(pg_catalog.convert_to(
                '{"retry_key":"' || activation.retry_key::text || '"}', 'UTF8'
            )), 'hex'
       )
       AND activation_audit.occurred_at = NEW.activated_at
       AND activation_audit.safe_metadata->>'contract_version' =
            'registration-configuration-lifecycle-v1'
       AND activation_audit.safe_metadata->'target_count' = '1'::jsonb
      JOIN public.audit_auditevent AS review_audit
        ON review_audit.schema_version = 1
       AND review_audit.organization_id = NEW.organization_id
       AND review_audit.event_edition_id = NEW.edition_id
       AND review_audit.principal_kind = 'account'
       AND review_audit.principal_id = review.actor_id
       AND review_audit.capability_code = 'registration.manage_configuration'
       AND review_audit.operation = 'registration.setup.configuration_reviewed'
       AND review_audit.target_type = 'registration.configuration'
       AND review_audit.target_id = NEW.id
       AND review_audit.outcome = 'allow'
       AND review_audit.correlation_id = review.correlation_id
       AND review_audit.source_channel = review.source_channel
       AND review_audit.changed_fields = ARRAY['review_state']::varchar[]
       AND review_audit.idempotency_key_hash = pg_catalog.encode(
            pg_catalog.sha256(pg_catalog.convert_to(
                '{"retry_key":"' || review.retry_key::text || '"}', 'UTF8'
            )), 'hex'
       )
       AND review_audit.safe_metadata->>'contract_version' =
            'registration-configuration-lifecycle-v1'
       AND review_audit.safe_metadata->'target_count' = '1'::jsonb
       AND review_audit.occurred_at <= activation_audit.occurred_at
      JOIN public.effects_domainevent AS activation_event
        ON activation_event.event_name = 'registration.configuration.activated.v1'
       AND activation_event.schema_version = 1
       AND activation_event.occurred_at = activation_audit.occurred_at
       AND activation_event.organization_id = NEW.organization_id
       AND activation_event.event_edition_id = NEW.edition_id
       AND activation_event.aggregate_type = 'registration.setup'
       AND activation_event.aggregate_id = control.id
       AND activation_event.aggregate_version = activation.resulting_version
       AND activation_event.payload = pg_catalog.jsonb_build_object(
            'configuration_version', NEW.version::text,
            'source_kind', NEW.origin
       )
       AND activation_event.correlation_id = activation.correlation_id
       AND activation_event.causation_id = activation_audit.id
       AND activation_event.actor_kind = 'account'
       AND activation_event.actor_id = activation.actor_id
       AND activation_event.retention_class = 'registration-restricted'
      JOIN public.effects_outboxmessage AS activation_outbox
        ON activation_outbox.event_id = activation_event.id
       AND activation_outbox.organization_id = NEW.organization_id
       AND activation_outbox.destination = 'internal'
       AND activation_outbox.workload_pool = 'default'
      JOIN public.effects_domainevent AS review_event
        ON review_event.event_name = 'registration.configuration.draft_changed.v1'
       AND review_event.schema_version = 1
       AND review_event.occurred_at = review_audit.occurred_at
       AND review_event.organization_id = NEW.organization_id
       AND review_event.event_edition_id = NEW.edition_id
       AND review_event.aggregate_type = 'registration.setup'
       AND review_event.aggregate_id = control.id
       AND review_event.aggregate_version = review.resulting_version
       AND review_event.payload = pg_catalog.jsonb_build_object(
            'action', 'configuration_reviewed',
            'configuration_version', NEW.version::text
       )
       AND review_event.correlation_id = review.correlation_id
       AND review_event.causation_id = review_audit.id
       AND review_event.actor_kind = 'account'
       AND review_event.actor_id = review.actor_id
       AND review_event.retention_class = 'registration-restricted'
      JOIN public.effects_outboxmessage AS review_outbox
        ON review_outbox.event_id = review_event.id
       AND review_outbox.organization_id = NEW.organization_id
       AND review_outbox.destination = 'internal'
       AND review_outbox.workload_pool = 'default'
     WHERE control.organization_id = NEW.organization_id
       AND control.edition_id = NEW.edition_id
       AND control.origin = NEW.origin
       AND control.provenance_status = 'complete'
       AND control.aggregate_version >= activation.resulting_version
       AND NEW.review_required = false
       AND NEW.activated_at IS NOT NULL
       AND NEW.content_digest ~ '^[0-9a-f]{64}$'
       AND NOT EXISTS (
            SELECT 1
              FROM public.registration_registrationsetupcommandtarget AS extra
             WHERE extra.receipt_id = activation.id
               AND extra.id != activation_target.id
       )
       AND NOT EXISTS (
            SELECT 1
              FROM public.registration_registrationsetupcommandtarget AS extra
             WHERE extra.receipt_id = review.id
               AND extra.id != review_target.id
       );
    IF evidence_count != 1 THEN
        RAISE EXCEPTION 'registration configuration activation evidence is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
SET TimeZone = 'UTC';

REVOKE ALL ON FUNCTION public.maru_guard_registration_configuration_activation_v2()
FROM PUBLIC;

CREATE CONSTRAINT TRIGGER registration_configuration_activation_v2_exact
AFTER INSERT OR UPDATE
ON public.registration_registrationconfiguration
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_guard_registration_configuration_activation_v2();

-- Installing a deferred trigger does not inspect rows that already exist.
-- Prove every complete published/retired template and active configuration
-- while the migration still owns an exclusive, transaction-scoped cutover.
-- A failed proof rolls the complete migration back, including trigger state.
DO $$
DECLARE
    candidate record;
BEGIN
    FOR candidate IN
        SELECT id
          FROM public.registration_registrationtemplate
         WHERE provenance_status = 'complete'
           AND status IN ('published', 'retired')
         ORDER BY id
    LOOP
        PERFORM public.maru_assert_registration_template_publication_v1(
            candidate.id
        );
    END LOOP;
END;
$$;

ALTER TABLE public.registration_registrationconfiguration
DISABLE TRIGGER registration_configuration_scope_and_version_guard;

UPDATE public.registration_registrationconfiguration
   SET updated_at = updated_at
 WHERE provenance_status = 'complete'
   AND status = 'active';

SET CONSTRAINTS registration_configuration_activation_v2_exact IMMEDIATE;
SET CONSTRAINTS registration_configuration_activation_v2_exact DEFERRED;

ALTER TABLE public.registration_registrationconfiguration
ENABLE TRIGGER registration_configuration_scope_and_version_guard;
"""


REVERSE_SQL = r"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.registration_registrationtemplatecatalogcommandreceipt
         WHERE action = 'template_published'
    ) OR EXISTS (
        SELECT 1
          FROM public.registration_registrationsetupcommandreceipt
         WHERE action = 'configuration_activated'
    ) THEN
        RAISE EXCEPTION
            'cannot reverse populated template/lifecycle evidence; use fix-forward recovery'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS registration_configuration_activation_v2_exact
ON public.registration_registrationconfiguration;
DROP TRIGGER IF EXISTS registration_template_catalog_target_v2_exact
ON public.registration_registrationtemplatecatalogcommandtarget;
DROP TRIGGER IF EXISTS registration_template_catalog_target_v2_no_truncate
ON public.registration_registrationtemplatecatalogcommandtarget;
DROP TRIGGER IF EXISTS registration_template_catalog_target_v2_immutable
ON public.registration_registrationtemplatecatalogcommandtarget;
DROP TRIGGER IF EXISTS registration_template_catalog_receipt_v2_exact
ON public.registration_registrationtemplatecatalogcommandreceipt;
DROP TRIGGER IF EXISTS registration_template_catalog_receipt_v2_no_truncate
ON public.registration_registrationtemplatecatalogcommandreceipt;
DROP TRIGGER IF EXISTS registration_template_catalog_receipt_v2_immutable
ON public.registration_registrationtemplatecatalogcommandreceipt;
DROP TRIGGER IF EXISTS registration_template_publication_v2_exact
ON public.registration_registrationtemplate;
DROP TRIGGER IF EXISTS registration_template_publication_v2_no_truncate
ON public.registration_registrationtemplate;
DROP TRIGGER IF EXISTS registration_template_publication_v2_immutable
ON public.registration_registrationtemplate;
DROP TRIGGER IF EXISTS registration_template_catalog_control_v2_exact
ON public.registration_registrationtemplatecatalogcontrol;
DROP TRIGGER IF EXISTS registration_template_catalog_control_v2_no_truncate
ON public.registration_registrationtemplatecatalogcontrol;
DROP TRIGGER IF EXISTS registration_template_catalog_control_v2_immutable
ON public.registration_registrationtemplatecatalogcontrol;
DROP FUNCTION IF EXISTS public.maru_guard_registration_configuration_activation_v2();
DROP FUNCTION IF EXISTS public.maru_guard_registration_template_catalog_v2();
DROP FUNCTION IF EXISTS public.maru_assert_registration_template_publication_v1(uuid);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("registration", "0036_profile_extension_value_commands"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
