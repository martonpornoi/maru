"""Add immutable owner-safe Position-assignment command evidence."""

import uuid
from typing import ClassVar

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_guard_workforce_assignment()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $assignment_guard$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_department uuid;
    scoped_account uuid;
    has_decision boolean;
    has_end boolean;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce assignments cannot be deleted'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, department_id
      INTO scoped_organization, scoped_edition, scoped_department
      FROM public.workforce_position
     WHERE id = NEW.position_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id
       OR scoped_edition IS DISTINCT FROM NEW.edition_id
    THEN
        RAISE EXCEPTION 'workforce assignment position scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id = NEW.proposed_by_id
    THEN
        RAISE EXCEPTION 'workforce assignment requires independent approval'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.role_assignment_id IS NOT NULL
       AND NOT public.maru_workforce_role_evidence_matches_position(
           NEW.role_assignment_id,
           NEW.position_id,
           NEW.organization_id,
           NEW.edition_id,
           scoped_department,
           NEW.account_id
       )
    THEN
        RAISE EXCEPTION 'workforce assignment role evidence scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.participation_capacity_id IS NOT NULL THEN
        SELECT participation.organization_id,
               participation.edition_id,
               participation.account_id
          INTO scoped_organization, scoped_edition, scoped_account
          FROM public.participation_participationcapacity AS capacity
          JOIN public.participation_participation AS participation
            ON participation.id = capacity.participation_id
         WHERE capacity.id = NEW.participation_capacity_id;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR scoped_account IS DISTINCT FROM NEW.account_id
        THEN
            RAISE EXCEPTION 'workforce assignment capacity evidence scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.status = 'active' AND (
        NEW.approved_by_id IS NULL
        OR NEW.role_assignment_id IS NULL
        OR NEW.participation_capacity_id IS NULL
    ) THEN
        RAISE EXCEPTION 'active workforce assignment lacks approval evidence'
            USING ERRCODE = '23514';
    END IF;

    has_decision := NEW.decision_by_id IS NOT NULL
        AND NEW.decision_at IS NOT NULL
        AND pg_catalog.btrim(NEW.decision_reason) <> '';
    has_end := NEW.ended_by_id IS NOT NULL
        AND NEW.ended_at IS NOT NULL
        AND pg_catalog.btrim(NEW.end_reason) <> '';
    IF NEW.command_version IS NOT NULL THEN
        IF NEW.command_version < 1 THEN
            RAISE EXCEPTION 'workforce assignment command version is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'proposed' AND NOT (
            NEW.command_version = 1
            AND NEW.approved_by_id IS NULL
            AND NEW.role_assignment_id IS NULL
            AND NEW.participation_capacity_id IS NULL
            AND NEW.decision_by_id IS NULL
            AND NEW.decision_at IS NULL
            AND NEW.decision_reason = ''
            AND NEW.ended_by_id IS NULL
            AND NEW.ended_at IS NULL
            AND NEW.end_reason = ''
        ) THEN
            RAISE EXCEPTION 'governed proposal evidence is invalid'
                USING ERRCODE = '23514';
        ELSIF NEW.status = 'active' AND NOT (
            NEW.command_version >= 2
            AND has_decision
            AND NEW.decision_by_id = NEW.approved_by_id
            AND NEW.approved_by_id IS NOT NULL
            AND NEW.role_assignment_id IS NOT NULL
            AND NEW.participation_capacity_id IS NOT NULL
            AND NOT has_end
            AND NEW.ended_by_id IS NULL
            AND NEW.ended_at IS NULL
            AND NEW.end_reason = ''
        ) THEN
            RAISE EXCEPTION 'governed activation evidence is invalid'
                USING ERRCODE = '23514';
        ELSIF NEW.status = 'rejected' AND NOT (
            NEW.command_version >= 2
            AND has_decision
            AND NEW.approved_by_id IS NULL
            AND NEW.role_assignment_id IS NULL
            AND NEW.participation_capacity_id IS NULL
            AND NEW.ended_by_id IS NULL
            AND NEW.ended_at IS NULL
            AND NEW.end_reason = ''
        ) THEN
            RAISE EXCEPTION 'governed rejection evidence is invalid'
                USING ERRCODE = '23514';
        ELSIF NEW.status = 'ended' AND NOT (
            NEW.command_version >= 3
            AND has_decision
            AND NEW.decision_by_id = NEW.approved_by_id
            AND NEW.approved_by_id IS NOT NULL
            AND NEW.role_assignment_id IS NOT NULL
            AND NEW.participation_capacity_id IS NOT NULL
            AND has_end
        ) THEN
            RAISE EXCEPTION 'governed ending evidence is invalid'
                USING ERRCODE = '23514';
        ELSIF NEW.status NOT IN ('proposed', 'active', 'rejected', 'ended') THEN
            RAISE EXCEPTION 'unsupported workforce assignment state'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.status = 'rejected' THEN
        RAISE EXCEPTION 'rejected assignment lacks governed evidence'
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.position_id IS DISTINCT FROM OLD.position_id
           OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
           OR NEW.edition_id IS DISTINCT FROM OLD.edition_id
           OR NEW.account_id IS DISTINCT FROM OLD.account_id
           OR NEW.proposed_by_id IS DISTINCT FROM OLD.proposed_by_id
           OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
           OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
           OR NEW.reason IS DISTINCT FROM OLD.reason
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN
            RAISE EXCEPTION 'workforce assignment proposal identity is immutable'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.status = NEW.status THEN
            IF OLD.status IN ('active', 'rejected', 'ended')
               AND NEW IS DISTINCT FROM OLD
            THEN
                RAISE EXCEPTION 'decided workforce assignments are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.command_version IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
                RAISE EXCEPTION 'governed workforce proposals are immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.command_version IS DISTINCT FROM OLD.command_version THEN
                RAISE EXCEPTION 'assignment version requires a state transition'
                    USING ERRCODE = '23514';
            END IF;
        ELSIF NOT (
            (OLD.status = 'proposed' AND NEW.status IN ('active', 'rejected'))
            OR (OLD.status = 'active' AND NEW.status = 'ended')
        ) THEN
            RAISE EXCEPTION 'invalid workforce assignment status transition'
                USING ERRCODE = '23514';
        ELSIF NEW.command_version IS NOT NULL AND (
            (OLD.command_version IS NOT NULL
             AND NEW.command_version <> OLD.command_version + 1)
            OR (OLD.command_version IS NULL AND OLD.status = 'proposed'
                AND NEW.command_version <> 2)
            OR (OLD.command_version IS NULL AND OLD.status = 'active'
                AND NEW.command_version <> 3)
        ) THEN
            RAISE EXCEPTION 'workforce assignment command version did not advance once'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$assignment_guard$;

