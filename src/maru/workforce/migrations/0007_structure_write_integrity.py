"""Activate the fail-closed Page 9 Department write boundary."""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import uuid4

from django.db import migrations
from django.utils import timezone

PAGE_9_STRUCTURE_ACTIVATION_LOCK_KEY = 4_400_460_007
AUTHORITY_PROVENANCE_ACTIVATION_LOCK_KEY = 4_400_440_007
RETIRED_DEPARTMENT_AUTHORITY_LOCK_KEY = 4_400_450_010

PINNED_TEMPLATE_DIGEST = (
    "a0eb4def29ed904b5e1279bd72bf4da7f99c94e804cabf10c196b536c5ca7901"
)


CUTOVER_AND_PREFLIGHT_SQL = r"""
SELECT pg_catalog.pg_advisory_xact_lock(4400460007);
SELECT pg_catalog.pg_advisory_xact_lock(4400440007);
SELECT pg_catalog.pg_advisory_xact_lock(4400450010);

LOCK TABLE public.organizations_organization IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.organizations_conventionseries IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.events_eventedition IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.workforce_editionstructurecontrol IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.workforce_department IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.workforce_position IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.workforce_positionassignment IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.authorization_scopedresourcebinding IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.authorization_capabilitygrant IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.authorization_roleassignment IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.workforce_editionstructurecommandreceipt
    IN SHARE ROW EXCLUSIVE MODE;

DO $page9_preflight$
DECLARE
    structure_control_count bigint;
    structure_receipt_count bigint;
    structure_metadata_count bigint;
    malformed_department_count bigint;
    department_scope_count bigint;
    department_parent_count bigint;
    department_cycle_count bigint;
    department_depth_count bigint;
    department_limit_count bigint;
    position_scope_count bigint;
    assignment_scope_count bigint;
    binding_scope_count bigint;
    authority_scope_count bigint;
    unsupported_fk_count bigint;
BEGIN
    SELECT COUNT(*) INTO structure_control_count
      FROM public.workforce_editionstructurecontrol;
    SELECT COUNT(*) INTO structure_receipt_count
      FROM public.workforce_editionstructurecommandreceipt;
    SELECT COUNT(*) INTO structure_metadata_count
      FROM public.workforce_department AS department
     WHERE department.created_in_structure_version IS NOT NULL
        OR department.last_changed_in_structure_version IS NOT NULL
        OR department.retired_at IS NOT NULL
        OR department.retired_by_id IS NOT NULL
        OR department.retired_in_structure_version IS NOT NULL;

    SELECT COUNT(*) INTO malformed_department_count
      FROM public.workforce_department AS department
     WHERE department.code !~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'
        OR department.name = ''
        OR department.name <> pg_catalog.btrim(department.name)
        OR department.name ~ '[[:cntrl:]]'
        OR department.description <> pg_catalog.btrim(department.description)
        OR department.description ~ '[[:cntrl:]]'
        OR department.position < 0
        OR department.position > 65535;

    SELECT COUNT(*) INTO department_scope_count
      FROM public.workforce_department AS department
      LEFT JOIN public.events_eventedition AS edition
        ON edition.id = department.edition_id
     WHERE edition.id IS NULL
        OR edition.organization_id <> department.organization_id;

    SELECT COUNT(*) INTO department_parent_count
      FROM public.workforce_department AS department
      LEFT JOIN public.workforce_department AS parent
        ON parent.id = department.parent_id
     WHERE department.parent_id IS NOT NULL
       AND (
            parent.id IS NULL
            OR parent.id = department.id
            OR parent.organization_id <> department.organization_id
            OR parent.edition_id <> department.edition_id
       );

    WITH RECURSIVE ancestry AS (
        SELECT department.id AS start_id,
               department.parent_id AS next_id,
               ARRAY[department.id]::uuid[] AS path,
               0 AS depth,
               FALSE AS cycle
          FROM public.workforce_department AS department
        UNION ALL
        SELECT ancestry.start_id,
               parent.parent_id,
               ancestry.path || parent.id,
               ancestry.depth + 1,
               parent.id = ANY(ancestry.path)
          FROM ancestry
          JOIN public.workforce_department AS parent
            ON parent.id = ancestry.next_id
         WHERE NOT ancestry.cycle
           AND ancestry.depth <= 32
    )
    SELECT COUNT(DISTINCT start_id) FILTER (WHERE cycle),
           COUNT(DISTINCT start_id) FILTER (WHERE depth >= 32)
      INTO department_cycle_count, department_depth_count
      FROM ancestry;

    SELECT COUNT(*) INTO department_limit_count
      FROM (
          SELECT edition_id
            FROM public.workforce_department
           GROUP BY edition_id
          HAVING COUNT(*) > 256
      ) AS over_limit;

    SELECT COUNT(*) INTO position_scope_count
      FROM public.workforce_position AS position
      LEFT JOIN public.events_eventedition AS edition
        ON edition.id = position.edition_id
      LEFT JOIN public.workforce_department AS department
        ON department.id = position.department_id
      LEFT JOIN public.workforce_position AS manager
        ON manager.id = position.reports_to_id
      LEFT JOIN public.workforce_positiontemplate AS template
        ON template.id = position.template_id
      LEFT JOIN public.authorization_rolebundle AS bundle
        ON bundle.id = position.role_bundle_id
     WHERE edition.id IS NULL
        OR edition.organization_id <> position.organization_id
        OR department.id IS NULL
        OR department.organization_id <> position.organization_id
        OR department.edition_id <> position.edition_id
        OR template.id IS NULL
        OR template.organization_id <> position.organization_id
        OR bundle.id IS NULL
        OR bundle.organization_id <> position.organization_id
        OR (
            position.reports_to_id IS NOT NULL
            AND (
                manager.id IS NULL
                OR manager.organization_id <> position.organization_id
                OR manager.edition_id <> position.edition_id
            )
        );

    SELECT COUNT(*) INTO assignment_scope_count
      FROM public.workforce_positionassignment AS assignment
      LEFT JOIN public.events_eventedition AS edition
        ON edition.id = assignment.edition_id
      LEFT JOIN public.workforce_position AS position
        ON position.id = assignment.position_id
     WHERE edition.id IS NULL
        OR edition.organization_id <> assignment.organization_id
        OR position.id IS NULL
        OR position.organization_id <> assignment.organization_id
        OR position.edition_id <> assignment.edition_id;

    SELECT COUNT(*) INTO binding_scope_count
      FROM public.authorization_scopedresourcebinding AS binding
      LEFT JOIN public.events_eventedition AS edition
        ON edition.id = binding.edition_id
      LEFT JOIN public.workforce_department AS department
        ON department.id = binding.department_id
      LEFT JOIN public.workforce_position AS position
        ON position.id = binding.resource_id
       AND binding.resource_kind = 'workforce.position'
     WHERE edition.id IS NULL
        OR edition.organization_id <> binding.organization_id
        OR department.id IS NULL
        OR department.organization_id <> binding.organization_id
        OR department.edition_id <> binding.edition_id
        OR binding.resource_kind <> 'workforce.position'
        OR position.id IS NULL
        OR position.organization_id <> binding.organization_id
        OR position.edition_id <> binding.edition_id
        OR position.department_id <> binding.department_id;

    SELECT COUNT(*) INTO authority_scope_count
      FROM (
          SELECT authority.id
            FROM public.authorization_capabilitygrant AS authority
            LEFT JOIN public.workforce_department AS department
              ON department.id = authority.department_id
           WHERE authority.department_id IS NOT NULL
             AND (
                  authority.edition_id IS NULL
                  OR department.id IS NULL
                  OR department.organization_id <> authority.organization_id
                  OR department.edition_id <> authority.edition_id
             )
          UNION ALL
          SELECT authority.id
            FROM public.authorization_roleassignment AS authority
            LEFT JOIN public.workforce_department AS department
              ON department.id = authority.department_id
           WHERE authority.department_id IS NOT NULL
             AND (
                  authority.edition_id IS NULL
                  OR department.id IS NULL
                  OR department.organization_id <> authority.organization_id
                  OR department.edition_id <> authority.edition_id
             )
      ) AS malformed_authority;

    SELECT COUNT(*) INTO unsupported_fk_count
      FROM pg_catalog.pg_constraint AS constraint_record
     WHERE constraint_record.contype = 'f'
       AND constraint_record.confrelid =
           'public.workforce_department'::pg_catalog.regclass
       AND NOT (
           constraint_record.confdeltype IN ('a', 'r')
           AND (
               SELECT pg_catalog.array_agg(attribute.attname::text
                                           ORDER BY key_column.ordinality)
                 FROM pg_catalog.unnest(constraint_record.confkey)
                      WITH ORDINALITY AS key_column(attnum, ordinality)
                 JOIN pg_catalog.pg_attribute AS attribute
                   ON attribute.attrelid = constraint_record.confrelid
                  AND attribute.attnum = key_column.attnum
           ) = ARRAY['id']::text[]
           AND CASE constraint_record.conrelid
               WHEN 'public.workforce_department'::pg_catalog.regclass THEN
                   (
                       SELECT pg_catalog.array_agg(attribute.attname::text
                                                   ORDER BY key_column.ordinality)
                         FROM pg_catalog.unnest(constraint_record.conkey)
                              WITH ORDINALITY AS key_column(attnum, ordinality)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = constraint_record.conrelid
                          AND attribute.attnum = key_column.attnum
                   ) = ARRAY['parent_id']::text[]
               WHEN 'public.workforce_position'::pg_catalog.regclass THEN
                   (
                       SELECT pg_catalog.array_agg(attribute.attname::text
                                                   ORDER BY key_column.ordinality)
                         FROM pg_catalog.unnest(constraint_record.conkey)
                              WITH ORDINALITY AS key_column(attnum, ordinality)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = constraint_record.conrelid
                          AND attribute.attnum = key_column.attnum
                   ) = ARRAY['department_id']::text[]
               WHEN 'public.authorization_scopedresourcebinding'::pg_catalog.regclass
                   THEN (
                       SELECT pg_catalog.array_agg(attribute.attname::text
                                                   ORDER BY key_column.ordinality)
                         FROM pg_catalog.unnest(constraint_record.conkey)
                              WITH ORDINALITY AS key_column(attnum, ordinality)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = constraint_record.conrelid
                          AND attribute.attnum = key_column.attnum
                   ) = ARRAY['department_id']::text[]
               WHEN 'public.authorization_capabilitygrant'::pg_catalog.regclass THEN
                   (
                       SELECT pg_catalog.array_agg(attribute.attname::text
                                                   ORDER BY key_column.ordinality)
                         FROM pg_catalog.unnest(constraint_record.conkey)
                              WITH ORDINALITY AS key_column(attnum, ordinality)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = constraint_record.conrelid
                          AND attribute.attnum = key_column.attnum
                   ) = ARRAY['department_id']::text[]
               WHEN 'public.authorization_roleassignment'::pg_catalog.regclass THEN
                   (
                       SELECT pg_catalog.array_agg(attribute.attname::text
                                                   ORDER BY key_column.ordinality)
                         FROM pg_catalog.unnest(constraint_record.conkey)
                              WITH ORDINALITY AS key_column(attnum, ordinality)
                         JOIN pg_catalog.pg_attribute AS attribute
                           ON attribute.attrelid = constraint_record.conrelid
                          AND attribute.attnum = key_column.attnum
                   ) = ARRAY['department_id']::text[]
               ELSE FALSE
           END
       );

    IF structure_control_count > 0
       OR structure_receipt_count > 0
       OR structure_metadata_count > 0
       OR malformed_department_count > 0
       OR department_scope_count > 0
       OR department_parent_count > 0
       OR department_cycle_count > 0
       OR department_depth_count > 0
       OR department_limit_count > 0
       OR position_scope_count > 0
       OR assignment_scope_count > 0
       OR binding_scope_count > 0
       OR authority_scope_count > 0
       OR unsupported_fk_count > 0
    THEN
        RAISE EXCEPTION
            'Page 9 structure preflight failed: controls %, receipts %, metadata %, malformed %, scope %, parents %, cycles %, depth %, limits %, positions %, assignments %, bindings %, authority %, foreign keys %',
            structure_control_count,
            structure_receipt_count,
            structure_metadata_count,
            malformed_department_count,
            department_scope_count,
            department_parent_count,
            department_cycle_count,
            department_depth_count,
            department_limit_count,
            position_scope_count,
            assignment_scope_count,
            binding_scope_count,
            authority_scope_count,
            unsupported_fk_count
            USING ERRCODE = '23514';
    END IF;
END;
$page9_preflight$;
"""


