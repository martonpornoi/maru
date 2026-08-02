"""Let the least-privileged runtime serialize writers without latch UPDATE."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_lock_authority_provenance_latch()
RETURNS smallint AS $$
DECLARE
    latch_generation smallint;
BEGIN
    SELECT generation
      INTO STRICT latch_generation
      FROM public.authorization_provenanceactivationlatch
     WHERE singleton IS TRUE
     FOR SHARE;
    RETURN latch_generation;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'authority provenance activation latch is unavailable'
            USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_lock_authority_provenance_latch()
FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.maru_lock_authority_provenance_writer()
RETURNS trigger AS $$
DECLARE
    latch_generation smallint;
    cutover_time timestamptz;
BEGIN
    PERFORM pg_advisory_xact_lock_shared(4400440007);

    latch_generation := public.maru_lock_authority_provenance_latch();

    IF latch_generation = 1 THEN
        SELECT activated_at
          INTO cutover_time
          FROM public.authorization_authorityprovenanceactivation
         WHERE singleton IS TRUE;
        IF cutover_time IS NULL THEN
            RAISE EXCEPTION 'authority provenance cutover state is inconsistent'
                USING ERRCODE = '23514';
        END IF;
        IF transaction_timestamp() < cutover_time THEN
            RAISE EXCEPTION
                'authority writer transaction predates provenance activation'
                USING ERRCODE = '40001';
        END IF;
    ELSIF latch_generation != 0 THEN
        RAISE EXCEPTION 'authority provenance latch generation is unknown'
            USING ERRCODE = '23514';
    END IF;

    IF TG_LEVEL = 'ROW' AND TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSIF TG_LEVEL = 'ROW' THEN
        RETURN NEW;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp;
"""


REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_lock_authority_provenance_writer()
RETURNS trigger AS $$
DECLARE
    latch_generation smallint;
    cutover_time timestamptz;
BEGIN
    PERFORM pg_advisory_xact_lock_shared(4400440007);

    SELECT generation
      INTO STRICT latch_generation
      FROM public.authorization_provenanceactivationlatch
     WHERE singleton IS TRUE
     FOR SHARE;

    IF latch_generation = 1 THEN
        SELECT activated_at
          INTO cutover_time
          FROM public.authorization_authorityprovenanceactivation
         WHERE singleton IS TRUE;
        IF cutover_time IS NULL THEN
            RAISE EXCEPTION 'authority provenance cutover state is inconsistent'
                USING ERRCODE = '23514';
        END IF;
        IF transaction_timestamp() < cutover_time THEN
            RAISE EXCEPTION
                'authority writer transaction predates provenance activation'
                USING ERRCODE = '40001';
        END IF;
    ELSIF latch_generation != 0 THEN
        RAISE EXCEPTION 'authority provenance latch generation is unknown'
            USING ERRCODE = '23514';
    END IF;

    IF TG_LEVEL = 'ROW' AND TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSIF TG_LEVEL = 'ROW' THEN
        RETURN NEW;
    END IF;
    RETURN NULL;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'authority provenance activation latch is unavailable'
            USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog, public, pg_temp;

DROP FUNCTION IF EXISTS public.maru_lock_authority_provenance_latch();
"""


def refuse_runtime_latch_helper_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Do not restore a runtime-incompatible writer after one-way cutover."""

    del apps
    schema_editor.execute(
        """
        LOCK TABLE
            public.audit_auditevent,
            public.authorization_authorityprovenanceactivation,
            public.authorization_provenanceactivationlatch
        IN ACCESS EXCLUSIVE MODE
        """
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*)
                   FROM public.authorization_authorityprovenanceactivation),
                (SELECT COUNT(*)
                   FROM public.audit_auditevent
                  WHERE operation =
                        'authorization.authority_provenance.activate'),
                (SELECT COUNT(*)
                   FROM public.authorization_provenanceactivationlatch),
                EXISTS (
                    SELECT 1
                      FROM public.authorization_provenanceactivationlatch
                     WHERE singleton IS TRUE AND generation = 0
                )
            """
        )
        row = cursor.fetchone()
    if row is None or not (
        int(row[0]) == 0 and int(row[1]) == 0 and int(row[2]) == 1 and bool(row[3])
    ):
        raise RuntimeError(
            "Cannot remove the runtime authority latch-lock helper after "
            "provenance activation. Keep compatible code and fix forward, or "
            "restore the whole database to one consistent pre-activation point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0007_authority_provenance_activation_guards"),
        ("audit", "0006_reserved_authority_activation_audit_guard"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_runtime_latch_helper_downgrade,
        ),
    ]
