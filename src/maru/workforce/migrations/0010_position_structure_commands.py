"""Add governed Position and paired-opportunity structure evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from django.conf import settings
from django.db import migrations, models

if TYPE_CHECKING:
    from django.apps.registry import Apps
    from django.db.backends.base.schema import BaseDatabaseSchemaEditor
    from django.db.migrations.operations.base import Operation


def _preflight_position_template_bindings(
    apps: Apps,
    schema_editor: BaseDatabaseSchemaEditor,
) -> None:
    position = apps.get_model("workforce", "Position")
    alias = schema_editor.connection.alias
    mismatch = (
        position.objects.using(alias)
        .exclude(role_bundle_id=models.F("template__role_bundle_id"))
        .exists()
    )
    if mismatch:
        raise RuntimeError(
            "Position template and role-bundle mismatches must be reconciled "
            "before governed Position writers are installed."
        )


INSTALL_SQL = r"""
CREATE FUNCTION public.maru_validate_position_structure_receipt()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $position_receipt$
DECLARE
    control_version bigint;
    position_organization_id uuid;
    position_edition_id uuid;
    position_department_id uuid;
    position_created_version bigint;
    position_changed_version bigint;
    position_status text;
    position_closed_by_id uuid;
    opportunity_created_version bigint;
    opportunity_changed_version bigint;
    duplicate_count bigint;
