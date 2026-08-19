# ruff: noqa: E501

from typing import ClassVar

from django.db import migrations, models
from django.db.models import Q

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_guard_registration_configuration_binding()
RETURNS trigger AS $$
DECLARE
    binding_payload text;
    binding_digest text;
    control_id uuid;
    control_version bigint;
    expected_action varchar;
    matching_evidence bigint;
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        IF public.maru_authority_provenance_test_reset_allowed() THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'registration configuration binding cannot be truncated'
            USING ERRCODE = '23514';
    END IF;

    IF TG_WHEN = 'BEFORE' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'registration configurations use retirement'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.version IS DISTINCT FROM OLD.version
           OR NEW.source_template_id IS DISTINCT FROM OLD.source_template_id
           OR NEW.source_edition_id IS DISTINCT FROM OLD.source_edition_id
           OR NEW.source_configuration_id IS DISTINCT FROM OLD.source_configuration_id
           OR NEW.origin IS DISTINCT FROM OLD.origin
           OR NEW.provenance_status IS DISTINCT FROM OLD.provenance_status
           OR NEW.source_version IS DISTINCT FROM OLD.source_version
           OR NEW.source_content_digest IS DISTINCT FROM OLD.source_content_digest
           OR NEW.source_imported_at IS DISTINCT FROM OLD.source_imported_at
           OR NEW.source_imported_by_id IS DISTINCT FROM OLD.source_imported_by_id
           OR NEW.created_in_setup_version IS DISTINCT FROM OLD.created_in_setup_version
           OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
        THEN
            RAISE EXCEPTION 'registration configuration source binding is immutable'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.provenance_status != 'complete' THEN
        RETURN NEW;
    END IF;

    SELECT control.id, control.aggregate_version
      INTO control_id, control_version
      FROM registration_registrationsetupcontrol AS control
     WHERE control.organization_id = NEW.organization_id
       AND control.edition_id = NEW.edition_id
       AND control.origin = NEW.origin
       AND control.provenance_status = 'complete';
    IF control_id IS NULL
       OR NEW.created_in_setup_version IS NULL
       OR control_version < NEW.created_in_setup_version
    THEN
        RAISE EXCEPTION 'registration configuration lacks its exact setup control'
            USING ERRCODE = '23514';
    END IF;

    binding_payload :=
        '{"configuration_id":' || pg_catalog.to_json(NEW.id)::text ||
        ',"contract":"maru.registration-configuration-source-binding.v1"' ||
        ',"edition_id":' || pg_catalog.to_json(NEW.edition_id)::text ||
        ',"organization_id":' || pg_catalog.to_json(NEW.organization_id)::text ||
        ',"origin":' || pg_catalog.to_json(NEW.origin)::text ||
        ',"source_configuration_id":' ||
            COALESCE(pg_catalog.to_json(NEW.source_configuration_id)::text, 'null') ||
        ',"source_content_digest":' ||
            pg_catalog.to_json(NEW.source_content_digest)::text ||
        ',"source_edition_id":' ||
            COALESCE(pg_catalog.to_json(NEW.source_edition_id)::text, 'null') ||
        ',"source_imported_at":' ||
            COALESCE(
                CASE
                    WHEN (
                        pg_catalog.date_part(
                            'microseconds',
                            NEW.source_imported_at
                        )::bigint % 1000000
                    ) = 0
                    THEN pg_catalog.to_json(
                        pg_catalog.to_char(
                            NEW.source_imported_at AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS'
                        ) || '+00:00'
                    )::text
                    ELSE pg_catalog.to_json(
                        pg_catalog.to_char(
                            NEW.source_imported_at AT TIME ZONE 'UTC',
                            'YYYY-MM-DD"T"HH24:MI:SS.US'
                        ) || '+00:00'
                    )::text
                END,
                'null'
            ) ||
        ',"source_imported_by_id":' ||
            COALESCE(pg_catalog.to_json(NEW.source_imported_by_id)::text, 'null') ||
        ',"source_template_id":' ||
            COALESCE(pg_catalog.to_json(NEW.source_template_id)::text, 'null') ||
        ',"source_version":' ||
            COALESCE(pg_catalog.to_json(NEW.source_version)::text, 'null') ||
        '}';
    binding_digest := pg_catalog.encode(
        pg_catalog.sha256(pg_catalog.convert_to(binding_payload, 'UTF8')),
        'hex'
    );
    expected_action := CASE
        WHEN NEW.origin = 'successor' THEN 'successor_started'
        ELSE 'setup_started'
    END;

    SELECT count(*)
      INTO matching_evidence
      FROM registration_registrationsetupcommandreceipt AS receipt
      JOIN registration_registrationsetupcommandtarget AS target
        ON target.receipt_id = receipt.id
      JOIN audit_auditevent AS audit
        ON audit.schema_version = 1
       AND audit.organization_id = NEW.organization_id
       AND audit.event_edition_id = NEW.edition_id
       AND audit.principal_kind = 'account'
       AND audit.principal_id = receipt.actor_id
       AND audit.capability_code = 'registration.manage_configuration'
       AND audit.operation = 'registration.setup.started'
       AND audit.target_type = 'registration.setup'
       AND audit.target_id = control_id
       AND audit.outcome = 'allow'
       AND audit.correlation_id = receipt.correlation_id
       AND audit.source_channel = receipt.source_channel
       AND audit.changed_fields @>
            ARRAY['configuration', 'provenance']::varchar[]
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
            'registration-setup-start-v1'
       AND audit.safe_metadata->>'policy_version' ~
            '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[1-9][0-9]*$'
       AND audit.safe_metadata->'target_count' = pg_catalog.to_jsonb(
            (
                SELECT count(*)
                  FROM registration_registrationsetupcommandtarget AS counted
                 WHERE counted.receipt_id = receipt.id
            )
       )
       AND (
            SELECT count(*)
              FROM pg_catalog.jsonb_object_keys(audit.safe_metadata)
       ) = 3
       AND (
            NEW.origin = 'blank'
            OR audit.occurred_at = NEW.source_imported_at
       )
      JOIN effects_domainevent AS event
        ON event.event_name = 'registration.configuration.draft_created.v1'
       AND event.schema_version = 1
       AND event.occurred_at = audit.occurred_at
       AND event.organization_id = NEW.organization_id
       AND event.event_edition_id = NEW.edition_id
       AND event.aggregate_type = 'registration.setup'
       AND event.aggregate_id = control_id
       AND event.aggregate_version = receipt.resulting_version
       AND event.payload = pg_catalog.jsonb_build_object(
            'configuration_version', NEW.version::text,
            'source_kind', NEW.origin
       )
       AND event.correlation_id = receipt.correlation_id
       AND event.causation_id = audit.id
       AND event.actor_kind = 'account'
       AND event.actor_id = receipt.actor_id
       AND event.retention_class = 'registration-restricted'
      JOIN effects_outboxmessage AS outbox
        ON outbox.event_id = event.id
       AND outbox.organization_id = NEW.organization_id
       AND outbox.destination = 'internal'
       AND outbox.workload_pool = 'default'
     WHERE receipt.setup_id = control_id
       AND receipt.organization_id = NEW.organization_id
       AND receipt.edition_id = NEW.edition_id
       AND receipt.action = expected_action
       AND receipt.resulting_version = NEW.created_in_setup_version
       AND receipt.actor_id = NEW.created_by_id
       AND receipt.retry_key IS NOT NULL
       AND receipt.request_digest ~ '^[0-9a-f]{64}$'
       AND target.target_kind = 'configuration'
       AND target.target_id = NEW.id
       AND target.change_kind = 'created'
       AND target.target_schema_version = NEW.version
       AND target.content_digest = binding_digest
       AND NOT EXISTS (
            SELECT 1
              FROM registration_registrationsetupcommandtarget AS extra
             WHERE extra.receipt_id = receipt.id
               AND extra.target_kind = 'configuration'
               AND extra.id != target.id
       );
    IF matching_evidence != 1 THEN
        RAISE EXCEPTION 'registration configuration setup binding is incomplete'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
