"""Add durable cancellation, late-result, and operator reconciliation evidence."""

from __future__ import annotations

import uuid

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def suppress_invitation_legacy_delivery(apps, schema_editor):  # type: ignore[no-untyped-def]
    del schema_editor
    challenge = apps.get_model("identity", "IdentityChallenge")
    challenge.objects.filter(purpose="account_invitation").update(
        delivery_status="suppressed",
        delivery_attempt_count=0,
        last_delivery_attempt_at=None,
        delivered_at=None,
        delivery_error_code="",
    )


def restore_invitation_legacy_delivery(apps, schema_editor):  # type: ignore[no-untyped-def]
    del schema_editor
    challenge = apps.get_model("identity", "IdentityChallenge")
    challenge.objects.filter(
        purpose="account_invitation",
        delivery_status="suppressed",
    ).update(delivery_status="pending")


INSTALL_APPEND_ONLY_GUARDS = r"""
CREATE FUNCTION identity_page10_delivery_version_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
    IF NEW.aggregate_version <> OLD.aggregate_version + 1 THEN
        RAISE EXCEPTION 'identity delivery version must advance exactly once'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE FUNCTION identity_page10_reconcile_receipt_guard() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp AS $$
DECLARE
    actor_is_platform boolean;
    delivery_version bigint;
BEGIN
    SELECT (is_active AND account_kind = 'platform_administrator')
      INTO actor_is_platform
      FROM identity_account WHERE id = NEW.actor_id;
    SELECT aggregate_version INTO delivery_version
      FROM identity_platformidentitydelivery WHERE id = NEW.delivery_id;
    IF NEW.inventory_control_id IS DISTINCT FROM true
       OR actor_is_platform IS DISTINCT FROM true
       OR delivery_version IS DISTINCT FROM NEW.result_version
       OR NEW.expected_version < 1
       OR NEW.result_version <> NEW.expected_version + 1
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR btrim(NEW.reason) = ''
       OR NEW.reason IS DISTINCT FROM btrim(NEW.reason)
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,39}$' THEN
        RAISE EXCEPTION 'identity delivery reconciliation receipt is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION identity_page10_delivery_version_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION identity_page10_reconcile_receipt_guard() FROM PUBLIC;

CREATE TRIGGER identity_page10_delivery_version
BEFORE UPDATE ON identity_platformidentitydelivery
FOR EACH ROW EXECUTE FUNCTION identity_page10_delivery_version_guard();

CREATE TRIGGER identity_page10_late_outcome_insert
BEFORE INSERT ON identity_platformidentitydeliverylateoutcome
FOR EACH ROW EXECUTE FUNCTION identity_page10_attempt_guard();
CREATE TRIGGER identity_page10_late_outcome_immutable
BEFORE UPDATE OR DELETE ON identity_platformidentitydeliverylateoutcome
FOR EACH ROW EXECUTE FUNCTION identity_page10_append_only_guard();
CREATE TRIGGER identity_page10_late_outcome_no_truncate
BEFORE TRUNCATE ON identity_platformidentitydeliverylateoutcome
FOR EACH STATEMENT EXECUTE FUNCTION identity_page10_append_only_guard();

CREATE TRIGGER identity_page10_reconcile_receipt_immutable
BEFORE UPDATE OR DELETE ON identity_platformidentitydeliveryreconciliationreceipt
FOR EACH ROW EXECUTE FUNCTION identity_page10_append_only_guard();
CREATE TRIGGER identity_page10_reconcile_receipt_insert
BEFORE INSERT ON identity_platformidentitydeliveryreconciliationreceipt
FOR EACH ROW EXECUTE FUNCTION identity_page10_reconcile_receipt_guard();
CREATE TRIGGER identity_page10_reconcile_receipt_no_truncate
BEFORE TRUNCATE ON identity_platformidentitydeliveryreconciliationreceipt
FOR EACH STATEMENT EXECUTE FUNCTION identity_page10_append_only_guard();
"""

