"""Retain used Announcements setup and adoption evidence during downgrade."""

from importlib import import_module
from typing import Any, ClassVar
from django.db import migrations


def refuse_used_setup_receipt_downgrade(apps: Any, schema_editor: Any) -> None:
    """Serialize the unused downgrade check and retain any completed setup."""
    schema_editor.execute(
        "LOCK TABLE public.events_announcementsadoptionsetupreceipt, "
        "public.events_eventedition "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("events", "AnnouncementsAdoptionSetupReceipt").objects.exists()
        or apps.get_model("events", "EventEdition")
        .objects.filter(adoption_profile_code="announcements_only")
        .exists()
    ):
        raise RuntimeError(
            "Announcements editions or setup evidence exist; retain them and fix forward."
        )
    # A reversal of an older joined owner also reverses these successors first.
    # Preserve the frozen predecessor's complete preflight before any new guard
    # or migration-recorder entry can disappear. Never call current services.
    retained = import_module(
        "maru.events.migrations.0018_programme_retained_recovery_fence"
    )
    retained.refuse_retained_programme_downgrade(apps, schema_editor)
    # Workforce 0029 also retains a bare Programme edition, before any assignment
    # exists. Its check is embedded in a mutating reverse operation, so do not
    # call that operation here. Preserve the same data-only refusal before the
    # new Events profile constraint can be removed by a joined reverse plan.
    if (
        apps.get_model("events", "EventEdition")
        .objects.filter(adoption_profile_code="programme_operations")
        .exists()
    ):
        raise RuntimeError(
            "Used Programme assignment adoption requires fix-forward recovery."
        )
    # New Announcements foundations can be retained before an edition is set up.
    # Their own frozen read-only fences must precede successor removal as well.
    for reference in (
        "organizations.0015_announcements_representation",
        "authorization.0042_announcements_operator_lineage",
        "authorization.0041_announcements_capabilities",
    ):
        owner, migration = reference.split(".", 1)
        boundary = import_module(f"maru.{owner}.migrations.{migration}")
        boundary.refuse_used_downgrade(apps, schema_editor)



class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0020_announcements_setup_integrity")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_setup_receipt_downgrade
        )
    ]