CREATE FUNCTION public.maru_guard_assignment_command_receipt()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $receipt_guard$
DECLARE
    assignment_organization uuid;
    assignment_edition uuid;
    assignment_position uuid;
    assignment_proposer uuid;
    assignment_decider uuid;
    assignment_ender uuid;
    assignment_status varchar;
    assignment_version bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'workforce assignment command receipts are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id,
           edition_id,
           position_id,
           proposed_by_id,
           decision_by_id,
           ended_by_id,
           status,
           command_version
      INTO assignment_organization,
           assignment_edition,
           assignment_position,
           assignment_proposer,
           assignment_decider,
           assignment_ender,
           assignment_status,
           assignment_version
      FROM public.workforce_positionassignment
     WHERE id = NEW.assignment_id
     FOR KEY SHARE;
    IF NOT FOUND
       OR assignment_organization IS DISTINCT FROM NEW.organization_id
       OR assignment_edition IS DISTINCT FROM NEW.edition_id
       OR assignment_position IS DISTINCT FROM NEW.position_id
       OR assignment_version IS DISTINCT FROM NEW.resulting_version
       OR pg_catalog.btrim(NEW.reason) = ''
       OR pg_catalog.btrim(NEW.source_channel) = ''
       OR NEW.request_digest !~ '^[0-9a-f]{64}$'
       OR NOT (
           (NEW.action = 'proposed'
            AND assignment_status = 'proposed'
            AND assignment_version = 1
            AND NEW.actor_id = assignment_proposer)
           OR (NEW.action = 'approved'
               AND assignment_status = 'active'
               AND NEW.actor_id = assignment_decider)
           OR (NEW.action = 'rejected'
               AND assignment_status = 'rejected'
               AND NEW.actor_id = assignment_decider)
           OR (NEW.action = 'ended'
               AND assignment_status = 'ended'
               AND NEW.actor_id = assignment_ender)
       )
    THEN
        RAISE EXCEPTION 'assignment receipt does not match its command state'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$receipt_guard$;

CREATE TRIGGER workforce_assignment_command_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.workforce_positionassignmentcommandreceipt
FOR EACH ROW EXECUTE FUNCTION public.maru_guard_assignment_command_receipt();