BEGIN
    SELECT aggregate_version
      INTO control_version
      FROM public.workforce_editionstructurecontrol
     WHERE id = NEW.structure_id
       AND organization_id = NEW.organization_id
       AND edition_id = NEW.edition_id;
    IF NOT FOUND OR control_version <> NEW.resulting_version THEN
        RAISE EXCEPTION 'Position receipt must match the current structure version'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.action NOT IN (
        'position_created',
        'position_updated',
        'position_closed',
        'opportunity_updated'
    ) THEN
        RAISE EXCEPTION 'unknown Position receipt action'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.reason = ''
       OR NEW.reason <> pg_catalog.btrim(NEW.reason)
       OR NEW.reason ~ '[[:cntrl:]]'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
       OR NEW.affected_position_id IS NULL
       OR NEW.template_code <> ''
       OR NEW.template_version IS NOT NULL
       OR NEW.template_digest <> ''
       OR NEW.deleted_name_snapshot <> ''
    THEN
        RAISE EXCEPTION 'Position receipt evidence is malformed'
            USING ERRCODE = '23514';
    END IF;
    IF pg_catalog.array_ndims(NEW.changed_fields) <> 1
       OR pg_catalog.cardinality(NEW.changed_fields) < 1
       OR pg_catalog.cardinality(NEW.changed_fields) > 16
       OR pg_catalog.array_position(NEW.changed_fields, NULL) IS NOT NULL
       OR pg_catalog.array_ndims(NEW.affected_department_ids) <> 1
       OR pg_catalog.cardinality(NEW.affected_department_ids) <> 1
       OR pg_catalog.array_position(NEW.affected_department_ids, NULL) IS NOT NULL
    THEN
        RAISE EXCEPTION 'Position receipt arrays are malformed'
            USING ERRCODE = '23514';
    END IF;
    SELECT COUNT(*) - COUNT(DISTINCT supplied.value)
      INTO duplicate_count
      FROM pg_catalog.unnest(NEW.changed_fields) AS supplied(value);
    IF duplicate_count <> 0
       OR NEW.changed_fields <> ARRAY(
           SELECT supplied.value
             FROM pg_catalog.unnest(NEW.changed_fields) AS supplied(value)
            ORDER BY supplied.value
       )
    THEN
        RAISE EXCEPTION 'Position changed fields must be unique and canonical'
            USING ERRCODE = '23514';
    END IF;

    SELECT position.organization_id,
           position.edition_id,
           position.department_id,
           position.created_in_structure_version,
           position.last_changed_in_structure_version,
           position.status,
           position.closed_by_id
      INTO position_organization_id,
           position_edition_id,
           position_department_id,
           position_created_version,
           position_changed_version,
           position_status,
           position_closed_by_id
      FROM public.workforce_position AS position
     WHERE position.id = NEW.affected_position_id;
    IF NOT FOUND
       OR position_organization_id <> NEW.organization_id
       OR position_edition_id <> NEW.edition_id
       OR NEW.affected_department_ids <> ARRAY[position_department_id]::uuid[]
    THEN
        RAISE EXCEPTION 'Position receipt target scope is malformed'
            USING ERRCODE = '23514';
    END IF;

    SELECT opportunity.created_in_structure_version,
           opportunity.last_changed_in_structure_version
      INTO opportunity_created_version,
           opportunity_changed_version
      FROM public.workforce_volunteeropportunity AS opportunity
     WHERE opportunity.position_id = NEW.affected_position_id;

    IF NEW.action = 'position_created' THEN
        IF NEW.retry_key IS NULL
           OR NEW.request_digest !~ '^[0-9a-f]{64}$'
           OR NEW.changed_fields <>
              ARRAY['opportunity', 'position', 'resource_binding']::varchar[]
           OR position_created_version <> NEW.resulting_version
           OR position_changed_version <> NEW.resulting_version
           OR position_status <> 'planned'
           OR opportunity_created_version <> NEW.resulting_version
           OR opportunity_changed_version <> NEW.resulting_version
           OR NOT EXISTS (
               SELECT 1
                 FROM public.authorization_scopedresourcebinding AS binding
                WHERE binding.resource_kind = 'workforce.position'
                  AND binding.resource_id = NEW.affected_position_id
                  AND binding.organization_id = NEW.organization_id
                  AND binding.edition_id = NEW.edition_id
                  AND binding.department_id = position_department_id
           )
        THEN
            RAISE EXCEPTION 'Position creation evidence is incomplete'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.retry_key IS NOT NULL OR NEW.request_digest <> '' THEN
            RAISE EXCEPTION 'non-creation Position receipt has retry evidence'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.action = 'position_updated' THEN
            IF position_changed_version <> NEW.resulting_version
               OR EXISTS (
                   SELECT 1
                     FROM pg_catalog.unnest(NEW.changed_fields) AS supplied(value)
                    WHERE supplied.value NOT IN (
                        'description', 'headcount', 'reports_to', 'title'
                    )
               )
            THEN
                RAISE EXCEPTION 'Position update evidence is malformed'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.action = 'position_closed' THEN
            IF position_changed_version <> NEW.resulting_version
               OR position_status <> 'closed'
               OR position_closed_by_id <> NEW.actor_id
               OR NEW.changed_fields NOT IN (
                   ARRAY['closure']::varchar[],
                   ARRAY['closure', 'opportunity.status']::varchar[]
               )
            THEN
                RAISE EXCEPTION 'Position closure evidence is malformed'
                    USING ERRCODE = '23514';
            END IF;
            IF 'opportunity.status' = ANY(NEW.changed_fields)
               AND opportunity_changed_version <> NEW.resulting_version
            THEN
                RAISE EXCEPTION 'Position closure lost opportunity evidence'
                    USING ERRCODE = '23514';
            END IF;
        ELSE
            IF opportunity_changed_version <> NEW.resulting_version
               OR NOT EXISTS (
                   SELECT 1
                     FROM pg_catalog.unnest(NEW.changed_fields) AS supplied(value)
                    WHERE supplied.value LIKE 'opportunity.%'
               )
               OR EXISTS (
                   SELECT 1
                     FROM pg_catalog.unnest(NEW.changed_fields) AS supplied(value)
                    WHERE supplied.value NOT IN (
                        'opportunity.applications_close_at',
                        'opportunity.applications_open_at',
                        'opportunity.description',
                        'opportunity.headline',
                        'opportunity.status',
                        'opportunity.visible_when_filled',
                        'status'
                    )
               )
               OR (
                   'status' = ANY(NEW.changed_fields)
                   AND position_changed_version <> NEW.resulting_version
               )
            THEN
                RAISE EXCEPTION 'Opportunity update evidence is malformed'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$position_receipt$;

