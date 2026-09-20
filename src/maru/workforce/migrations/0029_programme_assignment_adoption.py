"""Prepare exact Programme assignment evidence without admitting a profile."""

import hashlib
import json
from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations
from django.db.migrations.operations.base import Operation

_COMMANDS = import_module("maru.workforce.migrations.0011_owner_assignment_commands")
_MODULAR = import_module(
    "maru.workforce.migrations.0014_workforce_only_assignment_evidence"
)
_EXACT = import_module(
    "maru.workforce.migrations.0015_exact_assignment_adoption_profile"
)
_FENCE = import_module(
    "maru.workforce.migrations.0028_programme_starter_execution_fence"
)
_PREVIOUS_SOURCE = "768710cc292c4a9e10fec5fbcfeb46c0bb52d01dc4679ca1c71647bf12180c41"
_PREVIOUS_METADATA = "4bea17fcf22ae5509e37b353365b0ddd9a0ceeedd5c29e8668c5c52d26a0935a"


def function_source(*, programme: bool) -> str:
    """Extend only the frozen no-Participation branch to one exact future pair."""
    source: str = _COMMANDS.FORWARD_SQL.split("$assignment_guard$")[1]
    # Reuse only this owner's immutable historical transformation contracts.
    source = _MODULAR._assignment_source(source, enable=True)  # noqa: SLF001
    source = _EXACT._assignment_source(source, enable=True)  # noqa: SLF001
    if hashlib.sha256(source.encode()).hexdigest() != _PREVIOUS_SOURCE:
        raise RuntimeError("Frozen assignment source changed.")
    if not programme:
        return source
    previous = "ELSIF assignment_profile_code = 'workforce_only'"
    if source.count(previous) != 1:
        raise RuntimeError("Exact assignment profile branch changed.")
    return source.replace(
        previous,
        "ELSIF assignment_profile_code IN ('workforce_only', 'programme_operations')",
    )


def _state(cursor: Any) -> tuple[Any, ...]:
    cursor.execute(
        """
        SELECT p.oid, p.proowner, p.proacl, p.prosrc, l.lanname::text,
               p.provolatile::text, p.proparallel::text, p.prosecdef,
               p.proleakproof, p.proisstrict, p.proretset, p.prokind::text,
               p.proconfig, pg_catalog.pg_get_function_result(p.oid)
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_language l ON l.oid = p.prolang
        WHERE p.oid = pg_catalog.to_regprocedure(
            'public.maru_guard_workforce_assignment()'
        )
        """
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Native assignment guard is unavailable.")
    return tuple(row)


def _fingerprint(definition: tuple[Any, ...]) -> str:
    keys = (
        "source",
        "language",
        "volatility",
        "parallel",
        "security_definer",
        "leakproof",
        "strict",
        "returns_set",
        "kind",
        "config",
        "result",
    )
    return hashlib.sha256(
        json.dumps(
            dict(zip(keys, definition, strict=True)),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _replace(schema_editor: Any, *, programme: bool) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE public.events_eventedition, "
            "public.workforce_positionassignment IN ACCESS EXCLUSIVE MODE"
        )
        if not programme:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM public.events_eventedition "
                "WHERE adoption_profile_code = 'programme_operations')"
            )
            if cursor.fetchone()[0]:
                raise RuntimeError(
                    "Used Programme assignment adoption requires fix-forward recovery."
                )
        before = _state(cursor)
        previous = function_source(programme=False)
        projected = function_source(programme=True)
        if (
            before[3] != (previous if programme else projected)
            or _fingerprint((previous, *before[4:])) != _PREVIOUS_METADATA
        ):
            raise RuntimeError("Refusing changed native assignment metadata.")
        # Preserve the historical DDL attributes rather than deriving new ones.
        _EXACT._replace_function(  # noqa: SLF001
            cursor, projected if programme else previous
        )
        after = _state(cursor)
        if (
            after[:3] != before[:3]
            or after[4:] != before[4:]
            or after[3] != (projected if programme else previous)
        ):
            raise RuntimeError("Assignment function identity or privileges changed.")


def install_programme_assignment(apps: Any, schema_editor: Any) -> None:
    """Prepare the exact Programme pair while retaining all existing evidence rules."""
    del apps
    _replace(schema_editor, programme=True)


def restore_assignment(apps: Any, schema_editor: Any) -> None:
    """Retain the inherited shared fence before reversing the exact-pair guard."""
    _FENCE.refuse_used_starter_execution_downgrade(apps, schema_editor)
    _replace(schema_editor, programme=False)


class Migration(migrations.Migration):
    """Add no model, grant, route, edition profile or rewritten assignment."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("workforce", "0028_programme_starter_execution_fence"),
    ]
    operations: ClassVar[list[Operation]] = [
        migrations.RunPython(install_programme_assignment, restore_assignment),
    ]
