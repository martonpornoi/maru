"""Recognize the Programme-import batch owner Department reference."""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.workforce.migrations.0016_programme_call_department_fk_contract"
)

_PROGRAMME_CALL_RELATION = """                             (
                                 'public.applications_programmecall'::pg_catalog.regclass,
                                 ARRAY['owner_department_id']::text[]
                             ),"""

_PROGRAMME_IMPORT_RELATION = """                             (
                                 'public.applications_programmeimportbatch'::pg_catalog.regclass,
                                 ARRAY['owner_department_id']::text[]
                             ),"""

if _previous.FORWARD_SQL.count(_PROGRAMME_CALL_RELATION) != 1:
    raise RuntimeError(
        "Refusing to extend an unrecognized Workforce Department FK contract."
    )

FORWARD_SQL = _previous.FORWARD_SQL.replace(
    _PROGRAMME_CALL_RELATION,
    f"{_PROGRAMME_CALL_RELATION}\n{_PROGRAMME_IMPORT_RELATION}",
)
REVERSE_SQL = _previous.FORWARD_SQL


class Migration(migrations.Migration):
    """Install the exact known Programme-import Department reference."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0007_programme_import_persistence"),
        ("workforce", "0016_programme_call_department_fk_contract"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
