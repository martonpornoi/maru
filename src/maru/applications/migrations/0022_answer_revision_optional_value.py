"""Align answer validation with the existing nullable append-only value contract."""

from typing import ClassVar

from django.db import migrations, models


class Migration(migrations.Migration):
    """Change model validation only; retain all answer rows and database guards."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0021_programme_file_downgrade_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.AlterField(
            model_name="applicationanswerrevision",
            name="value",
            field=models.JSONField(blank=True, null=True),
        ),
    ]
