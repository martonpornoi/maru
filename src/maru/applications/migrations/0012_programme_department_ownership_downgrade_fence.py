"""Refuse removal after Programme ownership-continuity forms are populated."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations
from django.db.models import Q


def refuse_populated_ownership_continuity_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Refuse reversal once new transition or monotonic-version data exists."""
    call_receipt = apps.get_model("applications", "ProgrammeCommandReceipt")
    import_batch = apps.get_model("applications", "ProgrammeImportBatch")
    import_preview = apps.get_model(
        "applications",
        "ProgrammeImportPreviewRevision",
    )
    import_receipt = apps.get_model(
        "applications",
        "ProgrammeImportCommandReceipt",
    )
    schema_editor.execute(
        "LOCK TABLE public.applications_programmecommandreceipt, "
        "public.applications_programmeimportbatch, "
        "public.applications_programmeimportpreviewrevision, "
        "public.applications_programmeimportcommandreceipt "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if (
        call_receipt.objects.filter(
            Q(
                action__in=(
                    "call_reassigned",
                    "recovery_call_reassigned",
                    "recovery_call_retired",
                )
            )
            | Q(source_department__isnull=False)
            | Q(destination_department__isnull=False)
        ).exists()
        or import_receipt.objects.filter(
            Q(action="batch_reassigned")
            | Q(source_department__isnull=False)
            | Q(destination_department__isnull=False)
        ).exists()
        or import_batch.objects.exclude(
            Q(state="staged", aggregate_version=1)
            | Q(state="discarded", aggregate_version=2)
        ).exists()
        or import_preview.objects.exclude(source_batch_version=1).exists()
    ):
        raise RuntimeError(
            "Cannot remove Programme ownership continuity after transition or "
            "monotonic-version evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Install a populated-data reversal fence after authoritative integrity."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0011_programme_department_ownership_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_populated_ownership_continuity_downgrade,
        ),
    ]
