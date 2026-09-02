"""Add exact authority for preview-first Applications Programme imports."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.authorization.migrations.0021_applications_programme_capabilities"
)

IMPORT_CAPABILITIES = (
    "applications.import_programme",
    "applications.dispose_programme_import",
)
ORGANIZATION_CAPABILITIES = _previous.ORGANIZATION_CAPABILITIES
EDITION_CAPABILITIES = (
    *_previous.EDITION_CAPABILITIES,
    "applications.dispose_programme_import",
)
DEPARTMENT_CAPABILITIES = (
    *_previous.DEPARTMENT_CAPABILITIES,
    "applications.import_programme",
)
RESOURCE_CAPABILITIES = _previous.RESOURCE_CAPABILITIES


def _capability_sql() -> str:
    organization_values = ",".join(
        f"'{code}'" for code in ORGANIZATION_CAPABILITIES
    )
    edition_values = ",".join(f"'{code}'" for code in EDITION_CAPABILITIES)
    department_values = ",".join(f"'{code}'" for code in DEPARTMENT_CAPABILITIES)
    resource_values = ",".join(f"'{code}'" for code in RESOURCE_CAPABILITIES)
    return f"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(
    capability_code text
)
RETURNS smallint AS $$
BEGIN
    IF capability_code = ANY (ARRAY[{organization_values}]) THEN RETURN 0; END IF;
    IF capability_code = ANY (ARRAY[{edition_values}]) THEN RETURN 1; END IF;
    IF capability_code = ANY (ARRAY[{department_values}]) THEN RETURN 2; END IF;
    IF capability_code = ANY (ARRAY[{resource_values}]) THEN RETURN 3; END IF;
    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION
    public.maru_authorization_capability_min_scope(text)
FROM PUBLIC;
"""


FORWARD_SQL = _capability_sql()
REVERSE_SQL = _previous._capability_sql(  # noqa: SLF001
    include_applications_programme=True,
)


def refuse_used_programme_import_capability_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Refuse capability contraction after durable authority uses either code."""
    capability_grant = apps.get_model("authorization", "CapabilityGrant")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    used = (
        capability_grant.objects.filter(
            capability_code__in=IMPORT_CAPABILITIES
        ).exists()
        or role_bundle.objects.filter(
            capability_codes__overlap=list(IMPORT_CAPABILITIES)
        ).exists()
    )
    if used:
        raise RuntimeError(
            "Cannot remove Programme-import authority after durable grants or "
            "role evidence exists; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Install import capability scopes and a populated downgrade fence."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0021_applications_programme_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_programme_import_capability_downgrade,
        ),
    ]
