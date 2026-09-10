"""Keep exact work lineage and integrity installed once a binding is retained."""

from typing import Any, ClassVar

from django.db import migrations


def refuse_used_programme_binding_downgrade(apps: Any, schema_editor: Any) -> None:
    """Refuse removal before any guard is dropped if retained binding evidence exists."""
    schema_editor.execute(
        "LOCK TABLE public.workforce_programmeshiftbinding, "
        "public.workforce_programmeshiftbindingrevision IN ACCESS EXCLUSIVE MODE"
    )
    if any(
        apps.get_model("workforce", model).objects.exists()
        for model in (
            "ProgrammeShiftBinding",
            "ProgrammeShiftBindingRevision",
        )
    ):
        raise RuntimeError(
            "Cannot remove retained Programme Shift lineage; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Block populated downgrade before the integrity migration can be reversed."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0020_programme_binding_integrity")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_programme_binding_downgrade,
        ),
    ]