REVOKE ALL ON FUNCTION public.maru_guard_assignment_command_receipt()
FROM PUBLIC;

CREATE FUNCTION public.maru_assert_assignment_command_evidence()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $assignment_evidence$
DECLARE
    expected_action varchar;
    matching_receipts bigint;
BEGIN
    IF NEW.command_version IS NULL THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'INSERT' THEN
        expected_action := 'proposed';
    ELSIF OLD.status = 'proposed' AND NEW.status = 'active' THEN
        expected_action := 'approved';
    ELSIF OLD.status = 'proposed' AND NEW.status = 'rejected' THEN
        expected_action := 'rejected';
    ELSIF OLD.status = 'active' AND NEW.status = 'ended' THEN
        expected_action := 'ended';
    ELSE
        RETURN NULL;
    END IF;
    SELECT COUNT(*) INTO matching_receipts
      FROM public.workforce_positionassignmentcommandreceipt AS receipt
     WHERE receipt.assignment_id = NEW.id
       AND receipt.organization_id = NEW.organization_id
       AND receipt.edition_id = NEW.edition_id
       AND receipt.position_id = NEW.position_id
       AND receipt.resulting_version = NEW.command_version
       AND receipt.action = expected_action;
    IF matching_receipts <> 1 THEN
        RAISE EXCEPTION 'assignment mutation lacks exact immutable command evidence'
            USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$assignment_evidence$;

CREATE CONSTRAINT TRIGGER workforce_assignment_command_evidence
AFTER INSERT OR UPDATE
ON public.workforce_positionassignment
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION public.maru_assert_assignment_command_evidence();

REVOKE ALL ON FUNCTION public.maru_assert_assignment_command_evidence()
FROM PUBLIC;
"""


REVERSE_SQL = r"""
DO $assignment_reverse_fence$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.workforce_positionassignmentcommandreceipt
    ) THEN
        RAISE EXCEPTION
            'Cannot reverse governed assignment commands; use a fix-forward recovery';
    END IF;
END;
$assignment_reverse_fence$;

DROP TRIGGER IF EXISTS workforce_assignment_command_evidence
ON public.workforce_positionassignment;
DROP FUNCTION IF EXISTS public.maru_assert_assignment_command_evidence();
DROP TRIGGER IF EXISTS workforce_assignment_command_receipt_guard
ON public.workforce_positionassignmentcommandreceipt;
DROP FUNCTION IF EXISTS public.maru_guard_assignment_command_receipt();

CREATE OR REPLACE FUNCTION public.maru_guard_workforce_assignment()
RETURNS trigger
LANGUAGE plpgsql
VOLATILE
CALLED ON NULL INPUT
SECURITY INVOKER
PARALLEL UNSAFE
SET search_path = pg_catalog, public, pg_temp
AS $assignment_guard$
DECLARE
    scoped_organization uuid;
    scoped_edition uuid;
    scoped_department uuid;
    scoped_account uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'workforce assignments cannot be deleted'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, department_id
      INTO scoped_organization, scoped_edition, scoped_department
      FROM public.workforce_position
     WHERE id = NEW.position_id
     FOR KEY SHARE;
    IF scoped_organization IS DISTINCT FROM NEW.organization_id
       OR scoped_edition IS DISTINCT FROM NEW.edition_id
    THEN
        RAISE EXCEPTION 'workforce assignment position scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.approved_by_id IS NOT NULL
       AND NEW.approved_by_id = NEW.proposed_by_id
    THEN
        RAISE EXCEPTION 'workforce assignment requires independent approval'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.role_assignment_id IS NOT NULL
       AND NOT public.maru_workforce_role_evidence_matches_position(
           NEW.role_assignment_id,
           NEW.position_id,
           NEW.organization_id,
           NEW.edition_id,
           scoped_department,
           NEW.account_id
       )
    THEN
        RAISE EXCEPTION 'workforce assignment role evidence scope mismatch'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.participation_capacity_id IS NOT NULL THEN
        SELECT participation.organization_id,
               participation.edition_id,
               participation.account_id
          INTO scoped_organization, scoped_edition, scoped_account
          FROM public.participation_participationcapacity AS capacity
          JOIN public.participation_participation AS participation
            ON participation.id = capacity.participation_id
         WHERE capacity.id = NEW.participation_capacity_id;
        IF scoped_organization IS DISTINCT FROM NEW.organization_id
           OR scoped_edition IS DISTINCT FROM NEW.edition_id
           OR scoped_account IS DISTINCT FROM NEW.account_id
        THEN
            RAISE EXCEPTION 'workforce assignment capacity evidence scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.status = 'active' AND (
        NEW.approved_by_id IS NULL
        OR NEW.role_assignment_id IS NULL
        OR NEW.participation_capacity_id IS NULL
    ) THEN
        RAISE EXCEPTION 'active workforce assignment lacks approval evidence'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'active' AND NEW.status = 'active'
           AND NEW IS DISTINCT FROM OLD
        THEN
            RAISE EXCEPTION 'active workforce assignments are immutable'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.status <> NEW.status AND NOT (
            (OLD.status = 'proposed' AND NEW.status = 'active')
            OR (OLD.status = 'active' AND NEW.status = 'ended')
        ) THEN
            RAISE EXCEPTION 'invalid workforce assignment status transition'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$assignment_guard$;
