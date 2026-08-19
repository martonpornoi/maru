"""Protect immutable charity scope and append-only review evidence."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_prevent_charity_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'charity evidence is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_charity_partner_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'charity partners require lifecycle retirement'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
    THEN
        RAISE EXCEPTION 'charity partner identity and tenant scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_charity_media_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'charity media requires governed withdrawal'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.partner_id IS DISTINCT FROM OLD.partner_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.source_reference IS DISTINCT FROM OLD.source_reference
       OR NEW.owner_name IS DISTINCT FROM OLD.owner_name
       OR NEW.license_basis IS DISTINCT FROM OLD.license_basis
       OR NEW.usage_scope IS DISTINCT FROM OLD.usage_scope
       OR NEW.attribution IS DISTINCT FROM OLD.attribution
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
       OR NEW.submitted_by_id IS DISTINCT FROM OLD.submitted_by_id
    THEN
        RAISE EXCEPTION 'charity media provenance is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_charity_selection_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'charity selections are retained with their edition'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
       OR NEW.responsible_department_id IS DISTINCT FROM OLD.responsible_department_id
       OR NEW.partner_id IS DISTINCT FROM OLD.partner_id
       OR NEW.proposed_by_id IS DISTINCT FROM OLD.proposed_by_id
    THEN
        RAISE EXCEPTION 'charity selection identity and exact scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_require_charity_selection_binding()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM public.authorization_scopedresourcebinding AS binding
         WHERE binding.resource_kind = 'charity.selection'
           AND binding.resource_id = NEW.id
           AND binding.organization_id = NEW.organization_id
           AND binding.edition_id = NEW.edition_id
           AND binding.department_id = NEW.responsible_department_id
    ) THEN
        RAISE EXCEPTION 'charity selection requires its exact resource binding'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER charity_partner_scope_immutable
BEFORE UPDATE OR DELETE ON public.charities_charitypartner
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_charity_partner_mutation();

CREATE TRIGGER charity_media_provenance_immutable
BEFORE UPDATE OR DELETE ON public.charities_charitypartnermedia
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_charity_media_mutation();

CREATE TRIGGER charity_selection_scope_immutable
BEFORE UPDATE OR DELETE ON public.charities_charityselection
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_charity_selection_mutation();

CREATE TRIGGER charity_timeline_append_only
BEFORE UPDATE OR DELETE ON public.charities_charityselectiontimelineentry
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_charity_evidence_mutation();

CREATE TRIGGER charity_publication_append_only
BEFORE UPDATE OR DELETE ON public.charities_charitypublicationsnapshot
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_charity_evidence_mutation();

CREATE TRIGGER charity_receipt_append_only
BEFORE UPDATE OR DELETE ON public.charities_charitycommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_charity_evidence_mutation();

CREATE CONSTRAINT TRIGGER charity_selection_binding_required
AFTER INSERT ON public.charities_charityselection
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_charity_selection_binding();

REVOKE ALL ON FUNCTION public.maru_prevent_charity_evidence_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_charity_partner_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_charity_media_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_charity_selection_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_require_charity_selection_binding() FROM PUBLIC;
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS charity_selection_binding_required
ON public.charities_charityselection;
DROP TRIGGER IF EXISTS charity_receipt_append_only
ON public.charities_charitycommandreceipt;
DROP TRIGGER IF EXISTS charity_publication_append_only
ON public.charities_charitypublicationsnapshot;
DROP TRIGGER IF EXISTS charity_timeline_append_only
ON public.charities_charityselectiontimelineentry;
DROP TRIGGER IF EXISTS charity_selection_scope_immutable
ON public.charities_charityselection;
DROP TRIGGER IF EXISTS charity_media_provenance_immutable
ON public.charities_charitypartnermedia;
DROP TRIGGER IF EXISTS charity_partner_scope_immutable
ON public.charities_charitypartner;
DROP FUNCTION IF EXISTS public.maru_require_charity_selection_binding();
DROP FUNCTION IF EXISTS public.maru_guard_charity_selection_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_charity_media_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_charity_partner_mutation();
DROP FUNCTION IF EXISTS public.maru_prevent_charity_evidence_mutation();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0013_charity_capabilities_and_resource_kind"),
        ("charities", "0001_initial"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
