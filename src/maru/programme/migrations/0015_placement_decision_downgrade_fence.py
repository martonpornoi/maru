"""Retain accountable placement decisions and their database integrity."""

from typing import Any, ClassVar

from django.db import migrations


def refuse_used_placement_decision_downgrade(apps: Any, schema_editor: Any) -> None:
    """Fence unused-only reversal before removing any retained decision guard."""
    schema_editor.execute(
        "LOCK TABLE public.programme_programmeplacementdecision IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("programme", "ProgrammePlacementDecision").objects.exists():
        raise RuntimeError(
            "Cannot remove retained Programme placement decisions; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Require an unused graph before reversing guarded source decisions."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0014_placement_decision_integrity")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_placement_decision_downgrade,
        ),
    ]
