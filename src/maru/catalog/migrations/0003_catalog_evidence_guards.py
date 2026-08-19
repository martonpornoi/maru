"""Harden append-only evidence and active catalog definitions in PostgreSQL."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_catalog_prevent_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'catalog evidence is append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_catalog_prevent_evidence_mutation() FROM PUBLIC;

CREATE TRIGGER catalog_stock_adjustment_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogstockadjustment
FOR EACH ROW EXECUTE FUNCTION public.maru_catalog_prevent_evidence_mutation();
CREATE TRIGGER catalog_command_receipt_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogcommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_catalog_prevent_evidence_mutation();
CREATE TRIGGER catalog_payment_event_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogpaymentevent
FOR EACH ROW EXECUTE FUNCTION public.maru_catalog_prevent_evidence_mutation();
CREATE TRIGGER catalog_order_timeline_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogordertimelineentry
FOR EACH ROW EXECUTE FUNCTION public.maru_catalog_prevent_evidence_mutation();
CREATE TRIGGER catalog_order_line_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogorderline
FOR EACH ROW EXECUTE FUNCTION public.maru_catalog_prevent_evidence_mutation();

CREATE OR REPLACE FUNCTION public.maru_catalog_guard_active_definition()
RETURNS trigger AS $$
DECLARE
    catalog_state text;
BEGIN
    IF TG_TABLE_NAME = 'catalog_catalogproduct' THEN
        SELECT status INTO catalog_state
          FROM public.catalog_editioncatalog
         WHERE id = OLD.catalog_id
         FOR KEY SHARE;
    ELSE
        SELECT catalog.status INTO catalog_state
          FROM public.catalog_editioncatalog catalog
          JOIN public.catalog_catalogproduct product
            ON product.catalog_id = catalog.id
         WHERE product.id = OLD.product_id
         FOR KEY SHARE OF catalog;
    END IF;
    IF catalog_state IN ('active', 'closed') THEN
        RAISE EXCEPTION 'active catalog definitions are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_catalog_guard_active_definition() FROM PUBLIC;

CREATE TRIGGER catalog_active_product_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogproduct
FOR EACH ROW EXECUTE FUNCTION public.maru_catalog_guard_active_definition();
CREATE TRIGGER catalog_active_variant_immutable
BEFORE UPDATE OR DELETE ON public.catalog_catalogvariant
FOR EACH ROW EXECUTE FUNCTION public.maru_catalog_guard_active_definition();
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS catalog_active_variant_immutable
    ON public.catalog_catalogvariant;
DROP TRIGGER IF EXISTS catalog_active_product_immutable
    ON public.catalog_catalogproduct;
DROP FUNCTION IF EXISTS public.maru_catalog_guard_active_definition();
DROP TRIGGER IF EXISTS catalog_order_line_immutable
    ON public.catalog_catalogorderline;
DROP TRIGGER IF EXISTS catalog_order_timeline_immutable
    ON public.catalog_catalogordertimelineentry;
DROP TRIGGER IF EXISTS catalog_payment_event_immutable
    ON public.catalog_catalogpaymentevent;
DROP TRIGGER IF EXISTS catalog_command_receipt_immutable
    ON public.catalog_catalogcommandreceipt;
DROP TRIGGER IF EXISTS catalog_stock_adjustment_immutable
    ON public.catalog_catalogstockadjustment;
DROP FUNCTION IF EXISTS public.maru_catalog_prevent_evidence_mutation();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("catalog", "0002_alter_catalogcommandreceipt_operation"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
