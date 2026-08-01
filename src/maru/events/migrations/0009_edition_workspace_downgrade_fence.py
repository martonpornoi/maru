from django.db import migrations


def refuse_nonempty_edition_workspace_downgrade(apps, schema_editor):
    del schema_editor
    event_edition = apps.get_model("events", "EventEdition")
    creation_receipt = apps.get_model("events", "EditionCreationReceipt")
    if event_edition.objects.exists() or creation_receipt.objects.exists():
        raise RuntimeError(
            "Cannot reverse the edition-workspace migrations while event "
            "editions or creation receipts exist. Keep compatible code and "
            "fix forward, or use an explicitly approved backup/PITR recovery "
            "plan."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0008_creation_receipt_digest_guard"),
        ("organizations", "0007_convention_series_downgrade_fence"),
    ]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_nonempty_edition_workspace_downgrade,
        ),
    ]
