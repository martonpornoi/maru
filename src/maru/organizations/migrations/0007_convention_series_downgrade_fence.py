from django.db import migrations


def refuse_nonempty_series_downgrade(apps, schema_editor):
    del schema_editor
    convention_series = apps.get_model("organizations", "ConventionSeries")
    if convention_series.objects.exists():
        raise RuntimeError(
            "Cannot reverse the convention-series profile-version migrations "
            "while convention series exist. Keep compatible code and fix "
            "forward, or use an explicitly approved backup/PITR recovery plan."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0006_convention_series_profile_integrity_guard"),
    ]

    operations = [
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_nonempty_series_downgrade,
        ),
    ]