"""


class Migration(migrations.Migration):
    """Install assignment command state, receipts, and database guards."""

    dependencies: ClassVar[list[object]] = [
        ("authorization", "0016_logistics_capabilities_and_resource_kind"),
        ("events", "0009_edition_workspace_downgrade_fence"),
        ("organizations", "0013_runtime_executable_function_hardening"),
        ("participation", "0004_idn011_convention_subject_guards"),
        ("workforce", "0010_position_structure_commands"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="PositionAssignmentCommandReceipt",
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
                            ("proposed", "Assignment proposed"),
                            ("approved", "Assignment approved"),
                            ("rejected", "Assignment rejected"),
                            ("ended", "Assignment ended"),
                        ],
                        max_length=16,
                    ),
                ),
                ("resulting_version", models.PositiveBigIntegerField()),
                ("reason", models.CharField(max_length=240)),
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
            ],
            options={
                "ordering": ("assignment_id", "resulting_version", "id"),
            },
        ),
        migrations.AddField(
            model_name="positionassignment",
            name="command_version",
            field=models.PositiveBigIntegerField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="positionassignment",
            name="decision_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="positionassignment",
            name="decision_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workforce_assignments_decided",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="positionassignment",
            name="decision_reason",
            field=models.CharField(blank=True, editable=False, max_length=240),
        ),
        migrations.AddField(
            model_name="positionassignment",
            name="end_reason",
            field=models.CharField(blank=True, editable=False, max_length=240),
        ),
        migrations.AddField(
            model_name="positionassignment",
            name="ended_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workforce_assignments_ended",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="positionassignment",
            name="status",
            field=models.CharField(
                choices=[
                    ("proposed", "Proposed"),
                    ("active", "Active"),
                    ("rejected", "Rejected"),
                    ("ended", "Ended"),
                ],
                default="proposed",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="positionassignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("command_version__isnull", True),
                    ("command_version__gt", 0),
                    _connector="OR",
                ),
                name="workforce_assignment_command_version_positive",
            ),
        ),
        migrations.AddField(
            model_name="positionassignmentcommandreceipt",
            name="actor",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workforce_assignment_commands_acted",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="positionassignmentcommandreceipt",
            name="assignment",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="command_receipts",
                to="workforce.positionassignment",
            ),
        ),
        migrations.AddField(
            model_name="positionassignmentcommandreceipt",
            name="edition",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workforce_assignment_command_receipts",
                to="events.eventedition",
            ),
        ),
        migrations.AddField(
            model_name="positionassignmentcommandreceipt",
            name="organization",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="workforce_assignment_command_receipts",
                to="organizations.organization",
            ),
        ),
        migrations.AddField(
            model_name="positionassignmentcommandreceipt",
            name="position",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assignment_command_receipts",
                to="workforce.position",
            ),
        ),
        migrations.AddIndex(
            model_name="positionassignmentcommandreceipt",
            index=models.Index(
                fields=["organization", "edition", "action", "created_at"],
                name="wrk_assignment_action_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="positionassignmentcommandreceipt",
            index=models.Index(
                fields=["position", "created_at"], name="wrk_assignment_pos_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="positionassignmentcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("assignment", "resulting_version"),
                name="workforce_assignment_receipt_version_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="positionassignmentcommandreceipt",
            constraint=models.UniqueConstraint(
                fields=("edition", "actor", "retry_key"),
                name="workforce_assignment_retry_key_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="positionassignmentcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(("resulting_version__gt", 0)),
                name="workforce_assignment_receipt_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="positionassignmentcommandreceipt",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("reason", ""), _negated=True),
                    models.Q(("source_channel", ""), _negated=True),
                ),
                name="workforce_assignment_receipt_evidence_nonblank",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
