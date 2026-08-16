"""Add charity authority and the exact charity-selection resource kind."""

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
)
CHARITY_ORGANIZATION_CAPABILITIES = (
    "charities.view_partners",
    "charities.manage_partners",
)
CHARITY_EDITION_CAPABILITIES = (
    "charities.view_review_queue",
    "charities.propose_selection",
)
CHARITY_RESOURCE_CAPABILITIES = (
    "charities.view_selection",
    "charities.review_selection",
    "charities.comment_selection",
    "charities.publish_selection",
)
CHARITY_CAPABILITIES = (
    *CHARITY_ORGANIZATION_CAPABILITIES,
    *CHARITY_EDITION_CAPABILITIES,
    *CHARITY_RESOURCE_CAPABILITIES,
)


def _capability_sql(
    *,
    organization_codes: tuple[str, ...],
    edition_codes: tuple[str, ...],
    resource_codes: tuple[str, ...] = (),
) -> str:
    organization_values = ",".join(f"'{code}'" for code in organization_codes)
    edition_values = ",".join(f"'{code}'" for code in edition_codes)
    resource_values = ",".join(f"'{code}'" for code in resource_codes)
    resource_branch = (
        f"IF capability_code = ANY (ARRAY[{resource_values}]) "
        "THEN RETURN 3; END IF;"
        if resource_values
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(
    capability_code text
)
RETURNS smallint AS $$
BEGIN
    IF capability_code = ANY (ARRAY[{organization_values}]) THEN RETURN 0; END IF;
    IF capability_code = ANY (ARRAY[{edition_values}]) THEN RETURN 1; END IF;
    {resource_branch}
    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_authorization_capability_min_scope(text)
FROM PUBLIC;
"""


CAPABILITY_FORWARD_SQL = _capability_sql(
    organization_codes=ORGANIZATION_CAPABILITIES
    + CHARITY_ORGANIZATION_CAPABILITIES,
    edition_codes=EDITION_CAPABILITIES + CHARITY_EDITION_CAPABILITIES,
    resource_codes=CHARITY_RESOURCE_CAPABILITIES,
)
CAPABILITY_REVERSE_SQL = _capability_sql(
    organization_codes=ORGANIZATION_CAPABILITIES,
    edition_codes=EDITION_CAPABILITIES,
)

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
    position_organization uuid;
    position_edition uuid;
    position_department uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RETURN NEW;
    END IF;
    IF NEW.resource_kind <> 'workforce.position' THEN
        RAISE EXCEPTION 'unknown scoped resource binding kind'
            USING ERRCODE = '23514';
    END IF;
    SELECT organization_id, edition_id, department_id
      INTO position_organization, position_edition, position_department
      FROM public.workforce_position
     WHERE id = NEW.resource_id
     FOR UPDATE;
    IF position_organization IS NULL
       OR position_organization IS DISTINCT FROM NEW.organization_id
       OR position_edition IS DISTINCT FROM NEW.edition_id
       OR position_department IS DISTINCT FROM NEW.department_id
    THEN
        RAISE EXCEPTION 'scoped resource binding does not match its exact position'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_validate_scoped_resource_binding() FROM PUBLIC;
"""


def refuse_used_charity_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    capability_grant = apps.get_model("authorization", "CapabilityGrant")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    resource_binding = apps.get_model("authorization", "ScopedResourceBinding")
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle, "
        "public.authorization_scopedresourcebinding "
        "IN ACCESS EXCLUSIVE MODE"
    )
    used_capability = capability_grant.objects.filter(
        capability_code__in=CHARITY_CAPABILITIES
    ).exists() or role_bundle.objects.filter(
        capability_codes__overlap=list(CHARITY_CAPABILITIES)
    ).exists()
    used_binding = resource_binding.objects.filter(
        resource_kind="charity.selection"
    ).exists()
    if used_capability or used_binding:
        raise RuntimeError(
            "Cannot remove charity authority after durable authority or exact "
            "resource evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0012_application_capabilities"),
        ("charities", "0001_initial"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            CAPABILITY_FORWARD_SQL,
            reverse_sql=CAPABILITY_REVERSE_SQL,
        ),
        migrations.AlterField(
            model_name="scopedresourcebinding",
            name="resource_kind",
            field=models.CharField(
                choices=[
                    ("workforce.position", "Workforce position"),
                    ("charity.selection", "Charity selection"),
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
            reverse_code=refuse_used_charity_downgrade,
        ),
    ]
