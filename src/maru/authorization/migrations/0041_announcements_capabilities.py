"""Register exact-edition Announcements capabilities without granting them."""

import re
from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module(
    "maru.authorization.migrations.0037_programme_archive_capability"
)
ANNOUNCEMENTS_CAPABILITIES = (
    "announcements.view",
    "announcements.compose",
    "announcements.review",
    "announcements.record_publication",
    "announcements.manage_settings",
    "announcements.export_evidence",
)
ANNOUNCEMENTS_OPERATOR_CAPABILITIES = (
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
    "events.change_profile",
    "events.transition",
    *ANNOUNCEMENTS_CAPABILITIES,
)
ORGANIZATION_CAPABILITIES = _previous.ORGANIZATION_CAPABILITIES
EDITION_CAPABILITIES = (*_previous.EDITION_CAPABILITIES, *ANNOUNCEMENTS_CAPABILITIES)
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
    return _previous.FORWARD_SQL.replace(
        _previous.FORWARD_SQL.split("BEGIN\n")[1].split("    RETURN -1;")[0],
        branches + "\n",
    )


FORWARD_SQL = _capability_sql()
REVERSE_SQL = _previous.FORWARD_SQL


def _replace(schema_editor: Any, *, forward: bool) -> None:
    """Require the predecessor source and preserve function identity/privileges."""
    lineage = import_module(
        "maru.authorization.migrations.0039_accountable_representation_lineage"
    )
    identity = "maru_authorization_capability_min_scope(text)"
    expected, desired = (
        (REVERSE_SQL, FORWARD_SQL) if forward else (FORWARD_SQL, REVERSE_SQL)
    )
    with schema_editor.connection.cursor() as cursor:
        before = lineage._state(cursor, identity)
        if before[3] != expected.split("$$")[1]:
            raise RuntimeError("Refusing changed capability-scope source.")
        # Existing ACL is preserved by CREATE OR REPLACE; PUBLIC stays revoked.
        cursor.execute(desired)
        after = lineage._state(cursor, identity)
        if (
            before[:3] != after[:3]
            or before[4:] != after[4:]
            or after[3] != desired.split("$$")[1]
        ):
            raise RuntimeError("Capability-scope identity or metadata changed.")


def install(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=True)


def restore(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=False)


def refuse_used_downgrade(apps: Any, schema_editor: Any) -> None:
    schema_editor.execute(
        "LOCK TABLE public.authorization_capabilitygrant, public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    grants = apps.get_model("authorization", "CapabilityGrant")
    bundles = apps.get_model("authorization", "RoleBundle")
    if (
        grants.objects.filter(capability_code__in=ANNOUNCEMENTS_CAPABILITIES).exists()
        or bundles.objects.filter(
            capability_codes__overlap=list(ANNOUNCEMENTS_CAPABILITIES)
        ).exists()
    ):
        raise RuntimeError("Announcements authority exists; retain it and fix forward.")


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0040_programme_stop_boundary")
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(install, restore),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade),
    ]