REMOVE_APPEND_ONLY_GUARDS = r"""
DROP TRIGGER IF EXISTS identity_page10_reconcile_receipt_no_truncate
    ON identity_platformidentitydeliveryreconciliationreceipt;
DROP TRIGGER IF EXISTS identity_page10_reconcile_receipt_immutable
    ON identity_platformidentitydeliveryreconciliationreceipt;
DROP TRIGGER IF EXISTS identity_page10_reconcile_receipt_insert
    ON identity_platformidentitydeliveryreconciliationreceipt;
DROP TRIGGER IF EXISTS identity_page10_late_outcome_no_truncate
    ON identity_platformidentitydeliverylateoutcome;
DROP TRIGGER IF EXISTS identity_page10_late_outcome_immutable
    ON identity_platformidentitydeliverylateoutcome;
DROP TRIGGER IF EXISTS identity_page10_late_outcome_insert
    ON identity_platformidentitydeliverylateoutcome;
DROP TRIGGER IF EXISTS identity_page10_delivery_version
    ON identity_platformidentitydelivery;
DROP FUNCTION IF EXISTS identity_page10_reconcile_receipt_guard() CASCADE;
DROP FUNCTION IF EXISTS identity_page10_delivery_version_guard() CASCADE;
"""


class Migration(migrations.Migration):
    dependencies = [("identity", "0011_platform_account_invitations")]  # noqa: RUF012

    operations = [  # noqa: RUF012
        migrations.CreateModel(
            name="PlatformIdentityDeliveryLateOutcome",
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
                ("attempt_number", models.PositiveSmallIntegerField()),
                ("lease_token", models.UUIDField()),
                ("observed_at", models.DateTimeField()),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("delivered", "Delivered"),
                            ("transient_failure", "Transient failure"),
                            ("permanent_failure", "Permanent failure"),
                            ("uncertain", "Uncertain provider result"),
                        ],
                        max_length=24,
                    ),
                ),
                (
                    "classification",
                    models.CharField(
                        choices=[
                            ("lifecycle_cancelled", "Lifecycle cancelled"),
                            ("lease_superseded", "Lease superseded"),
                            ("terminal_state", "Delivery already terminal"),
                        ],
                        max_length=24,
                    ),
                ),
                ("provider_reference", models.CharField(blank=True, max_length=160)),
                (
                    "safe_error_code",
                    models.CharField(
                        blank=True,
                        max_length=120,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_delivery_code",
                                message="Use a stable lowercase delivery code.",
                                regex="^[a-z0-9][a-z0-9_.-]{0,119}$",
                            )
                        ],
                    ),
                ),
            ],
            options={
                "ordering": (
                    "delivery_id",
                    "attempt_number",
                    "observed_at",
                    "id",
                )
            },
        ),
        migrations.CreateModel(
            name="PlatformIdentityDeliveryReconciliationReceipt",
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
                    "operation",
                    models.CharField(
                        choices=[
                            ("resolve_delivered", "Resolve as delivered"),
                            ("resolve_retry", "Resolve and retry"),
                        ],
                        max_length=24,
                    ),
                ),
                ("reason", models.CharField(max_length=240)),
                ("retry_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_digest",
                                message="Use a lowercase SHA-256 hex digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                ("expected_version", models.PositiveBigIntegerField()),
                ("result_version", models.PositiveBigIntegerField()),
                ("correlation_id", models.UUIDField()),
                (
                    "source_channel",
                    models.CharField(
                        max_length=40,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_invitation_source_channel",
                                message="Use a stable lowercase source-channel code.",
                                regex="^[a-z][a-z0-9_-]{0,39}$",
                            )
                        ],
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.RemoveConstraint(
            model_name="platformidentitydelivery",
            name="identity_delivery_error_matches_status",
        ),
        migrations.AddField(
            model_name="platformidentitydelivery",
            name="aggregate_version",
            field=models.PositiveBigIntegerField(default=1, editable=False),
        ),
        migrations.AddField(
            model_name="platformidentitydelivery",
            name="cancellation_code",
            field=models.CharField(
                blank=True,
                max_length=120,
                validators=[
                    django.core.validators.RegexValidator(
                        code="invalid_delivery_code",
                        message="Use a stable lowercase delivery code.",
                        regex="^[a-z0-9][a-z0-9_.-]{0,119}$",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="platformidentitydelivery",
            name="cancellation_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="platformidentitydelivery",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="identitychallenge",
            name="delivery_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("succeeded", "Succeeded"),
                    ("permanent_failed", "Permanent failure"),
                    ("suppressed", "Managed by identity delivery"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="platformidentitydelivery",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("processing", "Processing"),
                    ("delivered", "Delivered"),
                    ("retrying", "Retrying"),
                    ("permanent_failed", "Permanent failure"),
                    ("cancelled", "Cancelled"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
        migrations.RunPython(
            suppress_invitation_legacy_delivery,
            restore_invitation_legacy_delivery,
        ),
        migrations.AddConstraint(
            model_name="identitychallenge",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        purpose="account_invitation",
                        delivery_status="suppressed",
                        delivery_attempt_count=0,
                        last_delivery_attempt_at__isnull=True,
                        delivered_at__isnull=True,
                        delivery_error_code="",
                    )
                    | ~models.Q(purpose="account_invitation")
                ),
                name="identity_invitation_legacy_delivery_suppressed",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydelivery",
            constraint=models.CheckConstraint(
                condition=models.Q(aggregate_version__gt=0),
                name="identity_delivery_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydelivery",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        models.Q(
                            status__in=(
                                "retrying",
                                "permanent_failed",
                                "cancelled",
                            )
                        )
                        & ~models.Q(safe_error_code="")
                    )
                    | (
                        models.Q(status__in=("pending", "processing", "delivered"))
                        & models.Q(safe_error_code="")
                    )
                ),
                name="identity_delivery_error_matches_status",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydelivery",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        cancellation_requested_at__isnull=True,
                        cancellation_code="",
                        cancelled_at__isnull=True,
                    )
                    | (
                        models.Q(
                            cancellation_requested_at__isnull=False,
                            status__in=("processing", "cancelled"),
                            payload_destroyed_at__isnull=False,
                        )
                        & ~models.Q(cancellation_code="")
                    )
                ),
                name="identity_delivery_cancellation_evidence",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydelivery",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(status="cancelled", cancelled_at__isnull=False)
                    | (
                        ~models.Q(status="cancelled")
                        & models.Q(cancelled_at__isnull=True)
                    )
                ),
                name="identity_delivery_cancelled_timestamp",
            ),
        ),
        migrations.AddField(
            model_name="platformidentitydeliverylateoutcome",
            name="delivery",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="late_outcomes",
                to="identity.platformidentitydelivery",
            ),
        ),
        migrations.AddField(
            model_name="platformidentitydeliveryreconciliationreceipt",
            name="actor",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="platform_identity_delivery_reconciliations",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="platformidentitydeliveryreconciliationreceipt",
            name="delivery",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reconciliation_receipts",
                to="identity.platformidentitydelivery",
            ),
        ),
        migrations.AddField(
            model_name="platformidentitydeliveryreconciliationreceipt",
            name="inventory_control",
            field=models.ForeignKey(
                default=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="delivery_reconciliation_receipts",
                to="identity.platformaccountinventorycontrol",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydeliverylateoutcome",
            constraint=models.UniqueConstraint(
                fields=("delivery", "attempt_number", "lease_token"),
                name="identity_delivery_late_outcome_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydeliverylateoutcome",
            constraint=models.CheckConstraint(
                condition=models.Q(attempt_number__gte=1, attempt_number__lte=100),
                name="identity_delivery_late_attempt_bounds",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydeliverylateoutcome",
            constraint=models.CheckConstraint(
                condition=(
                    (
                        models.Q(outcome="delivered", safe_error_code="")
                        & ~models.Q(provider_reference="")
                    )
                    | (
                        models.Q(
                            outcome__in=(
                                "transient_failure",
                                "permanent_failure",
                                "uncertain",
                            ),
                            provider_reference="",
                        )
                        & ~models.Q(safe_error_code="")
                    )
                ),
                name="identity_delivery_late_outcome_evidence",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydeliveryreconciliationreceipt",
            constraint=models.UniqueConstraint(
                fields=("inventory_control", "actor", "retry_key"),
                name="identity_delivery_reconcile_retry_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydeliveryreconciliationreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                name="identity_delivery_reconcile_digest",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydeliveryreconciliationreceipt",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(expected_version__gt=0)
                    & models.Q(result_version=models.F("expected_version") + 1)
                ),
                name="identity_delivery_reconcile_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="platformidentitydeliveryreconciliationreceipt",
            constraint=models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="identity_delivery_reconcile_reason",
            ),
        ),
        migrations.RunSQL(
            sql=INSTALL_APPEND_ONLY_GUARDS,
            reverse_sql=REMOVE_APPEND_ONLY_GUARDS,
        ),
    ]
