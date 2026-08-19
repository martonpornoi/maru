"""Add exact-edition staff capabilities for registration profile extensions.

The capability catalog is enforced in PostgreSQL as well as Python.  Expanding
the code-owned catalog therefore replaces the immutable scope function in one
atomic migration.  Reversal is allowed only while neither capability has ever
been used by a grant or role bundle; otherwise old code would reinterpret
persisted authority as an unknown capability.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

PROFILE_EXTENSION_CAPABILITIES = (
    "registration.view_profile_extensions",
    "registration.update_profile_extensions",
)


FORWARD_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(
    capability_code text
)
RETURNS smallint AS $$
BEGIN
    IF capability_code = ANY (ARRAY[
        'organizations.view_basic',
        'organizations.change_profile',
        'organizations.create_series',
        'organizations.change_series',
        'organizations.manage_representation',
        'events.view_basic',
        'events.create',
        'authorization.delegate',
        'authorization.grant_direct',
        'authorization.revoke',
        'authorization.manage_roles',
        'effects.replay',
        'privacy.manage_requests',
        'audit.view_security'
    ]) THEN
        RETURN 0;
    END IF;

    IF capability_code = ANY (ARRAY[
        'events.change_profile',
        'events.transition',
        'participation.view_staff_summary',
        'identity.manage_restrictions',
        'registration.manage_configuration',
        'registration.view_profile_extensions',
        'registration.update_profile_extensions',
        'registration.view_service_summary',
        'registration.view_attendee_reporting',
        'registration.view_payment_summary',
        'registration.manage_exceptions',
        'registration.register_on_behalf',
        'registration.manage_finance',
        'registration.check_in',
        'accreditation.issue',
        'accreditation.revoke',
        'accreditation.manage_offline',
        'registration.moderate_public_profile',
        'workforce.view_structure',
        'workforce.manage_structure',
        'workforce.manage_applications',
        'workforce.manage_documents',
        'workforce.manage_assignments'
    ]) THEN
        RETURN 1;
    END IF;

    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION
    public.maru_authorization_capability_min_scope(text)
FROM PUBLIC;
"""


REVERSE_SQL = r"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(
    capability_code text
)
RETURNS smallint AS $$
BEGIN
    IF capability_code = ANY (ARRAY[
        'organizations.view_basic',
        'organizations.change_profile',
        'organizations.create_series',
        'organizations.change_series',
        'organizations.manage_representation',
        'events.view_basic',
        'events.create',
        'authorization.delegate',
        'authorization.grant_direct',
        'authorization.revoke',
        'authorization.manage_roles',
        'effects.replay',
        'privacy.manage_requests',
        'audit.view_security'
    ]) THEN
        RETURN 0;
    END IF;

    IF capability_code = ANY (ARRAY[
        'events.change_profile',
        'events.transition',
        'participation.view_staff_summary',
        'identity.manage_restrictions',
        'registration.manage_configuration',
        'registration.view_service_summary',
        'registration.view_attendee_reporting',
        'registration.view_payment_summary',
        'registration.manage_exceptions',
        'registration.register_on_behalf',
        'registration.manage_finance',
        'registration.check_in',
        'accreditation.issue',
        'accreditation.revoke',
        'accreditation.manage_offline',
        'registration.moderate_public_profile',
        'workforce.view_structure',
        'workforce.manage_structure',
        'workforce.manage_applications',
        'workforce.manage_documents',
        'workforce.manage_assignments'
    ]) THEN
        RETURN 1;
    END IF;

    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;

REVOKE ALL ON FUNCTION
    public.maru_authorization_capability_min_scope(text)
FROM PUBLIC;
"""


def refuse_used_capability_downgrade(apps, schema_editor) -> None:  # type: ignore[no-untyped-def]
    """Keep the expanded catalog once either capability has persisted evidence."""

    capability_grant = apps.get_model("authorization", "CapabilityGrant")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    if capability_grant.objects.filter(
        capability_code__in=PROFILE_EXTENSION_CAPABILITIES
    ).exists() or role_bundle.objects.filter(
        capability_codes__overlap=list(PROFILE_EXTENSION_CAPABILITIES)
    ).exists():
        raise RuntimeError(
            "Cannot remove registration profile-extension capabilities after "
            "authority evidence exists. Keep compatible code and fix forward, "
            "or restore the complete authorization state."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0010_retired_department_authority_guards"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_capability_downgrade,
        ),
    ]
