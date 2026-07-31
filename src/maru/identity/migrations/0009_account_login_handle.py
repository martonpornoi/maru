from django.db import migrations, models
from django.db.models.functions import Lower

import maru.identity.models


class Migration(migrations.Migration):
    dependencies = [
        ("identity", "0008_identitychallenge_delivered_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="login_handle",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Optional human sign-in name. It is unique without regard "
                    "to letter case."
                ),
                max_length=120,
                validators=(maru.identity.models.validate_login_handle,),
            ),
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.UniqueConstraint(
                Lower("login_handle"),
                condition=~models.Q(login_handle=""),
                name="account_login_handle_case_insensitive_unique",
            ),
        ),
    ]