REVOKE ALL ON FUNCTION public.maru_validate_position_structure_receipt()
FROM PUBLIC;

DROP TRIGGER ac_workforce_page9_receipt_guard
ON public.workforce_editionstructurecommandreceipt;

CREATE TRIGGER ac_workforce_page9_receipt_guard
BEFORE INSERT
ON public.workforce_editionstructurecommandreceipt
FOR EACH ROW
WHEN (NEW.action NOT IN (
    'position_created',
    'position_updated',
    'position_closed',
    'opportunity_updated'
))
EXECUTE FUNCTION public.maru_validate_edition_structure_receipt();

CREATE TRIGGER ac_workforce_position_receipt_guard
BEFORE INSERT
ON public.workforce_editionstructurecommandreceipt
FOR EACH ROW
WHEN (NEW.action IN (
    'position_created',
    'position_updated',
    'position_closed',
    'opportunity_updated'
))
EXECUTE FUNCTION public.maru_validate_position_structure_receipt();

CREATE FUNCTION public.maru_validate_position_structure_write()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $position_write$
DECLARE
    department_organization_id uuid;
    department_edition_id uuid;
    department_retired_at timestamptz;
    template_organization_id uuid;
    template_role_bundle_id uuid;
    template_status text;
    manager_organization_id uuid;
    manager_edition_id uuid;
    manager_status text;
    control_version bigint;
    ancestor_depth integer;
    hierarchy_cycle boolean;
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed()
       AND NEW.created_in_structure_version IS NULL
       AND NEW.last_changed_in_structure_version IS NULL
    THEN
        RETURN NEW;
    END IF;

    SELECT organization_id, edition_id, retired_at
      INTO department_organization_id, department_edition_id, department_retired_at
      FROM public.workforce_department
     WHERE id = NEW.department_id;
    SELECT organization_id, role_bundle_id, status
      INTO template_organization_id, template_role_bundle_id, template_status
      FROM public.workforce_positiontemplate
     WHERE id = NEW.template_id;
    IF department_organization_id IS DISTINCT FROM NEW.organization_id
       OR department_edition_id IS DISTINCT FROM NEW.edition_id
       OR department_retired_at IS NOT NULL
       OR template_organization_id IS DISTINCT FROM NEW.organization_id
       OR template_role_bundle_id IS DISTINCT FROM NEW.role_bundle_id
       OR template_status <> 'published'
    THEN
        RAISE EXCEPTION 'Position scope, Department, or template is unavailable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.reports_to_id IS NOT NULL THEN
        SELECT organization_id, edition_id, status
          INTO manager_organization_id, manager_edition_id, manager_status
          FROM public.workforce_position
         WHERE id = NEW.reports_to_id;
        IF manager_organization_id IS DISTINCT FROM NEW.organization_id
           OR manager_edition_id IS DISTINCT FROM NEW.edition_id
           OR manager_status = 'closed'
           OR NEW.reports_to_id = NEW.id
        THEN
            RAISE EXCEPTION 'Position manager is unavailable'
                USING ERRCODE = '23514';
        END IF;
        WITH RECURSIVE ancestry AS (
            SELECT manager.id,
                   manager.reports_to_id,
                   1 AS depth,
                   ARRAY[NEW.id, manager.id]::uuid[] AS path,
                   manager.id = NEW.id AS cycle
              FROM public.workforce_position AS manager
             WHERE manager.id = NEW.reports_to_id
            UNION ALL
            SELECT manager.id,
                   manager.reports_to_id,
                   ancestry.depth + 1,
                   ancestry.path || manager.id,
                   manager.id = ANY(ancestry.path)
              FROM ancestry
              JOIN public.workforce_position AS manager
                ON manager.id = ancestry.reports_to_id
             WHERE NOT ancestry.cycle
               AND ancestry.depth <= 32
        )
        SELECT COALESCE(MAX(depth), 0), COALESCE(BOOL_OR(cycle), FALSE)
          INTO ancestor_depth, hierarchy_cycle
          FROM ancestry;
        IF hierarchy_cycle OR ancestor_depth > 32 THEN
            RAISE EXCEPTION 'Position reporting line exceeds the acyclic bound'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    SELECT aggregate_version
      INTO control_version
      FROM public.workforce_editionstructurecontrol
     WHERE organization_id = NEW.organization_id
       AND edition_id = NEW.edition_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Position write requires a structure control'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.created_in_structure_version IS NULL
           OR NEW.created_in_structure_version <> control_version
           OR NEW.last_changed_in_structure_version <> control_version
           OR NEW.status <> 'planned'
           OR NEW.closed_at IS NOT NULL
           OR NEW.closed_by_id IS NOT NULL
        THEN
            RAISE EXCEPTION 'new Position lacks command-version evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
       OR NEW.template_id IS DISTINCT FROM OLD.template_id
       OR NEW.department_id IS DISTINCT FROM OLD.department_id
       OR NEW.role_bundle_id IS DISTINCT FROM OLD.role_bundle_id
       OR NEW.code IS DISTINCT FROM OLD.code
       OR NEW.capacity_codes IS DISTINCT FROM OLD.capacity_codes
       OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
       OR NEW.created_in_structure_version IS DISTINCT FROM
          OLD.created_in_structure_version
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'Position identity, authority mapping, and scope are immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.title IS DISTINCT FROM OLD.title
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.headcount IS DISTINCT FROM OLD.headcount
       OR NEW.reports_to_id IS DISTINCT FROM OLD.reports_to_id
       OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
       OR NEW.closed_by_id IS DISTINCT FROM OLD.closed_by_id
       OR (
           NEW.status IS DISTINCT FROM OLD.status
           AND NEW.last_changed_in_structure_version IS DISTINCT FROM
               OLD.last_changed_in_structure_version
       )
    THEN
        IF NEW.last_changed_in_structure_version IS NULL
           OR NEW.last_changed_in_structure_version <> control_version
        THEN
            RAISE EXCEPTION 'Position change lacks current aggregate evidence'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.last_changed_in_structure_version IS DISTINCT FROM
          OLD.last_changed_in_structure_version
    THEN
        RAISE EXCEPTION 'Position version cannot move without a governed change'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status = 'closed' AND OLD.status <> 'closed' THEN
        IF NEW.closed_at IS NULL OR NEW.closed_by_id IS NULL
           OR EXISTS (
               SELECT 1
                 FROM public.workforce_positionassignment
                WHERE position_id = NEW.id
                  AND status IN ('proposed', 'active')
           )
           OR EXISTS (
               SELECT 1
                 FROM public.workforce_position
                WHERE reports_to_id = NEW.id
                  AND status <> 'closed'
           )
        THEN
            RAISE EXCEPTION 'Position closure has current dependencies'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'closed' AND NEW.status <> 'closed' THEN
        RAISE EXCEPTION 'closed Positions cannot be reopened'
            USING ERRCODE = '23514';
    ELSIF NEW.status IS DISTINCT FROM OLD.status
       AND NEW.status NOT IN ('planned', 'open', 'filled')
    THEN
        RAISE EXCEPTION 'unsupported Position status transition'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.headcount < (
        SELECT COUNT(*)
          FROM public.workforce_positionassignment
         WHERE position_id = NEW.id
           AND status IN ('proposed', 'active')
    ) THEN
        RAISE EXCEPTION 'Position headcount is below current assignments'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$position_write$;

