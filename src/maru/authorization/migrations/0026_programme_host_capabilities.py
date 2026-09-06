"""Declare independent host-manager vocabulary without grants or profile activation."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from django.db import migrations

_previous = importlib.import_module("maru.authorization.migrations.0025_programme_conversion_capability")
HOST_CAPABILITIES = ("programme.manage_hosts", "programme.view_hosts")
ORGANIZATION_CAPABILITIES = _previous.ORGANIZATION_CAPABILITIES
EDITION_CAPABILITIES = (*_previous.EDITION_CAPABILITIES, *HOST_CAPABILITIES)
DEPARTMENT_CAPABILITIES = _previous.DEPARTMENT_CAPABILITIES
RESOURCE_CAPABILITIES = _previous.RESOURCE_CAPABILITIES


def _capability_sql() -> str:
    branches = "\n".join(
        "    IF capability_code = ANY (ARRAY[" + ",".join(f"'{code}'" for code in codes)
        + f"]) THEN RETURN {level}; END IF;"
        for level, codes in enumerate((ORGANIZATION_CAPABILITIES, EDITION_CAPABILITIES, DEPARTMENT_CAPABILITIES, RESOURCE_CAPABILITIES))
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


def refuse_used_host_capability_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain vocabulary after any grant or role bundle references host authority."""
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    grant = apps.get_model("authorization", "CapabilityGrant")
    bundle = apps.get_model("authorization", "RoleBundle")
    if grant.objects.filter(capability_code__in=HOST_CAPABILITIES).exists() or any(
        bundle.objects.filter(capability_codes__contains=[code]).exists() for code in HOST_CAPABILITIES
    ):
        raise RuntimeError("Cannot remove retained Programme host authority vocabulary; keep compatible code and fix forward.")


class Migration(migrations.Migration):
    """Keep self-only host capabilities non-persistable and organizer grants edition-scoped."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [("authorization", "0025_programme_conversion_capability")]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(migrations.RunPython.noop, reverse_code=refuse_used_host_capability_downgrade),
    ]
