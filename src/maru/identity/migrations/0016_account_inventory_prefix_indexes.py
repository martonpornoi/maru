"""Install the measured expression indexes used by account prefix search."""

from __future__ import annotations

import django.contrib.postgres.indexes
from django.db import migrations, models
from django.db.models.functions import Upper


class Migration(migrations.Migration):
    atomic = False

    dependencies = [  # noqa: RUF012
        ("identity", "0015_platform_invitation_scheduler_runs"),
    ]

    operations = [  # noqa: RUF012
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY id_account_email_prefix_idx "
                        "ON identity_account ((UPPER(email)) varchar_pattern_ops)"
                    ),
                    reverse_sql=(
                        "DROP INDEX CONCURRENTLY IF EXISTS "
                        "id_account_email_prefix_idx"
                    ),
                )
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="account",
                    index=models.Index(
                        django.contrib.postgres.indexes.OpClass(
                            Upper("email"),
                            name="varchar_pattern_ops",
                        ),
                        name="id_account_email_prefix_idx",
                    ),
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY id_account_handle_prefix_idx "
                        "ON identity_account "
                        "((UPPER(login_handle)) varchar_pattern_ops)"
                    ),
                    reverse_sql=(
                        "DROP INDEX CONCURRENTLY IF EXISTS "
                        "id_account_handle_prefix_idx"
                    ),
                )
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="account",
                    index=models.Index(
                        django.contrib.postgres.indexes.OpClass(
                            Upper("login_handle"),
                            name="varchar_pattern_ops",
                        ),
                        name="id_account_handle_prefix_idx",
                    ),
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY id_account_name_prefix_idx "
                        "ON identity_account "
                        "((UPPER(display_name)) varchar_pattern_ops)"
                    ),
                    reverse_sql=(
                        "DROP INDEX CONCURRENTLY IF EXISTS "
                        "id_account_name_prefix_idx"
                    ),
                )
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="account",
                    index=models.Index(
                        django.contrib.postgres.indexes.OpClass(
                            Upper("display_name"),
                            name="varchar_pattern_ops",
                        ),
                        name="id_account_name_prefix_idx",
                    ),
                ),
            ],
        ),
    ]
