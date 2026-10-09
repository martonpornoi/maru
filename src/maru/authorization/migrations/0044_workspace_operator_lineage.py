"""Admit one exact Workspace root through the existing two-person lineage."""

import re
from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations

_previous = import_module(
    "maru.authorization.migrations.0039_accountable_representation_lineage"
)
_ann = import_module(
    "maru.authorization.migrations.0042_announcements_operator_lineage"
)
_adoption = import_module(
    "maru.authorization.migrations.0019_progressive_adoption_authority"
)
_original = import_module(
    "maru.authorization.migrations.0007_authority_provenance_activation_guards"
)
_controls = import_module(
    "maru.authorization.migrations.0006_authority_issuance_schema"
)
_caps = import_module("maru.authorization.migrations.0043_guidance_capabilities")
_ARRAY = (
    "ARRAY["
    + ",".join(f"'{c}'" for c in _caps.WORKSPACE_OPERATOR_CAPABILITIES)
    + "]::text[]"
)
_IDENTITIES = (
    _previous._COMPLETE,
    _previous._BUNDLE,
    _previous._ASSIGNMENT,
    "maru_validate_role_assignment()",
    "maru_validate_profile_bound_role_assignment_scope()",
    "maru_validate_representation_control_type_insert()",
    "maru_validate_authority_control_insert()",
)


def _source(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE (?:OR REPLACE )?FUNCTION (?:public\.)?{name}\(.*?AS \$\$(.*?)\$\$",
        sql,
        re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Frozen authority source is unavailable.")
    return match[1]


def previous_source(identity: str) -> str:
    return _ann.next_source(identity)


def next_source(identity: str) -> str:
    source = previous_source(identity)
    once = _previous._once
    if identity == _previous._COMPLETE:
        return once(
            source,
            "ARRAY['executive-board', 'maru-operators', 'announcements-operators']",
            "ARRAY['executive-board', 'maru-operators', 'announcements-operators', 'workspace-operators']",
        )
    if identity in (_previous._BUNDLE, _previous._ASSIGNMENT):
        if identity == _previous._BUNDLE:
            start, end = (
                "    IF bundle_code = 'executive-board' THEN",
                "    FOR control_record IN",
            )
        else:
            start = "    IF source_kind = 'assignment'\n       AND source_bundle_code = 'executive-board'"
            end = "    IF source_kind = 'assignment'\n       AND NOT public.maru_authority_bundle_historical_v1("
        first = source.index(start)
        last = source.index(end, first)
        block = source[first:last]
        array = (
            "ARRAY[\n"
            + ",\n".join(
                f"               '{c}'"
                for c in sorted(_caps.WORKSPACE_OPERATOR_CAPABILITIES)
            )
            + "\n           ]::varchar[]"
        )
        pattern = r"ARRAY\[\n\s*'audit\.view_security'.*?\]::varchar\[\]"
        if len(re.findall(pattern, block, re.DOTALL)) != 1:
            raise RuntimeError("Frozen Board ceremony capability array is unavailable.")
        new = re.sub(pattern, lambda _m: array, block, flags=re.DOTALL)
        new = (
            new.replace("'executive-board'", "'workspace-operators'")
            .replace("'executive_board'", "'workspace_operators'")
            .replace("'Executive Board'", "'Workspace operators'")
            .replace("'Executive Board controller'", "'Workspace operator'")
            .replace("!= 12", "!= 10")
        )
        return once(source, block, new + block)
    if identity == "maru_validate_role_assignment()":
        old = (
            """                      AND bundle_capability_codes = """
            + _ann._ARRAY
            + """
                      AND EXISTS (
                          SELECT 1 FROM public.authorization_rolebundle AS root
                           WHERE root.id = NEW.role_bundle_id
                             AND root.code = 'announcements-operators'
                             AND root.version = 1
                      )"""
        )
        workspace = old.replace(_ann._ARRAY, _ARRAY).replace(
            "'announcements-operators'", "'workspace-operators'"
        )
        new = (
            "                      AND (("
            + old.strip().removeprefix("AND ")
            + ") OR ("
            + workspace.strip().removeprefix("AND ")
            + "))"
        )
        return once(source, old, new)
    if identity == "maru_validate_profile_bound_role_assignment_scope()":
        old = "    IF NEW.edition_id IS NULL"
        guard = (
            """    IF bundle_code = 'workspace-operators'
       AND bundle_capability_codes IS DISTINCT FROM """
            + _ARRAY
            + """
    THEN
        RAISE EXCEPTION 'Workspace operator authority requires its canonical capabilities'
            USING ERRCODE = '23514';
    END IF;

"""
        )
        source = once(source, old, guard + old)
        return once(
            source,
            "AND bundle_code NOT IN ('maru-operators', 'announcements-operators')",
            "AND bundle_code NOT IN ('maru-operators', 'announcements-operators', 'workspace-operators')",
        )
    if identity == "maru_validate_representation_control_type_insert()":
        old = "(target_role_code = 'announcements-operators'\n         AND target_representation_code = 'announcements_operators')"
        return once(
            source,
            old,
            old
            + "\n        OR\n        (target_role_code = 'workspace-operators'\n         AND target_representation_code = 'workspace_operators')",
        )
    old = "ARRAY['executive-board', 'maru-operators', 'announcements-operators']"
    if source.count(old) != 2:
        raise RuntimeError("Frozen control root comparisons changed.")
    return source.replace(
        old,
        "ARRAY['executive-board', 'maru-operators', 'announcements-operators', 'workspace-operators']",
    )


def _sql(identity: str, source: str) -> str:
    if identity in (_previous._COMPLETE, _previous._BUNDLE, _previous._ASSIGNMENT):
        original = _previous.function_sql(identity, corrected=True)
        return original.split("$$")[0] + "$$" + source + "$$" + original.split("$$")[2]
    return (
        f"CREATE OR REPLACE FUNCTION public.{identity} RETURNS trigger AS $$"
        + source
        + "$$ LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp;"
    )


def _replace(schema_editor: Any, *, forward: bool) -> None:
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "LOCK TABLE public.authorization_rolebundle, public.authorization_roleassignment, public.authorization_authorityissuance, public.authorization_authoritycontrol IN ACCESS EXCLUSIVE MODE"
        )
        for identity in _IDENTITIES:
            previous, desired = previous_source(identity), next_source(identity)
            if not forward:
                previous, desired = desired, previous
            before = _previous._state(cursor, identity)
            if before[3] != previous:
                raise RuntimeError(
                    f"Refusing changed native authority source: {identity}."
                )
            cursor.execute(_sql(identity, desired))
            after = _previous._state(cursor, identity)
            if (
                after[:3] != before[:3]
                or after[4:] != before[4:]
                or after[3] != desired
            ):
                raise RuntimeError("Authority function identity or privileges changed.")


def install(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=True)


def restore(apps: Any, schema_editor: Any) -> None:
    del apps
    _replace(schema_editor, forward=False)


def refuse_used_downgrade(apps: Any, schema_editor: Any) -> None:
    schema_editor.execute(
        "LOCK TABLE public.authorization_rolebundle IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("authorization", "RoleBundle")
        .objects.filter(code="workspace-operators")
        .exists()
    ):
        raise RuntimeError(
            "Workspace operator lineage exists; retain it and fix forward."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("authorization", "0043_guidance_capabilities"),
        ("organizations", "0016_workspace_representation"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunPython(install, restore),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade),
    ]