SET TimeZone = 'UTC';

REVOKE ALL ON FUNCTION public.maru_guard_registration_configuration_binding()
FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.maru_guard_registration_setup_control_binding()
RETURNS trigger AS $$
DECLARE
    matching_configurations bigint;
BEGIN
    IF TG_OP = 'TRUNCATE' THEN
        IF public.maru_authority_provenance_test_reset_allowed() THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'registration setup control binding cannot be truncated'
            USING ERRCODE = '23514';
    END IF;

    IF TG_WHEN = 'BEFORE' THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'registration setup controls are retained evidence'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.origin IS DISTINCT FROM OLD.origin
           OR NEW.provenance_status IS DISTINCT FROM OLD.provenance_status
        THEN
            RAISE EXCEPTION 'registration setup control source binding is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.aggregate_version < OLD.aggregate_version THEN
            RAISE EXCEPTION 'registration setup version cannot move backwards'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.provenance_status != 'complete' THEN
        RETURN NEW;
    END IF;
    SELECT count(*)
      INTO matching_configurations
      FROM registration_registrationconfiguration AS configuration
     WHERE configuration.organization_id = NEW.organization_id
       AND configuration.edition_id = NEW.edition_id
       AND configuration.origin = NEW.origin
       AND configuration.provenance_status = 'complete'
       AND configuration.created_in_setup_version IS NOT NULL
       AND configuration.created_in_setup_version <= NEW.aggregate_version;
    IF matching_configurations < 1 THEN
        RAISE EXCEPTION 'registration setup control lacks its source configuration'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_guard_registration_setup_control_binding()
FROM PUBLIC;

DROP TRIGGER IF EXISTS registration_configuration_binding_immutable
ON registration_registrationconfiguration;
CREATE TRIGGER registration_configuration_binding_immutable
BEFORE UPDATE OR DELETE ON registration_registrationconfiguration
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_configuration_binding();