CREATE FUNCTION public.maru_assert_position_structure_evidence()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $position_evidence$
DECLARE
    actual_fields varchar[] := ARRAY[]::varchar[];
    matching_receipts bigint;
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed()
       AND NEW.created_in_structure_version IS NULL
       AND NEW.last_changed_in_structure_version IS NULL
    THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.action = 'position_created'
           AND receipt.affected_position_id = NEW.id
           AND receipt.resulting_version = NEW.created_in_structure_version;
    ELSIF NEW.status = 'closed' AND OLD.status <> 'closed' THEN
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.action = 'position_closed'
           AND receipt.affected_position_id = NEW.id
           AND receipt.resulting_version = NEW.last_changed_in_structure_version;
    ELSIF NEW.last_changed_in_structure_version IS NOT DISTINCT FROM
          OLD.last_changed_in_structure_version
    THEN
        RETURN NULL;
    ELSIF NEW.status IS DISTINCT FROM OLD.status
       AND NEW.title IS NOT DISTINCT FROM OLD.title
       AND NEW.description IS NOT DISTINCT FROM OLD.description
       AND NEW.headcount IS NOT DISTINCT FROM OLD.headcount
       AND NEW.reports_to_id IS NOT DISTINCT FROM OLD.reports_to_id
    THEN
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.action = 'opportunity_updated'
           AND receipt.affected_position_id = NEW.id
           AND receipt.resulting_version = NEW.last_changed_in_structure_version
           AND 'status' = ANY(receipt.changed_fields);
    ELSE
        IF NEW.description IS DISTINCT FROM OLD.description THEN
            actual_fields := actual_fields || 'description'::varchar;
        END IF;
        IF NEW.headcount IS DISTINCT FROM OLD.headcount THEN
            actual_fields := actual_fields || 'headcount'::varchar;
        END IF;
        IF NEW.reports_to_id IS DISTINCT FROM OLD.reports_to_id THEN
            actual_fields := actual_fields || 'reports_to'::varchar;
        END IF;
        IF NEW.title IS DISTINCT FROM OLD.title THEN
            actual_fields := actual_fields || 'title'::varchar;
        END IF;
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.action = 'position_updated'
           AND receipt.affected_position_id = NEW.id
           AND receipt.resulting_version = NEW.last_changed_in_structure_version
           AND receipt.changed_fields = actual_fields;
    END IF;
    IF matching_receipts <> 1 THEN
        RAISE EXCEPTION 'Position mutation lacks exact immutable command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$position_evidence$;

