"""Converge and fence the runtime-executable function hardening contract."""

from typing import ClassVar

from django.db import migrations


def refuse_activated_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Only a pristine dormant deployment may restore path-sensitive code."""

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
            "Cannot remove the runtime-executable function hardening contract "
            "after authority provenance activation. Keep compatible code and "
            "fix forward, or restore the whole database to one consistent "
            "pre-activation point."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0008_runtime_latch_lock_helper"),
        ("organizations", "0013_runtime_executable_function_hardening"),
        ("workforce", "0005_runtime_executable_function_hardening"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_activated_downgrade,
        ),
    ]
