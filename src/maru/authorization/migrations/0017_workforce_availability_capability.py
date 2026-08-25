"""Add the edition-scoped organizer availability-read capability."""

from __future__ import annotations

from typing import Any, ClassVar

from django.db import migrations

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
    "logistics.manage_catalog",
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
    "logistics.view_restricted_contacts",
    "logistics.view_workspace",
    "logistics.manage_operations",
    "logistics.review_offers",
    "logistics.reconcile_offline",
)
RESOURCE_CAPABILITIES = (
    "charities.view_selection",
    "charities.review_selection",
    "charities.comment_selection",
    "charities.publish_selection",
    "venues.view_space_schedule",
    "venues.manage_space_schedule",
    "venues.publish_space_schedule",
    "logistics.view_manifest",
    "logistics.manage_manifest",
)
AVAILABILITY_CAPABILITIES = ("workforce.view_availability",)


def _capability_sql(*, include_availability: bool) -> str:
    edition_codes = EDITION_CAPABILITIES + (
        AVAILABILITY_CAPABILITIES if include_availability else ()
    )
    organization_values = ",".join(
        f"'{code}'" for code in ORGANIZATION_CAPABILITIES
    )
    edition_values = ",".join(f"'{code}'" for code in edition_codes)
    resource_values = ",".join(f"'{code}'" for code in RESOURCE_CAPABILITIES)
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


def refuse_used_availability_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Refuse removing a capability after durable authority references it."""
    capability_grant = apps.get_model("authorization", "CapabilityGrant")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    used = capability_grant.objects.filter(
        capability_code__in=AVAILABILITY_CAPABILITIES
    ).exists() or role_bundle.objects.filter(
        capability_codes__overlap=list(AVAILABILITY_CAPABILITIES)
    ).exists()
    if used:
        raise RuntimeError(
            "Cannot remove Workforce availability authority after durable grants "
            "or role evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Install the PostgreSQL capability scope contract and downgrade fence."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0016_logistics_capabilities_and_resource_kind"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            _capability_sql(include_availability=True),
            reverse_sql=_capability_sql(include_availability=False),
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_availability_downgrade,
        ),
    ]
