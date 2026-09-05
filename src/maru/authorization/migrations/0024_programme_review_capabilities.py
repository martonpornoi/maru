"""Declare dedicated dormant Programme review capabilities without granting them."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.authorization.migrations.0023_programme_department_ownership_recovery"
)
REVIEW_CAPABILITIES = (
    "applications.manage_programme_review",
    "applications.review_programme",
    "applications.moderate_programme_review",
    "applications.decide_programme",
)
ORGANIZATION_CAPABILITIES = _previous.ORGANIZATION_CAPABILITIES
EDITION_CAPABILITIES = _previous.EDITION_CAPABILITIES
DEPARTMENT_CAPABILITIES = (*_previous.DEPARTMENT_CAPABILITIES, *REVIEW_CAPABILITIES)
RESOURCE_CAPABILITIES = _previous.RESOURCE_CAPABILITIES


def _capability_sql() -> str:
    branches = "\n".join(
        "    IF capability_code = ANY (ARRAY["
        + ",".join(f"'{code}'" for code in codes)
        + f"]) THEN RETURN {level}; END IF;"
        for level, codes in enumerate((
            ORGANIZATION_CAPABILITIES, EDITION_CAPABILITIES,
            DEPARTMENT_CAPABILITIES, RESOURCE_CAPABILITIES,
        ))
    )
    return f"""
CREATE OR REPLACE FUNCTION public.maru_authorization_capability_min_scope(
    capability_code text
)
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


def refuse_used_review_capability_downgrade(apps: Any, schema_editor: Any) -> None:
    """Retain declared review vocabulary after durable grant or role evidence."""
    capability_grant = apps.get_model("authorization", "CapabilityGrant")
    role_bundle = apps.get_model("authorization", "RoleBundle")
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, "
        "public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    if capability_grant.objects.filter(capability_code__in=REVIEW_CAPABILITIES).exists() or any(
        role_bundle.objects.filter(capability_codes__contains=[code]).exists()
        for code in REVIEW_CAPABILITIES
    ):
        raise RuntimeError(
            "Cannot remove Programme review vocabulary after durable authority "
            "evidence exists; retain compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Install exact Department scope declarations with an unused-only reverse."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0023_programme_department_ownership_recovery"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_used_review_capability_downgrade,
        ),
    ]
