"""Prevent contraction from discarding private supporting bytes or evidence."""

from typing import Any, ClassVar

from django.db import migrations


def refuse_populated_programme_file_downgrade(apps: Any, schema_editor: Any) -> None:
    """Fence populated custody before removing any integrity guard."""
    schema_editor.execute(
        "LOCK TABLE public.applications_programmefileintake, "
        "public.applications_programmefilecontent, "
        "public.applications_applicationfilereceipt, "
        "public.applications_applicationanswerrevision IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("applications", "ProgrammeFileIntake").objects.exists()
        or apps.get_model("applications", "ProgrammeFileContent").objects.exists()
        or apps.get_model("applications", "ApplicationFileReceipt")
        .objects.filter(storage_key__startswith="programme-db/")
        .exists()
    ):
        raise RuntimeError(
            "Cannot remove Programme file custody after durable evidence exists; "
            "retain compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Permit unused reversal, never destruction of retained custody."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0020_programme_file_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_populated_programme_file_downgrade,
        ),
    ]
