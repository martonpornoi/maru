"""Fence reversal after any Programme-import state or evidence is retained."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations

PROGRAMME_IMPORT_MODEL_NAMES: tuple[str, ...] = (
    "ProgrammeImportBatch",
    "ProgrammeImportItem",
    "ProgrammeImportPreviewRevision",
    "ProgrammeImportPreviewItemResult",
    "ProgrammeImportSourceBinding",
    "ProgrammeImportAppliedCommand",
    "ProgrammeImportCommandReceipt",
)


def refuse_used_programme_import_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Keep the complete guard set once any import row exists."""
    models = tuple(
        apps.get_model("applications", model_name)
        for model_name in PROGRAMME_IMPORT_MODEL_NAMES
    )
    schema_editor.execute(
        "LOCK TABLE "
        + ", ".join(
            f"public.{model._meta.db_table}"  # noqa: SLF001
            for model in models
        )
        + " IN ACCESS EXCLUSIVE MODE"
    )
    if any(model.objects.exists() for model in models):
        raise RuntimeError(
            "Cannot remove Programme-import database integrity after durable "
            "batch, item, preview, binding, nested-command, or receipt evidence "
            "exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Fence reversal of the complete Programme-import integrity contract."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0008_programme_import_integrity_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_programme_import_downgrade,
        ),
    ]
