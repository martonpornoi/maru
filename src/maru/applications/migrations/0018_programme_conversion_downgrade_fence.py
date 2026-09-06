"""Refuse conversion contraction before either owner's guards are removed."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations


def refuse_populated_programme_conversion_downgrade(apps: Any, schema_editor: Any) -> None:
    """Preserve reciprocal accepted sources and items after the first conversion."""
    source = apps.get_model("applications", "ProgrammeAcceptedTransition")
    schema_editor.execute(
        "LOCK TABLE public.applications_programmeacceptedtransition, "
        "public.programme_programmeitem, public.programme_programmeitemsourcebinding "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if source.objects.exists():
        raise RuntimeError(
            "Cannot remove Programme conversion guards after durable accepted sources "
            "exist; retain compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Allow unused reverse without discarding completed conversion evidence."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0017_programme_conversion_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_populated_programme_conversion_downgrade,
        ),
    ]
