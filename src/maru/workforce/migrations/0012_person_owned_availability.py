"""Add person-owned current Availability with minimized command evidence."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

FORWARD_SQL = r"""
CREATE FUNCTION public.maru_guard_workforce_availability_plan()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $availability_plan_guard$
DECLARE
    edition_organization uuid;
    edition_time_zone varchar;
    subject_kind varchar;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce availability plans cannot be deleted normally'
            USING ERRCODE = '23514';
    END IF;

    SELECT organization_id, time_zone
      INTO edition_organization, edition_time_zone
      FROM public.events_eventedition
     WHERE id = NEW.edition_id
     FOR KEY SHARE;
    IF NOT FOUND
       OR edition_organization IS DISTINCT FROM NEW.organization_id
       OR edition_time_zone IS DISTINCT FROM NEW.time_zone
    THEN
        RAISE EXCEPTION 'workforce availability edition scope mismatch'
            USING ERRCODE = '23514';
    END IF;

    SELECT account_kind INTO subject_kind
      FROM public.identity_account
     WHERE id = NEW.account_id
     FOR KEY SHARE;
    IF subject_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION 'platform accounts cannot own workforce availability'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.window_set_digest !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'workforce availability digest is invalid'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.command_version <> 1 THEN
            RAISE EXCEPTION 'workforce availability must begin at version one'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.account_id IS DISTINCT FROM OLD.account_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'workforce availability plan identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.command_version <> OLD.command_version + 1 THEN
            RAISE EXCEPTION 'workforce availability version did not advance once'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.status IN ('draft', 'submitted')
       AND NOT EXISTS (
           SELECT 1
             FROM public.workforce_positionassignment
            WHERE organization_id = NEW.organization_id
              AND edition_id = NEW.edition_id
              AND account_id = NEW.account_id
              AND status IN ('proposed', 'active')
       )
    THEN
        RAISE EXCEPTION 'open workforce assignment required for availability'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$availability_plan_guard$;

CREATE TRIGGER workforce_availability_plan_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_personavailabilityplan
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_availability_plan();

REVOKE ALL ON FUNCTION public.maru_guard_workforce_availability_plan()
FROM PUBLIC;

CREATE TRIGGER workforce_idn011_availability_subject_guard
BEFORE INSERT OR UPDATE
ON public.workforce_personavailabilityplan
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_idn011_subject();

CREATE FUNCTION public.maru_guard_workforce_availability_window()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $availability_window_guard$
DECLARE
    plan_version bigint;
    plan_status varchar;
    plan_time_zone varchar;
    edition_starts_on date;
    edition_ends_on date;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'workforce availability periods are replacement-only'
            USING ERRCODE = '23514';
    END IF;

    SELECT plan.command_version,
           plan.status,
           plan.time_zone,
           edition.starts_on,
           edition.ends_on
      INTO plan_version,
           plan_status,
           plan_time_zone,
           edition_starts_on,
           edition_ends_on
      FROM public.workforce_personavailabilityplan AS plan
      JOIN public.events_eventedition AS edition ON edition.id = plan.edition_id
     WHERE plan.id = CASE WHEN TG_OP = 'DELETE' THEN OLD.plan_id ELSE NEW.plan_id END
     FOR KEY SHARE OF plan, edition;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'workforce availability plan is unavailable'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'DELETE' THEN
        IF plan_version <= OLD.created_by_version THEN
            RAISE EXCEPTION 'replace the complete workforce availability plan'
                USING ERRCODE = '23514';
        END IF;
        RETURN OLD;
    END IF;

    IF plan_status = 'withdrawn'
       OR NEW.created_by_version IS DISTINCT FROM plan_version
    THEN
        RAISE EXCEPTION 'workforce availability period version mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.preference NOT IN ('available', 'preferred')
       OR NEW.ends_at <= NEW.starts_at
    THEN
        RAISE EXCEPTION 'workforce availability period is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.starts_at < (edition_starts_on::timestamp AT TIME ZONE plan_time_zone)
       OR NEW.ends_at > (
           (edition_ends_on + 1)::timestamp AT TIME ZONE plan_time_zone
       )
    THEN
        RAISE EXCEPTION 'workforce availability period is outside edition dates'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$availability_window_guard$;

