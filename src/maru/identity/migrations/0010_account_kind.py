from django.db import migrations, models


def classify_existing_superusers(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del schema_editor
    account = apps.get_model("identity", "Account")
    account.objects.filter(is_superuser=True).update(
        account_kind="platform_administrator"
    )


def restore_person_classification(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    del schema_editor
    account = apps.get_model("identity", "Account")
    account.objects.filter(account_kind="platform_administrator").update(
        account_kind="person"
    )


class Migration(migrations.Migration):
    dependencies = [("identity", "0009_account_login_handle")]

    operations = [
        migrations.AddField(
            model_name="account",
            name="account_kind",
            field=models.CharField(
                choices=[
                    ("person", "Person"),
                    ("platform_administrator", "Platform administrator"),
                ],
                default="person",
                max_length=32,
            ),
        ),
        migrations.RunPython(
            classify_existing_superusers,
            restore_person_classification,
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(account_kind="platform_administrator")
                    | (models.Q(is_staff=True) & models.Q(is_superuser=True))
                ),
                name="account_platform_admin_has_privileges",
            ),
        ),
        migrations.AddConstraint(
            model_name="account",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(is_superuser=False)
                    | models.Q(account_kind="platform_administrator")
                ),
                name="account_superuser_is_platform_admin",
            ),
        ),
    ]
