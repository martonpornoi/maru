"""Fence removal of durable exact-revision Programme review evidence."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations


def refuse_populated_programme_review_downgrade(apps: Any, schema_editor: Any) -> None:
    """Lock the exact seven relations and refuse evidence loss before reversal."""
    models = (
        "ProgrammeReviewPolicy",
        "ProgrammeReviewCase",
        "ProgrammeReviewAssignment",
        "ProgrammeReviewEntry",
        "ProgrammeReviewDecision",
        "ProgrammeDecisionAcknowledgement",
        "ProgrammeReviewReceipt",
    )
    retained = tuple(apps.get_model("applications", name) for name in models)
    tables = ", ".join(
        "public." + schema_editor.quote_name(model._meta.db_table) for model in retained
    )
    schema_editor.execute("LOCK TABLE " + tables + " IN ACCESS EXCLUSIVE MODE")
    if any(
        model.objects.using(schema_editor.connection.alias).exists()
        for model in retained
    ):
        raise RuntimeError(
            "Cannot remove Programme review after durable evidence exists; "
            "keep compatible code and fix forward or restore one consistent database point."
        )


class Migration(migrations.Migration):
    """Refuse populated reversal before any review trigger or table is removed."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0014_programme_review_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_populated_programme_review_downgrade,
        ),
    ]
