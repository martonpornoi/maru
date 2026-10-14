"""Fence the complete retained joined graph before any Guidance successor reverses."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations


def refuse_used_guidance_downgrade(apps: Any, schema_editor: Any) -> None:
    """Lock all new retained relations, then invoke the frozen Announcements preflight."""
    retained = (
        ("events", "GuidanceAdoptionSetupReceipt"),
        ("events", "GuidanceActivationRequest"),
        ("events", "GuidanceActivationDecision"),
        ("events", "GuidanceActivationReceipt"),
        ("authorization", "GuidanceTeam"),
        ("authorization", "GuidanceAuthoritySetupReceipt"),
        ("authorization", "GuidanceRecipeQualification"),
        ("authorization", "GuidanceAccessRequest"),
        ("authorization", "GuidanceAccessDecision"),
        ("authorization", "GuidanceRevocationReceipt"),
    )
    schema_editor.execute(
        "LOCK TABLE public.events_eventedition, "
        + ", ".join(
            "public." + apps.get_model(app, model)._meta.db_table
            for app, model in retained
        )
        + " IN ACCESS EXCLUSIVE MODE"
    )
    if (
        any(apps.get_model(app, model).objects.exists() for app, model in retained)
        or apps.get_model("events", "EventEdition")
        .objects.filter(
            adoption_profile_code__in=("guidance_only", "announcements_guidance")
        )
        .exists()
    ):
        raise RuntimeError(
            "Guidance adoption or responsibility evidence exists; retain the complete graph and fix forward."
        )
    for name in (
        "maru.organizations.migrations.0016_workspace_representation",
        "maru.authorization.migrations.0044_workspace_operator_lineage",
        "maru.authorization.migrations.0043_guidance_capabilities",
    ):
        import_module(name).refuse_used_downgrade(apps, schema_editor)
    predecessor = import_module("maru.announcements.migrations.0003_downgrade_fence")
    predecessor.refuse_used_downgrade(apps, schema_editor)


def install_adoption_guard(apps: Any, schema_editor: Any) -> None:
    import_module("maru.events.migrations.0023_guidance_adoption_integrity").install(
        apps, schema_editor
    )


def restore_adoption_guard(apps: Any, schema_editor: Any) -> None:
    import_module("maru.events.migrations.0023_guidance_adoption_integrity").restore(
        apps, schema_editor
    )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0023_guidance_adoption_integrity")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(install_adoption_guard, restore_adoption_guard),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_guidance_downgrade),
    ]
