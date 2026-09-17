"""Fence native guard removal before any retained approval intent loses protection."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations


def refuse_used_approval_guard_downgrade(apps: Any, schema_editor: Any) -> None:
    """Reuse the serialized unused-only contraction check before removing guards."""
    schema = import_module(
        "maru.authorization.migrations.0032_programme_role_approval_records"
    )
    schema.refuse_used_programme_role_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    """Preserve requests, terminal decisions and their native safety boundary."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0033_programme_role_approval_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_approval_guard_downgrade
        ),
    ]
