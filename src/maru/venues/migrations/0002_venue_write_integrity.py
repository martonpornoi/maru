"""Protect immutable venue scope, occupancy, and append-only evidence."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_prevent_venue_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'venue evidence is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_venue_property_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'venue properties require lifecycle retirement'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
    THEN
        RAISE EXCEPTION 'venue property identity and tenant scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_venue_media_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'venue media requires governed withdrawal'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.property_id IS DISTINCT FROM OLD.property_id
       OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.source_reference IS DISTINCT FROM OLD.source_reference
       OR NEW.owner_name IS DISTINCT FROM OLD.owner_name
       OR NEW.license_basis IS DISTINCT FROM OLD.license_basis
       OR NEW.usage_scope IS DISTINCT FROM OLD.usage_scope
       OR NEW.attribution IS DISTINCT FROM OLD.attribution
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
       OR NEW.submitted_by_id IS DISTINCT FROM OLD.submitted_by_id
    THEN
        RAISE EXCEPTION 'venue media provenance is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_venue_layout_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'venue layouts require governed withdrawal'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.space_id IS DISTINCT FROM OLD.space_id
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.visibility IS DISTINCT FROM OLD.visibility
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.checksum_sha256 IS DISTINCT FROM OLD.checksum_sha256
       OR NEW.source_reference IS DISTINCT FROM OLD.source_reference
       OR NEW.submitted_by_id IS DISTINCT FROM OLD.submitted_by_id
    THEN
        RAISE EXCEPTION 'venue layout provenance is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_edition_venue_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'edition venues are retained with their edition'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
       OR NEW.property_id IS DISTINCT FROM OLD.property_id
       OR NEW.responsible_department_id IS DISTINCT FROM OLD.responsible_department_id
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
    THEN
        RAISE EXCEPTION 'edition venue identity and exact scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_edition_space_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'edition spaces are retained with their edition'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
       OR NEW.venue_selection_id IS DISTINCT FROM OLD.venue_selection_id
       OR NEW.responsible_department_id IS DISTINCT FROM OLD.responsible_department_id
       OR NEW.source_space_id IS DISTINCT FROM OLD.source_space_id
       OR NEW.source_combination_id IS DISTINCT FROM OLD.source_combination_id
       OR NEW.selected_configuration_id IS DISTINCT FROM OLD.selected_configuration_id
    THEN
        RAISE EXCEPTION 'edition space identity, source, and exact scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_venue_booking_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'venue bookings require lifecycle cancellation'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
       OR NEW.space_selection_id IS DISTINCT FROM OLD.space_selection_id
       OR NEW.responsible_department_id IS DISTINCT FROM OLD.responsible_department_id
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
    THEN
        RAISE EXCEPTION 'venue booking identity and exact scope are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_venue_occupancy_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'venue occupancy is retained as scheduling evidence'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.booking_id IS DISTINCT FROM OLD.booking_id
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
       OR NEW.source_space_id IS DISTINCT FROM OLD.source_space_id
       OR NEW.conflict_group IS DISTINCT FROM OLD.conflict_group
       OR NEW.occupied_range IS DISTINCT FROM OLD.occupied_range
       OR NEW.booking_version IS DISTINCT FROM OLD.booking_version
       OR (OLD.active = FALSE AND NEW.active = TRUE)
    THEN
        RAISE EXCEPTION 'venue occupancy identity is immutable and cannot reactivate'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_require_edition_space_binding()
RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM public.authorization_scopedresourcebinding AS binding
         WHERE binding.resource_kind = 'venue.edition_space'
           AND binding.resource_id = NEW.id
           AND binding.organization_id = NEW.organization_id
           AND binding.edition_id = NEW.edition_id
           AND binding.department_id = NEW.responsible_department_id
    ) THEN
        RAISE EXCEPTION 'edition space requires its exact resource binding'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER venue_property_scope_immutable
BEFORE UPDATE OR DELETE ON public.venues_venueproperty
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_venue_property_mutation();

CREATE TRIGGER venue_media_provenance_immutable
BEFORE UPDATE OR DELETE ON public.venues_venuepropertymedia
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_venue_media_mutation();

CREATE TRIGGER venue_layout_provenance_immutable
BEFORE UPDATE OR DELETE ON public.venues_venuelayoutversion
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_venue_layout_mutation();

CREATE TRIGGER venue_edition_selection_scope_immutable
BEFORE UPDATE OR DELETE ON public.venues_editionvenueselection
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_edition_venue_mutation();

CREATE TRIGGER venue_space_selection_scope_immutable
BEFORE UPDATE OR DELETE ON public.venues_editionspaceselection
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_edition_space_mutation();

CREATE TRIGGER venue_booking_scope_immutable
BEFORE UPDATE OR DELETE ON public.venues_venuebooking
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_venue_booking_mutation();

CREATE TRIGGER venue_occupancy_monotonic
BEFORE UPDATE OR DELETE ON public.venues_venuebookingoccupancy
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_venue_occupancy_mutation();

CREATE TRIGGER venue_combination_member_append_only
BEFORE UPDATE OR DELETE ON public.venues_venuespacecombinationmember
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_venue_evidence_mutation();

CREATE TRIGGER venue_space_member_append_only
BEFORE UPDATE OR DELETE ON public.venues_editionspacemember
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_venue_evidence_mutation();

CREATE TRIGGER venue_availability_append_only
BEFORE UPDATE OR DELETE ON public.venues_editionspaceavailabilitywindow
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_venue_evidence_mutation();

CREATE TRIGGER venue_booking_history_append_only
BEFORE UPDATE OR DELETE ON public.venues_venuebookinghistory
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_venue_evidence_mutation();

CREATE TRIGGER venue_receipt_append_only
BEFORE UPDATE OR DELETE ON public.venues_venuecommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_prevent_venue_evidence_mutation();

CREATE CONSTRAINT TRIGGER venue_space_binding_required
AFTER INSERT ON public.venues_editionspaceselection
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_require_edition_space_binding();

REVOKE ALL ON FUNCTION public.maru_prevent_venue_evidence_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_venue_property_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_venue_media_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_venue_layout_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_edition_venue_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_edition_space_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_venue_booking_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_guard_venue_occupancy_mutation() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_require_edition_space_binding() FROM PUBLIC;
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS venue_space_binding_required
ON public.venues_editionspaceselection;
DROP TRIGGER IF EXISTS venue_receipt_append_only
ON public.venues_venuecommandreceipt;
DROP TRIGGER IF EXISTS venue_booking_history_append_only
ON public.venues_venuebookinghistory;
DROP TRIGGER IF EXISTS venue_availability_append_only
ON public.venues_editionspaceavailabilitywindow;
DROP TRIGGER IF EXISTS venue_space_member_append_only
ON public.venues_editionspacemember;
DROP TRIGGER IF EXISTS venue_combination_member_append_only
ON public.venues_venuespacecombinationmember;
DROP TRIGGER IF EXISTS venue_occupancy_monotonic
ON public.venues_venuebookingoccupancy;
DROP TRIGGER IF EXISTS venue_booking_scope_immutable
ON public.venues_venuebooking;
DROP TRIGGER IF EXISTS venue_space_selection_scope_immutable
ON public.venues_editionspaceselection;
DROP TRIGGER IF EXISTS venue_edition_selection_scope_immutable
ON public.venues_editionvenueselection;
DROP TRIGGER IF EXISTS venue_layout_provenance_immutable
ON public.venues_venuelayoutversion;
DROP TRIGGER IF EXISTS venue_media_provenance_immutable
ON public.venues_venuepropertymedia;
DROP TRIGGER IF EXISTS venue_property_scope_immutable
ON public.venues_venueproperty;
DROP FUNCTION IF EXISTS public.maru_require_edition_space_binding();
DROP FUNCTION IF EXISTS public.maru_guard_venue_occupancy_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_venue_booking_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_edition_space_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_edition_venue_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_venue_layout_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_venue_media_mutation();
DROP FUNCTION IF EXISTS public.maru_guard_venue_property_mutation();
DROP FUNCTION IF EXISTS public.maru_prevent_venue_evidence_mutation();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0014_venue_capabilities_and_resource_kind"),
        ("venues", "0001_initial"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
