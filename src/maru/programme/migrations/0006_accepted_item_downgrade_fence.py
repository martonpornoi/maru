"""Require both owners' conversion guards and refuse populated contraction."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations


def refuse_populated_accepted_item_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep accepted-item provenance and creation rules after first use."""
    item = apps.get_model("programme", "ProgrammeItem")
    schema_editor.execute(
        "LOCK TABLE public.applications_programmeacceptedtransition, "
        "public.programme_programmeitem, public.programme_programmeitemsourcebinding "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if item.objects.filter(provenance_kind="applications_accepted").exists():
        raise RuntimeError(
            "Cannot remove accepted Programme item integrity after durable provenance "
            "exists; retain compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Close the cross-owner graph before accepted-item readiness can pass."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0005_accepted_item_integrity"),
        ("applications", "0018_programme_conversion_downgrade_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_populated_accepted_item_downgrade,
        ),
    ]
