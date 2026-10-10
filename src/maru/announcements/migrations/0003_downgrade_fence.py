"""Retain Announcements and its joined foundation before successor reversal."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations


def refuse_used_downgrade(apps: Any, schema_editor: Any) -> None:
    """Fence retained owner and ancestor evidence before removing any successor."""
    schema_editor.execute(
        "LOCK TABLE public.announcements_announcementcontrol, "
        "public.announcements_announcementcommandreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("announcements", "AnnouncementControl").objects.exists()
        or apps.get_model("announcements", "AnnouncementCommandReceipt").objects.exists()
    ):
        raise RuntimeError("Announcement history exists; retain it and fix forward.")
    # This frozen ancestor includes the older joined Programme recovery boundary.
    # Its original locks and refusal messages must run before this leaf reverses.
    setup = import_module(
        "maru.events.migrations.0021_announcements_setup_downgrade_fence"
    )
    setup.refuse_used_setup_receipt_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("announcements", "0002_integrity")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade)
    ]