CREATE TRIGGER workforce_availability_window_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_personavailabilitywindow
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_availability_window();

REVOKE ALL ON FUNCTION public.maru_guard_workforce_availability_window()
FROM PUBLIC;

CREATE FUNCTION public.maru_guard_workforce_availability_receipt()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $availability_receipt_guard$
DECLARE
    plan_organization uuid;
    plan_edition uuid;
    plan_account uuid;
    plan_status varchar;
    plan_version bigint;
    plan_window_count integer;
    plan_digest varchar;
    actor_kind varchar;
    actor_active boolean;
    expected_action varchar;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'workforce availability receipts are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id,
           edition_id,
           account_id,
           status,
           command_version,
           window_count,
           window_set_digest
      INTO plan_organization,
           plan_edition,
           plan_account,
           plan_status,
           plan_version,
           plan_window_count,
           plan_digest
      FROM public.workforce_personavailabilityplan
     WHERE id = NEW.plan_id
     FOR KEY SHARE;
    SELECT account_kind, is_active
      INTO actor_kind, actor_active
      FROM public.identity_account
     WHERE id = NEW.actor_id
     FOR KEY SHARE;
    expected_action := CASE plan_status
        WHEN 'draft' THEN 'draft_saved'
        WHEN 'submitted' THEN 'submitted'
        WHEN 'withdrawn' THEN 'withdrawn'
        ELSE NULL
    END;
    IF plan_organization IS DISTINCT FROM NEW.organization_id
       OR plan_edition IS DISTINCT FROM NEW.edition_id
       OR plan_account IS DISTINCT FROM NEW.actor_id
       OR plan_status IS DISTINCT FROM NEW.resulting_status
       OR plan_version IS DISTINCT FROM NEW.resulting_version
       OR plan_window_count IS DISTINCT FROM NEW.window_count
       OR plan_digest IS DISTINCT FROM NEW.window_set_digest
       OR expected_action IS DISTINCT FROM NEW.action
       OR actor_kind IS DISTINCT FROM 'person'
       OR actor_active IS DISTINCT FROM TRUE
       OR NEW.window_set_digest !~ '^[0-9a-f]{64}$'
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NEW.source_channel !~ '^[a-z][a-z0-9_-]{0,31}$'
    THEN
        RAISE EXCEPTION 'workforce availability receipt evidence mismatch'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$availability_receipt_guard$;

CREATE TRIGGER workforce_availability_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_personavailabilitycommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_workforce_availability_receipt();

REVOKE ALL ON FUNCTION public.maru_guard_workforce_availability_receipt()
FROM PUBLIC;

CREATE FUNCTION public.maru_deferred_validate_workforce_availability()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $availability_deferred_guard$
DECLARE
    checked_plan_id uuid;
    plan_status varchar;
    plan_version bigint;
    plan_window_count integer;
    plan_digest varchar;
    actual_window_count bigint;
    stale_window_count bigint;
    matching_receipt_count bigint;
