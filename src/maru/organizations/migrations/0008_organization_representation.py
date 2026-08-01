import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


FORWARD_SQL = """
CREATE FUNCTION maru_validate_organization_representation()
RETURNS trigger AS $$
DECLARE
    organization_lifecycle varchar;
    provisioner_account_kind varchar;
    activator_account_kind varchar;
    active_controller_count integer;
BEGIN
    SELECT lifecycle INTO organization_lifecycle
      FROM organizations_organization
     WHERE id = NEW.organization_id;

    IF TG_OP = 'INSERT' THEN
        SELECT account.account_kind INTO provisioner_account_kind
          FROM identity_account AS account
         WHERE account.id = NEW.provisioned_by_id;
        IF provisioner_account_kind IS DISTINCT FROM 'platform_administrator'
           OR organization_lifecycle IS DISTINCT FROM 'draft'
        THEN
            RAISE EXCEPTION 'invalid initial organization representation'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.provisioned_by_id IS DISTINCT FROM OLD.provisioned_by_id THEN
        SELECT account.account_kind INTO provisioner_account_kind
          FROM identity_account AS account
         WHERE account.id = NEW.provisioned_by_id;
        IF provisioner_account_kind IS DISTINCT FROM 'platform_administrator' THEN
            RAISE EXCEPTION 'invalid organization representation provisioner'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.activated_by_id IS NOT NULL
       AND (
           TG_OP = 'INSERT'
           OR NEW.activated_by_id IS DISTINCT FROM OLD.activated_by_id
           OR NEW.state IS DISTINCT FROM OLD.state
       )
    THEN
        SELECT account.account_kind INTO activator_account_kind
          FROM identity_account AS account
         WHERE account.id = NEW.activated_by_id;
        IF activator_account_kind IS DISTINCT FROM 'platform_administrator' THEN
            RAISE EXCEPTION 'invalid organization representation activator'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.state = 'active'
       AND (TG_OP = 'INSERT' OR NEW.state IS DISTINCT FROM OLD.state)
    THEN
        SELECT COUNT(*) INTO active_controller_count
          FROM organizations_representationappointment
         WHERE representation_id = NEW.id
           AND state = 'active';
        IF organization_lifecycle IS DISTINCT FROM 'draft'
           OR active_controller_count < 2
        THEN
            RAISE EXCEPTION 'organization representation activation invariant failed'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF organization_lifecycle = 'active' AND NEW.state <> 'active' THEN
        RAISE EXCEPTION 'active organization requires active representation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_representation_guard
BEFORE INSERT OR UPDATE
ON organizations_organizationrepresentation
FOR EACH ROW EXECUTE FUNCTION maru_validate_organization_representation();

CREATE FUNCTION maru_validate_representation_appointment()
RETURNS trigger AS $$
DECLARE
    subject_account_kind varchar;
    representation_organization uuid;
    assignment_organization uuid;
    assignment_principal uuid;
    assignment_edition uuid;
    assignment_role_code varchar;
BEGIN
    SELECT account.account_kind INTO subject_account_kind
      FROM identity_account AS account
     WHERE account.id = NEW.account_id;
    IF subject_account_kind IS DISTINCT FROM 'person' THEN
        RAISE EXCEPTION 'platform accounts cannot hold representation appointments'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.role_assignment_id IS NOT NULL THEN
        SELECT organization_id INTO representation_organization
          FROM organizations_organizationrepresentation
         WHERE id = NEW.representation_id;
        SELECT assignment.organization_id,
               assignment.principal_id,
               assignment.edition_id,
               bundle.code
          INTO assignment_organization,
               assignment_principal,
               assignment_edition,
               assignment_role_code
          FROM authorization_roleassignment AS assignment
          JOIN authorization_rolebundle AS bundle
            ON bundle.id = assignment.role_bundle_id
         WHERE assignment.id = NEW.role_assignment_id;
        IF assignment_organization IS NULL
           OR assignment_organization IS DISTINCT FROM representation_organization
           OR assignment_principal IS DISTINCT FROM NEW.account_id
           OR assignment_edition IS NOT NULL
           OR assignment_role_code IS DISTINCT FROM 'executive-board'
        THEN
            RAISE EXCEPTION 'representation authority assignment scope mismatch'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_representation_appointment_guard
BEFORE INSERT OR UPDATE
ON organizations_representationappointment
FOR EACH ROW EXECUTE FUNCTION maru_validate_representation_appointment();

CREATE FUNCTION maru_validate_organization_activation()
RETURNS trigger AS $$
DECLARE
    representation_state varchar;
    active_controller_count integer;
BEGIN
    IF NEW.lifecycle = 'active' AND OLD.lifecycle IS DISTINCT FROM 'active' THEN
        SELECT state INTO representation_state
          FROM organizations_organizationrepresentation
         WHERE organization_id = NEW.id;
        SELECT COUNT(*) INTO active_controller_count
          FROM organizations_representationappointment AS appointment
          JOIN organizations_organizationrepresentation AS representation
            ON representation.id = appointment.representation_id
         WHERE representation.organization_id = NEW.id
           AND appointment.state = 'active';
        IF representation_state IS DISTINCT FROM 'active'
           OR active_controller_count < 2
        THEN
            RAISE EXCEPTION 'organization activation requires active representation'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER organizations_activation_guard
BEFORE UPDATE OF lifecycle
ON organizations_organization
FOR EACH ROW EXECUTE FUNCTION maru_validate_organization_activation();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS organizations_activation_guard
ON organizations_organization;
DROP FUNCTION IF EXISTS maru_validate_organization_activation();
DROP TRIGGER IF EXISTS organizations_representation_appointment_guard
ON organizations_representationappointment;
DROP FUNCTION IF EXISTS maru_validate_representation_appointment();
DROP TRIGGER IF EXISTS organizations_representation_guard
ON organizations_organizationrepresentation;
DROP FUNCTION IF EXISTS maru_validate_organization_representation();
"""


