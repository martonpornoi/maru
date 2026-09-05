"""Coordinate Department retirement with Applications Programme ownership."""

# ruff: noqa: E501, FLY002 -- SQL contract text stays exact and reviewable.

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from django.db import migrations

_previous = importlib.import_module(
    "maru.workforce.migrations.0017_programme_import_department_fk_contract"
)
_structure = importlib.import_module(
    "maru.workforce.migrations.0007_structure_write_integrity"
)

_PROGRAMME_IMPORT_RELATION = """                             (
                                 'public.applications_programmeimportbatch'::pg_catalog.regclass,
                                 ARRAY['owner_department_id']::text[]
                             ),"""

_TRANSITION_RELATIONS = """                             (
                                 'public.applications_programmecommandreceipt'::pg_catalog.regclass,
                                 ARRAY['source_department_id']::text[]
                             ),
                             (
                                 'public.applications_programmecommandreceipt'::pg_catalog.regclass,
                                 ARRAY['destination_department_id']::text[]
                             ),
                             (
                                 'public.applications_programmeimportcommandreceipt'::pg_catalog.regclass,
                                 ARRAY['source_department_id']::text[]
                             ),
                             (
                                 'public.applications_programmeimportcommandreceipt'::pg_catalog.regclass,
                                 ARRAY['destination_department_id']::text[]
                             ),"""

if _previous.FORWARD_SQL.count(_PROGRAMME_IMPORT_RELATION) != 1:
    raise RuntimeError(
        "Refusing to extend an unrecognized Programme Department FK contract."
    )

DEPARTMENT_FK_CONTRACT_SQL = _previous.FORWARD_SQL.replace(
    _PROGRAMME_IMPORT_RELATION,
    f"{_PROGRAMME_IMPORT_RELATION}\n{_TRANSITION_RELATIONS}",
)

_DEPARTMENT_START = (
    "CREATE FUNCTION public.maru_validate_department_structure_write()"
)
_DEPARTMENT_END = "CREATE FUNCTION public.maru_assert_department_structure_evidence()"
_start = _structure.INSTALL_DEPARTMENT_FUNCTIONS_SQL.index(_DEPARTMENT_START)
_end = _structure.INSTALL_DEPARTMENT_FUNCTIONS_SQL.index(_DEPARTMENT_END, _start)
_legacy_department_function = _structure.INSTALL_DEPARTMENT_FUNCTIONS_SQL[
    _start:_end
]

_LOCAL_RETIREMENT_END = """            ) THEN
                RAISE EXCEPTION 'current or future operations block Department retirement'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;"""
_PROGRAMME_RETIREMENT_END = """            ) THEN
                RAISE EXCEPTION 'current or future operations block Department retirement'
                    USING ERRCODE = '23514';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM public.applications_programmecall AS call
                  JOIN public.applications_applicationdefinition AS definition
                    ON definition.id = call.definition_id
                 WHERE call.organization_id = OLD.organization_id
                   AND call.edition_id = OLD.edition_id
                   AND call.owner_department_id = OLD.id
                   AND definition.organization_id = OLD.organization_id
                   AND definition.edition_id = OLD.edition_id
                   AND definition.target_adapter_kind = 'programme_item'
                   AND definition.status IN ('draft', 'active')
            ) OR EXISTS (
                SELECT 1
                  FROM public.applications_programmeimportbatch AS batch
                 WHERE batch.organization_id = OLD.organization_id
                   AND batch.edition_id = OLD.edition_id
                   AND batch.owner_department_id = OLD.id
                   AND batch.state = 'staged'
                   AND EXISTS (
                       SELECT 1
                         FROM public.applications_programmeimportitem AS item
                        WHERE item.batch_id = batch.id
                          AND item.organization_id = OLD.organization_id
                          AND item.edition_id = OLD.edition_id
                          AND item.state = 'staged'
                   )
            ) THEN
                RAISE EXCEPTION 'current Programme dependencies block Department retirement'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;"""

if _legacy_department_function.count(_LOCAL_RETIREMENT_END) != 1:
    raise RuntimeError("Unrecognized Department retirement integrity function.")

DEPARTMENT_RETIREMENT_FUNCTION_SQL = _legacy_department_function.replace(
    _DEPARTMENT_START,
    "CREATE OR REPLACE FUNCTION public.maru_validate_department_structure_write()",
).replace(
    _LOCAL_RETIREMENT_END,
    _PROGRAMME_RETIREMENT_END,
)

FORWARD_SQL = "\n\n".join(
    (
        DEPARTMENT_FK_CONTRACT_SQL.strip(),
        DEPARTMENT_RETIREMENT_FUNCTION_SQL.strip(),
        "REVOKE ALL ON FUNCTION public."
        "maru_validate_department_structure_write() FROM PUBLIC;",
    )
)

REVERSE_SQL = "\n\n".join(
    (
        _previous.FORWARD_SQL.strip(),
        _legacy_department_function.replace(
            _DEPARTMENT_START,
            "CREATE OR REPLACE FUNCTION "
            "public.maru_validate_department_structure_write()",
        ).strip(),
        "REVOKE ALL ON FUNCTION public."
        "maru_validate_department_structure_write() FROM PUBLIC;",
    )
)


def refuse_unsafe_retirement_contract_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Refuse reversal while a live Programme dependency needs protection."""
    call = apps.get_model("applications", "ProgrammeCall")
    import_batch = apps.get_model("applications", "ProgrammeImportBatch")
    import_item = apps.get_model("applications", "ProgrammeImportItem")
    schema_editor.execute(
        "LOCK TABLE public.workforce_department, "
        "public.applications_programmecall, "
        "public.applications_applicationdefinition, "
        "public.applications_programmeimportbatch, "
        "public.applications_programmeimportitem IN ACCESS EXCLUSIVE MODE"
    )
    if (
        call.objects.filter(definition__status__in=("draft", "active")).exists()
        or import_batch.objects.filter(
            state="staged",
            id__in=import_item.objects.filter(state="staged").values("batch_id"),
        ).exists()
    ):
        raise RuntimeError(
            "Cannot remove Programme Department retirement protection while live "
            "calls or unresolved staged imports exist; resolve them and retry."
        )


class Migration(migrations.Migration):
    """Install the 19-reference FK catalog and retirement backstop."""

    atomic = True
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("applications", "0012_programme_department_ownership_downgrade_fence"),
        ("workforce", "0017_programme_import_department_fk_contract"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_unsafe_retirement_contract_downgrade,
        ),
    ]
