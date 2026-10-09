"""Retain used Announcements setup and adoption evidence during downgrade."""

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


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("events", "0020_announcements_setup_integrity")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_setup_receipt_downgrade
        )
    ]
