"""Capture opt-in new audit evidence without changing historical audit rows."""

from typing import Any, ClassVar

import django.db.models.deletion
from django.core.validators import RegexValidator
from django.db import migrations, models

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_audit_current_native_transaction_stamp()
RETURNS text AS $$
    SELECT encode(sha256(convert_to(
        pg_current_xact_id()::text || ':' || pg_backend_pid()::text || ':' ||
        extract(epoch FROM pg_postmaster_start_time())::text, 'UTF8'
    )), 'hex');
$$ LANGUAGE sql VOLATILE
SET search_path = pg_catalog;

CREATE FUNCTION public.maru_audit_native_witness_guard()
RETURNS trigger AS $$
BEGIN
    IF TG_OP <> 'INSERT'
       OR TG_RELID <> 'public.audit_auditnativemutationwitness'::regclass
       OR pg_trigger_depth() <> 2
       OR current_setting('maru.audit_native_event_id', TRUE)
          IS DISTINCT FROM NEW.audit_event_id::text
       OR NEW.transaction_stamp IS DISTINCT FROM
          public.maru_audit_current_native_transaction_stamp()
       OR NOT EXISTS (SELECT 1 FROM public.audit_auditevent event
                      WHERE event.id = NEW.audit_event_id
                        AND event.outcome = 'allow') THEN
        RAISE EXCEPTION 'native audit witness requires its actual new audit insert'
          USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_audit_capture_native_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_RELID <> 'public.audit_auditevent'::regclass
       OR TG_OP <> 'INSERT' OR TG_WHEN <> 'AFTER' THEN
        RAISE EXCEPTION 'native audit capture requires its owning relation'
          USING ERRCODE = '23514';
    END IF;
    IF current_setting('maru.audit_native_event_id', TRUE)
       IS DISTINCT FROM NEW.id::text THEN
        RETURN NEW;
    END IF;
    IF pg_trigger_depth() <> 1 THEN
        RAISE EXCEPTION 'native audit capture requires its direct owner append'
          USING ERRCODE = '23514';
    END IF;
    INSERT INTO public.audit_auditnativemutationwitness
        (audit_event_id, transaction_stamp, created_at)
    VALUES (NEW.id, public.maru_audit_current_native_transaction_stamp(),
            clock_timestamp());
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER audit_native_witness_shape
BEFORE INSERT OR UPDATE OR DELETE ON public.audit_auditnativemutationwitness
FOR EACH ROW EXECUTE FUNCTION public.maru_audit_native_witness_guard();

CREATE TRIGGER audit_native_witness_no_truncate
BEFORE TRUNCATE ON public.audit_auditnativemutationwitness
FOR EACH STATEMENT EXECUTE FUNCTION public.maru_prevent_audit_event_truncate();

CREATE TRIGGER audit_native_mutation_capture
AFTER INSERT ON public.audit_auditevent
FOR EACH ROW EXECUTE FUNCTION public.maru_audit_capture_native_mutation();
"""

REVERSE_SQL = r"""
DROP TRIGGER audit_native_mutation_capture ON public.audit_auditevent;
DROP TRIGGER audit_native_witness_no_truncate
ON public.audit_auditnativemutationwitness;
DROP TRIGGER audit_native_witness_shape ON public.audit_auditnativemutationwitness;
DROP FUNCTION public.maru_audit_capture_native_mutation();
DROP FUNCTION public.maru_audit_native_witness_guard();
DROP FUNCTION public.maru_audit_current_native_transaction_stamp();
"""


def refuse_used_witness_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain populated proof until its consumers have a reviewed recovery path."""
    witness = apps.get_model("audit", "AuditNativeMutationWitness")
    schema_editor.execute(
        "LOCK TABLE public.audit_auditnativemutationwitness IN ACCESS EXCLUSIVE MODE"
    )
    if witness.objects.exists():
        raise RuntimeError(
            "Native audit witness history exists; retain guards and fix forward."
        )


class Migration(migrations.Migration):
    """Keep ordinary audit append and its historical semantic digest unchanged."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("audit", "0008_identity_retention_audit_uniqueness"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="AuditNativeMutationWitness",
            fields=[
                (
                    "audit_event",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        primary_key=True,
                        related_name="native_mutation_witness",
                        serialize=False,
                        to="audit.auditevent",
                    ),
                ),
                (
                    "transaction_stamp",
                    models.CharField(
                        max_length=64,
                        validators=[
                            RegexValidator(
                                regex="^[0-9a-f]{64}$",
                                message="Use a lowercase SHA-256 hex digest.",
                                code="invalid_digest",
                            )
                        ],
                    ),
                ),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(transaction_stamp__regex=r"^[0-9a-f]{64}$"),
                        name="audit_native_witness_stamp_shape",
                    )
                ]
            },
        ),
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, reverse_code=refuse_used_witness_downgrade
        ),
    ]
