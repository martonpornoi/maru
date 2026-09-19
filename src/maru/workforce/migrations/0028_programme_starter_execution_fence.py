"""Preserve the shared execution boundary before any starter successor reverses."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_starter = import_module(
    "maru.workforce.migrations.0027_programme_starter_downgrade_fence"
)
_notice = import_module("maru.scheduling.migrations.0022_change_notice_integrity")


def refuse_used_starter_execution_downgrade(apps: Any, schema_editor: Any) -> None:
    """Run both frozen retained-evidence preflights before removing any successor."""
    _starter.refuse_used_starter_downgrade(apps, schema_editor)
    _notice.refuse_used_notice_boundary_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    """Keep unused reversal, but stop used contraction before recorder changes."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0027_programme_starter_downgrade_fence"),
        ("scheduling", "0022_change_notice_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            refuse_used_starter_execution_downgrade,
        ),
    ]
