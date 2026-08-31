"""Retain replay rationale and bind every retry-budget increase to evidence."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

FORWARD_SQL = """
CREATE FUNCTION public.maru_guard_effect_replay_receipt()
RETURNS trigger AS $$
BEGIN
    IF TG_OP != 'INSERT' THEN
        IF TG_OP = 'TRUNCATE'
           AND public.maru_authority_provenance_test_reset_allowed()
        THEN
            RETURN NULL;
        END IF;
        RAISE EXCEPTION 'effect replay receipts are append-only'
            USING ERRCODE = '23514';
    END IF;

    IF char_length(btrim(NEW.reason)) < 1
       OR char_length(NEW.reason) > 240
       OR NEW.additional_attempts < 1
       OR NEW.additional_attempts > 20
       OR NEW.new_max_attempts != (
           NEW.previous_max_attempts + NEW.additional_attempts
       )
       OR NEW.new_max_attempts > 100
    THEN
        RAISE EXCEPTION 'effect replay receipt is outside bounded policy'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.identity_account AS actor
         WHERE actor.id = NEW.actor_id
           AND actor.is_active
    )
    THEN
        RAISE EXCEPTION 'effect replay receipt actor must be an active account'
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM public.effects_outboxmessage AS message
         WHERE message.id = NEW.outbox_message_id
           AND message.organization_id = NEW.organization_id
           AND message.status = 'quarantined'
           AND message.max_attempts = NEW.previous_max_attempts
           AND message.replay_count + 1 = NEW.replay_count
    )
    THEN
        RAISE EXCEPTION 'effect replay receipt must match locked quarantined work'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_guard_effect_replay_receipt() FROM PUBLIC;

CREATE TRIGGER effect_replay_receipt_append_only
BEFORE INSERT OR UPDATE OR DELETE
ON public.effects_effectreplayreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_effect_replay_receipt();

CREATE TRIGGER effect_replay_receipt_refuse_truncate
BEFORE TRUNCATE
ON public.effects_effectreplayreceipt
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_guard_effect_replay_receipt();

CREATE OR REPLACE FUNCTION public.maru_guard_outbox_message()
RETURNS trigger AS $$
DECLARE
    event_organization uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'outbox messages require controlled retention'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT organization_id INTO event_organization
          FROM public.effects_domainevent WHERE id = NEW.event_id;
        IF event_organization IS NULL
           OR event_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'outbox tenant must match its domain event'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.event_id != OLD.event_id
       OR NEW.organization_id != OLD.organization_id
       OR NEW.destination != OLD.destination
       OR NEW.workload_pool != OLD.workload_pool
    THEN
        RAISE EXCEPTION 'outbox routing envelope is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status != 'quarantined'
       AND (
           NEW.max_attempts != OLD.max_attempts
           OR NEW.replay_count != OLD.replay_count
       )
    THEN
        RAISE EXCEPTION 'outbox retry policy is immutable outside replay'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'pending'
       AND NEW.status IN ('processing', 'cancelled')
    THEN
        IF NEW.status = 'processing'
           AND NEW.attempt_count != OLD.attempt_count + 1
        THEN
            RAISE EXCEPTION 'claim must increment attempt count'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'cancelled'
           AND NEW.attempt_count != OLD.attempt_count
        THEN
            RAISE EXCEPTION 'cancellation cannot change attempt count'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'processing'
       AND NEW.status IN ('pending', 'succeeded', 'quarantined')
       AND NEW.attempt_count = OLD.attempt_count
    THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'processing'
       AND NEW.status = 'processing'
       AND OLD.lease_expires_at <= NEW.claimed_at
       AND NEW.attempt_count = OLD.attempt_count + 1
    THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'quarantined'
       AND NEW.status = 'pending'
       AND NEW.attempt_count = OLD.attempt_count
       AND NEW.max_attempts > OLD.max_attempts
       AND NEW.replay_count = OLD.replay_count + 1
       AND EXISTS (
           SELECT 1
             FROM public.effects_effectreplayreceipt AS receipt
            WHERE receipt.outbox_message_id = OLD.id
              AND receipt.organization_id = OLD.organization_id
              AND receipt.previous_max_attempts = OLD.max_attempts
              AND receipt.new_max_attempts = NEW.max_attempts
              AND receipt.replay_count = NEW.replay_count
       )
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'invalid outbox state transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION public.maru_guard_outbox_message() FROM PUBLIC;
"""

REVERSE_SQL = """
CREATE OR REPLACE FUNCTION public.maru_guard_outbox_message()
RETURNS trigger AS $$
DECLARE
    event_organization uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'outbox messages require controlled retention'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        SELECT organization_id INTO event_organization
          FROM public.effects_domainevent WHERE id = NEW.event_id;
        IF event_organization IS NULL
           OR event_organization != NEW.organization_id
        THEN
            RAISE EXCEPTION 'outbox tenant must match its domain event'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.event_id != OLD.event_id
       OR NEW.organization_id != OLD.organization_id
       OR NEW.destination != OLD.destination
       OR NEW.workload_pool != OLD.workload_pool
    THEN
        RAISE EXCEPTION 'outbox routing envelope is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status != 'quarantined'
       AND (
           NEW.max_attempts != OLD.max_attempts
           OR NEW.replay_count != OLD.replay_count
       )
    THEN
        RAISE EXCEPTION 'outbox retry policy is immutable outside replay'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'pending'
       AND NEW.status IN ('processing', 'cancelled')
    THEN
        IF NEW.status = 'processing'
           AND NEW.attempt_count != OLD.attempt_count + 1
        THEN
            RAISE EXCEPTION 'claim must increment attempt count'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'cancelled'
           AND NEW.attempt_count != OLD.attempt_count
        THEN
            RAISE EXCEPTION 'cancellation cannot change attempt count'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'processing'
       AND NEW.status IN ('pending', 'succeeded', 'quarantined')
       AND NEW.attempt_count = OLD.attempt_count
    THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'processing'
       AND NEW.status = 'processing'
       AND OLD.lease_expires_at <= NEW.claimed_at
       AND NEW.attempt_count = OLD.attempt_count + 1
    THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'quarantined'
       AND NEW.status = 'pending'
       AND NEW.attempt_count = OLD.attempt_count
       AND NEW.max_attempts > OLD.max_attempts
       AND NEW.replay_count = OLD.replay_count + 1
    THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'invalid outbox state transition'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION public.maru_guard_outbox_message() TO PUBLIC;

