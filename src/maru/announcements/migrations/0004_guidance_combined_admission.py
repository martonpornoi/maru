"""Retain Announcements admission after the one accepted Guidance expansion edge."""

import re
from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module("maru.announcements.migrations.0002_integrity")
_lineage = import_module(
    "maru.authorization.migrations.0039_accountable_representation_lineage"
)
# Retain the full expected SQL contract; RunPython changes only one frozen helper.
CONTRACT_SQL = _previous.FORWARD_SQL.replace(
    "edition.adoption_profile_code = 'announcements_only'",
    "edition.adoption_profile_code IN ('announcements_only', 'announcements_guidance')",
)


def _body(sql: str) -> str:
    match = re.search(
        r"CREATE FUNCTION public.maru_announcements_row_guard\(\).*?AS \$\$(.*?)\$\$",
        sql,
        re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Frozen Announcements scope guard is unavailable.")
    return match[1]


def _replace(schema_editor: Any, *, forward: bool) -> None:
    identity = "maru_announcements_row_guard()"
    previous, desired = _body(_previous.FORWARD_SQL), _body(CONTRACT_SQL)
    if not forward:
        previous, desired = desired, previous
    with schema_editor.connection.cursor() as cursor:
        before = _lineage._state(cursor, identity)
        if before[3] != previous:
            raise RuntimeError(
                "Refusing changed Announcements native admission source."
            )
        cursor.execute(
            "CREATE OR REPLACE FUNCTION public.maru_announcements_row_guard() RETURNS trigger AS $$"
            + desired
            + "$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;"
        )
        after = _lineage._state(cursor, identity)
        if after[:3] != before[:3] or after[4:] != before[4:] or after[3] != desired:
            raise RuntimeError(
                "Announcements admission changed helper identity or ACL."
            )


def install(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=True)


def restore(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=False)


def refuse_joined_downgrade(apps: Any, schema_editor: Any) -> None:
    import_module(
        "maru.events.migrations.0024_guidance_adoption_downgrade_fence"
    ).refuse_used_guidance_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("announcements", "0003_downgrade_fence"),
        ("events", "0024_guidance_adoption_downgrade_fence"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(install, restore),
        migrations.RunPython(migrations.RunPython.noop, refuse_joined_downgrade),
    ]
