"""Fence reversal after Applications-owned Programme state is retained."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations

PROGRAMME_MODEL_NAMES: tuple[str, ...] = (
    "ProgrammeCall",
    "ProgrammeCallTrack",
    "ProgrammeCallFormat",
    "ProgrammeCallContributorField",
    "ProgrammeProposal",
    "ProgrammeProposalSelectionRevision",
    "ProgrammeProposalCollaborator",
    "ProgrammeProposalCollaboratorTransition",
    "ProgrammeProposalContributorProfileRevision",
    "ProgrammeProposalRevision",
    "ProgrammeProposalRevisionAnswer",
    "ProgrammeProposalRevisionContributor",
    "ProgrammeProposalRevisionResponse",
    "ProgrammeCommandReceipt",
)


def refuse_used_applications_programme_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Keep the complete guard set once any Programme evidence exists.

    Parameters
    ----------
    apps : Any
        Historical application registry for this migration state.
    schema_editor : Any
        Active schema editor used for race-free table locking.

    Raises
    ------
    RuntimeError
        If any Programme call, proposal, immutable evidence, generic Programme
        parent marker, or prohibited future target record remains.
    """
    models = tuple(
        apps.get_model("applications", model_name)
        for model_name in PROGRAMME_MODEL_NAMES
    )
    definition = apps.get_model("applications", "ApplicationDefinition")
    answer = apps.get_model("applications", "ApplicationAnswerRevision")
    target = apps.get_model("applications", "ApplicationTargetRecord")
    locked_models = (*models, definition, answer, target)
    schema_editor.execute(
        "LOCK TABLE "
        + ", ".join(
            f"public.{model._meta.db_table}"  # noqa: SLF001
            for model in locked_models
        )
        + " IN ACCESS EXCLUSIVE MODE"
    )
    used = any(model.objects.exists() for model in models)
    used = used or definition.objects.filter(
        target_adapter_kind="programme_item"
    ).exists()
    used = used or answer.objects.filter(resulting_version__isnull=False).exists()
    used = used or target.objects.filter(adapter_kind="programme_item").exists()
    if used:
        raise RuntimeError(
            "Cannot remove Applications Programme database integrity after "
            "durable call, proposal, revision, receipt, version, or adapter "
            "evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Fence reversal of the complete Applications Programme contract."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0005_programme_integrity_guards"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_applications_programme_downgrade,
        ),
    ]
