"""Register dormant Programme staffing authority without grants or activation."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.authorization.migrations.0027_scheduling_capabilities"
)
STAFFING_CAPABILITIES = ("programme.manage_staffing", "programme.view_staffing")
ORGANIZATION_CAPABILITIES = _previous.ORGANIZATION_CAPABILITIES
EDITION_CAPABILITIES = (*_previous.EDITION_CAPABILITIES, *STAFFING_CAPABILITIES)
DEPARTMENT_CAPABILITIES = _previous.DEPARTMENT_CAPABILITIES
RESOURCE_CAPABILITIES = _previous.RESOURCE_CAPABILITIES


def _capability_sql() -> str:
    branches = "\n".join(
        "    IF capability_code = ANY (ARRAY["
        + ",".join(f"'{code}'" for code in codes)
        + f"]) THEN RETURN {level}; END IF;"
        for level, codes in enumerate(
            (
                ORGANIZATION_CAPABILITIES,
                EDITION_CAPABILITIES,
                DEPARTMENT_CAPABILITIES,
                RESOURCE_CAPABILITIES,
            )
        )
    )
    return f"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(capability_code text)
RETURNS smallint AS $$
BEGIN
{branches}
    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_authorization_capability_min_scope(text) FROM PUBLIC;
"""


FORWARD_SQL = _capability_sql()
REVERSE_SQL = _previous.FORWARD_SQL


def refuse_used_staffing_capability_downgrade(apps: Any, schema_editor: Any) -> None:
    """Preserve the closed vocabulary after any retained grant or role uses it."""
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    grant = apps.get_model("authorization", "CapabilityGrant")
    bundle = apps.get_model("authorization", "RoleBundle")
    if grant.objects.filter(capability_code__in=STAFFING_CAPABILITIES).exists() or any(
        bundle.objects.filter(capability_codes__contains=[code]).exists()
        for code in STAFFING_CAPABILITIES
    ):
        raise RuntimeError(
            "Cannot remove retained Programme staffing authority; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Add two exact-edition capabilities without changing any profile manifest."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0027_scheduling_capabilities")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_staffing_capability_downgrade,
        ),
    ]
