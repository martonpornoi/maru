"""Add immutable edition adoption profiles and guided Workforce receipts."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_edition_aggregate_version()
RETURNS trigger AS $$
DECLARE
    profile_changed boolean;
    lifecycle_changed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 THEN
            RAISE EXCEPTION 'new editions must start at aggregate version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.series_id IS DISTINCT FROM OLD.series_id
       OR NEW.slug IS DISTINCT FROM OLD.slug
       OR NEW.adoption_profile_code IS DISTINCT FROM OLD.adoption_profile_code
       OR NEW.adoption_profile_version IS DISTINCT FROM OLD.adoption_profile_version
    THEN
        RAISE EXCEPTION 'edition ownership and stable slug are immutable; adoption profile is immutable'
            USING ERRCODE = '23514';
    END IF;

    profile_changed :=
        NEW.name IS DISTINCT FROM OLD.name
        OR NEW.time_zone IS DISTINCT FROM OLD.time_zone
        OR NEW.language_codes IS DISTINCT FROM OLD.language_codes
        OR NEW.currency_codes IS DISTINCT FROM OLD.currency_codes
        OR NEW.starts_on IS DISTINCT FROM OLD.starts_on
        OR NEW.ends_on IS DISTINCT FROM OLD.ends_on;
    lifecycle_changed :=
        NEW.lifecycle IS DISTINCT FROM OLD.lifecycle
        OR NEW.lifecycle_version IS DISTINCT FROM OLD.lifecycle_version;

    IF profile_changed AND lifecycle_changed THEN
        RAISE EXCEPTION 'edition profile and lifecycle require separate commands'
            USING ERRCODE = '23514';
    END IF;
    IF profile_changed AND OLD.lifecycle NOT IN ('draft', 'preparing') THEN
        RAISE EXCEPTION 'edition profile is read-only in this lifecycle'
            USING ERRCODE = '23514';
    END IF;
    IF profile_changed OR lifecycle_changed THEN
        IF NEW.aggregate_version != OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'edition change must increment aggregate version'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.aggregate_version != OLD.aggregate_version THEN
        RAISE EXCEPTION 'aggregate version changes only with edition facts'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE FUNCTION public.maru_validate_workforce_adoption_setup_receipt()
RETURNS trigger AS $$
BEGIN
    IF TG_OP != 'INSERT' THEN
        RAISE EXCEPTION 'Workforce adoption setup receipts are append-only'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.request_digest !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'Workforce setup digest must be lowercase SHA-256'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.events_eventedition AS edition
         WHERE edition.id = NEW.edition_id
           AND edition.organization_id = NEW.organization_id
           AND edition.series_id = NEW.series_id
           AND edition.adoption_profile_code = 'workforce_only'
           AND edition.adoption_profile_version = 1
    ) THEN
        RAISE EXCEPTION 'Workforce setup receipt scope or profile does not match'
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM public.organizations_organizationrepresentation AS representation
         WHERE representation.organization_id = NEW.organization_id
           AND representation.code = NEW.representation_code
    ) THEN
        RAISE EXCEPTION 'Workforce setup representation does not match'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_workforce_adoption_setup_receipt_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.events_workforceadoptionsetupreceipt
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_workforce_adoption_setup_receipt();

CREATE FUNCTION public.maru_refuse_workforce_adoption_setup_receipt_truncate()
RETURNS trigger AS $$
BEGIN
    IF public.maru_authority_provenance_test_reset_allowed() THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'Workforce adoption setup receipts cannot be truncated'
        USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;

CREATE TRIGGER events_workforce_adoption_setup_receipt_truncate_guard
BEFORE TRUNCATE
ON public.events_workforceadoptionsetupreceipt
FOR EACH STATEMENT
EXECUTE FUNCTION public.maru_refuse_workforce_adoption_setup_receipt_truncate();
"""


REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS events_workforce_adoption_setup_receipt_truncate_guard
    ON public.events_workforceadoptionsetupreceipt;
DROP FUNCTION IF EXISTS
    public.maru_refuse_workforce_adoption_setup_receipt_truncate();
DROP TRIGGER IF EXISTS events_workforce_adoption_setup_receipt_guard
    ON public.events_workforceadoptionsetupreceipt;
DROP FUNCTION IF EXISTS public.maru_validate_workforce_adoption_setup_receipt();

