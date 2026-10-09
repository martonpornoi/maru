"""Bind standalone setup receipts to exact owner and same-transaction audit evidence."""

from typing import ClassVar
from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_announcements_setup_receipt_guard()
RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'Announcements setup receipts are append-only'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.idempotency_key = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.correlation_id = '00000000-0000-0000-0000-000000000000'::uuid
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR btrim(NEW.reason) = ''
       OR NEW.reason ~ '[[:cntrl:]]'
    THEN
        RAISE EXCEPTION 'Announcements setup requires an exact key and accountable reason'
            USING ERRCODE = '23514';
    END IF;

    -- Existing representation commands lock the representation before its parent.
    PERFORM 1 FROM public.organizations_organizationrepresentation AS representation
     WHERE representation.id = NEW.representation_id
       AND representation.organization_id = NEW.organization_id
       AND representation.aggregate_version = NEW.representation_version
       AND representation.code IN ('executive_board', 'announcements_operators')
       AND representation.state IN ('provisioning', 'active')
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Announcements setup representation is unavailable or stale'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.organizations_organization AS organization
      JOIN public.organizations_organizationrepresentation AS representation
        ON representation.id = NEW.representation_id
     WHERE organization.id = NEW.organization_id
       AND organization.slug = NEW.organization_slug
       AND ((organization.lifecycle = 'draft' AND representation.state = 'provisioning')
         OR (organization.lifecycle = 'active' AND representation.state = 'active'))
     FOR SHARE OF organization;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Announcements setup organization accountability does not match'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.organizations_conventionseries AS series
     WHERE series.id = NEW.series_id AND series.organization_id = NEW.organization_id
       AND series.is_active FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Announcements setup series is outside the active foundation'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.events_eventedition AS edition
     WHERE edition.id = NEW.edition_id AND edition.organization_id = NEW.organization_id
       AND edition.series_id = NEW.series_id AND edition.lifecycle = 'draft'
       AND edition.aggregate_version = 1
       AND edition.adoption_profile_code = 'announcements_only'
       AND edition.adoption_profile_version = 1
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Announcements setup requires its exact new profile edition'
            USING ERRCODE = '23514';
    END IF;
    PERFORM 1 FROM public.identity_account AS actor
     WHERE actor.id = NEW.actor_id AND actor.is_active
       AND actor.account_kind = 'platform_administrator'
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Announcements setup requires current platform administration'
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
        RAISE EXCEPTION 'Announcements setup edition creation evidence does not match'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.audit_auditevent AS audit
          JOIN public.audit_auditnativemutationwitness AS witness
            ON witness.audit_event_id = audit.id
           AND witness.transaction_stamp = public.maru_audit_current_native_transaction_stamp()
         WHERE audit.id = NEW.source_audit_id AND audit.principal_kind = 'account'
           AND audit.principal_id = NEW.actor_id AND audit.principal_context_id IS NULL
           AND audit.organization_id = NEW.organization_id
           AND audit.event_edition_id = NEW.edition_id
           AND audit.operation = 'events.announcements_adoption.setup'
           AND audit.capability_code = 'events.create'
           AND audit.target_type = 'events.announcements_setup_receipt'
           AND audit.target_id = NEW.id
           AND audit.outcome = 'allow' AND audit.reason_code = 'platform_administration'
           AND audit.correlation_id = NEW.correlation_id
           AND audit.source_channel = NEW.source_channel
           AND audit.retention_class = 'security-standard'
    ) THEN
        RAISE EXCEPTION 'Announcements setup audit evidence does not match'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_announcements_setup_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.events_announcementsadoptionsetupreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_announcements_setup_receipt_guard();

CREATE FUNCTION public.maru_announcements_setup_refuse_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Announcements setup receipts cannot be truncated'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_announcements_setup_no_truncate
BEFORE TRUNCATE ON public.events_announcementsadoptionsetupreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_announcements_setup_refuse_truncate();

REVOKE ALL ON FUNCTION public.maru_announcements_setup_receipt_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_announcements_setup_refuse_truncate() FROM PUBLIC;
"""

REVERSE_SQL = r"""
DROP TRIGGER events_announcements_setup_no_truncate
    ON public.events_announcementsadoptionsetupreceipt;
DROP TRIGGER events_announcements_setup_receipt_guard
    ON public.events_announcementsadoptionsetupreceipt;
DROP FUNCTION public.maru_announcements_setup_refuse_truncate();
DROP FUNCTION public.maru_announcements_setup_receipt_guard();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0019_announcements_adoption_profile")
    ]
    operations: ClassVar[list[object]] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