def backfill_legacy_structure_controls(apps: Any, schema_editor: Any) -> None:
    """Create one version-one legacy control for every populated edition."""

    control_model = apps.get_model("workforce", "EditionStructureControl")
    alias = schema_editor.connection.alias
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT populated.organization_id, populated.edition_id
              FROM (
                  SELECT organization_id, edition_id
                    FROM public.workforce_department
                  UNION
                  SELECT organization_id, edition_id
                    FROM public.workforce_position
                  UNION
                  SELECT organization_id, edition_id
                    FROM public.workforce_positionassignment
                  UNION
                  SELECT organization_id, edition_id
                    FROM public.authorization_scopedresourcebinding
                   WHERE resource_kind = 'workforce.position'
              ) AS populated
             ORDER BY populated.organization_id, populated.edition_id
            """
        )
        populated_scopes = tuple(cursor.fetchall())

    recorded_at = timezone.now()
    control_model.objects.using(alias).bulk_create(
        [
            control_model(
                id=uuid4(),
                created_at=recorded_at,
                updated_at=recorded_at,
                organization_id=organization_id,
                edition_id=edition_id,
                origin="legacy_existing",
                aggregate_version=1,
            )
            for organization_id, edition_id in populated_scopes
        ]
    )


def refuse_structure_integrity_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep Page 9 evidence and every populated edition on compatible code."""

    del apps
    schema_editor.execute(
        """
        SELECT pg_catalog.pg_advisory_xact_lock(4400460007);
        SELECT pg_catalog.pg_advisory_xact_lock(4400440007);
        SELECT pg_catalog.pg_advisory_xact_lock(4400450010);
        LOCK TABLE public.organizations_organization IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.organizations_conventionseries IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.events_eventedition IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.workforce_editionstructurecontrol
            IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.workforce_department IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.workforce_position IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.workforce_positionassignment IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.authorization_scopedresourcebinding
            IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.authorization_capabilitygrant
            IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.authorization_roleassignment
            IN ACCESS EXCLUSIVE MODE;
        LOCK TABLE public.workforce_editionstructurecommandreceipt
            IN ACCESS EXCLUSIVE MODE;
        """
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM public.workforce_editionstructurecontrol
                UNION ALL
                SELECT 1 FROM public.workforce_editionstructurecommandreceipt
                UNION ALL
                SELECT 1 FROM public.workforce_department
                UNION ALL
                SELECT 1 FROM public.workforce_position
                UNION ALL
                SELECT 1 FROM public.workforce_positionassignment
                UNION ALL
                SELECT 1
                  FROM public.authorization_scopedresourcebinding
                 WHERE resource_kind = 'workforce.position'
            )
            """
        )
        populated = cursor.fetchone()
    if populated is None or bool(populated[0]):
        raise RuntimeError(
            "Cannot remove Page 9 structure integrity after structure evidence or "
            "edition workforce data exists. Keep compatible code and fix forward, "
            "or restore the complete database to a consistent pre-cutover point."
        )


INSTALL_BARRIER_FUNCTIONS_SQL = r"""
CREATE FUNCTION public.maru_workforce_page9_writer_barrier()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_barrier$
BEGIN
    IF NOT pg_catalog.pg_try_advisory_xact_lock_shared(4400460007) THEN
        RAISE EXCEPTION
            'Page 9 structure cutover is in progress; retry the complete transaction'
            USING ERRCODE = '40001';
    END IF;
    RETURN NULL;
END;
$page9_barrier$;

