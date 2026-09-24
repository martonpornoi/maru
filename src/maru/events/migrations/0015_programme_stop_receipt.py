"""Retain dormant stop receipts; terminal admission is installed separately."""

import uuid
from typing import Any, ClassVar

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def refuse_used_stop_receipt_downgrade(apps: Any, schema_editor: Any) -> None:
    """Serialize the evidence check before removing accountable stop history."""
    schema_editor.execute(
        "LOCK TABLE public.events_programmestopreceipt IN ACCESS EXCLUSIVE MODE"
    )
    if apps.get_model("events", "ProgrammeStopReceipt").objects.exists():
        raise RuntimeError("Programme stop evidence exists; retain it and fix forward.")


FORWARD_SQL = r"""
CREATE FUNCTION public.maru_programme_stop_receipt_guard()
RETURNS trigger AS $$
BEGIN
    -- Storage is not permission to stop. The complete owner-closure migration
    -- replaces insertion admission only after all terminal writer guards exist.
    RAISE EXCEPTION 'Programme stop receipts require complete native stop admission'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_programme_stop_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE ON public.events_programmestopreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_programme_stop_receipt_guard();

CREATE FUNCTION public.maru_programme_stop_refuse_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Programme stop receipts cannot be truncated'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_programme_stop_no_truncate
BEFORE TRUNCATE ON public.events_programmestopreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_programme_stop_refuse_truncate();

REVOKE ALL ON FUNCTION public.maru_programme_stop_receipt_guard() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.maru_programme_stop_refuse_truncate() FROM PUBLIC;
"""

REVERSE_SQL = r"""
DROP TRIGGER events_programme_stop_no_truncate ON public.events_programmestopreceipt;
DROP TRIGGER events_programme_stop_receipt_guard ON public.events_programmestopreceipt;
DROP FUNCTION public.maru_programme_stop_refuse_truncate();
DROP FUNCTION public.maru_programme_stop_receipt_guard();
"""


class Migration(migrations.Migration):
    """Add protected dormant storage without admitting any terminal operation."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0009_native_mutation_witness"),
        ("events", "0014_programme_setup_downgrade_fence"),
        ("organizations", "0014_purpose_bounded_representation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="ProgrammeStopReceipt",
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
                ("idempotency_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest."
                            )
                        ],
                    ),
                ),
                (
                    "preview_fingerprint",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                r"^[0-9a-f]{64}\Z", "Use a SHA-256 digest."
                            )
                        ],
                    ),
                ),
                (
                    "previous_lifecycle",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("preparing", "Preparing"),
                            ("ready", "Ready"),
                            ("live", "Live"),
                            ("closing", "Closing"),
                        ],
                        max_length=20,
                    ),
                ),
                ("expected_aggregate_version", models.PositiveIntegerField()),
                ("expected_lifecycle_version", models.PositiveIntegerField()),
                ("impact_document", models.JSONField()),
                ("reason", models.CharField(max_length=240)),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_stop_receipts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_stop_receipt",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_stop_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "source_audit",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_stop_receipt",
                        to="audit.auditevent",
                    ),
                ),
                (
                    "transition",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="programme_stop_receipt",
                        to="events.editionlifecycletransition",
                    ),
                ),
            ],
            options={
                "ordering": ("created_at", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("actor", "idempotency_key"),
                        name="programme_stop_actor_key_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(expected_aggregate_version__gte=1),
                        name="programme_stop_aggregate_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            previous_lifecycle__in=(
                                "draft",
                                "preparing",
                                "ready",
                                "live",
                                "closing",
                            )
                        ),
                        name="programme_stop_previous_state",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(request_digest__regex=r"^[0-9a-f]{64}$"),
                        name="programme_stop_request_digest",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            preview_fingerprint__regex=r"^[0-9a-f]{64}$"
                        ),
                        name="programme_stop_preview_digest",
                    ),
                    models.CheckConstraint(
                        condition=~models.Q(reason=""),
                        name="programme_stop_reason_nonempty",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_stop_receipt_downgrade
        ),
    ]