BEGIN
    IF TG_TABLE_NAME = 'workforce_personavailabilityplan' THEN
        checked_plan_id := NEW.id;
    ELSIF TG_OP = 'DELETE' THEN
        checked_plan_id := OLD.plan_id;
    ELSE
        checked_plan_id := NEW.plan_id;
    END IF;
    SELECT status, command_version, window_count, window_set_digest
      INTO plan_status, plan_version, plan_window_count, plan_digest
      FROM public.workforce_personavailabilityplan
     WHERE id = checked_plan_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'workforce availability plan disappeared'
            USING ERRCODE = '23514';
    END IF;
    SELECT COUNT(*),
           COUNT(*) FILTER (WHERE created_by_version <> plan_version)
      INTO actual_window_count, stale_window_count
      FROM public.workforce_personavailabilitywindow
     WHERE plan_id = checked_plan_id;
    IF actual_window_count IS DISTINCT FROM plan_window_count
       OR stale_window_count <> 0
       OR (plan_status = 'withdrawn' AND actual_window_count <> 0)
    THEN
        RAISE EXCEPTION 'workforce availability current periods are inconsistent'
            USING ERRCODE = '23514';
    END IF;
    SELECT COUNT(*)
      INTO matching_receipt_count
      FROM public.workforce_personavailabilitycommandreceipt
     WHERE plan_id = checked_plan_id
       AND resulting_version = plan_version
       AND resulting_status = plan_status
       AND window_count = plan_window_count
       AND window_set_digest = plan_digest
       AND action = CASE plan_status
           WHEN 'draft' THEN 'draft_saved'
           WHEN 'submitted' THEN 'submitted'
           WHEN 'withdrawn' THEN 'withdrawn'
           ELSE ''
       END;
    IF matching_receipt_count <> 1 THEN
        RAISE EXCEPTION 'workforce availability lacks exact command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$availability_deferred_guard$;

CREATE CONSTRAINT TRIGGER workforce_availability_plan_evidence_guard
AFTER INSERT OR UPDATE
ON public.workforce_personavailabilityplan
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_workforce_availability();

CREATE CONSTRAINT TRIGGER workforce_availability_window_evidence_guard
AFTER INSERT OR DELETE
ON public.workforce_personavailabilitywindow
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_workforce_availability();

CREATE CONSTRAINT TRIGGER workforce_availability_receipt_evidence_guard
AFTER INSERT
ON public.workforce_personavailabilitycommandreceipt
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_deferred_validate_workforce_availability();

REVOKE ALL ON FUNCTION public.maru_deferred_validate_workforce_availability()
FROM PUBLIC;

CREATE FUNCTION public.maru_refuse_workforce_availability_truncate()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY DEFINER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $availability_truncate_guard$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'workforce availability tables cannot be truncated'
        USING ERRCODE = '23514';
END;
$availability_truncate_guard$;

CREATE TRIGGER workforce_availability_plan_truncate_guard
BEFORE TRUNCATE ON public.workforce_personavailabilityplan
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_refuse_workforce_availability_truncate();
CREATE TRIGGER workforce_availability_window_truncate_guard
BEFORE TRUNCATE ON public.workforce_personavailabilitywindow
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_refuse_workforce_availability_truncate();
CREATE TRIGGER workforce_availability_receipt_truncate_guard
BEFORE TRUNCATE ON public.workforce_personavailabilitycommandreceipt
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_refuse_workforce_availability_truncate();

REVOKE ALL ON FUNCTION public.maru_refuse_workforce_availability_truncate()
FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.maru_deferred_validate_workforce_idn011_account()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $workforce_subject_guard$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (
               SELECT 1 FROM public.workforce_volunteerapplication
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1 FROM public.workforce_onboardingdocumentrequest
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1 FROM public.workforce_positionassignment
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1 FROM public.workforce_personavailabilityplan
                WHERE account_id = NEW.id
           )
       )
    THEN
        RAISE EXCEPTION 'platform account cannot retain workforce subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$workforce_subject_guard$;
