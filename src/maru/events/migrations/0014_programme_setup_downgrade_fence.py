"""Require unused setup evidence before removing its native integrity boundary."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations


def refuse_used_setup_guard_downgrade(apps: Any, schema_editor: Any) -> None:
    """Run the same serialized evidence fence before removing any native guard."""
    schema = import_module("maru.events.migrations.0012_programme_setup_receipt")
    schema.refuse_used_setup_receipt_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    """Fence the complete setup boundary while leaving current profiles untouched."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0013_programme_setup_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            refuse_used_setup_guard_downgrade,
        ),
    ]