CREATE FUNCTION public.maru_validate_opportunity_structure_write()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $opportunity_write$
DECLARE
    control_version bigint;
    position_organization_id uuid;
    position_edition_id uuid;
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed()
       AND NEW.created_in_structure_version IS NULL
       AND NEW.last_changed_in_structure_version IS NULL
    THEN
        RETURN NEW;
    END IF;
    SELECT organization_id, edition_id
      INTO position_organization_id, position_edition_id
      FROM public.workforce_position
     WHERE id = NEW.position_id;
    SELECT aggregate_version
      INTO control_version
      FROM public.workforce_editionstructurecontrol
     WHERE organization_id = position_organization_id
       AND edition_id = position_edition_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Opportunity write requires a structure control'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.applications_open_at IS NOT NULL
       AND NEW.applications_close_at IS NOT NULL
       AND NEW.applications_close_at <= NEW.applications_open_at
    THEN
        RAISE EXCEPTION 'Opportunity window is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.created_in_structure_version IS NULL
           OR NEW.created_in_structure_version <> control_version
           OR NEW.last_changed_in_structure_version <> control_version
        THEN
            RAISE EXCEPTION 'new Opportunity lacks command-version evidence'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.position_id IS DISTINCT FROM OLD.position_id
       OR NEW.created_in_structure_version IS DISTINCT FROM
          OLD.created_in_structure_version
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'Opportunity identity is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status
       OR NEW.headline IS DISTINCT FROM OLD.headline
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.applications_open_at IS DISTINCT FROM OLD.applications_open_at
       OR NEW.applications_close_at IS DISTINCT FROM OLD.applications_close_at
       OR NEW.visible_when_filled IS DISTINCT FROM OLD.visible_when_filled
    THEN
        IF NEW.last_changed_in_structure_version IS NULL
           OR NEW.last_changed_in_structure_version <> control_version
        THEN
            RAISE EXCEPTION 'Opportunity change lacks current aggregate evidence'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.last_changed_in_structure_version IS DISTINCT FROM
          OLD.last_changed_in_structure_version
    THEN
        RAISE EXCEPTION 'Opportunity version cannot move without a governed change'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'withdrawn' AND NEW.status <> 'withdrawn' THEN
        RAISE EXCEPTION 'withdrawn Opportunities cannot be reopened'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$opportunity_write$;

