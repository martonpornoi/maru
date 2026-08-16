import uuid

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("identity", "0018_invitation_retention_v8")]  # noqa: RUF012

    operations = [  # noqa: RUF012
        migrations.CreateModel(
            name="NavigationPin",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "destination_code",
                    models.CharField(
                        max_length=160,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_navigation_destination_code",
                                message=(
                                    "Use a stable lowercase navigation destination "
                                    "code."
                                ),
                                regex=r"^[a-z0-9][a-z0-9._-]{0,159}$",
                            )
                        ],
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="navigation_pins",
                        to="identity.account",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddConstraint(
            model_name="navigationpin",
            constraint=models.UniqueConstraint(
                fields=("account", "destination_code"),
                name="identity_navigation_pin_account_destination_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="navigationpin",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    destination_code__regex=r"^[a-z0-9][a-z0-9._-]{0,159}$"
                ),
                name="identity_navigation_pin_destination_code_valid",
            ),
        ),
    ]
