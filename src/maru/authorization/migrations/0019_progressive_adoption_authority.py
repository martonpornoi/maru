"""Allow accountable Workforce authority across adopted edition profiles."""

from __future__ import annotations

import hashlib
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
    "events.change_profile",
    "events.transition",
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
    "workforce.view_structure",
    "workforce.manage_structure",
    "workforce.manage_applications",
    "workforce.manage_documents",
    "workforce.manage_assignments",
    "workforce.view_availability",
    "workforce.view_shifts",
    "workforce.manage_shifts",
)

EDITION_CAPABILITIES = (
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

PRIOR_ORGANIZATION_CAPABILITIES = tuple(
    code
    for code in ORGANIZATION_CAPABILITIES
    if code
    not in {
        "events.change_profile",
        "events.transition",
        "workforce.view_structure",
        "workforce.manage_structure",
        "workforce.manage_applications",
        "workforce.manage_documents",
        "workforce.manage_assignments",
        "workforce.view_availability",
        "workforce.view_shifts",
        "workforce.manage_shifts",
    }
)
PRIOR_EDITION_CAPABILITIES = (
    "events.change_profile",
    "events.transition",
    "workforce.view_structure",
    "workforce.manage_structure",
    "workforce.manage_applications",
    "workforce.manage_documents",
    "workforce.manage_assignments",
    "workforce.view_availability",
    *EDITION_CAPABILITIES,
    "workforce.view_shifts",
    "workforce.manage_shifts",
)

PURPOSE_BOUND_EDITION_CAPABILITIES = (
    "events.change_profile",
    "events.transition",
    "workforce.view_structure",
    "workforce.manage_structure",
    "workforce.manage_applications",
    "workforce.manage_documents",
    "workforce.manage_assignments",
    "workforce.view_availability",
    "workforce.view_shifts",
    "workforce.manage_shifts",
)

MARU_OPERATOR_CAPABILITIES = (
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
    "audit.view_security",
    *PURPOSE_BOUND_EDITION_CAPABILITIES,
)

_PURPOSE_BOUND_EDITION_SQL = ",".join(
    f"'{code}'" for code in PURPOSE_BOUND_EDITION_CAPABILITIES
)
_MARU_OPERATOR_CAPABILITY_SQL = ",".join(
    f"'{code}'" for code in MARU_OPERATOR_CAPABILITIES
)

_AUTHORITY_CONTROL_SOURCE_SHA256 = (
    "632c97420c433a6f645ed0e6a552d3b7e838360a35901a8a62804523d41cfde3"
)
_SAFE_SEARCH_PATH = ("search_path=pg_catalog, public, pg_temp",)


def _capability_sql(
    organization_codes: tuple[str, ...],
    edition_codes: tuple[str, ...],
) -> str:
    organization_values = ",".join(f"'{code}'" for code in organization_codes)
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


SUPPLEMENTAL_CONTROL_SQL = rf"""
CREATE FUNCTION public.maru_validate_profile_bound_capability_grant_scope()
RETURNS trigger AS $$
BEGIN
    IF NEW.edition_id IS NULL
       AND NEW.capability_code = ANY (
           ARRAY[{_PURPOSE_BOUND_EDITION_SQL}]::text[]
       )
    THEN
        RAISE EXCEPTION 'purpose-bound capability requires exact edition scope'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_validate_profile_bound_capability_grant_scope()
FROM PUBLIC;

CREATE TRIGGER authorization_profile_bound_capability_scope_guard
BEFORE INSERT OR UPDATE
ON public.authorization_capabilitygrant
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_profile_bound_capability_grant_scope();

CREATE FUNCTION public.maru_validate_profile_bound_role_assignment_scope()
RETURNS trigger AS $$
DECLARE
    bundle_code varchar;
    bundle_capability_codes text[];
BEGIN
    SELECT role_bundle.code, role_bundle.capability_codes
      INTO bundle_code, bundle_capability_codes
      FROM public.authorization_rolebundle AS role_bundle
     WHERE role_bundle.id = NEW.role_bundle_id
     FOR KEY SHARE;

    IF bundle_code = 'maru-operators'
       AND bundle_capability_codes IS DISTINCT FROM
           ARRAY[{_MARU_OPERATOR_CAPABILITY_SQL}]::text[]
    THEN
        RAISE EXCEPTION 'Maru-operator authority must use its canonical capability set'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.edition_id IS NULL
       AND bundle_capability_codes &&
           ARRAY[{_PURPOSE_BOUND_EDITION_SQL}]::text[]
       AND bundle_code IS DISTINCT FROM 'maru-operators'
    THEN
        RAISE EXCEPTION 'purpose-bound role authority requires exact edition scope'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_validate_profile_bound_role_assignment_scope()
FROM PUBLIC;

CREATE TRIGGER authorization_profile_bound_role_scope_guard
BEFORE INSERT OR UPDATE
ON public.authorization_roleassignment
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_profile_bound_role_assignment_scope();

CREATE FUNCTION public.maru_validate_representation_control_type_insert()
RETURNS trigger AS $$
DECLARE
    target_role_code varchar;
    target_representation_code varchar;
BEGIN
    IF NEW.basis NOT IN (
        'platform_representation_bootstrap',
        'representation_acceptance'
    ) THEN
        RETURN NEW;
    END IF;

    SELECT COALESCE(role_bundle.code, assignment_bundle.code)
      INTO target_role_code
      FROM public.authorization_authorityissuance AS issuance
      LEFT JOIN public.authorization_rolebundle AS role_bundle
        ON role_bundle.id = issuance.role_bundle_id
      LEFT JOIN public.authorization_roleassignment AS role_assignment
        ON role_assignment.id = issuance.role_assignment_id
      LEFT JOIN public.authorization_rolebundle AS assignment_bundle
        ON assignment_bundle.id = role_assignment.role_bundle_id
     WHERE issuance.ordinal = NEW.issuance_id;

    SELECT representation.code
      INTO target_representation_code
      FROM public.organizations_organizationrepresentation AS representation
     WHERE representation.id = NEW.representation_id;

    IF NOT (
        (target_role_code = 'executive-board'
         AND target_representation_code = 'executive_board')
        OR
        (target_role_code = 'maru-operators'
         AND target_representation_code = 'maru_operators')
    ) THEN
        RAISE EXCEPTION 'representation control type does not match root authority'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_validate_representation_control_type_insert()
FROM PUBLIC;

CREATE TRIGGER authorization_representation_control_type_insert_guard
BEFORE INSERT
ON public.authorization_authoritycontrol
FOR EACH ROW
EXECUTE FUNCTION public.maru_validate_representation_control_type_insert();
"""

SUPPLEMENTAL_CONTROL_REVERSE_SQL = r"""
DROP TRIGGER IF EXISTS authorization_representation_control_type_insert_guard
    ON public.authorization_authoritycontrol;
DROP FUNCTION IF EXISTS
    public.maru_validate_representation_control_type_insert();
DROP TRIGGER IF EXISTS authorization_profile_bound_role_scope_guard
    ON public.authorization_roleassignment;
DROP FUNCTION IF EXISTS
    public.maru_validate_profile_bound_role_assignment_scope();
DROP TRIGGER IF EXISTS authorization_profile_bound_capability_scope_guard
    ON public.authorization_capabilitygrant;
DROP FUNCTION IF EXISTS
    public.maru_validate_profile_bound_capability_grant_scope();
"""


def _source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _control_function_state(cursor: Any) -> tuple[object, str, tuple[str, ...], object, object]:
    cursor.execute(
        """
        SELECT procedure.oid,
               procedure.prosrc,
               procedure.proconfig,
               procedure.proowner,
               procedure.proacl
          FROM pg_catalog.pg_proc AS procedure
         WHERE procedure.oid = pg_catalog.to_regprocedure(
                   'public.maru_validate_authority_control_insert()'
               )
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("The authority-control validator is unavailable.")
    return (row[0], str(row[1]), tuple(row[2] or ()), row[3], row[4])


def _rewrite_control_source(source: str, *, enable: bool) -> str:
    replacements = (
        (
            "role_bundle.code = 'executive-board'",
            "role_bundle.code = ANY (ARRAY['executive-board', 'maru-operators'])",
        ),
        (
            "assignment_bundle.code = 'executive-board'",
            "assignment_bundle.code = ANY (ARRAY['executive-board', 'maru-operators'])",
        ),
        (
            "representation control requires Executive Board authority",
            "representation control requires reserved representation authority",
        ),
    )
    rewritten = source
    for old, new in replacements:
        source_value, target_value = (old, new) if enable else (new, old)
        if rewritten.count(source_value) != 1:
            raise RuntimeError(
                "Refusing an unrecognized authority-control validator rewrite."
            )
        rewritten = rewritten.replace(source_value, target_value)
    return rewritten


def _replace_control_function(schema_editor: Any, *, enable: bool) -> None:
    with schema_editor.connection.cursor() as cursor:
        before = _control_function_state(cursor)
        if enable and _source_sha256(before[1]) != _AUTHORITY_CONTROL_SOURCE_SHA256:
            raise RuntimeError(
                "Refusing to broaden an unrecognized authority-control validator."
            )
        if before[2] != _SAFE_SEARCH_PATH:
            raise RuntimeError(
                "Refusing to rewrite an authority-control validator with an "
                "unexpected search path."
            )
        rewritten = _rewrite_control_source(before[1], enable=enable)
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
                public.maru_validate_authority_control_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
            """,
            [rewritten],
        )
        after = _control_function_state(cursor)
        if (
            after[0] != before[0]
            or after[2:] != before[2:]
            or after[1] != rewritten
        ):
            raise RuntimeError(
                "Authority-control function identity or privileges changed."
            )


def broaden_representation_control(apps: Any, schema_editor: Any) -> None:
    """Permit both code-owned representation roots in the existing guard."""
    del apps
    _replace_control_function(schema_editor, enable=True)


def restore_board_representation_control(apps: Any, schema_editor: Any) -> None:
    """Restore the Board-only authority-control validator."""
    del apps
    _replace_control_function(schema_editor, enable=False)


def refuse_neutral_authority_downgrade(apps: Any, schema_editor: Any) -> None:
    """Refuse removing neutral-root authority after durable use."""
    del schema_editor
    role_bundle = apps.get_model("authorization", "RoleBundle")
    if role_bundle.objects.filter(code="maru-operators").exists():
        raise RuntimeError(
            "Cannot remove Maru-operator authority after a reserved role bundle "
            "exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Broaden root authority while retaining exact profile enforcement."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0018_workforce_shift_capabilities"),
        ("events", "0010_workforce_adoption_profile"),
        ("organizations", "0013_runtime_executable_function_hardening"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(
            _capability_sql(ORGANIZATION_CAPABILITIES, EDITION_CAPABILITIES),
            reverse_sql=_capability_sql(
                PRIOR_ORGANIZATION_CAPABILITIES,
                PRIOR_EDITION_CAPABILITIES,
            ),
        ),
        migrations.RunPython(
            broaden_representation_control,
            reverse_code=restore_board_representation_control,
        ),
        migrations.RunSQL(
            SUPPLEMENTAL_CONTROL_SQL,
            reverse_sql=SUPPLEMENTAL_CONTROL_REVERSE_SQL,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_neutral_authority_downgrade,
        ),
    ]
