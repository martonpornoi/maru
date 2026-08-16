from collections.abc import Sequence
from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models
from django.db.migrations.operations.base import Operation
from django.db.models import Q

FORWARD_BACKFILL_SQL = """
ALTER TABLE public.registration_registrationprofileextensionfield
DISABLE TRIGGER registration_profile_extension_field_guard;

UPDATE registration_registrationprofileextensionfield
   SET audience_policy = CASE
       WHEN attendee_visible THEN 'self'
       ELSE 'registration_staff'
   END
 WHERE audience_policy IS NULL;

ALTER TABLE public.registration_registrationprofileextensionfield
ENABLE TRIGGER registration_profile_extension_field_guard;
"""


REVERSE_BACKFILL_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
         FROM registration_registrationprofileextensionfield
         WHERE audience_policy NOT IN ('self', 'registration_staff')
    ) THEN
        RAISE EXCEPTION
            'cannot reverse populated profile audience policies'
            USING ERRCODE = '55000';
    END IF;
END;
$$;
"""


FORWARD_AUDIENCE_GUARD_SQL = """
CREATE OR REPLACE FUNCTION public.maru_guard_registration_profile_audience_v1()
RETURNS trigger AS $$
DECLARE
    department_organization uuid;
    department_edition uuid;
    department_retired timestamptz;
    owner_visible boolean;
BEGIN
    owner_visible := NEW.audience_policy IN (
        'self', 'confirmed_attendees', 'public'
    );
    IF NEW.audience_policy NOT IN (
        'self',
        'registration_staff',
        'department',
        'confirmed_attendees',
        'public'
    ) OR NEW.attendee_visible IS DISTINCT FROM owner_visible
    THEN
        RAISE EXCEPTION 'invalid profile extension audience policy'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.audience_policy = 'department' THEN
        SELECT organization_id, edition_id, retired_at
          INTO department_organization, department_edition, department_retired
          FROM workforce_department
         WHERE id = NEW.audience_department_id;
        IF department_organization IS NULL
           OR department_organization != NEW.organization_id
           OR department_edition != NEW.edition_id
           OR department_retired IS NOT NULL
        THEN
            RAISE EXCEPTION 'profile extension audience department mismatch'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.audience_department_id IS NOT NULL THEN
        RAISE EXCEPTION 'profile extension audience department is unexpected'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.writer_policy IN ('attendee', 'attendee_and_staff')
       AND NOT owner_visible
    THEN
        RAISE EXCEPTION 'attendee writer requires an owner-visible audience'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