CREATE FUNCTION public.maru_assert_opportunity_structure_evidence()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $opportunity_evidence$
DECLARE
    actual_fields varchar[] := ARRAY[]::varchar[];
    position_organization_id uuid;
    position_edition_id uuid;
    matching_receipts bigint;
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed()
       AND NEW.created_in_structure_version IS NULL
       AND NEW.last_changed_in_structure_version IS NULL
    THEN
        RETURN NULL;
    END IF;
    SELECT organization_id, edition_id
      INTO position_organization_id, position_edition_id
      FROM public.workforce_position
     WHERE id = NEW.position_id;
    IF TG_OP = 'INSERT' THEN
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = position_organization_id
           AND receipt.edition_id = position_edition_id
           AND receipt.affected_position_id = NEW.position_id
           AND receipt.resulting_version = NEW.created_in_structure_version
           AND receipt.action IN ('position_created', 'opportunity_updated');
    ELSIF NEW.last_changed_in_structure_version IS NOT DISTINCT FROM
          OLD.last_changed_in_structure_version
    THEN
        RETURN NULL;
    ELSE
        IF NEW.applications_close_at IS DISTINCT FROM OLD.applications_close_at THEN
            actual_fields := actual_fields ||
                'opportunity.applications_close_at'::varchar;
        END IF;
        IF NEW.applications_open_at IS DISTINCT FROM OLD.applications_open_at THEN
            actual_fields := actual_fields ||
                'opportunity.applications_open_at'::varchar;
        END IF;
        IF NEW.description IS DISTINCT FROM OLD.description THEN
            actual_fields := actual_fields || 'opportunity.description'::varchar;
        END IF;
        IF NEW.headline IS DISTINCT FROM OLD.headline THEN
            actual_fields := actual_fields || 'opportunity.headline'::varchar;
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status THEN
            actual_fields := actual_fields || 'opportunity.status'::varchar;
        END IF;
        IF NEW.visible_when_filled IS DISTINCT FROM OLD.visible_when_filled THEN
            actual_fields := actual_fields ||
                'opportunity.visible_when_filled'::varchar;
        END IF;
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = position_organization_id
           AND receipt.edition_id = position_edition_id
           AND receipt.affected_position_id = NEW.position_id
           AND receipt.resulting_version = NEW.last_changed_in_structure_version
           AND (
               (
                   receipt.action = 'opportunity_updated'
                   AND actual_fields <@ receipt.changed_fields
                   AND receipt.changed_fields <@
                       (actual_fields || ARRAY['status']::varchar[])
               )
               OR (
                   receipt.action = 'position_closed'
                   AND actual_fields = ARRAY['opportunity.status']::varchar[]
                   AND 'opportunity.status' = ANY(receipt.changed_fields)
               )
           );
    END IF;
    IF matching_receipts <> 1 THEN
        RAISE EXCEPTION 'Opportunity mutation lacks immutable command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$opportunity_evidence$;

REVOKE ALL ON FUNCTION
    public.maru_validate_position_structure_write(),
    public.maru_assert_position_structure_evidence(),
    public.maru_validate_opportunity_structure_write(),
    public.maru_assert_opportunity_structure_evidence()
FROM PUBLIC;

CREATE TRIGGER ac_workforce_position_structure_guard
BEFORE INSERT OR UPDATE
ON public.workforce_position
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_position_structure_write();

CREATE CONSTRAINT TRIGGER workforce_position_structure_evidence
AFTER INSERT OR UPDATE
ON public.workforce_position
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_assert_position_structure_evidence();

CREATE TRIGGER ac_workforce_opportunity_structure_guard
BEFORE INSERT OR UPDATE
ON public.workforce_volunteeropportunity
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_opportunity_structure_write();

CREATE CONSTRAINT TRIGGER workforce_opportunity_structure_evidence
AFTER INSERT OR UPDATE
ON public.workforce_volunteeropportunity
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_assert_opportunity_structure_evidence();
"""


REMOVE_SQL = r"""
DROP TRIGGER IF EXISTS workforce_opportunity_structure_evidence
    ON public.workforce_volunteeropportunity;
