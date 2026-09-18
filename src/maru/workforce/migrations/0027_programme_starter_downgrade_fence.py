"""Refuse contraction once any original Programme starter approval intent exists."""

from typing import Any, ClassVar

from django.db import migrations


def refuse_used_starter_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep retained starter evidence intact; only unused schema can contract."""
    schema_editor.execute(
        "LOCK TABLE public.workforce_programmestarterrequest, "
        "public.workforce_programmestarterdecision IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("workforce", "ProgrammeStarterRequest").objects.exists()
        or apps.get_model("workforce", "ProgrammeStarterDecision").objects.exists()
    ):
        raise RuntimeError("Retained Programme starter approval exists; fix forward.")


class Migration(migrations.Migration):
    """Serialize empty-only reversal before removing native guards or records."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0026_programme_starter_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(migrations.RunPython.noop, refuse_used_starter_downgrade),
    ]
