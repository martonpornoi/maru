"""Keep task placements optional in model validation; native rules are unchanged."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0003_downgrade_fence")]

    operations = [
        migrations.AlterField(
            model_name="guidancerevision",
            name="placements",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