DROP TRIGGER IF EXISTS ac_workforce_opportunity_structure_guard
    ON public.workforce_volunteeropportunity;
DROP TRIGGER IF EXISTS workforce_position_structure_evidence
    ON public.workforce_position;
DROP TRIGGER IF EXISTS ac_workforce_position_structure_guard
    ON public.workforce_position;
DROP TRIGGER IF EXISTS ac_workforce_position_receipt_guard
    ON public.workforce_editionstructurecommandreceipt;
DROP TRIGGER IF EXISTS ac_workforce_page9_receipt_guard
    ON public.workforce_editionstructurecommandreceipt;
CREATE TRIGGER ac_workforce_page9_receipt_guard
BEFORE INSERT
ON public.workforce_editionstructurecommandreceipt
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_edition_structure_receipt();
DROP FUNCTION IF EXISTS public.maru_assert_opportunity_structure_evidence();
DROP FUNCTION IF EXISTS public.maru_validate_opportunity_structure_write();
DROP FUNCTION IF EXISTS public.maru_assert_position_structure_evidence();
DROP FUNCTION IF EXISTS public.maru_validate_position_structure_write();
DROP FUNCTION IF EXISTS public.maru_validate_position_structure_receipt();
"""


class Migration(migrations.Migration):
    """Install Position command evidence and stopped-writer protections."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0009_reconcile_fictional_structure_template")
    ]

    operations: ClassVar[list[Operation]] = [
        migrations.RunPython(
            _preflight_position_template_bindings,
            migrations.RunPython.noop,
        ),
        migrations.AddField(
            model_name="editionstructurecommandreceipt",
            name="affected_position",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=models.PROTECT,
                related_name="structure_command_receipts",
                to="workforce.position",
            ),
        ),
        migrations.AlterField(
            model_name="editionstructurecommandreceipt",
            name="action",
            field=models.CharField(
                choices=[
                    ("template_applied", "Template applied"),
                    ("department_created", "Department created"),
                    ("department_updated", "Department updated"),
                    ("department_retired", "Department retired"),
                    ("department_deleted", "Department deleted"),
                    ("position_created", "Position created"),
                    ("position_updated", "Position updated"),
                    ("position_closed", "Position closed"),
                    ("opportunity_updated", "Opportunity updated"),
                ],
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="position",
            name="closed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="position",
            name="closed_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=models.PROTECT,
                related_name="workforce_positions_closed",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="position",
            name="created_in_structure_version",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="position",
            name="last_changed_in_structure_version",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="volunteeropportunity",
            name="created_in_structure_version",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="volunteeropportunity",
            name="last_changed_in_structure_version",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="position",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(created_in_structure_version__isnull=True)
                    | models.Q(
                        created_in_structure_version__gt=0,
                        last_changed_in_structure_version__gte=models.F(
                            "created_in_structure_version"
                        ),
                    )
                ),
                name="workforce_position_structure_versions_consistent",
            ),
        ),
        migrations.AddConstraint(
            model_name="position",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(closed_at__isnull=True, closed_by__isnull=True)
                    | models.Q(
                        status="closed",
                        closed_at__isnull=False,
                        closed_by__isnull=False,
                    )
                ),
                name="workforce_position_closure_evidence_complete",
            ),
        ),
        migrations.AddConstraint(
            model_name="volunteeropportunity",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(created_in_structure_version__isnull=True)
                    | models.Q(
                        created_in_structure_version__gt=0,
                        last_changed_in_structure_version__gte=models.F(
                            "created_in_structure_version"
                        ),
                    )
                ),
                name="workforce_opportunity_structure_versions_consistent",
            ),
        ),
        migrations.AddIndex(
            model_name="editionstructurecommandreceipt",
            index=models.Index(
                fields=["affected_position", "resulting_version"],
                name="wrk_receipt_position_ver_idx",
            ),
        ),
        migrations.RunSQL(INSTALL_SQL, REMOVE_SQL),
    ]