DROP TRIGGER IF EXISTS effect_replay_receipt_refuse_truncate
    ON public.effects_effectreplayreceipt;
DROP TRIGGER IF EXISTS effect_replay_receipt_append_only
    ON public.effects_effectreplayreceipt;
DROP FUNCTION IF EXISTS public.maru_guard_effect_replay_receipt();
"""


def refuse_effect_replay_receipt_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Refuse removal once any retained operator rationale exists."""
    receipt = apps.get_model("effects", "EffectReplayReceipt")
    table = schema_editor.quote_name(receipt._meta.db_table)  # noqa: SLF001
    schema_editor.execute(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE")
    if receipt.objects.exists():
        raise RuntimeError(
            "Cannot remove retained effect replay rationale; fix forward."
        )


def refuse_unbounded_existing_effect_attempt_budgets(
    apps: Any,
    _schema_editor: Any,
) -> None:
    """Refuse activation while an existing delivery exceeds the safety cap."""
    outbox_message = apps.get_model("effects", "OutboxMessage")
    if outbox_message.objects.filter(max_attempts__gt=100).exists():
        raise RuntimeError(
            "Cannot activate the effect replay safety cap while an existing "
            "outbox message exceeds 100 attempts; reconcile it before retrying."
        )


class Migration(migrations.Migration):
    """Install immutable replay evidence and database-coupled replay guards."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0007_authority_provenance_activation_guards"),
        ("effects", "0002_integrity_guards"),
    ]

    operations: ClassVar[list[Any]] = [
        migrations.RunPython(
            refuse_unbounded_existing_effect_attempt_budgets,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="outboxmessage",
            constraint=models.CheckConstraint(
                condition=models.Q(("max_attempts__lte", 100)),
                name="outbox_max_attempts_bounded",
            ),
        ),
        migrations.CreateModel(
            name="EffectReplayReceipt",
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
                ("organization_id", models.UUIDField()),
                ("actor_id", models.UUIDField()),
                ("reason", models.CharField(max_length=240)),
                (
                    "additional_attempts",
                    models.PositiveSmallIntegerField(
                        validators=[
                            django.core.validators.MinValueValidator(1),
                            django.core.validators.MaxValueValidator(20),
                        ]
                    ),
                ),
                ("previous_max_attempts", models.PositiveIntegerField()),
                ("new_max_attempts", models.PositiveIntegerField()),
                ("replay_count", models.PositiveIntegerField()),
                ("correlation_id", models.UUIDField(db_index=True)),
                (
                    "retention_class",
                    models.CharField(
                        default="operations-extended",
                        editable=False,
                        max_length=80,
                    ),
                ),
                (
                    "outbox_message",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="replay_receipts",
                        to="effects.outboxmessage",
                    ),
                ),
            ],
            options={
                "ordering": (
                    "outbox_message_id",
                    "replay_count",
                    "created_at",
                    "id",
                ),
                "indexes": [
                    models.Index(
                        fields=[
                            "organization_id",
                            "outbox_message",
                            "-replay_count",
                        ],
                        name="effect_replay_org_message_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("outbox_message", "replay_count"),
                        name="effect_replay_count_unique",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("additional_attempts__gte", 1))
                            & models.Q(("additional_attempts__lte", 20))
                        ),
                        name="effect_replay_additional_attempts_bounded",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            (
                                "new_max_attempts",
                                models.F("previous_max_attempts")
                                + models.F("additional_attempts"),
                            )
                        ),
                        name="effect_replay_attempt_limit_arithmetic",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("new_max_attempts__lte", 100)),
                        name="effect_replay_total_attempts_bounded",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_effect_replay_receipt_downgrade,
        ),
    ]