CREATE FUNCTION public.maru_workforce_page9_try_scope_mutex(target_lock bigint)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_try_mutex$
BEGIN
    IF NOT pg_catalog.pg_try_advisory_xact_lock(target_lock) THEN
        RAISE EXCEPTION
            'Page 9 edition structure is being changed; retry the complete transaction'
            USING ERRCODE = '40001';
    END IF;
END;
$page9_try_mutex$;

CREATE FUNCTION public.maru_workforce_page9_scope_mutex()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_scope_mutex$
DECLARE
    old_lock bigint;
    new_lock bigint;
BEGIN
    IF TG_OP <> 'INSERT' AND OLD.edition_id IS NOT NULL THEN
        old_lock := pg_catalog.hashtextextended(
            'maru.workforce.department:' || OLD.organization_id::text || ':' ||
            OLD.edition_id::text,
            0
        );
    END IF;
    IF TG_OP <> 'DELETE' AND NEW.edition_id IS NOT NULL THEN
        new_lock := pg_catalog.hashtextextended(
            'maru.workforce.department:' || NEW.organization_id::text || ':' ||
            NEW.edition_id::text,
            0
        );
    END IF;

    IF old_lock IS NULL THEN
        IF new_lock IS NOT NULL THEN
            PERFORM public.maru_workforce_page9_try_scope_mutex(new_lock);
        END IF;
    ELSIF new_lock IS NULL OR old_lock = new_lock THEN
        PERFORM public.maru_workforce_page9_try_scope_mutex(old_lock);
    ELSIF old_lock < new_lock THEN
        PERFORM public.maru_workforce_page9_try_scope_mutex(old_lock);
        PERFORM public.maru_workforce_page9_try_scope_mutex(new_lock);
    ELSE
        PERFORM public.maru_workforce_page9_try_scope_mutex(new_lock);
        PERFORM public.maru_workforce_page9_try_scope_mutex(old_lock);
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$page9_scope_mutex$;

REVOKE ALL ON FUNCTION
    public.maru_workforce_page9_writer_barrier(),
    public.maru_workforce_page9_try_scope_mutex(bigint),
    public.maru_workforce_page9_scope_mutex()
FROM PUBLIC;
"""


REMOVE_BARRIER_FUNCTIONS_SQL = r"""
DROP FUNCTION IF EXISTS public.maru_workforce_page9_scope_mutex();
DROP FUNCTION IF EXISTS public.maru_workforce_page9_try_scope_mutex(bigint);
DROP FUNCTION IF EXISTS public.maru_workforce_page9_writer_barrier();
"""


INSTALL_CORE_FUNCTIONS_SQL = r"""
CREATE FUNCTION public.maru_validate_edition_structure_control()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_control$
DECLARE
    edition_organization_id uuid;
    edition_lifecycle text;
    organization_lifecycle text;
BEGIN
    SELECT edition.organization_id, edition.lifecycle, organization.lifecycle
      INTO edition_organization_id, edition_lifecycle, organization_lifecycle
      FROM public.events_eventedition AS edition
      JOIN public.organizations_organization AS organization
        ON organization.id = edition.organization_id
     WHERE edition.id = NEW.edition_id;
    IF NOT FOUND
       OR edition_organization_id <> NEW.organization_id
    THEN
        RAISE EXCEPTION 'structure control scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF organization_lifecycle NOT IN ('draft', 'active')
       OR edition_lifecycle NOT IN ('draft', 'preparing')
    THEN
        RAISE EXCEPTION 'structure control lifecycle is read-only'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.origin NOT IN ('manual', 'builtin_template')
           OR NEW.aggregate_version <> 1
        THEN
            RAISE EXCEPTION 'new structure control must start at version one'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.workforce_department
             WHERE organization_id = NEW.organization_id
               AND edition_id = NEW.edition_id
        ) OR EXISTS (
            SELECT 1 FROM public.workforce_position
             WHERE organization_id = NEW.organization_id
               AND edition_id = NEW.edition_id
        ) OR EXISTS (
            SELECT 1 FROM public.workforce_positionassignment
             WHERE organization_id = NEW.organization_id
               AND edition_id = NEW.edition_id
        ) OR EXISTS (
            SELECT 1 FROM public.authorization_scopedresourcebinding
             WHERE organization_id = NEW.organization_id
               AND edition_id = NEW.edition_id
               AND resource_kind = 'workforce.position'
        ) THEN
            RAISE EXCEPTION 'new structure control requires an empty workforce scope'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
       OR NEW.origin IS DISTINCT FROM OLD.origin
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.aggregate_version <> OLD.aggregate_version + 1
    THEN
        RAISE EXCEPTION 'structure control is immutable except for one version step'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$page9_control$;

CREATE FUNCTION public.maru_assert_edition_structure_control_evidence()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_control_evidence$
DECLARE
    current_origin text;
    current_version bigint;
    expected_first_version bigint;
    receipt_count bigint;
    receipt_min bigint;
    receipt_max bigint;
BEGIN
    IF NEW.origin = 'legacy_existing' AND NEW.aggregate_version = 1 THEN
        RETURN NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.structure_id = NEW.id
           AND receipt.resulting_version = NEW.aggregate_version
    ) THEN
        RAISE EXCEPTION 'structure control version lacks its immutable receipt'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.aggregate_version = 1
       AND (
           (NEW.origin = 'manual' AND NOT EXISTS (
               SELECT 1
                 FROM public.workforce_editionstructurecommandreceipt
                WHERE structure_id = NEW.id
                  AND resulting_version = 1
                  AND action = 'department_created'
           ))
           OR (NEW.origin = 'builtin_template' AND NOT EXISTS (
               SELECT 1
                 FROM public.workforce_editionstructurecommandreceipt
                WHERE structure_id = NEW.id
                  AND resulting_version = 1
                  AND action = 'template_applied'
           ))
       )
    THEN
        RAISE EXCEPTION 'first structure receipt does not match its origin'
            USING ERRCODE = '23514';
    END IF;

    SELECT control.origin, control.aggregate_version
      INTO current_origin, current_version
      FROM public.workforce_editionstructurecontrol AS control
     WHERE control.id = NEW.id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'structure control disappeared before evidence validation'
            USING ERRCODE = '23514';
    END IF;
    expected_first_version := CASE
        WHEN current_origin = 'legacy_existing' THEN 2
        ELSE 1
    END;
    SELECT COUNT(*), MIN(resulting_version), MAX(resulting_version)
      INTO receipt_count, receipt_min, receipt_max
      FROM public.workforce_editionstructurecommandreceipt
     WHERE structure_id = NEW.id;
    IF current_version < expected_first_version THEN
        IF receipt_count <> 0 THEN
            RAISE EXCEPTION 'legacy structure has fabricated initial evidence'
                USING ERRCODE = '23514';
        END IF;
    ELSIF receipt_count <> current_version - expected_first_version + 1
       OR receipt_min <> expected_first_version
       OR receipt_max <> current_version
    THEN
        RAISE EXCEPTION 'structure receipt history is not contiguous'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$page9_control_evidence$;

CREATE FUNCTION public.maru_prevent_edition_structure_control_mutation()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_control_no_mutation$
BEGIN
    IF TG_OP = 'TRUNCATE'
       AND public.maru_authority_provenance_test_reset_allowed()
    THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'structure controls cannot be deleted or truncated'
        USING ERRCODE = '23514';
END;
$page9_control_no_mutation$;

REVOKE ALL ON FUNCTION
    public.maru_validate_edition_structure_control(),
    public.maru_assert_edition_structure_control_evidence(),
    public.maru_prevent_edition_structure_control_mutation()
FROM PUBLIC;
"""


REMOVE_CORE_FUNCTIONS_SQL = r"""
DROP FUNCTION IF EXISTS public.maru_prevent_edition_structure_control_mutation();
DROP FUNCTION IF EXISTS public.maru_assert_edition_structure_control_evidence();
DROP FUNCTION IF EXISTS public.maru_validate_edition_structure_control();
"""


INSTALL_RECEIPT_FUNCTIONS_SQL = r"""
CREATE FUNCTION public.maru_validate_edition_structure_receipt()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_receipt$
DECLARE
    control_origin text;
    control_version bigint;
    control_organization_id uuid;
    control_edition_id uuid;
    duplicate_count bigint;
    mismatch_count bigint;
