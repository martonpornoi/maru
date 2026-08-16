"""Add Logistics authority and the exact manifest resource kind."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations, models

ORGANIZATION_CAPABILITIES = (
    "organizations.view_basic",
    "organizations.change_profile",
    "organizations.create_series",
    "organizations.change_series",
    "organizations.manage_representation",
    "events.view_basic",
    "events.create",
    "authorization.delegate",
    "authorization.grant_direct",
    "authorization.revoke",
    "authorization.manage_roles",
    "effects.replay",
    "privacy.manage_requests",
    "audit.view_security",
    "charities.view_partners",
    "charities.manage_partners",
    "venues.view_properties",
    "venues.manage_properties",
    "venues.manage_accommodation",
)
EDITION_CAPABILITIES = (
    "events.change_profile",
    "events.transition",
    "participation.view_staff_summary",
    "identity.manage_restrictions",
    "registration.manage_configuration",
    "registration.view_profile_extensions",
    "registration.update_profile_extensions",
    "registration.view_service_summary",
    "registration.view_attendee_reporting",
    "registration.view_payment_summary",
    "registration.manage_exceptions",
    "registration.register_on_behalf",
    "registration.manage_finance",
    "registration.check_in",
    "accreditation.issue",
    "accreditation.revoke",
    "accreditation.manage_offline",
    "registration.moderate_public_profile",
    "workforce.view_structure",
    "workforce.manage_structure",
    "workforce.manage_applications",
    "workforce.manage_documents",
    "workforce.manage_assignments",
    "applications.manage_definitions",
    "applications.review",
    "applications.review_sensitive",
    "charities.view_review_queue",
    "charities.propose_selection",
    "venues.view_workspace",
    "venues.select_for_edition",
    "catalog.manage",
    "catalog.manage_stock",
    "catalog.manage_payments",
    "catalog.view_activity",
)
RESOURCE_CAPABILITIES = (
    "charities.view_selection",
    "charities.review_selection",
    "charities.comment_selection",
    "charities.publish_selection",
    "venues.view_space_schedule",
    "venues.manage_space_schedule",
    "venues.publish_space_schedule",
)
LOGISTICS_ORGANIZATION_CAPABILITIES = ("logistics.manage_catalog",)
LOGISTICS_EDITION_CAPABILITIES = (
    "logistics.view_restricted_contacts",
    "logistics.view_workspace",
    "logistics.manage_operations",
    "logistics.review_offers",
    "logistics.reconcile_offline",
)
LOGISTICS_RESOURCE_CAPABILITIES = (
    "logistics.view_manifest",
    "logistics.manage_manifest",
)
LOGISTICS_CAPABILITIES = (
    *LOGISTICS_ORGANIZATION_CAPABILITIES,
    *LOGISTICS_EDITION_CAPABILITIES,
    *LOGISTICS_RESOURCE_CAPABILITIES,
)


def _capability_sql(*, include_logistics: bool) -> str:
    organization_codes = ORGANIZATION_CAPABILITIES + (
        LOGISTICS_ORGANIZATION_CAPABILITIES if include_logistics else ()
    )
    edition_codes = EDITION_CAPABILITIES + (
        LOGISTICS_EDITION_CAPABILITIES if include_logistics else ()
    )
    resource_codes = RESOURCE_CAPABILITIES + (
        LOGISTICS_RESOURCE_CAPABILITIES if include_logistics else ()
    )
    organization_values = ",".join(f"'{code}'" for code in organization_codes)
    edition_values = ",".join(f"'{code}'" for code in edition_codes)
    resource_values = ",".join(f"'{code}'" for code in resource_codes)
    return f"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(
    capability_code text
)
RETURNS smallint AS $$
BEGIN
    IF capability_code = ANY (ARRAY[{organization_values}]) THEN RETURN 0; END IF;
    IF capability_code = ANY (ARRAY[{edition_values}]) THEN RETURN 1; END IF;
    IF capability_code = ANY (ARRAY[{resource_values}]) THEN RETURN 3; END IF;
    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_authorization_capability_min_scope(text)
FROM PUBLIC;
"""


