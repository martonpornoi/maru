"""Retained Announcements evidence requires fix-forward rather than downgrade."""

from django.db import migrations


def refuse_used_downgrade(apps, schema_editor):
    """Fence before removing any native protection or table with retained evidence."""
    schema_editor.execute("LOCK TABLE public.announcements_announcementcontrol, public.announcements_announcementcommandreceipt IN ACCESS EXCLUSIVE MODE")
    if apps.get_model("announcements", "AnnouncementControl").objects.exists() or apps.get_model("announcements", "AnnouncementCommandReceipt").objects.exists():
        raise RuntimeError("Announcement history exists; retain it and fix forward.")


class Migration(migrations.Migration):
    dependencies = [("announcements", "0002_integrity")]
    operations = [migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade)]
