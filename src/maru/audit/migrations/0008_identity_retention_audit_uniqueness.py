"""Keep each Page 10 invitation retention action bound to one audit row."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("audit", "0007_identity_reconciliation_audit_uniqueness"),
    ]

    operations = [  # noqa: RUF012
        migrations.AddConstraint(
            model_name="auditevent",
            constraint=models.UniqueConstraint(
                fields=("operation", "target_id"),
                condition=(
                    models.Q(
                        operation__in=(
                            "identity.account_invitation.retention_apply",
                            "identity.account_invitation.retention_hold.place",
                            "identity.account_invitation.retention_hold.release",
                        )
                    )
                    & models.Q(target_id__isnull=False)
                ),
                name="audit_identity_retention_action_unique",
            ),
        ),
    ]