DROP TRIGGER IF EXISTS registration_profile_audience_guard
ON public.registration_registrationprofileextensionfield;
CREATE TRIGGER registration_profile_audience_guard
BEFORE INSERT OR UPDATE
ON public.registration_registrationprofileextensionfield
FOR EACH ROW
EXECUTE FUNCTION public.maru_guard_registration_profile_audience_v1();
"""


REVERSE_AUDIENCE_GUARD_SQL = """
DROP TRIGGER IF EXISTS registration_profile_audience_guard
ON public.registration_registrationprofileextensionfield;
DROP FUNCTION IF EXISTS public.maru_guard_registration_profile_audience_v1();
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("registration", "0038_governed_registration_commerce"),
        ("workforce", "0007_structure_write_integrity"),
    ]

    operations: ClassVar[Sequence[Operation]] = [
        migrations.AlterField(
            model_name="registrationconfiguration",
            name="origin",
            field=models.CharField(
                choices=[
                    ("legacy_existing", "Legacy existing"),
                    ("blank", "Blank"),
                    ("platform_starter", "Platform starter"),
                    ("published_template", "Published template"),
                    ("prior_edition", "Prior edition"),
                    ("successor", "Successor"),
                ],
                default="legacy_existing",
                editable=False,
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="registrationsetupcontrol",
            name="origin",
            field=models.CharField(
                choices=[
                    ("legacy_existing", "Legacy existing"),
                    ("blank", "Blank"),
                    ("platform_starter", "Platform starter"),
                    ("published_template", "Published template"),
                    ("prior_edition", "Prior edition"),
                    ("successor", "Successor"),
                ],
                max_length=24,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="registrationconfiguration",
            name="reg_configuration_complete_provenance_shape",
        ),
        migrations.AddConstraint(
            model_name="registrationconfiguration",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(provenance_status="complete")
                    | (
                        Q(content_digest__regex=r"^[0-9a-f]{64}$")
                        & Q(created_in_setup_version__isnull=False)
                        & Q(last_changed_in_setup_version__isnull=False)
                        & (
                            Q(
                                origin="blank",
                                source_template__isnull=True,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=True,
                                source_content_digest="",
                                source_imported_at__isnull=True,
                                source_imported_by__isnull=True,
                            )
                            | Q(
                                origin="published_template",
                                source_template__isnull=False,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                            | Q(
                                origin="platform_starter",
                                source_template__isnull=True,
                                source_edition__isnull=True,
                                source_configuration__isnull=True,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                            | Q(
                                origin__in=("prior_edition", "successor"),
                                source_template__isnull=True,
                                source_edition__isnull=False,
                                source_configuration__isnull=False,
                                source_version__isnull=False,
                                source_content_digest__regex=r"^[0-9a-f]{64}$",
                                source_imported_at__isnull=False,
                                source_imported_by__isnull=False,
                            )
                        )
                    )
                ),
                name="reg_configuration_complete_provenance_shape",
            ),
        ),
        migrations.AddField(
            model_name="registrationprofileextensionfield",
            name="audience_policy",
            field=models.CharField(
                blank=True,
                choices=[
                    ("self", "Registration owner"),
                    ("registration_staff", "Exact registration staff"),
                    ("department", "Exact department or team"),
                    ("confirmed_attendees", "All confirmed attendees"),
                    ("public", "Public attendee directory"),
                ],
                max_length=24,
                null=True,
            ),
        ),
        migrations.RunSQL(
            FORWARD_BACKFILL_SQL,
            reverse_sql=REVERSE_BACKFILL_SQL,
        ),
        migrations.AlterField(
            model_name="registrationprofileextensionfield",
            name="audience_policy",
            field=models.CharField(
                choices=[
                    ("self", "Registration owner"),
                    ("registration_staff", "Exact registration staff"),
                    ("department", "Exact department or team"),
                    ("confirmed_attendees", "All confirmed attendees"),
                    ("public", "Public attendee directory"),
                ],
                default="self",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="registrationprofileextensionfield",
            name="audience_department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="registration_profile_extension_audiences",
                to="workforce.department",
            ),
        ),
        migrations.AddConstraint(
            model_name="registrationprofileextensionfield",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        audience_policy="department",
                        audience_department__isnull=False,
                    )
                    | (
                        ~Q(audience_policy="department")
                        & Q(audience_department__isnull=True)
                    )
                ),
                name="reg_profile_audience_department_shape",
            ),
        ),
        migrations.AddConstraint(
            model_name="registrationprofileextensionfield",
            constraint=models.CheckConstraint(
                condition=(
                    Q(
                        audience_policy__in=(
                            "self",
                            "confirmed_attendees",
                            "public",
                        ),
                        attendee_visible=True,
                    )
                    | Q(
                        audience_policy__in=("registration_staff", "department"),
                        attendee_visible=False,
                    )
                ),
                name="reg_profile_audience_legacy_visibility",
            ),
        ),
        migrations.AddIndex(
            model_name="registrationprofileextensionfield",
            index=models.Index(
                fields=["organization", "edition", "audience_policy", "position"],
                name="reg_profile_audience_idx",
            ),
        ),
        migrations.RunSQL(
            FORWARD_AUDIENCE_GUARD_SQL,
            reverse_sql=REVERSE_AUDIENCE_GUARD_SQL,
        ),
    ]
