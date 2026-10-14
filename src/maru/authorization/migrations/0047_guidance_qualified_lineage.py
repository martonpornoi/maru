"""Source-pinned replacement of the ordinary exact-lineage qualification rule."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_guard = import_module(
    "maru.authorization.migrations.0046_guidance_authority_integrity"
)


def install(apps: Any, schema_editor: Any) -> None:
    _guard.install(apps, schema_editor)


def restore(apps: Any, schema_editor: Any) -> None:
    _guard.restore(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0046_guidance_authority_integrity")
    ]
    operations: ClassVar[list[object]] = [migrations.RunPython(install, restore)]
