"""Restore exact Department references and preserve the shared execution boundary."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_starter = import_module(
    "maru.workforce.migrations.0027_programme_starter_downgrade_fence"
)
_notice = import_module("maru.scheduling.migrations.0022_change_notice_integrity")
_ownership = import_module(
    "maru.workforce.migrations.0018_programme_department_ownership_contract"
)

_PRIOR_RELATION = """                             (
                                 'public.authorization_roleassignment'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),"""
_PROGRAMME_RELATIONS = """                             (
                                 'public.authorization_programmerolerequest'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),
                             (
                                 'public.events_programmeadoptionsetupreceipt'::pg_catalog.regclass,
                                 ARRAY['department_id']::text[]
                             ),"""

if _ownership.DEPARTMENT_FK_CONTRACT_SQL.count(_PRIOR_RELATION) != 1:
    raise RuntimeError("Unrecognized Programme Department-reference contract.")

FORWARD_SQL = _ownership.DEPARTMENT_FK_CONTRACT_SQL.replace(
    _PRIOR_RELATION, f"{_PRIOR_RELATION}\n{_PROGRAMME_RELATIONS}"
)
REVERSE_SQL = _ownership.DEPARTMENT_FK_CONTRACT_SQL


def refuse_used_starter_execution_downgrade(apps: Any, schema_editor: Any) -> None:
    """Run both frozen retained-evidence preflights before removing any successor."""
    _starter.refuse_used_starter_downgrade(apps, schema_editor)
    _notice.refuse_used_notice_boundary_downgrade(apps, schema_editor)


class Migration(migrations.Migration):
    """Keep unused reversal, but stop used contraction before recorder changes."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0027_programme_starter_downgrade_fence"),
        ("scheduling", "0022_change_notice_integrity"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            refuse_used_starter_execution_downgrade,
        ),
    ]