BEGIN
    SELECT control.origin,
           control.aggregate_version,
           control.organization_id,
           control.edition_id
      INTO control_origin,
           control_version,
           control_organization_id,
           control_edition_id
      FROM public.workforce_editionstructurecontrol AS control
     WHERE control.id = NEW.structure_id;
    IF NOT FOUND
       OR control_organization_id <> NEW.organization_id
       OR control_edition_id <> NEW.edition_id
       OR control_version <> NEW.resulting_version
    THEN
        RAISE EXCEPTION 'structure receipt must match the current control version'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.events_eventedition AS edition
         WHERE edition.id = NEW.edition_id
           AND edition.organization_id = NEW.organization_id
    ) THEN
        RAISE EXCEPTION 'structure receipt edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF control_origin = 'legacy_existing' AND NEW.resulting_version = 1 THEN
        RAISE EXCEPTION 'legacy structure version one has no fabricated receipt'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.action NOT IN (
        'template_applied',
        'department_created',
        'department_updated',
        'department_retired',
        'department_deleted'
    ) THEN
        RAISE EXCEPTION 'unknown structure receipt action'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.reason = ''
       OR NEW.reason <> pg_catalog.btrim(NEW.reason)
       OR NEW.reason ~ '[[:cntrl:]]'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
    THEN
        RAISE EXCEPTION 'structure receipt text evidence is malformed'
            USING ERRCODE = '23514';
    END IF;
    IF pg_catalog.array_ndims(NEW.changed_fields) <> 1
       OR pg_catalog.cardinality(NEW.changed_fields) < 1
       OR pg_catalog.cardinality(NEW.changed_fields) > 16
       OR pg_catalog.array_position(NEW.changed_fields, NULL) IS NOT NULL
       OR pg_catalog.array_ndims(NEW.affected_department_ids) <> 1
       OR pg_catalog.cardinality(NEW.affected_department_ids) < 1
       OR pg_catalog.cardinality(NEW.affected_department_ids) > 256
       OR pg_catalog.array_position(NEW.affected_department_ids, NULL) IS NOT NULL
    THEN
        RAISE EXCEPTION 'structure receipt arrays are malformed'
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
        RAISE EXCEPTION 'changed fields must be unique and canonical'
            USING ERRCODE = '23514';
    END IF;
    SELECT COUNT(*) - COUNT(DISTINCT supplied.value)
      INTO duplicate_count
      FROM pg_catalog.unnest(NEW.affected_department_ids) AS supplied(value);
    IF duplicate_count <> 0 THEN
        RAISE EXCEPTION 'affected Department identifiers must be unique'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.action IN ('template_applied', 'department_created') THEN
        IF NEW.retry_key IS NULL
           OR NEW.request_digest !~ '^[0-9a-f]{64}$'
        THEN
            RAISE EXCEPTION 'creation receipt retry evidence is incomplete'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.retry_key IS NOT NULL OR NEW.request_digest <> '' THEN
        RAISE EXCEPTION 'non-creation receipt cannot contain retry evidence'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.action = 'template_applied' THEN
        IF NEW.template_code <> 'awoostria-reference'
           OR NEW.template_version <> 1
           OR NEW.template_digest <>
              'a0eb4def29ed904b5e1279bd72bf4da7f99c94e804cabf10c196b536c5ca7901'
           OR NEW.deleted_name_snapshot <> ''
           OR NEW.changed_fields <> ARRAY['departments']::varchar[]
           OR pg_catalog.cardinality(NEW.affected_department_ids) <> 22
        THEN
            RAISE EXCEPTION 'template receipt does not match the pinned catalog'
                USING ERRCODE = '23514';
        END IF;

        WITH expected(
            ordinality,
            code,
            name,
            description,
            display_order,
            parent_code
        ) AS (
            VALUES
            (1, 'helper-board', 'Helper Board',
             'Readiness, risks, approvals, cross-department blockers, and material changes.',
             0, NULL::text),
            (2, 'art', 'Art',
             'Configured applications, allocations, content classification, inventory, staffing, payments, and reconciliation.',
             1, 'helper-board'),
            (3, 'charity', 'Charity',
             'Configured applications, allocations, content classification, inventory, staffing, payments, and reconciliation.',
             2, 'helper-board'),
            (4, 'ceremonies', 'Ceremonies',
             'Service capacity, spaces, programme dependencies, queues, shifts, and run of show.',
             3, 'helper-board'),
            (5, 'dealers-den', 'Dealers'' Den',
             'Configured applications, allocations, content classification, inventory, staffing, payments, and reconciliation.',
             4, 'helper-board'),
            (6, 'decorations', 'Decorations',
             'Storage, boxes, kits, manifests, movements, maintenance, deployment, and return.',
             5, 'helper-board'),
            (7, 'events-programming', 'Events & Programming',
             'Calls, proposals, review, readiness, timetable, hosts, and public copy.',
             6, 'helper-board'),
            (8, 'front-desk', 'Front Desk',
             'Attendee lookup, payment and check-in state, badges, service requests, knowledge, and surge staffing.',
             7, 'helper-board'),
            (9, 'fursuit-support', 'Fursuit Support',
             'Service capacity, spaces, programme dependencies, queues, shifts, and run of show.',
             8, 'helper-board'),
            (10, 'graphics-design', 'Graphics Design',
             'Briefs, assets, approvals, rights, publishing schedule, and public content renditions.',
             9, 'helper-board'),
            (11, 'human-resources', 'Human Resources',
             'Opportunities, applications, onboarding, qualifications, assignments, availability, hours, and handover.',
             10, 'helper-board'),
            (12, 'it', 'IT',
             'Storage, boxes, kits, manifests, movements, maintenance, deployment, and return.',
             11, 'helper-board'),
            (13, 'legal-compliance', 'Legal & Compliance',
             'Narrowly scoped cases, duty routing, access policy, retention, and ordinary minimum-disclosure tasks.',
             12, 'helper-board'),
            (14, 'logistics', 'Logistics',
             'Storage, boxes, kits, manifests, movements, maintenance, deployment, and return.',
             13, 'helper-board'),
            (15, 'maid-cafe', 'Maid Café',
             'Configured applications, allocations, content classification, inventory, staffing, payments, and reconciliation.',
             14, 'helper-board'),
            (16, 'multimedia', 'Multimedia',
             'Riders, cues, equipment, rehearsals, setup and teardown, operator shifts, and media consent.',
             15, 'helper-board'),
            (17, 'peer', 'PEER',
             'Narrowly scoped cases, duty routing, access policy, retention, and ordinary minimum-disclosure tasks.',
             16, 'helper-board'),
            (18, 'registration', 'Registration',
             'Attendee lookup, payment and check-in state, badges, service requests, knowledge, and surge staffing.',
             17, 'helper-board'),
            (19, 'security', 'Security',
             'Narrowly scoped cases, duty routing, access policy, retention, and ordinary minimum-disclosure tasks.',
             18, 'helper-board'),
            (20, 'social-media', 'Social Media',
             'Briefs, assets, approvals, rights, publishing schedule, and public content renditions.',
             19, 'helper-board'),
            (21, 'stage-tech', 'Stage Tech',
             'Riders, cues, equipment, rehearsals, setup and teardown, operator shifts, and media consent.',
             20, 'helper-board'),
            (22, 'story', 'Story',
             'Briefs, assets, approvals, rights, publishing schedule, and public content renditions.',
             21, 'helper-board')
        ), affected AS (
            SELECT supplied.department_id, supplied.ordinality
              FROM pg_catalog.unnest(NEW.affected_department_ids)
                   WITH ORDINALITY AS supplied(department_id, ordinality)
        )
        SELECT COUNT(*) INTO mismatch_count
          FROM affected
          JOIN expected USING (ordinality)
          LEFT JOIN public.workforce_department AS department
            ON department.id = affected.department_id
          LEFT JOIN public.workforce_department AS parent
            ON parent.id = department.parent_id
         WHERE department.id IS NULL
            OR department.organization_id <> NEW.organization_id
            OR department.edition_id <> NEW.edition_id
            OR department.code <> expected.code
            OR department.name <> expected.name
            OR department.description <> expected.description
            OR department.position <> expected.display_order
            OR parent.code IS DISTINCT FROM expected.parent_code
            OR department.created_in_structure_version <> NEW.resulting_version
            OR department.last_changed_in_structure_version <>
               NEW.resulting_version
            OR department.retired_at IS NOT NULL;
        IF mismatch_count <> 0 THEN
            RAISE EXCEPTION 'template receipt does not match copied Departments'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.template_code <> ''
           OR NEW.template_version IS NOT NULL
           OR NEW.template_digest <> ''
        THEN
            RAISE EXCEPTION 'non-template receipt cannot contain template evidence'
                USING ERRCODE = '23514';
        END IF;
        IF pg_catalog.cardinality(NEW.affected_department_ids) <> 1 THEN
            RAISE EXCEPTION 'Department receipt must affect exactly one identifier'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.action IN ('department_created', 'department_deleted')
           AND NEW.changed_fields <> ARRAY['departments']::varchar[]
        THEN
            RAISE EXCEPTION 'creation/deletion changed-fields evidence is malformed'
                USING ERRCODE = '23514';
        ELSIF NEW.action = 'department_retired'
           AND NEW.changed_fields <> ARRAY['retirement']::varchar[]
        THEN
            RAISE EXCEPTION 'retirement changed-fields evidence is malformed'
                USING ERRCODE = '23514';
        ELSIF NEW.action = 'department_updated'
           AND EXISTS (
               SELECT 1
                 FROM pg_catalog.unnest(NEW.changed_fields) AS supplied(value)
                WHERE supplied.value NOT IN (
                    'description',
                    'display_order',
                    'name',
                    'parent_department'
                )
           )
        THEN
            RAISE EXCEPTION 'update changed-fields evidence is malformed'
                USING ERRCODE = '23514';
        END IF;

        IF NEW.action = 'department_deleted' THEN
            IF NEW.deleted_name_snapshot = ''
               OR NEW.deleted_name_snapshot <>
                  pg_catalog.btrim(NEW.deleted_name_snapshot)
               OR NEW.deleted_name_snapshot ~ '[[:cntrl:]]'
               OR EXISTS (
                   SELECT 1 FROM public.workforce_department
                    WHERE id = NEW.affected_department_ids[1]
               )
            THEN
                RAISE EXCEPTION 'deleted Department tombstone is malformed'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NEW.deleted_name_snapshot <> '' THEN
            RAISE EXCEPTION 'only deletion retains a Department name tombstone'
                USING ERRCODE = '23514';
        END IF;

        IF NEW.action = 'department_created'
           AND NOT EXISTS (
               SELECT 1 FROM public.workforce_department AS department
                WHERE department.id = NEW.affected_department_ids[1]
                  AND department.organization_id = NEW.organization_id
                  AND department.edition_id = NEW.edition_id
                  AND department.created_in_structure_version =
                      NEW.resulting_version
                  AND department.last_changed_in_structure_version =
                      NEW.resulting_version
                  AND department.retired_at IS NULL
           )
        THEN
            RAISE EXCEPTION 'created Department receipt precedes its target state'
                USING ERRCODE = '23514';
        ELSIF NEW.action = 'department_updated'
           AND NOT EXISTS (
               SELECT 1 FROM public.workforce_department AS department
                WHERE department.id = NEW.affected_department_ids[1]
                  AND department.organization_id = NEW.organization_id
                  AND department.edition_id = NEW.edition_id
                  AND department.last_changed_in_structure_version =
                      NEW.resulting_version
                  AND department.retired_at IS NULL
           )
        THEN
            RAISE EXCEPTION 'updated Department receipt precedes its target state'
                USING ERRCODE = '23514';
        ELSIF NEW.action = 'department_retired'
           AND NOT EXISTS (
               SELECT 1 FROM public.workforce_department AS department
                WHERE department.id = NEW.affected_department_ids[1]
                  AND department.organization_id = NEW.organization_id
                  AND department.edition_id = NEW.edition_id
                  AND department.retired_at IS NOT NULL
                  AND department.retired_in_structure_version =
                      NEW.resulting_version
                  AND department.last_changed_in_structure_version =
                      NEW.resulting_version
           )
        THEN
            RAISE EXCEPTION 'retirement receipt precedes its target state'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$page9_receipt$;

