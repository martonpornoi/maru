"""Retain the composed Programme exit generation after native attribution use."""

from typing import Any, ClassVar

from django.db import migrations


def refuse_used_exit_generation_downgrade(apps: Any, schema_editor: Any) -> None:
    """Fence the joined successors before any retained native guard can reverse."""
    schema_editor.execute(
        "LOCK TABLE public.audit_auditnativemutationwitness, "
        "public.scheduling_schedulingreleasedependencykey IN ACCESS EXCLUSIVE MODE"
    )
    witness = apps.get_model("audit", "AuditNativeMutationWitness")
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    if witness.objects.exists() or key.objects.exists():
        raise RuntimeError(
            "Native release evidence exists; retain its execution boundary "
            "and Programme exit guards, and fix forward."
        )


class Migration(migrations.Migration):
    """Extend the existing used-release fence across the newly joined owner guards."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0016_programme_stop_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_exit_generation_downgrade
        ),
    ]
