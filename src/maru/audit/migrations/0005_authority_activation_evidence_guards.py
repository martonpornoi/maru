"""Protect the audit evidence that makes authority cutover durable."""

from typing import ClassVar

from django.db import migrations

HARDEN_EXISTING_AUDIT_FUNCTION_FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_guard_audit_event()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit events are append-only'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.integrity_batch_id IS NOT NULL THEN
            RAISE EXCEPTION 'new audit events cannot join a sealed batch'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.integrity_batch_id IS NULL
       AND NEW.integrity_batch_id IS NOT NULL
       AND (
           to_jsonb(NEW) - 'integrity_batch_id'
           = to_jsonb(OLD) - 'integrity_batch_id'
       )
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'audit events are append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
"""


HARDEN_EXISTING_AUDIT_FUNCTION_REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_guard_audit_event()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit events are append-only'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.integrity_batch_id IS NOT NULL THEN
            RAISE EXCEPTION 'new audit events cannot join a sealed batch'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.integrity_batch_id IS NULL
       AND NEW.integrity_batch_id IS NOT NULL
       AND (
           to_jsonb(NEW) - 'integrity_batch_id'
           = to_jsonb(OLD) - 'integrity_batch_id'
       )
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'audit events are append-only'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

ALTER FUNCTION public.maru_guard_audit_event() RESET ALL;
"""

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_audit_test_reset_allowed()
RETURNS boolean AS $$
    SELECT current_database() LIKE 'test\_%' ESCAPE '\'
       AND current_setting(
               'maru.authority_provenance_test_reset',
               TRUE
           ) = 'on';
$$ LANGUAGE sql STABLE
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_prevent_audit_event_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_audit_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'audit events cannot be truncated'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE UNIQUE INDEX authorization_provenance_activation_audit_unique
ON public.audit_auditevent (operation, correlation_id)
WHERE operation = 'authorization.authority_provenance.activate';

CREATE TRIGGER authorization_activation_audit_provenance_no_truncate
BEFORE TRUNCATE ON public.audit_auditevent
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_audit_event_truncate();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS authorization_activation_audit_provenance_no_truncate
    ON public.audit_auditevent;
DROP INDEX IF EXISTS public.authorization_provenance_activation_audit_unique;
DROP FUNCTION IF EXISTS public.maru_prevent_audit_event_truncate();
DROP FUNCTION IF EXISTS public.maru_audit_test_reset_allowed();
"""


def refuse_activated_audit_guard_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Keep the audit proof and its fence after the one-way cutover."""

    del apps
    # Hold the evidence table stable through the reverse DDL.  Evidence that
    # committed first is observed and refuses reversal; a concurrent insert
    # cannot slip between this check and removal of the guard/index.
    schema_editor.execute("LOCK TABLE public.audit_auditevent IN ACCESS EXCLUSIVE MODE")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM public.audit_auditevent
                 WHERE operation = 'authorization.authority_provenance.activate'
            )
            """
        )
        activation_evidence_exists = bool(cursor.fetchone()[0])
    if activation_evidence_exists:
        raise RuntimeError(
            "Cannot remove authority activation audit guards after provenance "
            "activation. Keep compatible code and fix forward, or restore the "
            "whole database to one consistent pre-activation point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0004_alter_auditevent_safe_metadata"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            HARDEN_EXISTING_AUDIT_FUNCTION_FORWARD_SQL,
            reverse_sql=HARDEN_EXISTING_AUDIT_FUNCTION_REVERSE_SQL,
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_activated_audit_guard_downgrade,
        ),
    ]