CREATE FUNCTION public.maru_prevent_edition_structure_receipt_mutation()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_receipt_immutable$
BEGIN
    IF TG_OP = 'TRUNCATE'
       AND public.maru_authority_provenance_test_reset_allowed()
    THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'structure receipts are immutable and cannot be truncated'
        USING ERRCODE = '23514';
END;
$page9_receipt_immutable$;

REVOKE ALL ON FUNCTION
    public.maru_validate_edition_structure_receipt(),
    public.maru_prevent_edition_structure_receipt_mutation()
FROM PUBLIC;
"""


REMOVE_RECEIPT_FUNCTIONS_SQL = r"""
DROP FUNCTION IF EXISTS public.maru_prevent_edition_structure_receipt_mutation();
DROP FUNCTION IF EXISTS public.maru_validate_edition_structure_receipt();
"""


INSTALL_DEPARTMENT_FUNCTIONS_SQL = r"""
CREATE FUNCTION public.maru_workforce_department_fk_contract_is_current()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_fk_contract$
    SELECT NOT EXISTS (
        SELECT 1
          FROM pg_catalog.pg_constraint AS constraint_record
         WHERE constraint_record.contype = 'f'
           AND constraint_record.confrelid =
               'public.workforce_department'::pg_catalog.regclass
           AND NOT (
               constraint_record.confdeltype IN ('a', 'r')
               AND (
                   SELECT pg_catalog.array_agg(attribute.attname::text
                                               ORDER BY key_column.ordinality)
                     FROM pg_catalog.unnest(constraint_record.confkey)
                          WITH ORDINALITY
                          AS key_column(attnum, ordinality)
                     JOIN pg_catalog.pg_attribute AS attribute
                       ON attribute.attrelid = constraint_record.confrelid
                      AND attribute.attnum = key_column.attnum
               ) = ARRAY['id']::text[]
               AND CASE constraint_record.conrelid
                   WHEN 'public.workforce_department'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['parent_id']::text[]
                   WHEN 'public.workforce_position'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   WHEN 'public.authorization_scopedresourcebinding'::pg_catalog.regclass
                       THEN (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   WHEN 'public.authorization_capabilitygrant'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   WHEN 'public.authorization_roleassignment'::pg_catalog.regclass THEN
                       (
                           SELECT pg_catalog.array_agg(attribute.attname::text
                                                       ORDER BY key_column.ordinality)
                             FROM pg_catalog.unnest(constraint_record.conkey)
                                  WITH ORDINALITY
                                  AS key_column(attnum, ordinality)
                             JOIN pg_catalog.pg_attribute AS attribute
                               ON attribute.attrelid = constraint_record.conrelid
                              AND attribute.attnum = key_column.attnum
                       ) = ARRAY['department_id']::text[]
                   ELSE FALSE
               END
           )
    );
$page9_fk_contract$;

CREATE FUNCTION public.maru_validate_department_structure_write()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_department$
DECLARE
    subject_id uuid;
    subject_organization_id uuid;
    subject_edition_id uuid;
    control_version bigint;
    edition_organization_id uuid;
    edition_lifecycle text;
    organization_lifecycle text;
    parent_organization_id uuid;
    parent_edition_id uuid;
    parent_retired_at timestamptz;
    ancestor_depth integer := 0;
    descendant_depth integer := 0;
    hierarchy_cycle boolean := FALSE;
    retirement_transition boolean := FALSE;
    semantic_change boolean := FALSE;
    creation_evidence_count bigint;
    other_evidence_count bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subject_id := OLD.id;
        subject_organization_id := OLD.organization_id;
        subject_edition_id := OLD.edition_id;
    ELSE
        subject_id := NEW.id;
        subject_organization_id := NEW.organization_id;
        subject_edition_id := NEW.edition_id;
    END IF;

    SELECT control.aggregate_version
      INTO control_version
      FROM public.workforce_editionstructurecontrol AS control
     WHERE control.organization_id = subject_organization_id
       AND control.edition_id = subject_edition_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Department write requires its structure control first'
            USING ERRCODE = '23514';
    END IF;
    SELECT edition.organization_id, edition.lifecycle, organization.lifecycle
      INTO edition_organization_id, edition_lifecycle, organization_lifecycle
      FROM public.events_eventedition AS edition
      JOIN public.organizations_organization AS organization
        ON organization.id = edition.organization_id
     WHERE edition.id = subject_edition_id;
    IF NOT FOUND OR edition_organization_id <> subject_organization_id THEN
        RAISE EXCEPTION 'Department edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF organization_lifecycle NOT IN ('draft', 'active')
       OR edition_lifecycle NOT IN ('draft', 'preparing')
    THEN
        RAISE EXCEPTION 'Department structure lifecycle is read-only'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF OLD.retired_at IS NOT NULL
           OR OLD.created_in_structure_version IS NULL
           OR OLD.last_changed_in_structure_version IS DISTINCT FROM
              OLD.created_in_structure_version
        THEN
            RAISE EXCEPTION 'only an unused, never-changed Department can be deleted'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.workforce_department
             WHERE parent_id = OLD.id
        ) OR EXISTS (
            SELECT 1 FROM public.workforce_position
             WHERE department_id = OLD.id
        ) OR EXISTS (
            SELECT 1 FROM public.authorization_scopedresourcebinding
             WHERE department_id = OLD.id
        ) OR EXISTS (
            SELECT 1 FROM public.authorization_capabilitygrant
             WHERE department_id = OLD.id
        ) OR EXISTS (
            SELECT 1 FROM public.authorization_roleassignment
             WHERE department_id = OLD.id
        ) THEN
            RAISE EXCEPTION 'Department deletion is protected by retained dependencies'
                USING ERRCODE = '23514';
        END IF;
        SELECT COUNT(*) FILTER (
                   WHERE receipt.action IN (
                       'template_applied', 'department_created'
                   )
               ),
               COUNT(*) FILTER (
                   WHERE receipt.action NOT IN (
                       'template_applied', 'department_created'
                   )
               )
          INTO creation_evidence_count, other_evidence_count
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE OLD.id = ANY(receipt.affected_department_ids);
        IF creation_evidence_count <> 1 OR other_evidence_count <> 0 THEN
            RAISE EXCEPTION 'Department deletion history is not creation-only'
                USING ERRCODE = '23514';
        END IF;
        IF NOT public.maru_workforce_department_fk_contract_is_current() THEN
            RAISE EXCEPTION 'Department foreign-key contract changed; deletion denied'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.code !~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'
       OR NEW.name = ''
       OR NEW.name <> pg_catalog.btrim(NEW.name)
       OR NEW.name ~ '[[:cntrl:]]'
       OR NEW.description <> pg_catalog.btrim(NEW.description)
       OR NEW.description ~ '[[:cntrl:]]'
       OR NEW.position < 0
       OR NEW.position > 65535
    THEN
        RAISE EXCEPTION 'Department fields violate the closed structure contract'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.created_in_structure_version IS NULL
           OR NEW.created_in_structure_version <> control_version
           OR NEW.last_changed_in_structure_version <> control_version
           OR NEW.retired_at IS NOT NULL
           OR NEW.retired_by_id IS NOT NULL
           OR NEW.retired_in_structure_version IS NOT NULL
        THEN
            RAISE EXCEPTION 'Department creation version evidence is malformed'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1
              FROM public.workforce_editionstructurecommandreceipt AS receipt
             WHERE NEW.id = ANY(receipt.affected_department_ids)
        ) THEN
            RAISE EXCEPTION 'a retained Department identifier cannot be reused'
                USING ERRCODE = '23514';
        END IF;
        IF (
            SELECT COUNT(*)
              FROM public.workforce_department
             WHERE organization_id = NEW.organization_id
               AND edition_id = NEW.edition_id
        ) >= 256 THEN
            RAISE EXCEPTION 'edition Department limit exceeded'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF OLD.retired_at IS NOT NULL THEN
            RAISE EXCEPTION 'retired Departments are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.code IS DISTINCT FROM OLD.code
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.created_in_structure_version IS DISTINCT FROM
              OLD.created_in_structure_version
        THEN
            RAISE EXCEPTION 'Department identity, scope, code, and creation are immutable'
                USING ERRCODE = '23514';
        END IF;
        retirement_transition :=
            OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL;
        semantic_change :=
            NEW.name IS DISTINCT FROM OLD.name
            OR NEW.description IS DISTINCT FROM OLD.description
            OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
            OR NEW.position IS DISTINCT FROM OLD.position;
        IF OLD.last_changed_in_structure_version IS NOT NULL
           AND OLD.last_changed_in_structure_version >= control_version
        THEN
            RAISE EXCEPTION 'Department already changed at the current structure version'
                USING ERRCODE = '23514';
        END IF;
        IF retirement_transition THEN
            IF semantic_change
               OR NEW.retired_by_id IS NULL
               OR NEW.retired_in_structure_version <> control_version
               OR NEW.last_changed_in_structure_version <> control_version
            THEN
                RAISE EXCEPTION 'Department retirement evidence is malformed'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1 FROM public.workforce_department AS child
                 WHERE child.parent_id = OLD.id
                   AND child.retired_at IS NULL
            ) OR EXISTS (
                SELECT 1 FROM public.workforce_position AS position
                 WHERE position.department_id = OLD.id
                   AND position.status <> 'closed'
            ) OR EXISTS (
                SELECT 1
                  FROM public.workforce_positionassignment AS assignment
                  JOIN public.workforce_position AS position
                    ON position.id = assignment.position_id
                 WHERE position.department_id = OLD.id
                   AND assignment.status = 'active'
                   AND (
                       assignment.expires_at IS NULL
                       OR assignment.expires_at >
                          pg_catalog.transaction_timestamp()
                   )
            ) OR EXISTS (
                SELECT 1 FROM public.authorization_capabilitygrant AS authority
                 WHERE authority.department_id = OLD.id
                   AND authority.revoked_at IS NULL
                   AND (
                       authority.expires_at IS NULL
                       OR authority.expires_at >
                          pg_catalog.transaction_timestamp()
                   )
            ) OR EXISTS (
                SELECT 1 FROM public.authorization_roleassignment AS authority
                 WHERE authority.department_id = OLD.id
                   AND authority.revoked_at IS NULL
                   AND (
                       authority.expires_at IS NULL
                       OR authority.expires_at >
                          pg_catalog.transaction_timestamp()
                   )
            ) THEN
                RAISE EXCEPTION 'current or future operations block Department retirement'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END IF;
        IF NEW.retired_at IS NOT NULL
           OR NEW.retired_by_id IS NOT NULL
           OR NEW.retired_in_structure_version IS NOT NULL
           OR NOT semantic_change
           OR NEW.last_changed_in_structure_version <> control_version
        THEN
            RAISE EXCEPTION 'Department update version evidence is malformed'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.parent_id IS NOT NULL THEN
        SELECT parent.organization_id, parent.edition_id, parent.retired_at
          INTO parent_organization_id, parent_edition_id, parent_retired_at
          FROM public.workforce_department AS parent
         WHERE parent.id = NEW.parent_id;
        IF NOT FOUND
           OR NEW.parent_id = NEW.id
           OR parent_organization_id <> NEW.organization_id
           OR parent_edition_id <> NEW.edition_id
           OR parent_retired_at IS NOT NULL
        THEN
            RAISE EXCEPTION 'Department parent must be active in the exact edition'
                USING ERRCODE = '23514';
        END IF;

        WITH RECURSIVE ancestry AS (
            SELECT parent.id,
                   parent.parent_id,
                   1 AS depth,
                   ARRAY[NEW.id, parent.id]::uuid[] AS path,
                   parent.id = NEW.id AS cycle
              FROM public.workforce_department AS parent
             WHERE parent.id = NEW.parent_id
            UNION ALL
            SELECT parent.id,
                   parent.parent_id,
                   ancestry.depth + 1,
                   ancestry.path || parent.id,
                   parent.id = ANY(ancestry.path)
              FROM ancestry
              JOIN public.workforce_department AS parent
                ON parent.id = ancestry.parent_id
             WHERE NOT ancestry.cycle
               AND ancestry.depth <= 32
        )
        SELECT COALESCE(MAX(depth), 0), COALESCE(BOOL_OR(cycle), FALSE)
          INTO ancestor_depth, hierarchy_cycle
          FROM ancestry;
    END IF;

    WITH RECURSIVE descendants AS (
        SELECT NEW.id AS id, 0 AS depth
        UNION ALL
        SELECT child.id, descendants.depth + 1
          FROM descendants
          JOIN public.workforce_department AS child
            ON child.parent_id = descendants.id
         WHERE descendants.depth <= 32
    )
    SELECT COALESCE(MAX(depth), 0)
      INTO descendant_depth
      FROM descendants;
    IF hierarchy_cycle OR 1 + ancestor_depth + descendant_depth > 32 THEN
        RAISE EXCEPTION 'Department hierarchy exceeds the acyclic depth bound'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$page9_department$;

