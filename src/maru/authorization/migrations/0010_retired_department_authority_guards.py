"""Stop new authority from targeting retired workforce Departments."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

PREFLIGHT_SQL = r"""
DO $$
DECLARE
    current_grant_count bigint;
    current_assignment_count bigint;
BEGIN
    SELECT COUNT(*)
      INTO current_grant_count
      FROM public.authorization_capabilitygrant AS authority
      JOIN public.workforce_department AS department
        ON department.id = authority.department_id
       AND department.organization_id = authority.organization_id
       AND department.edition_id = authority.edition_id
     WHERE department.retired_at IS NOT NULL
       AND authority.revoked_at IS NULL
       AND (
            authority.expires_at IS NULL
            OR authority.expires_at > pg_catalog.transaction_timestamp()
       );

    SELECT COUNT(*)
      INTO current_assignment_count
      FROM public.authorization_roleassignment AS authority
      JOIN public.workforce_department AS department
        ON department.id = authority.department_id
       AND department.organization_id = authority.organization_id
       AND department.edition_id = authority.edition_id
     WHERE department.retired_at IS NOT NULL
       AND authority.revoked_at IS NULL
       AND (
            authority.expires_at IS NULL
            OR authority.expires_at > pg_catalog.transaction_timestamp()
       );

    IF current_grant_count > 0
       OR current_assignment_count > 0
    THEN
        RAISE EXCEPTION
            'retired authority preflight failed: % grants, % roles',
            current_grant_count,
            current_assignment_count
            USING ERRCODE = '23514';
    END IF;
END;
$$;
"""


INSTALL_GUARDS_SQL = r"""
CREATE FUNCTION public.maru_lock_retired_department_authority_writer()
RETURNS trigger AS $$
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(4400450010);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_reject_retired_authority_target()
RETURNS trigger AS $$
DECLARE
    department_retired_at timestamptz;
BEGIN
    IF TG_TABLE_NAME = 'authorization_scopedresourcebinding' THEN
        SELECT department.retired_at
          INTO department_retired_at
          FROM public.workforce_department AS department
         WHERE department.id = NEW.department_id
           AND department.organization_id = NEW.organization_id
           AND department.edition_id = NEW.edition_id
         FOR UPDATE;
        IF FOUND AND department_retired_at IS NOT NULL THEN
            RAISE EXCEPTION 'retired Department cannot receive a resource binding'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.department_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Existing evidence may be closed after retirement. Inserts never gain
    -- this exemption, even when a caller attempts to manufacture old history.
    IF TG_OP = 'UPDATE'
       AND (
            NEW.revoked_at IS NOT NULL
            OR (
                NEW.expires_at IS NOT NULL
                AND NEW.expires_at <= pg_catalog.transaction_timestamp()
            )
       )
    THEN
        RETURN NEW;
    END IF;

    SELECT department.retired_at
      INTO department_retired_at
      FROM public.workforce_department AS department
     WHERE department.id = NEW.department_id
       AND department.organization_id = NEW.organization_id
       AND department.edition_id = NEW.edition_id
     FOR UPDATE;
    IF FOUND AND department_retired_at IS NOT NULL THEN
        RAISE EXCEPTION 'retired Department cannot receive current authority'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_guard_department_retirement_authority()
RETURNS trigger AS $$
BEGIN
    IF OLD.retired_at IS NULL AND NEW.retired_at IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
              FROM public.authorization_capabilitygrant AS authority
             WHERE authority.organization_id = NEW.organization_id
               AND authority.edition_id = NEW.edition_id
               AND authority.department_id = NEW.id
               AND authority.revoked_at IS NULL
               AND (
                    authority.expires_at IS NULL
                    OR authority.expires_at > pg_catalog.transaction_timestamp()
               )
        ) OR EXISTS (
            SELECT 1
              FROM public.authorization_roleassignment AS authority
             WHERE authority.organization_id = NEW.organization_id
               AND authority.edition_id = NEW.edition_id
               AND authority.department_id = NEW.id
               AND authority.revoked_at IS NULL
               AND (
                    authority.expires_at IS NULL
                    OR authority.expires_at > pg_catalog.transaction_timestamp()
               )
        ) THEN
            RAISE EXCEPTION 'current authority blocks Department retirement'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE
SET search_path = pg_catalog, public, pg_temp;

