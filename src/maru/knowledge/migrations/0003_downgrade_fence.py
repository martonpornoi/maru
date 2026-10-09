"""Retain Guides and the complete frozen joined owner graph before reversal."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_MODELS = (
    "GuidanceControl", "GuidanceItem", "GuidanceSettingsRevision",
    "GuidanceRevision", "GuidanceReview", "GuidanceCommandReceipt",
)


def refuse_used_downgrade(apps: Any, schema_editor: Any) -> None:
    """Run all retained-generation checks before any successor can be removed."""
    schema_editor.execute(
        "LOCK TABLE public.knowledge_guidancecontrol, public.knowledge_guidanceitem, "
        "public.knowledge_guidancesettingsrevision, public.knowledge_guidancerevision, "
        "public.knowledge_guidancereview, public.knowledge_guidancecommandreceipt "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if any(apps.get_model("knowledge", name).objects.exists() for name in _MODELS):
        raise RuntimeError("Guide history exists; retain it and fix forward.")
    # This frozen generation includes purpose authority, adoption, Announcements
    # and the complete older Programme recovery boundary. Never call live owners.
    joined = import_module("maru.events.migrations.0024_guidance_adoption_downgrade_fence")
    joined.refuse_used_guidance_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("knowledge", "0002_integrity"),
        ("announcements", "0004_guidance_combined_admission"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade)
    ]