"""

REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS workforce_availability_receipt_truncate_guard
    ON public.workforce_personavailabilitycommandreceipt;
DROP TRIGGER IF EXISTS workforce_availability_window_truncate_guard
    ON public.workforce_personavailabilitywindow;
DROP TRIGGER IF EXISTS workforce_availability_plan_truncate_guard
    ON public.workforce_personavailabilityplan;
DROP FUNCTION IF EXISTS public.maru_refuse_workforce_availability_truncate();
DROP TRIGGER IF EXISTS workforce_availability_receipt_evidence_guard
    ON public.workforce_personavailabilitycommandreceipt;
DROP TRIGGER IF EXISTS workforce_availability_window_evidence_guard
    ON public.workforce_personavailabilitywindow;
DROP TRIGGER IF EXISTS workforce_availability_plan_evidence_guard
    ON public.workforce_personavailabilityplan;
DROP FUNCTION IF EXISTS public.maru_deferred_validate_workforce_availability();
DROP TRIGGER IF EXISTS workforce_availability_receipt_guard
    ON public.workforce_personavailabilitycommandreceipt;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_availability_receipt();
DROP TRIGGER IF EXISTS workforce_availability_window_guard
    ON public.workforce_personavailabilitywindow;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_availability_window();
DROP TRIGGER IF EXISTS workforce_idn011_availability_subject_guard
    ON public.workforce_personavailabilityplan;
DROP TRIGGER IF EXISTS workforce_availability_plan_guard
    ON public.workforce_personavailabilityplan;
DROP FUNCTION IF EXISTS public.maru_guard_workforce_availability_plan();

CREATE OR REPLACE FUNCTION public.maru_deferred_validate_workforce_idn011_account()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $workforce_subject_guard$
BEGIN
    IF NEW.account_kind IS DISTINCT FROM 'person'
       AND (
           EXISTS (
               SELECT 1 FROM public.workforce_volunteerapplication
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1 FROM public.workforce_onboardingdocumentrequest
                WHERE account_id = NEW.id
           )
           OR EXISTS (
               SELECT 1 FROM public.workforce_positionassignment
                WHERE account_id = NEW.id
           )
       )
    THEN
        RAISE EXCEPTION 'platform account cannot retain workforce subject records'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$workforce_subject_guard$;
"""