BINDING_FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_scoped_resource_binding()
RETURNS trigger AS $$
DECLARE
    resource_organization uuid;
    resource_edition uuid;
    resource_department uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RETURN NEW;
    END IF;

    IF NEW.resource_kind = 'workforce.position' THEN
        SELECT organization_id, edition_id, department_id
          INTO resource_organization, resource_edition, resource_department
          FROM public.workforce_position
         WHERE id = NEW.resource_id
         FOR UPDATE;
    ELSIF NEW.resource_kind = 'charity.selection' THEN
        SELECT organization_id, edition_id, responsible_department_id
          INTO resource_organization, resource_edition, resource_department
          FROM public.charities_charityselection
         WHERE id = NEW.resource_id
         FOR UPDATE;
    ELSIF NEW.resource_kind = 'venue.edition_space' THEN
        SELECT organization_id, edition_id, responsible_department_id
          INTO resource_organization, resource_edition, resource_department
          FROM public.venues_editionspaceselection
         WHERE id = NEW.resource_id
         FOR UPDATE;
    ELSIF NEW.resource_kind = 'logistics.manifest' THEN
        SELECT organization_id, edition_id, responsible_department_id
          INTO resource_organization, resource_edition, resource_department
          FROM public.logistics_logisticsmanifest
         WHERE id = NEW.resource_id
         FOR UPDATE;
    ELSE
        RAISE EXCEPTION 'unknown scoped resource binding kind'
            USING ERRCODE = '23514';
    END IF;

    IF resource_organization IS NULL
       OR resource_organization IS DISTINCT FROM NEW.organization_id
       OR resource_edition IS DISTINCT FROM NEW.edition_id
       OR resource_department IS DISTINCT FROM NEW.department_id
    THEN
        RAISE EXCEPTION 'scoped resource binding does not match its exact resource'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_validate_scoped_resource_binding() FROM PUBLIC;
"""

BINDING_REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_validate_scoped_resource_binding()
RETURNS trigger AS $$
DECLARE
    resource_organization uuid;
    resource_edition uuid;
    resource_department uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RETURN NEW;
    END IF;

    IF NEW.resource_kind = 'workforce.position' THEN
        SELECT organization_id, edition_id, department_id
          INTO resource_organization, resource_edition, resource_department
          FROM public.workforce_position
         WHERE id = NEW.resource_id
         FOR UPDATE;
    ELSIF NEW.resource_kind = 'charity.selection' THEN
        SELECT organization_id, edition_id, responsible_department_id
          INTO resource_organization, resource_edition, resource_department
          FROM public.charities_charityselection
         WHERE id = NEW.resource_id
         FOR UPDATE;
    ELSIF NEW.resource_kind = 'venue.edition_space' THEN
        SELECT organization_id, edition_id, responsible_department_id
          INTO resource_organization, resource_edition, resource_department
          FROM public.venues_editionspaceselection
         WHERE id = NEW.resource_id
         FOR UPDATE;
    ELSE
        RAISE EXCEPTION 'unknown scoped resource binding kind'
            USING ERRCODE = '23514';
    END IF;

    IF resource_organization IS NULL
       OR resource_organization IS DISTINCT FROM NEW.organization_id
       OR resource_edition IS DISTINCT FROM NEW.edition_id
       OR resource_department IS DISTINCT FROM NEW.department_id
    THEN
        RAISE EXCEPTION 'scoped resource binding does not match its exact resource'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_validate_scoped_resource_binding() FROM PUBLIC;
"""


def refuse_used_logistics_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    capability_grant = apps.get_model("authorization", "CapabilityGrant")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    resource_binding = apps.get_model("authorization", "ScopedResourceBinding")
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle, "
        "public.authorization_scopedresourcebinding "
        "IN ACCESS EXCLUSIVE MODE"
    )
    used_capability = (
        capability_grant.objects.filter(
            capability_code__in=LOGISTICS_CAPABILITIES
        ).exists()
        or role_bundle.objects.filter(
            capability_codes__overlap=list(LOGISTICS_CAPABILITIES)
        ).exists()
    )
    used_binding = resource_binding.objects.filter(
        resource_kind="logistics.manifest"
    ).exists()
    if used_capability or used_binding:
        raise RuntimeError(
            "Cannot remove Logistics authority after durable authority or exact "
            "resource evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0015_catalog_capabilities"),
        ("logistics", "0001_initial"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            _capability_sql(include_logistics=True),
            reverse_sql=_capability_sql(include_logistics=False),
        ),
        migrations.AlterField(
            model_name="scopedresourcebinding",
            name="resource_kind",
            field=models.CharField(
                choices=[
                    ("workforce.position", "Workforce position"),
                    ("charity.selection", "Charity selection"),
                    ("venue.edition_space", "Edition venue space"),
                    ("logistics.manifest", "Logistics manifest"),
                ],
                max_length=80,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="scopedresourcebinding",
            name="authorization_resource_kind_known",
        ),
        migrations.AddConstraint(
            model_name="scopedresourcebinding",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    resource_kind__in=(
                        "workforce.position",
                        "charity.selection",
                        "venue.edition_space",
                        "logistics.manifest",
                    )
                ),
                name="authorization_resource_kind_known",
            ),
        ),
        migrations.RunSQL(
            BINDING_FORWARD_SQL,
            reverse_sql=BINDING_REVERSE_SQL,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_logistics_downgrade,
        ),
    ]
