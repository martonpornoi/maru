"""Retain used Announcements setup and adoption evidence during downgrade."""

from importlib import import_module
from typing import Any, ClassVar
from django.db import migrations


def refuse_used_setup_receipt_downgrade(apps: Any, schema_editor: Any) -> None:
    """Serialize the unused downgrade check and retain any completed setup."""
    schema_editor.execute(
        "LOCK TABLE public.events_announcementsadoptionsetupreceipt "
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


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0020_announcements_setup_integrity")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_setup_receipt_downgrade
        )
    ]