def refuse_used_availability_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Keep retained plans and receipts fix-forward once created."""
    plan = apps.get_model("workforce", "PersonAvailabilityPlan")
    window = apps.get_model("workforce", "PersonAvailabilityWindow")
    receipt = apps.get_model("workforce", "PersonAvailabilityCommandReceipt")
    schema_editor.execute(
        "LOCK TABLE public.workforce_personavailabilityplan, "
        "public.workforce_personavailabilitywindow, "
        "public.workforce_personavailabilitycommandreceipt "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if plan.objects.exists() or window.objects.exists() or receipt.objects.exists():
        raise RuntimeError(
            "Cannot remove person-owned Availability after durable plans or command "
            "evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Create the current-plan aggregate and its database-owned invariants."""

    dependencies: ClassVar[list[tuple[str, str] | object]] = [
        ("authorization", "0017_workforce_availability_capability"),
        ("events", "0009_edition_workspace_downgrade_fence"),
        ("organizations", "0013_runtime_executable_function_hardening"),
        ("workforce", "0011_owner_assignment_commands"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS btree_gist",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name="PersonAvailabilityPlan",
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
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Private draft"),
                            ("submitted", "Shared with organizers"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        max_length=16,
                    ),
                ),
                ("time_zone", models.CharField(max_length=63)),
                ("command_version", models.PositiveBigIntegerField(editable=False)),
                (
                    "window_count",
                    models.PositiveSmallIntegerField(default=0, editable=False),
                ),
                (
                    "window_set_digest",
                    models.CharField(
                        editable=False,
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_structure_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                (
                    "submitted_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "withdrawn_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_availability_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="person_availability_plans",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="person_availability_plans",
                        to="organizations.organization",
                    ),
                ),
            ],
            options={"ordering": ("edition_id", "account_id", "id")},
        ),
        migrations.CreateModel(
            name="PersonAvailabilityCommandReceipt",
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
                    "action",
                    models.CharField(
                        choices=[
                            ("draft_saved", "Private draft saved"),
                            ("submitted", "Availability shared"),
                            ("withdrawn", "Availability withdrawn"),
                        ],
                        max_length=16,
                    ),
                ),
                ("resulting_version", models.PositiveBigIntegerField()),
                (
                    "resulting_status",
                    models.CharField(
                        choices=[
                            ("draft", "Private draft"),
                            ("submitted", "Shared with organizers"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        max_length=16,
                    ),
                ),
                ("window_count", models.PositiveSmallIntegerField()),
                (
                    "window_set_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_structure_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                ("retry_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_structure_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                ("correlation_id", models.UUIDField()),
                ("source_channel", models.CharField(max_length=32)),
                (
                    "actor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_availability_commands_acted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="person_availability_command_receipts",
                        to="events.eventedition",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="person_availability_command_receipts",
                        to="organizations.organization",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="command_receipts",
                        to="workforce.personavailabilityplan",
                    ),
                ),
            ],
            options={"ordering": ("plan_id", "resulting_version", "id")},
        ),
        migrations.CreateModel(
            name="PersonAvailabilityWindow",
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
                ("starts_at", models.DateTimeField()),
                ("ends_at", models.DateTimeField()),
                (
                    "preference",
                    models.CharField(
                        choices=[
                            ("available", "Available"),
                            ("preferred", "Preferred"),
                        ],
                        max_length=16,
                    ),
                ),
                ("created_by_version", models.PositiveBigIntegerField(editable=False)),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="windows",
                        to="workforce.personavailabilityplan",
                    ),
                ),
            ],
            options={"ordering": ("plan_id", "starts_at", "ends_at", "id")},
        ),
        migrations.AddIndex(
            model_name="personavailabilityplan",
            index=models.Index(
                fields=["organization", "edition", "status"],
                name="wrk_avail_plan_state_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilityplan",
            constraint=models.UniqueConstraint(
                fields=("organization", "edition", "account"),
                name="workforce_avail_plan_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilityplan",
            constraint=models.CheckConstraint(
                condition=models.Q(("command_version__gt", 0)),
                name="workforce_avail_version_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilityplan",
            constraint=models.CheckConstraint(
                condition=models.Q(("window_count__lte", 64)),
                name="workforce_avail_count_bound",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilityplan",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("status", "draft"),
                        ("submitted_at__isnull", True),
                        ("withdrawn_at__isnull", True),
                    ),
                    models.Q(
                        ("status", "submitted"),
                        ("submitted_at__isnull", False),
                        ("withdrawn_at__isnull", True),
                    ),
                    models.Q(
                        ("status", "withdrawn"),
                        ("submitted_at__isnull", True),
                        ("window_count", 0),
                        ("withdrawn_at__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="workforce_avail_state_evidence",
            ),
        ),
        migrations.AddIndex(
            model_name="personavailabilitycommandreceipt",
            index=models.Index(
                fields=["organization", "edition", "action", "created_at"],
                name="wrk_avail_action_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitycommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("plan", "resulting_version"),
                name="workforce_avail_receipt_ver",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitycommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_avail_retry_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitycommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("resulting_version__gt", 0)),
                name="workforce_avail_receipt_pos",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitycommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("window_count__lte", 64)),
                name="workforce_avail_receipt_cnt",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitycommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("source_channel", ""), _negated=True),
                name="workforce_avail_source_set",
            ),
        ),
        migrations.AddIndex(
            model_name="personavailabilitywindow",
            index=models.Index(
                fields=["plan", "starts_at"],
                name="wrk_avail_window_start_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitywindow",
            constraint=models.CheckConstraint(
                condition=models.Q(("ends_at__gt", models.F("starts_at"))),
                name="workforce_avail_window_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitywindow",
            constraint=models.CheckConstraint(
                condition=models.Q(("created_by_version__gt", 0)),
                name="workforce_avail_window_ver",
            ),
        ),
        migrations.AddConstraint(
            model_name="personavailabilitywindow",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                expressions=(
                    ("plan", "="),
                    (
                        models.Func(
                            models.F("starts_at"),
                            models.F("ends_at"),
                            models.Value("[)"),
                            function="TSTZRANGE",
                            output_field=django.contrib.postgres.fields.ranges.DateTimeRangeField(),
                        ),
                        "&&",
                    ),
                ),
                name="workforce_avail_no_overlap",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_availability_downgrade,
        ),
    ]
