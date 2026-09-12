"""Reject used release contraction before removing any participating native guard."""

from typing import Any, ClassVar

from django.db import migrations


def refuse_used_release_boundary_downgrade(apps: Any, schema_editor: Any) -> None:
    """Fence the complete dependency chain before partial per-migration reversal.

    Existing reviewed copy is conservatively retained because the operational
    review predecessor also fences that history. Ordinary recovery runs in a
    separate committed maintenance transaction, never beside live commands.
    """
    identities = (
        ("audit", "AuditNativeMutationWitness"),
        ("programme", "ProgrammePublicRendition"),
        ("programme", "ProgrammePublicRenditionWithdrawal"),
        ("scheduling", "SchedulingReleaseDependencyKey"),
        ("scheduling", "SchedulingReleaseWarningAcknowledgement"),
        ("scheduling", "SchedulingReleaseApproval"),
        ("scheduling", "SchedulingRelease"),
        ("scheduling", "SchedulingReleasePointer"),
    )
    models = tuple(apps.get_model(app, model) for app, model in identities)
    for model in models:
        schema_editor.execute(
            "LOCK TABLE "
            + schema_editor.quote_name(model._meta.db_table)  # noqa: SLF001
            + " IN ACCESS EXCLUSIVE MODE"
        )
    if any(model.objects.exists() for model in models):
        raise RuntimeError(
            "Native release or reviewed-copy evidence exists; retain its execution "
            "boundary and fix forward before removing any participating guard."
        )


class Migration(migrations.Migration):
    """Seal the whole additive boundary without installing a runtime writer."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0019_reciprocal_published_person_guard"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_release_boundary_downgrade
        ),
    ]