CREATE FUNCTION public.maru_assert_department_structure_evidence()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_department_evidence$
DECLARE
    actual_fields varchar[] := ARRAY[]::varchar[];
    matching_receipts bigint;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_version = NEW.created_in_structure_version
           AND (
               (
                   receipt.action = 'department_created'
                   AND receipt.affected_department_ids = ARRAY[NEW.id]::uuid[]
               )
               OR (
                   receipt.action = 'template_applied'
                   AND NEW.id = ANY(receipt.affected_department_ids)
               )
           );
    ELSIF TG_OP = 'DELETE' THEN
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = OLD.organization_id
           AND receipt.edition_id = OLD.edition_id
           AND receipt.action = 'department_deleted'
           AND receipt.changed_fields = ARRAY['departments']::varchar[]
           AND receipt.affected_department_ids = ARRAY[OLD.id]::uuid[]
           AND receipt.deleted_name_snapshot = OLD.name;
    ELSIF OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL THEN
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_version = NEW.last_changed_in_structure_version
           AND receipt.action = 'department_retired'
           AND receipt.changed_fields = ARRAY['retirement']::varchar[]
           AND receipt.affected_department_ids = ARRAY[NEW.id]::uuid[]
           AND receipt.actor_id = NEW.retired_by_id;
    ELSE
        IF NEW.description IS DISTINCT FROM OLD.description THEN
            actual_fields := actual_fields || 'description'::varchar;
        END IF;
        IF NEW.position IS DISTINCT FROM OLD.position THEN
            actual_fields := actual_fields || 'display_order'::varchar;
        END IF;
        IF NEW.name IS DISTINCT FROM OLD.name THEN
            actual_fields := actual_fields || 'name'::varchar;
        END IF;
        IF NEW.parent_id IS DISTINCT FROM OLD.parent_id THEN
            actual_fields := actual_fields || 'parent_department'::varchar;
        END IF;
        SELECT COUNT(*) INTO matching_receipts
          FROM public.workforce_editionstructurecommandreceipt AS receipt
         WHERE receipt.organization_id = NEW.organization_id
           AND receipt.edition_id = NEW.edition_id
           AND receipt.resulting_version = NEW.last_changed_in_structure_version
           AND receipt.action = 'department_updated'
           AND receipt.changed_fields = actual_fields
           AND receipt.affected_department_ids = ARRAY[NEW.id]::uuid[];
    END IF;
    IF matching_receipts <> 1 THEN
        RAISE EXCEPTION 'Department mutation lacks exact immutable command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$page9_department_evidence$;