-- These statement triggers acquire the common sentinel before PostgreSQL
-- locks any authority or Department row. Existing provenance statement
-- triggers sort first and therefore retain the outermost cutover boundary.
CREATE TRIGGER authorization_retired_binding_writer_lock
BEFORE INSERT ON public.authorization_scopedresourcebinding
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_lock_retired_department_authority_writer();

CREATE TRIGGER authorization_retired_capability_writer_lock
BEFORE INSERT OR UPDATE ON public.authorization_capabilitygrant
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_lock_retired_department_authority_writer();

CREATE TRIGGER authorization_retired_role_writer_lock
BEFORE INSERT OR UPDATE ON public.authorization_roleassignment
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_lock_retired_department_authority_writer();

CREATE TRIGGER authorization_retired_department_writer_lock
BEFORE UPDATE OF retired_at ON public.workforce_department
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_lock_retired_department_authority_writer();

CREATE TRIGGER authorization_retired_binding_guard
BEFORE INSERT ON public.authorization_scopedresourcebinding
FOR EACH ROW EXECUTE FUNCTION public.maru_reject_retired_authority_target();

CREATE TRIGGER authorization_retired_capability_guard
BEFORE INSERT OR UPDATE ON public.authorization_capabilitygrant
FOR EACH ROW EXECUTE FUNCTION public.maru_reject_retired_authority_target();

CREATE TRIGGER authorization_retired_role_guard
BEFORE INSERT OR UPDATE ON public.authorization_roleassignment
FOR EACH ROW EXECUTE FUNCTION public.maru_reject_retired_authority_target();

CREATE TRIGGER authorization_retired_department_authority_guard
BEFORE UPDATE OF retired_at ON public.workforce_department
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_department_retirement_authority();

REVOKE ALL ON FUNCTION
    public.maru_lock_retired_department_authority_writer(),
    public.maru_reject_retired_authority_target(),
    public.maru_guard_department_retirement_authority()
FROM PUBLIC;
"""


REMOVE_GUARDS_SQL = r"""
DROP TRIGGER IF EXISTS authorization_retired_department_authority_guard
    ON public.workforce_department;
DROP TRIGGER IF EXISTS authorization_retired_role_guard
    ON public.authorization_roleassignment;
DROP TRIGGER IF EXISTS authorization_retired_capability_guard
    ON public.authorization_capabilitygrant;
DROP TRIGGER IF EXISTS authorization_retired_binding_guard
    ON public.authorization_scopedresourcebinding;
DROP TRIGGER IF EXISTS authorization_retired_department_writer_lock
    ON public.workforce_department;
DROP TRIGGER IF EXISTS authorization_retired_role_writer_lock
    ON public.authorization_roleassignment;
DROP TRIGGER IF EXISTS authorization_retired_capability_writer_lock
    ON public.authorization_capabilitygrant;
DROP TRIGGER IF EXISTS authorization_retired_binding_writer_lock
    ON public.authorization_scopedresourcebinding;
DROP FUNCTION IF EXISTS public.maru_guard_department_retirement_authority();
DROP FUNCTION IF EXISTS public.maru_reject_retired_authority_target();
DROP FUNCTION IF EXISTS public.maru_lock_retired_department_authority_writer();
"""


def refuse_retired_department_guard_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Do not reopen retired Departments as writable authority targets."""

    del apps
    schema_editor.execute(
        """
        LOCK TABLE
            public.authorization_capabilitygrant,
            public.authorization_roleassignment,
            public.authorization_scopedresourcebinding,
            public.workforce_department
        IN ACCESS EXCLUSIVE MODE
        """
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM public.workforce_department
                 WHERE retired_at IS NOT NULL
            )
            """
        )
        row = cursor.fetchone()
    if row is None or bool(row[0]):
        raise RuntimeError(
            "Cannot remove retired-Department authority guards while a retired "
            "Department exists. Keep compatible code and fix forward, or restore "
            "the complete workforce and authorization state."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0009_runtime_executable_function_contract"),
        ("workforce", "0006_edition_structure_schema"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(INSTALL_GUARDS_SQL, reverse_sql=REMOVE_GUARDS_SQL),
        # CREATE TRIGGER holds write-blocking table locks until this atomic
        # migration commits. The preflight therefore cannot race an authority
        # insert or Department retirement across the scan-to-guard boundary;
        # a blocker rolls the trigger installation back with the migration.
        migrations.RunSQL(PREFLIGHT_SQL, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_retired_department_guard_downgrade,
        ),
    ]