CREATE OR REPLACE FUNCTION public.maru_validate_edition_aggregate_version()
RETURNS trigger AS $$
DECLARE
    profile_changed boolean;
    lifecycle_changed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.aggregate_version != 1 THEN
            RAISE EXCEPTION 'new editions must start at aggregate version one'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
       OR NEW.series_id IS DISTINCT FROM OLD.series_id
       OR NEW.slug IS DISTINCT FROM OLD.slug
    THEN
        RAISE EXCEPTION 'edition ownership and stable slug are immutable'
            USING ERRCODE = '23514';
    END IF;
    profile_changed :=
        NEW.name IS DISTINCT FROM OLD.name
        OR NEW.time_zone IS DISTINCT FROM OLD.time_zone
        OR NEW.language_codes IS DISTINCT FROM OLD.language_codes
        OR NEW.currency_codes IS DISTINCT FROM OLD.currency_codes
        OR NEW.starts_on IS DISTINCT FROM OLD.starts_on
        OR NEW.ends_on IS DISTINCT FROM OLD.ends_on;
    lifecycle_changed :=
        NEW.lifecycle IS DISTINCT FROM OLD.lifecycle
        OR NEW.lifecycle_version IS DISTINCT FROM OLD.lifecycle_version;
    IF profile_changed AND lifecycle_changed THEN
        RAISE EXCEPTION 'edition profile and lifecycle require separate commands'
            USING ERRCODE = '23514';
    END IF;
    IF profile_changed AND OLD.lifecycle NOT IN ('draft', 'preparing') THEN
        RAISE EXCEPTION 'edition profile is read-only in this lifecycle'
            USING ERRCODE = '23514';
    END IF;
    IF profile_changed OR lifecycle_changed THEN
        IF NEW.aggregate_version != OLD.aggregate_version + 1 THEN
            RAISE EXCEPTION 'edition change must increment aggregate version'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.aggregate_version != OLD.aggregate_version THEN
        RAISE EXCEPTION 'aggregate version changes only with edition facts'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
"""


def refuse_adopted_profile_downgrade(apps: Any, schema_editor: Any) -> None:
    """Refuse removing a profile contract after it has durable evidence."""
    del schema_editor
    edition = apps.get_model("events", "EventEdition")
    receipt = apps.get_model("events", "WorkforceAdoptionSetupReceipt")
    if (
        edition.objects.filter(adoption_profile_code="workforce_only").exists()
        or receipt.objects.exists()
    ):
        raise RuntimeError(
            "Cannot remove Workforce adoption profiles after an edition or setup "
            "receipt uses them; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Install the versioned edition-adoption boundary and receipt evidence."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0007_authority_provenance_activation_guards"),
        ("events", "0009_edition_workspace_downgrade_fence"),
        ("organizations", "0013_runtime_executable_function_hardening"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.CreateModel(
            name="WorkforceAdoptionSetupReceipt",
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
                ("series_id", models.UUIDField()),
                ("actor_id", models.UUIDField()),
                ("idempotency_key", models.UUIDField()),
                (
                    "request_digest",
                    models.CharField(
                        max_length=64,
                        validators=[
                            django.core.validators.RegexValidator(
                                code="invalid_workforce_adoption_setup_digest",
                                message="Use a lowercase SHA-256 digest.",
                                regex="^[0-9a-f]{64}$",
                            )
                        ],
                    ),
                ),
                (
                    "mode",
                    models.CharField(
                        choices=[
                            (
                                "new_foundation",
                                "Create organization, series, and edition",
                            ),
                            (
                                "existing_organization",
                                "Add a series and edition to an organization",
                            ),
                            ("existing_series", "Add an edition to a series"),
                        ],
                        max_length=40,
                    ),
                ),
                ("representation_code", models.CharField(max_length=40)),
                ("created_organization", models.BooleanField()),
                ("created_series", models.BooleanField()),
                ("created_edition", models.BooleanField()),
                (
                    "edition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="workforce_adoption_setup_receipts",
                        to="events.eventedition",
                    ),
                ),
            ],
            options={"ordering": ("created_at", "id")},
        ),
        migrations.AddField(
            model_name="eventedition",
            name="adoption_profile_code",
            field=models.CharField(
                choices=[
                    ("full_convention", "Full convention"),
                    ("workforce_only", "Workforce only"),
                ],
                db_default="full_convention",
                default="full_convention",
                editable=False,
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="eventedition",
            name="adoption_profile_version",
            field=models.PositiveIntegerField(
                db_default=1,
                default=1,
                editable=False,
            ),
        ),
        migrations.AddConstraint(
            model_name="eventedition",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        adoption_profile_code="full_convention",
                        adoption_profile_version=1,
                    )
                    | models.Q(
                        adoption_profile_code="workforce_only",
                        adoption_profile_version=1,
                    )
                ),
                name="edition_adoption_profile_supported",
            ),
        ),
        migrations.AddConstraint(
            model_name="workforceadoptionsetupreceipt",
            constraint=models.UniqueConstraint(
                fields=("actor_id", "idempotency_key"),
                name="workforce_setup_actor_idempotency_unique",
            ),
        ),
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_adopted_profile_downgrade,
        ),
    ]
