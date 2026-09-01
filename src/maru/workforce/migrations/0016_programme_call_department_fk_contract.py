"""Recognize the Applications Programme-call Department reference."""

from __future__ import annotations

import importlib
from typing import ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.workforce.migrations.0008_department_fk_contract_successor"
)

_PRIOR_RELATION = """                             (
                                 'public.applications_applicationownerdepartment'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),"""

_PROGRAMME_RELATION = """                             (
                                 'public.applications_programmecall'::pg_catalog.regclass,
                                 ARRAY['owner_department_id']::text[]
                             ),"""

if _previous.FORWARD_SQL.count(_PRIOR_RELATION) != 1:
    raise RuntimeError(
        "Refusing to extend an unrecognized Workforce Department FK contract."
    )

FORWARD_SQL = _previous.FORWARD_SQL.replace(
    _PRIOR_RELATION,
    f"{_PRIOR_RELATION}\n{_PROGRAMME_RELATION}",
)
REVERSE_SQL = _previous.FORWARD_SQL


class Migration(migrations.Migration):
    """Install the exact known Programme-call Department reference."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0004_programme_calls_and_proposals"),
        ("workforce", "0015_exact_assignment_adoption_profile"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