DROP TRIGGER IF EXISTS registration_configuration_binding_no_truncate
ON registration_registrationconfiguration;
CREATE TRIGGER registration_configuration_binding_no_truncate
BEFORE TRUNCATE ON registration_registrationconfiguration
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_registration_configuration_binding();

DROP TRIGGER IF EXISTS registration_configuration_setup_binding_exact
ON registration_registrationconfiguration;
CREATE CONSTRAINT TRIGGER registration_configuration_setup_binding_exact
AFTER INSERT OR UPDATE ON registration_registrationconfiguration
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_configuration_binding();

DROP TRIGGER IF EXISTS registration_setup_control_binding_immutable
ON registration_registrationsetupcontrol;
CREATE TRIGGER registration_setup_control_binding_immutable
BEFORE UPDATE OR DELETE ON registration_registrationsetupcontrol
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_setup_control_binding();

DROP TRIGGER IF EXISTS registration_setup_control_binding_no_truncate
ON registration_registrationsetupcontrol;
CREATE TRIGGER registration_setup_control_binding_no_truncate
BEFORE TRUNCATE ON registration_registrationsetupcontrol
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_registration_setup_control_binding();

DROP TRIGGER IF EXISTS registration_setup_control_configuration_exact
ON registration_registrationsetupcontrol;
CREATE CONSTRAINT TRIGGER registration_setup_control_configuration_exact
AFTER INSERT OR UPDATE ON registration_registrationsetupcontrol
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_registration_setup_control_binding();

-- Revalidate complete rows that predate this migration. The existing
-- configuration guard rejects no-op updates to active rows, so disable that
-- one guard only while ACCESS EXCLUSIVE ALTER TABLE locks exclude concurrent
-- writers. PostgreSQL rolls the trigger state back with the migration if any
-- immediate or deferred validation fails.
ALTER TABLE registration_registrationconfiguration
DISABLE TRIGGER registration_configuration_scope_and_version_guard;

UPDATE registration_registrationconfiguration
   SET updated_at = updated_at
 WHERE provenance_status = 'complete';

SET CONSTRAINTS registration_configuration_setup_binding_exact IMMEDIATE;
SET CONSTRAINTS registration_configuration_setup_binding_exact DEFERRED;

ALTER TABLE registration_registrationconfiguration
ENABLE TRIGGER registration_configuration_scope_and_version_guard;

UPDATE registration_registrationsetupcontrol
   SET updated_at = updated_at
 WHERE provenance_status = 'complete';

SET CONSTRAINTS registration_setup_control_configuration_exact IMMEDIATE;
SET CONSTRAINTS registration_setup_control_configuration_exact DEFERRED;
"""


REVERSE_SQL = r"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM registration_registrationconfiguration
         WHERE provenance_status = 'complete'
    ) OR EXISTS (
        SELECT 1
          FROM registration_registrationsetupcontrol
         WHERE provenance_status = 'complete'
    ) THEN
        RAISE EXCEPTION
            'cannot reverse populated configuration source bindings; use fix-forward recovery'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER IF EXISTS registration_setup_control_configuration_exact
ON registration_registrationsetupcontrol;
DROP TRIGGER IF EXISTS registration_setup_control_binding_no_truncate
ON registration_registrationsetupcontrol;
DROP TRIGGER IF EXISTS registration_setup_control_binding_immutable
ON registration_registrationsetupcontrol;
DROP TRIGGER IF EXISTS registration_configuration_setup_binding_exact
ON registration_registrationconfiguration;
DROP TRIGGER IF EXISTS registration_configuration_binding_no_truncate
ON registration_registrationconfiguration;
DROP TRIGGER IF EXISTS registration_configuration_binding_immutable
ON registration_registrationconfiguration;
DROP FUNCTION IF EXISTS public.maru_guard_registration_setup_control_binding();
DROP FUNCTION IF EXISTS public.maru_guard_registration_configuration_binding();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("registration", "0034_profile_extension_definition_lifecycle"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.AddConstraint(
            model_name="registrationconfiguration",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(provenance_status="complete")
                    | (
                        Q(content_digest__regex=r"^[0-9a-f]{64}$")
                        & Q(created_in_setup_version__isnull=False)
                        & Q(last_changed_in_setup_version__isnull=False)
                        & (
                            Q(
                                origin="blank",
                                source_template__isnull=True,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=True,
                                source_content_digest="",
                                source_imported_at__isnull=True,
                                source_imported_by__isnull=True,
                            )
                            | Q(
                                origin="published_template",
                                source_template__isnull=False,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                            | Q(
                                origin__in=("prior_edition", "successor"),
                                source_template__isnull=True,
                                source_edition__isnull=False,
                                source_configuration__isnull=False,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                        )
                    )
                ),
                name="reg_configuration_complete_provenance_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="registrationsetupcontrol",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(provenance_status="complete") | ~Q(origin="legacy_existing")
                ),
                name="reg_setup_complete_origin_nonlegacy",
            ),
        ),
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
