"""Add exact-edition capabilities for the typed application portfolio."""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

APPLICATION_CAPABILITIES = (
    "applications.manage_definitions",
    "applications.review",
    "applications.review_sensitive",
)
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
)


def _sql(edition_codes: tuple[str, ...]) -> str:
    organization_values = ",".join(f"'{code}'" for code in ORGANIZATION_CAPABILITIES)
    edition_values = ",".join(f"'{code}'" for code in edition_codes)
    return f"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(
    capability_code text
)
RETURNS smallint AS $$
BEGIN
    IF capability_code = ANY (ARRAY[{organization_values}])
        THEN RETURN 0;
    END IF;
    IF capability_code = ANY (ARRAY[{edition_values}]) THEN RETURN 1; END IF;
    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_authorization_capability_min_scope(text) FROM PUBLIC;
"""


FORWARD_SQL = _sql(EDITION_CAPABILITIES + APPLICATION_CAPABILITIES)
REVERSE_SQL = _sql(EDITION_CAPABILITIES)


def refuse_used_capability_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    capability_grant = apps.get_model("authorization", "CapabilityGrant")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    if (
        capability_grant.objects.filter(
            capability_code__in=APPLICATION_CAPABILITIES
        ).exists()
        or role_bundle.objects.filter(
            capability_codes__overlap=list(APPLICATION_CAPABILITIES)
        ).exists()
    ):
        raise RuntimeError(
            "Cannot remove application capabilities after authority evidence exists; "
            "keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0011_registration_profile_extension_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, reverse_code=refuse_used_capability_downgrade
        ),
    ]
