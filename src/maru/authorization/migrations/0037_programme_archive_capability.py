"""Reserve exact-edition archive authority without granting or activating it."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module(
    "maru.authorization.migrations.0031_programme_change_communication_capabilities"
)
ARCHIVE_CAPABILITY = "programme.export_archive"
ORGANIZATION_CAPABILITIES = _previous.ORGANIZATION_CAPABILITIES
EDITION_CAPABILITIES = (*_previous.EDITION_CAPABILITIES, ARCHIVE_CAPABILITY)
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
CREATE OR REPLACE FUNCTION
    public.maru_authorization_capability_min_scope(capability_code text)
RETURNS smallint AS $$
BEGIN
{branches}
    RETURN -1;
END;
$$ LANGUAGE plpgsql IMMUTABLE STRICT
SET search_path = pg_catalog, public, pg_temp;
REVOKE ALL ON FUNCTION public.maru_authorization_capability_min_scope(text)
    FROM PUBLIC;
"""


FORWARD_SQL = _capability_sql()
REVERSE_SQL = _previous.FORWARD_SQL


def refuse_used_archive_capability_downgrade(apps: Any, schema_editor: Any) -> None:
    """Refuse capability contraction while any retained grant or role declares it."""
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    grant = apps.get_model("authorization", "CapabilityGrant")
    bundle = apps.get_model("authorization", "RoleBundle")
    if (
        grant.objects.filter(capability_code=ARCHIVE_CAPABILITY).exists()
        or bundle.objects.filter(
            capability_codes__contains=[ARCHIVE_CAPABILITY]
        ).exists()
    ):
        raise RuntimeError(
            "Programme archive authority exists; retain it and fix forward."
        )


class Migration(migrations.Migration):
    """Add a dormant scope rule, retaining preceding recipe and approval guards."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0036_programme_room_operations_recipe"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_used_archive_capability_downgrade
        ),
    ]
