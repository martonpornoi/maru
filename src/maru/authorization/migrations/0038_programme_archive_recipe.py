"""Add one literal archive-purpose recipe without altering historical definitions."""

import json
from importlib import import_module
from typing import ClassVar

from django.db import migrations

# Only immutable historical migration data is imported, never the live catalog.
_previous = import_module(
    "maru.authorization.migrations.0036_programme_room_operations_recipe"
)
_OLD_RECIPES = _previous._FROZEN_RECIPES  # noqa: SLF001 - immutable owner migration
_NEW_RECIPE = {
    "exit-archive@1": {
        "digest": "9b592f875bbcddef579fb21cb0bc216c3002900c2b9eafbc691e107fd5a04e98",
        "role_code": "programme-exit-archive",
        "version": 1,
        "name": "Programme restricted exit archive",
        "capabilities": ["programme.export_archive"],
        "scopes": ["edition"],
        "resource_kind": "",
    }
}
_FROZEN_RECIPES = json.dumps({**json.loads(_OLD_RECIPES), **_NEW_RECIPE}, indent=2)
_FUNCTION_SQL = _previous._FUNCTION_SQL  # noqa: SLF001 - immutable owner migration
_LOCKS = _previous._LOCKS  # noqa: SLF001 - immutable owner migration
_UNUSED_ONLY = """
DO $unused_archive_recipe_reverse$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.authorization_programmerolerequest
        WHERE recipe_code = 'exit-archive' AND recipe_version = 1
    ) OR EXISTS (
        SELECT 1 FROM public.authorization_rolebundle
        WHERE code = 'programme-exit-archive'
    ) THEN
        RAISE EXCEPTION 'Programme archive recipe exists; retain it and fix forward'
            USING ERRCODE = '23514';
    END IF;
END;
$unused_archive_recipe_reverse$;
"""
FORWARD_SQL = _LOCKS + _FUNCTION_SQL.replace("__RECIPES__", _FROZEN_RECIPES)
REVERSE_SQL = _LOCKS + _UNUSED_ONLY + _FUNCTION_SQL.replace("__RECIPES__", _OLD_RECIPES)


class Migration(migrations.Migration):
    """Fence request/role evidence before removing the exact new recipe."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0037_programme_archive_capability"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
