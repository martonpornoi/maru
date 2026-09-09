"""Retain staffing evidence and guards once any requirement has been recorded."""

from typing import Any, ClassVar

from django.db import migrations


def refuse_used_staffing_downgrade(apps: Any, schema_editor: Any) -> None:
    """Block removal of either relation while any retained staffing evidence exists."""
    schema_editor.execute(
        "LOCK TABLE public.programme_programmestaffingrequirement, "
        "public.programme_programmestaffingrevision IN ACCESS EXCLUSIVE MODE"
    )
    if any(apps.get_model("programme", model).objects.exists() for model in (
        "ProgrammeStaffingRequirement", "ProgrammeStaffingRevision",
    )):
        raise RuntimeError("Cannot remove retained Programme staffing integrity; keep compatible code and fix forward.")


class Migration(migrations.Migration):
    """Require an unused exact staffing graph before removing its protection."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [("programme", "0011_staffing_integrity")]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(migrations.RunPython.noop, reverse_code=refuse_used_staffing_downgrade),
    ]
