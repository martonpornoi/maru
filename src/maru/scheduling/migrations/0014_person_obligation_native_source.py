"""Authenticate one explicit global person-work source from native scoped receipts."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module("maru.scheduling.migrations.0008_release_dependency_guards")


def _definition(name: str) -> str:
    start = _previous.FORWARD_SQL.index(f"CREATE FUNCTION public.{name}(")
    ending = "SET search_path = pg_catalog, public, pg_temp;"
    end = _previous.FORWARD_SQL.index(ending, start) + len(ending)
    return _previous.FORWARD_SQL[start:end].replace(
        "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
    )


def _replace(statement: str, original: str, replacement: str) -> str:
    if statement.count(original) != 1:
        raise RuntimeError("The frozen Scheduling native source contract changed.")
    return statement.replace(original, replacement)


_lock = _definition("maru_scheduling_lock_release_source")
_valid = _definition("maru_scheduling_release_native_change_valid")
REVERSE_SQL = _lock + "\n" + _valid
_lock = _replace(
    _lock,
    "WHEN 'identity_account' THEN 'identity_account'",
    "WHEN 'identity_account' THEN 'identity_account'\n"
    "        WHEN 'workforce_person_obligations' THEN 'identity_account'",
)
_lock = _replace(
    _lock,
    "IF dependency_kind = 'identity_account' THEN",
    "IF dependency_kind IN ('identity_account', 'workforce_person_obligations') THEN",
)
_valid = _replace(
    _valid,
    "          AND event.organization_id IS NOT DISTINCT FROM organization\n"
    "          AND event.event_edition_id IS NOT DISTINCT FROM edition",
    "          AND (\n"
    "              (dependency_kind = 'workforce_person_obligations'\n"
    "               AND organization IS NULL AND edition IS NULL\n"
    "               AND event.organization_id IS NOT NULL\n"
    "               AND event.event_edition_id IS NOT NULL)\n"
    "              OR (dependency_kind <> 'workforce_person_obligations'\n"
    "                  AND event.organization_id IS NOT DISTINCT FROM organization\n"
    "                  AND event.event_edition_id IS NOT DISTINCT FROM edition)\n"
    "          )",
)
_valid = _replace(
    _valid,
    "('workforce_demand', 'workforce_assignment', 'workforce_availability')",
    "('workforce_demand', 'workforce_assignment',\n"
    "                             'workforce_availability', "
    "'workforce_person_obligations')",
)
FORWARD_SQL = _lock + "\n" + _valid


def refuse_tracked_person_work_downgrade(apps: Any, schema_editor: Any) -> None:
    """Keep the composed native guard generation after any retained attribution."""
    schema_editor.execute(
        "LOCK TABLE public.audit_auditnativemutationwitness, "
        "public.scheduling_schedulingreleasedependencykey "
        "IN ACCESS EXCLUSIVE MODE"
    )
    key = apps.get_model("scheduling", "SchedulingReleaseDependencyKey")
    witness = apps.get_model("audit", "AuditNativeMutationWitness")
    if key.objects.exists() or witness.objects.exists():
        raise RuntimeError(
            "Native release evidence exists; retain its execution boundary "
            "and fix forward."
        )


class Migration(migrations.Migration):
    """Keep native Audit scope intact; prove the specific account through Workforce."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("scheduling", "0013_person_obligation_dependency_kind"),
        ("identity", "0022_person_obligation_source_identity"),
        ("workforce", "0023_global_person_obligation_generation"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop, refuse_tracked_person_work_downgrade
        ),
    ]