def refuse_populated_representation_downgrade(apps, schema_editor):
    del schema_editor
    representation = apps.get_model("organizations", "OrganizationRepresentation")
    appointment = apps.get_model("organizations", "RepresentationAppointment")
    if representation.objects.exists() or appointment.objects.exists():
        raise RuntimeError(
            "Cannot reverse organization representation while governance records "
            "exist. Keep compatible code and fix forward, or use an explicitly "
            "approved backup/PITR recovery plan."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("authorization", "0003_capabilitygrant_approved_by_and_more"),
        ("organizations", "0007_convention_series_downgrade_fence"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationRepresentation",
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
                    "code",
                    models.CharField(
                        default="executive_board",
                        editable=False,
                        max_length=40,
                    ),
                ),
                (
                    "name",
                    models.CharField(default="Executive Board", max_length=120),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("provisioning", "Provisioning"),
                            ("active", "Active"),
                            ("suspended", "Suspended"),
                        ],
                        default="provisioning",
                        max_length=20,
                    ),
                ),
                (
                    "aggregate_version",
                    models.PositiveIntegerField(default=1, editable=False),
                ),
                ("provisioning_reason", models.CharField(max_length=240)),
                (
                    "activation_reason",
                    models.CharField(blank=True, max_length=240),
                ),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "activated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="organization_representations_activated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="representation",
                        to="organizations.organization",
                    ),
                ),
                (
                    "provisioned_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="organization_representations_provisioned",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("organization__name", "id")},
        ),
        migrations.CreateModel(
            name="RepresentationAppointment",
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
                    "role",
                    models.CharField(
                        choices=[("controller", "Controller")],
                        default="controller",
                        max_length=20,
                    ),
                ),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("invited", "Invited"),
                            ("accepted", "Accepted"),
                            ("active", "Active"),
                            ("declined", "Declined"),
                            ("ended", "Ended"),
                        ],
                        default="invited",
                        max_length=20,
                    ),
                ),
                (
                    "invitation_version",
                    models.PositiveIntegerField(default=1, editable=False),
                ),
                ("invited_at", models.DateTimeField()),
                ("responded_at", models.DateTimeField(blank=True, null=True)),
                ("activated_at", models.DateTimeField(blank=True, null=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("reason", models.CharField(max_length=240)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="representation_appointments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "invited_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="representation_appointments_invited",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "representation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="appointments",
                        to="organizations.organizationrepresentation",
                    ),
                ),
                (
                    "role_assignment",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="representation_appointment",
                        to="authorization.roleassignment",
                    ),
                ),
            ],
            options={"ordering": ("representation_id", "invited_at", "id")},
        ),
        migrations.AddConstraint(
            model_name="organizationrepresentation",
            constraint=models.CheckConstraint(
                condition=models.Q(code="executive_board"),
                name="organization_representation_exec_board_code",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationrepresentation",
            constraint=models.CheckConstraint(
                condition=models.Q(name="Executive Board"),
                name="organization_representation_exec_board_name",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationrepresentation",
            constraint=models.CheckConstraint(
                condition=models.Q(aggregate_version__gte=1),
                name="organization_representation_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationrepresentation",
            constraint=models.CheckConstraint(
                condition=~models.Q(provisioning_reason=""),
                name="organization_representation_reason_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationrepresentation",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        state="provisioning",
                        activated_at__isnull=True,
                        activated_by__isnull=True,
                        activation_reason="",
                    )
                    | (
                        models.Q(
                            state__in=("active", "suspended"),
                            activated_at__isnull=False,
                            activated_by__isnull=False,
                        )
                        & ~models.Q(activation_reason="")
                    )
                ),
                name="organization_representation_activation_state",
            ),
        ),
        migrations.AddConstraint(
            model_name="representationappointment",
            constraint=models.UniqueConstraint(
                condition=models.Q(state__in=("invited", "accepted", "active")),
                fields=("representation", "account"),
                name="one_open_representation_appointment_per_account",
            ),
        ),
        migrations.AddConstraint(
            model_name="representationappointment",
            constraint=models.CheckConstraint(
                condition=models.Q(role="controller"),
                name="representation_appointment_controller_role",
            ),
        ),
        migrations.AddConstraint(
            model_name="representationappointment",
            constraint=models.CheckConstraint(
                condition=models.Q(invitation_version__gte=1),
                name="representation_appointment_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="representationappointment",
            constraint=models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="representation_appointment_reason_required",
            ),
        ),
        migrations.AddConstraint(
            model_name="representationappointment",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        state="invited",
                        responded_at__isnull=True,
                        activated_at__isnull=True,
                        ended_at__isnull=True,
                        role_assignment__isnull=True,
                    )
                    | models.Q(
                        state="accepted",
                        responded_at__isnull=False,
                        activated_at__isnull=True,
                        ended_at__isnull=True,
                        role_assignment__isnull=True,
                    )
                    | models.Q(
                        state="active",
                        responded_at__isnull=False,
                        activated_at__isnull=False,
                        ended_at__isnull=True,
                        role_assignment__isnull=False,
                    )
                    | models.Q(
                        state="declined",
                        responded_at__isnull=False,
                        activated_at__isnull=True,
                        ended_at__isnull=False,
                        role_assignment__isnull=True,
                    )
                    | (
                        models.Q(
                            state="ended",
                            responded_at__isnull=False,
                            ended_at__isnull=False,
                        )
                        & (
                            models.Q(
                                activated_at__isnull=True,
                                role_assignment__isnull=True,
                            )
                            | models.Q(
                                activated_at__isnull=False,
                                role_assignment__isnull=False,
                            )
                        )
                    )
                ),
                name="representation_appointment_state_timestamps",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_populated_representation_downgrade,
        ),
    ]
