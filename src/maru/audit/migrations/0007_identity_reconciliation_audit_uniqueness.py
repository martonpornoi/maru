"""Keep Page 10 reconciliation audit evidence one-to-one with retry keys."""

from __future__ import annotations

from django.db import migrations, models


def validate_reconciliation_audit_uniqueness(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Fence writers and reject duplicate evidence before adding uniqueness."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            LOCK TABLE
                audit_auditevent,
                identity_platformidentitydeliveryreconciliationreceipt
            IN SHARE ROW EXCLUSIVE MODE
            """
        )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM audit_auditevent
                 WHERE capability_code =
                        'identity.reconcile_account_invitation_delivery'
                   AND operation =
                        'identity.account_invitation.delivery_reconcile'
                   AND idempotency_key_hash <> ''
                 GROUP BY principal_id, idempotency_key_hash
                HAVING count(*) > 1
            )
            """
        )
        if bool(cursor.fetchone()[0]):
            raise RuntimeError(
                "Audit 0007 forward migration refused: duplicate Page 10 "
                "reconciliation audit retry evidence exists. Repair or "
                "quarantine it under a controlled migration-owner recovery "
                "plan, then retry."
            )


def refuse_live_reconciliation_audit_rollback(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Do not remove uniqueness after reconciliation receipts are durable."""

    del apps
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            LOCK TABLE
                audit_auditevent,
                identity_platformidentitydeliveryreconciliationreceipt
            IN SHARE ROW EXCLUSIVE MODE
            """
        )
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                  FROM identity_platformidentitydeliveryreconciliationreceipt
            )
            """
        )
        if bool(cursor.fetchone()[0]):
            raise RuntimeError(
                "Audit 0007 rollback refused: live Page 10 reconciliation "
                "receipts depend on unique audit retry evidence. Use a "
                "controlled migration-owner recovery plan instead."
            )


class Migration(migrations.Migration):
    dependencies = [  # noqa: RUF012
        ("audit", "0006_reserved_authority_activation_audit_guard"),
        ("identity", "0013_invitation_token_digest_keys"),
    ]

    operations = [  # noqa: RUF012
        migrations.RunPython(
            validate_reconciliation_audit_uniqueness,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="auditevent",
            constraint=models.UniqueConstraint(
                fields=("principal_id", "idempotency_key_hash"),
                condition=(
                    models.Q(
                        capability_code=(
                            "identity.reconcile_account_invitation_delivery"
                        ),
                        operation=(
                            "identity.account_invitation.delivery_reconcile"
                        ),
                    )
                    & ~models.Q(idempotency_key_hash="")
                ),
                name="audit_identity_reconcile_retry_unique",
            ),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_live_reconciliation_audit_rollback,
        ),
    ]
