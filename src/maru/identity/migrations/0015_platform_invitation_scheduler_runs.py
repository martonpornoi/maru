"""Persist value-minimized Page 10 delivery and expiry heartbeats."""

from __future__ import annotations

import uuid

import django.utils.timezone
from django.db import migrations, models

INSTALL_APPEND_ONLY_GUARDS = r"""
CREATE TRIGGER identity_page10_scheduler_run_immutable
BEFORE UPDATE OR DELETE ON identity_platforminvitationschedulerrun
FOR EACH ROW EXECUTE FUNCTION identity_page10_append_only_guard();
CREATE TRIGGER identity_page10_scheduler_run_no_truncate
BEFORE TRUNCATE ON identity_platforminvitationschedulerrun
FOR EACH STATEMENT EXECUTE FUNCTION identity_page10_append_only_guard();
"""

REMOVE_APPEND_ONLY_GUARDS = r"""
DROP TRIGGER IF EXISTS identity_page10_scheduler_run_no_truncate
    ON identity_platforminvitationschedulerrun;
DROP TRIGGER IF EXISTS identity_page10_scheduler_run_immutable
    ON identity_platforminvitationschedulerrun;
"""


def refuse_live_scheduler_evidence_rollback(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Do not silently discard persisted liveness evidence during rollback."""

    del apps
    schema_editor.execute(
        "LOCK TABLE identity_platforminvitationschedulerrun "
        "IN ACCESS EXCLUSIVE MODE"
    )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM identity_platforminvitationschedulerrun)"
        )
        populated = cursor.fetchone()
    if populated is None or bool(populated[0]):
        raise RuntimeError(
            "Cannot remove Page 10 scheduler heartbeat storage after run evidence "
            "exists. Keep compatible code and fix forward, or restore the complete "
            "database to a consistent pre-heartbeat point."
        )


class Migration(migrations.Migration):
    dependencies = [("identity", "0014_invitation_delivery_integrity")]  # noqa: RUF012

    operations = [  # noqa: RUF012
        migrations.CreateModel(
            name="PlatformInvitationSchedulerRun",
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
                    "kind",
                    models.CharField(
                        choices=[
                            ("delivery", "Invitation delivery"),
                            ("expiry", "Invitation expiry"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "generation",
                    models.CharField(
                        choices=[
                            ("delivery-v1", "Delivery worker v1"),
                            ("expiry-v1", "Expiry scheduler v1"),
                        ],
                        max_length=24,
                    ),
                ),
                ("ran_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("processed_count", models.PositiveIntegerField(default=0)),
                ("remaining_count", models.PositiveBigIntegerField(default=0)),
                (
                    "private_key_coverage_complete",
                    models.BooleanField(default=False),
                ),
            ],
            options={"ordering": ("-ran_at", "-id")},
        ),
        migrations.AddIndex(
            model_name="platforminvitationschedulerrun",
            index=models.Index(
                fields=["kind", "-ran_at", "-id"],
                name="id_inv_scheduler_run_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationschedulerrun",
            constraint=models.CheckConstraint(
                condition=models.Q(processed_count__lte=1_000),
                name="identity_inv_scheduler_processed_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="platforminvitationschedulerrun",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        kind="delivery",
                        generation="delivery-v1",
                        private_key_coverage_complete=True,
                    )
                    | models.Q(
                        kind="expiry",
                        generation="expiry-v1",
                        private_key_coverage_complete=False,
                    )
                ),
                name="identity_inv_scheduler_kind_evidence",
            ),
        ),
        migrations.RunSQL(
            sql=INSTALL_APPEND_ONLY_GUARDS,
            reverse_sql=REMOVE_APPEND_ONLY_GUARDS,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_live_scheduler_evidence_rollback,
        ),
    ]
