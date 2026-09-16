"""Bind setup receipts to exact owner evidence; retain history without activation."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_programme_setup_receipt_guard()
RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Programme setup receipts are append-only'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.idempotency_key = '00000000-0000-0000-0000-000000000000'::uuid
       OR btrim(NEW.reason) = ''
       OR NEW.reason ~ '[[:cntrl:]]'
    THEN
        RAISE EXCEPTION 'Programme setup requires an exact key and accountable reason'
            USING ERRCODE = '23514';
    END IF;

    -- Existing representation commands lock the representation before its parent.
    PERFORM 1 FROM public.organizations_organizationrepresentation AS representation
     WHERE representation.id = NEW.representation_id
       AND representation.organization_id = NEW.organization_id
       AND representation.aggregate_version = NEW.representation_version
       AND representation.code IN ('executive_board', 'maru_operators')
       AND representation.state IN ('provisioning', 'active')
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Programme setup representation is unavailable or stale'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.organizations_organization AS organization
      JOIN public.organizations_organizationrepresentation AS representation
        ON representation.id = NEW.representation_id
     WHERE organization.id = NEW.organization_id
       AND ((organization.lifecycle = 'draft' AND representation.state = 'provisioning')
         OR (organization.lifecycle = 'active' AND representation.state = 'active'))
     FOR SHARE OF organization;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Programme setup organization accountability does not match'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.organizations_conventionseries AS series
     WHERE series.id = NEW.series_id AND series.organization_id = NEW.organization_id
       AND series.is_active FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Programme setup series is outside the active foundation'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.events_eventedition AS edition
     WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
       AND edition.series_id = NEW.series_id AND edition.lifecycle = 'draft'
       AND edition.aggregate_version = 1
       AND edition.adoption_profile_code = 'programme_operations'
       AND edition.adoption_profile_version = 1
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Programme setup requires its exact new dormant-profile edition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.workforce_department AS department
     WHERE department.id = NEW.department_id
       AND department.organization_id = NEW.organization_id
       AND department.edition_id = NEW.edition_id
       AND department.parent_id IS NULL AND department.retired_at IS NULL
       AND department.created_in_structure_version = 1
       AND department.last_changed_in_structure_version = 1
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Programme setup requires its exact first Department'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.identity_account AS actor
     WHERE actor.id = NEW.actor_id AND actor.is_active
       AND actor.account_kind = 'platform_administrator'
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Programme setup requires current platform administration'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.events_editioncreationreceipt AS creation
         WHERE creation.id = NEW.edition_creation_id
           AND creation.edition_id = NEW.edition_id
           AND creation.organization_id = NEW.organization_id
           AND creation.series_id = NEW.series_id
           AND creation.actor_id = NEW.actor_id
           AND creation.idempotency_key = NEW.idempotency_key
    ) THEN
        RAISE EXCEPTION 'Programme setup edition creation evidence does not match'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.workforce_editionstructurecommandreceipt AS creation
         WHERE creation.id = NEW.department_creation_id
           AND creation.edition_id = NEW.edition_id
           AND creation.organization_id = NEW.organization_id
           AND creation.actor_id = NEW.actor_id
           AND creation.retry_key = NEW.idempotency_key
           AND creation.resulting_version = 1
           AND creation.action = 'department_created'
           AND creation.affected_department_ids = ARRAY[NEW.department_id]::uuid[]
           AND creation.affected_position_id IS NULL AND creation.reason = NEW.reason
    ) THEN
        RAISE EXCEPTION 'Programme setup Department creation evidence does not match'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent AS audit
          JOIN public.workforce_editionstructurecommandreceipt AS creation
            ON creation.id = NEW.department_creation_id
         WHERE audit.id = NEW.source_audit_id AND audit.principal_kind = 'account'
           AND audit.principal_id = NEW.actor_id AND audit.principal_context_id IS NULL
           AND audit.organization_id = NEW.organization_id
           AND audit.event_edition_id = NEW.edition_id
           AND audit.operation = 'events.programme_adoption.setup'
           AND audit.capability_code = 'events.create'
           AND audit.target_type = 'events.programme_setup_receipt'
           AND audit.target_id = NEW.id
           AND audit.outcome = 'allow' AND audit.reason_code = 'platform_administration'
           AND audit.correlation_id = creation.correlation_id
           AND audit.source_channel = creation.source_channel
           AND audit.retention_class = 'security-standard'
    ) THEN
        RAISE EXCEPTION 'Programme setup audit evidence does not match'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_programme_setup_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.events_programmeadoptionsetupreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_setup_receipt_guard();

CREATE FUNCTION public.maru_programme_setup_refuse_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Programme setup receipts cannot be truncated'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_programme_setup_no_truncate
BEFORE TRUNCATE ON public.events_programmeadoptionsetupreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_programme_setup_refuse_truncate();

REVOKE ALL ON FUNCTION public.maru_programme_setup_receipt_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_programme_setup_refuse_truncate() FROM PUBLIC;
"""

REVERSE_SQL = r"""
DROP TRIGGER events_programme_setup_no_truncate
    ON public.events_programmeadoptionsetupreceipt;
DROP TRIGGER events_programme_setup_receipt_guard
    ON public.events_programmeadoptionsetupreceipt;
DROP FUNCTION public.maru_programme_setup_refuse_truncate();
DROP FUNCTION public.maru_programme_setup_receipt_guard();
"""


class Migration(migrations.Migration):
    """Install exact provenance guards without changing existing profile meanings."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0012_programme_setup_receipt"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