CREATE FUNCTION public.maru_prevent_department_structure_truncate()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_department_no_truncate$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Departments cannot be truncated after Page 9 cutover'
        USING ERRCODE = '23514';
END;
$page9_department_no_truncate$;

REVOKE ALL ON FUNCTION
    public.maru_workforce_department_fk_contract_is_current(),
    public.maru_validate_department_structure_write(),
    public.maru_assert_department_structure_evidence(),
    public.maru_prevent_department_structure_truncate()
FROM PUBLIC;
"""


REMOVE_DEPARTMENT_FUNCTIONS_SQL = r"""
DROP FUNCTION IF EXISTS public.maru_prevent_department_structure_truncate();
DROP FUNCTION IF EXISTS public.maru_assert_department_structure_evidence();
DROP FUNCTION IF EXISTS public.maru_validate_department_structure_write();
DROP FUNCTION IF EXISTS public.maru_workforce_department_fk_contract_is_current();
"""


INSTALL_OPERATIONAL_FUNCTIONS_SQL = r"""
CREATE FUNCTION public.maru_guard_position_retired_department()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_position_retired$
DECLARE
    department_retired_at timestamptz;
    department_organization_id uuid;
    department_edition_id uuid;
BEGIN
    SELECT department.retired_at,
           department.organization_id,
           department.edition_id
      INTO department_retired_at,
           department_organization_id,
           department_edition_id
      FROM public.workforce_department AS department
     WHERE department.id = NEW.department_id;
    IF NOT FOUND
       OR department_organization_id <> NEW.organization_id
       OR department_edition_id <> NEW.edition_id
    THEN
        RAISE EXCEPTION 'Position Department scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF department_retired_at IS NOT NULL
       AND (
           TG_OP = 'INSERT'
           OR NEW.department_id IS DISTINCT FROM OLD.department_id
           OR NEW.status <> 'closed'
           OR OLD.status <> 'closed'
       )
    THEN
        RAISE EXCEPTION 'retired Department cannot receive or reopen a Position'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$page9_position_retired$;

CREATE FUNCTION public.maru_guard_assignment_retired_department()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $page9_assignment_retired$
DECLARE
    position_organization_id uuid;
    position_edition_id uuid;
    department_retired_at timestamptz;
BEGIN
    SELECT position.organization_id,
           position.edition_id,
           department.retired_at
      INTO position_organization_id,
           position_edition_id,
           department_retired_at
      FROM public.workforce_position AS position
      JOIN public.workforce_department AS department
        ON department.id = position.department_id
     WHERE position.id = NEW.position_id;
    IF NOT FOUND
       OR position_organization_id <> NEW.organization_id
       OR position_edition_id <> NEW.edition_id
    THEN
        RAISE EXCEPTION 'Position assignment scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF department_retired_at IS NOT NULL
       AND (
           TG_OP = 'INSERT'
           OR NEW.position_id IS DISTINCT FROM OLD.position_id
           OR NEW.status <> 'ended'
       )
    THEN
        RAISE EXCEPTION 'retired Department cannot receive an open assignment'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$page9_assignment_retired$;

REVOKE ALL ON FUNCTION
    public.maru_guard_position_retired_department(),
    public.maru_guard_assignment_retired_department()
FROM PUBLIC;
"""


REMOVE_OPERATIONAL_FUNCTIONS_SQL = r"""
DROP FUNCTION IF EXISTS public.maru_guard_assignment_retired_department();
DROP FUNCTION IF EXISTS public.maru_guard_position_retired_department();
"""


INSTALL_STRUCTURE_TRIGGERS_SQL = r"""
CREATE TRIGGER aa_workforce_page9_department_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.workforce_department
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER aa_workforce_page9_control_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.workforce_editionstructurecontrol
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER aa_workforce_page9_receipt_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.workforce_editionstructurecommandreceipt
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER aa_workforce_page9_position_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.workforce_position
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER aa_workforce_page9_assignment_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.workforce_positionassignment
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER aa_workforce_page9_binding_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.authorization_scopedresourcebinding
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER aa_workforce_page9_capability_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.authorization_capabilitygrant
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER aa_workforce_page9_role_barrier
BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE
ON public.authorization_roleassignment
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_workforce_page9_writer_barrier();

