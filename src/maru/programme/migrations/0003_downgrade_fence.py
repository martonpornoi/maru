"""Refuse removal of Programme integrity after durable state exists."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations

PROGRAMME_MODEL_NAMES: tuple[str, ...] = (
    "ProgrammeEditionControl",
    "ProgrammeItem",
    "ProgrammeItemSourceBinding",
    "ProgrammeWorkingRevision",
    "ProgrammeDeliveryRevision",
    "ProgrammeDepartmentDiscussionEntry",
    "ProgrammeReadinessRequirement",
    "ProgrammeReadinessRequirementRevision",
    "ProgrammeReadinessEvidence",
    "ProgrammePublicRendition",
    "ProgrammeCommandReceipt",
)


def refuse_used_programme_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Keep guards and schema once any retained Programme record exists.

    Parameters
    ----------
    apps : Any
        Historical application registry for this migration state.
    schema_editor : Any
        Active schema editor used to acquire a race-free table lock.

    Raises
    ------
    RuntimeError
        If any durable Programme state, provenance, history, rendition, or
        receipt remains.
    """
    models = tuple(
        apps.get_model("programme", model_name) for model_name in PROGRAMME_MODEL_NAMES
    )
    schema_editor.execute(
        "LOCK TABLE "
        + ", ".join(f"public.{model._meta.db_table}" for model in models)  # noqa: SLF001
        + " IN ACCESS EXCLUSIVE MODE"
    )
    if any(model.objects.exists() for model in models):
        raise RuntimeError(
            "Cannot remove Programme database integrity after durable state, "
            "provenance, history, readiness, rendition, or command evidence "
            "exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Fence reversal of the complete dormant Programme schema."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("programme", "0002_integrity_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_programme_downgrade,
        ),
    ]
