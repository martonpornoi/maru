"""Fence populated host downgrade before removing any state or evidence guard."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations


def refuse_used_host_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain compatible code and fix forward after any durable hosting history."""
    schema_editor.execute(
        "LOCK TABLE public.programme_programmehostrelationship, "
        "public.programme_programmehostinvitation, public.programme_programmehostrevision, "
        "public.programme_programmehostavailabilitywindow IN ACCESS EXCLUSIVE MODE"
    )
    if any(apps.get_model("programme", model).objects.exists() for model in (
        "ProgrammeHostRelationship", "ProgrammeHostInvitation", "ProgrammeHostRevision", "ProgrammeHostAvailabilityWindow",
    )):
        raise RuntimeError(
            "Cannot remove Programme host integrity after retained relationship or "
            "history exists; retain compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Require an empty exact host graph before reversal."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [("programme", "0008_host_integrity")]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(migrations.RunPython.noop, reverse_code=refuse_used_host_downgrade),
    ]
