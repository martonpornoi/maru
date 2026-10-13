"""Keep task placements optional in model validation; native rules are unchanged."""

from importlib import import_module
from typing import Any

from django.db import migrations, models


def refuse_used_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain the frozen joined generation before reversing this successor."""
    import_module(
        "maru.knowledge.migrations.0003_downgrade_fence"
    ).refuse_used_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0003_downgrade_fence")]

    operations = [
        migrations.AlterField(
            model_name="guidancerevision",
            name="placements",
            field=models.JSONField(blank=True, default=list),
        ),
        # Reverse operations run last-to-first, before model state or recorder changes.
        migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade),
    ]