CREATE TRIGGER ab_workforce_page9_department_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_department
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ab_workforce_page9_control_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_editionstructurecontrol
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ab_workforce_page9_receipt_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_editionstructurecommandreceipt
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ab_workforce_page9_position_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_position
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ab_workforce_page9_assignment_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_positionassignment
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ab_workforce_page9_binding_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.authorization_scopedresourcebinding
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ab_workforce_page9_capability_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.authorization_capabilitygrant
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ab_workforce_page9_role_scope
BEFORE INSERT OR UPDATE OR DELETE
ON public.authorization_roleassignment
FOR EACH ROW
EXECUTE FUNCTION public.maru_workforce_page9_scope_mutex();

CREATE TRIGGER ac_workforce_page9_control_guard
BEFORE INSERT OR UPDATE
ON public.workforce_editionstructurecontrol
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_edition_structure_control();

CREATE TRIGGER ac_workforce_page9_control_no_delete
BEFORE DELETE
ON public.workforce_editionstructurecontrol
FOR EACH ROW
EXECUTE FUNCTION public.maru_prevent_edition_structure_control_mutation();

CREATE TRIGGER ac_workforce_page9_control_no_truncate
BEFORE TRUNCATE
ON public.workforce_editionstructurecontrol
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_prevent_edition_structure_control_mutation();

CREATE TRIGGER ac_workforce_page9_receipt_guard
BEFORE INSERT
ON public.workforce_editionstructurecommandreceipt
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_edition_structure_receipt();

CREATE TRIGGER ac_workforce_page9_receipt_immutable
BEFORE UPDATE OR DELETE
ON public.workforce_editionstructurecommandreceipt
FOR EACH ROW
EXECUTE FUNCTION public.maru_prevent_edition_structure_receipt_mutation();

CREATE TRIGGER ac_workforce_page9_receipt_no_truncate
BEFORE TRUNCATE
ON public.workforce_editionstructurecommandreceipt
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_prevent_edition_structure_receipt_mutation();

CREATE TRIGGER ac_workforce_page9_department_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_department
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_department_structure_write();

CREATE TRIGGER ac_workforce_page9_department_no_truncate
BEFORE TRUNCATE
ON public.workforce_department
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_prevent_department_structure_truncate();

CREATE TRIGGER ac_workforce_page9_position_retired_guard
BEFORE INSERT OR UPDATE OF department_id, organization_id, edition_id, status
ON public.workforce_position
FOR EACH ROW
EXECUTE FUNCTION public.maru_guard_position_retired_department();

CREATE TRIGGER ac_workforce_page9_assignment_retired_guard
BEFORE INSERT OR UPDATE OF position_id, organization_id, edition_id, status
ON public.workforce_positionassignment
FOR EACH ROW
EXECUTE FUNCTION public.maru_guard_assignment_retired_department();

CREATE CONSTRAINT TRIGGER workforce_page9_control_evidence
AFTER INSERT OR UPDATE
ON public.workforce_editionstructurecontrol
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_assert_edition_structure_control_evidence();

CREATE CONSTRAINT TRIGGER workforce_page9_department_evidence
AFTER INSERT OR UPDATE OR DELETE
ON public.workforce_department
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION public.maru_assert_department_structure_evidence();
"""


REMOVE_STRUCTURE_TRIGGERS_SQL = r"""
DROP TRIGGER IF EXISTS workforce_page9_department_evidence
    ON public.workforce_department;
DROP TRIGGER IF EXISTS workforce_page9_control_evidence
    ON public.workforce_editionstructurecontrol;
DROP TRIGGER IF EXISTS ac_workforce_page9_assignment_retired_guard
    ON public.workforce_positionassignment;
DROP TRIGGER IF EXISTS ac_workforce_page9_position_retired_guard
    ON public.workforce_position;
DROP TRIGGER IF EXISTS ac_workforce_page9_department_no_truncate
    ON public.workforce_department;
DROP TRIGGER IF EXISTS ac_workforce_page9_department_guard
    ON public.workforce_department;
DROP TRIGGER IF EXISTS ac_workforce_page9_receipt_no_truncate
    ON public.workforce_editionstructurecommandreceipt;
DROP TRIGGER IF EXISTS ac_workforce_page9_receipt_immutable
    ON public.workforce_editionstructurecommandreceipt;
DROP TRIGGER IF EXISTS ac_workforce_page9_receipt_guard
    ON public.workforce_editionstructurecommandreceipt;
DROP TRIGGER IF EXISTS ac_workforce_page9_control_no_truncate
    ON public.workforce_editionstructurecontrol;
DROP TRIGGER IF EXISTS ac_workforce_page9_control_no_delete
    ON public.workforce_editionstructurecontrol;
DROP TRIGGER IF EXISTS ac_workforce_page9_control_guard
    ON public.workforce_editionstructurecontrol;
DROP TRIGGER IF EXISTS ab_workforce_page9_role_scope
    ON public.authorization_roleassignment;
DROP TRIGGER IF EXISTS ab_workforce_page9_capability_scope
    ON public.authorization_capabilitygrant;
DROP TRIGGER IF EXISTS ab_workforce_page9_binding_scope
    ON public.authorization_scopedresourcebinding;
DROP TRIGGER IF EXISTS ab_workforce_page9_assignment_scope
    ON public.workforce_positionassignment;
DROP TRIGGER IF EXISTS ab_workforce_page9_position_scope
    ON public.workforce_position;
DROP TRIGGER IF EXISTS ab_workforce_page9_receipt_scope
    ON public.workforce_editionstructurecommandreceipt;
DROP TRIGGER IF EXISTS ab_workforce_page9_control_scope
    ON public.workforce_editionstructurecontrol;
DROP TRIGGER IF EXISTS ab_workforce_page9_department_scope
    ON public.workforce_department;
DROP TRIGGER IF EXISTS aa_workforce_page9_role_barrier
    ON public.authorization_roleassignment;
DROP TRIGGER IF EXISTS aa_workforce_page9_capability_barrier
    ON public.authorization_capabilitygrant;
DROP TRIGGER IF EXISTS aa_workforce_page9_binding_barrier
    ON public.authorization_scopedresourcebinding;
DROP TRIGGER IF EXISTS aa_workforce_page9_assignment_barrier
    ON public.workforce_positionassignment;
DROP TRIGGER IF EXISTS aa_workforce_page9_position_barrier
    ON public.workforce_position;
DROP TRIGGER IF EXISTS aa_workforce_page9_receipt_barrier
    ON public.workforce_editionstructurecommandreceipt;
DROP TRIGGER IF EXISTS aa_workforce_page9_control_barrier
    ON public.workforce_editionstructurecontrol;
DROP TRIGGER IF EXISTS aa_workforce_page9_department_barrier
    ON public.workforce_department;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0010_retired_department_authority_guards"),
        ("workforce", "0006_edition_structure_schema"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            CUTOVER_AND_PREFLIGHT_SQL,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(
            backfill_legacy_structure_controls,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RunSQL(
            INSTALL_BARRIER_FUNCTIONS_SQL,
            reverse_sql=REMOVE_BARRIER_FUNCTIONS_SQL,
        ),
        migrations.RunSQL(
            INSTALL_CORE_FUNCTIONS_SQL,
            reverse_sql=REMOVE_CORE_FUNCTIONS_SQL,
        ),
        migrations.RunSQL(
            INSTALL_RECEIPT_FUNCTIONS_SQL,
            reverse_sql=REMOVE_RECEIPT_FUNCTIONS_SQL,
        ),
        migrations.RunSQL(
            INSTALL_DEPARTMENT_FUNCTIONS_SQL,
            reverse_sql=REMOVE_DEPARTMENT_FUNCTIONS_SQL,
        ),
        migrations.RunSQL(
            INSTALL_OPERATIONAL_FUNCTIONS_SQL,
            reverse_sql=REMOVE_OPERATIONAL_FUNCTIONS_SQL,
        ),
        migrations.RunSQL(
            INSTALL_STRUCTURE_TRIGGERS_SQL,
            reverse_sql=REMOVE_STRUCTURE_TRIGGERS_SQL,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_structure_integrity_downgrade,
        ),
    ]
