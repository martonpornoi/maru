"""Add a purpose-specific two-person Workspace representation."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations, models

_previous = import_module(
    "maru.organizations.migrations.0014_purpose_bounded_representation"
)
_ann = import_module("maru.organizations.migrations.0015_announcements_representation")
_lineage = import_module(
    "maru.authorization.migrations.0039_accountable_representation_lineage"
)
_caps = import_module("maru.authorization.migrations.0043_guidance_capabilities")
_WORKSPACE_ARRAY = (
    "ARRAY[\n"
    + ",\n".join(
        f"           '{code}'" for code in sorted(_caps.WORKSPACE_OPERATOR_CAPABILITIES)
    )
    + "\n       ]::varchar[]"
)
_DISPATCH = _previous._NEUTRAL_DISPATCH.replace("maru_operators", "workspace_operators")
_PUBLIC = "maru_assert_active_executive_board(uuid)"
_MEMBERSHIP = "maru_assert_active_board_membership_provenance(uuid)"
_APPOINTMENT = "maru_validate_representation_appointment()"
_HELPERS = (
    "maru_assert_active_workspace_operators",
    "maru_assert_active_workspace_operators_v0009",
)


def _clone(board: str) -> str:
    source = _previous._replace_once(
        board, _previous._BOARD_CAPABILITY_ARRAY, _WORKSPACE_ARRAY
    )
    source = _previous._replace_once(
        source,
        "cardinality(reserved_bundle_capabilities) != 12",
        "cardinality(reserved_bundle_capabilities) != 10",
    )
    return (
        source.replace("maru_assert_active_executive_board_v0009", _HELPERS[1])
        .replace("'Executive Board controller'", "'Workspace operator'")
        .replace("'executive-board'", "'workspace-operators'")
        .replace("'executive_board'", "'workspace_operators'")
        .replace("Executive Board", "Workspace operators")
    )


def _rewritten(identity: str, source: str, *, forward: bool) -> str:
    if identity == _PUBLIC:
        result = _previous._replace_once(
            source,
            "BEGIN\n" if forward else _DISPATCH,
            _DISPATCH if forward else "BEGIN\n",
        )
    elif identity == _MEMBERSHIP:
        old = "WHEN representation.code = 'announcements_operators'\n                                     THEN 'Announcements operator'"
        new = (
            old
            + "\n                                 WHEN representation.code = 'workspace_operators'\n                                     THEN 'Workspace operator'"
        )
        expected, desired = (old, new) if forward else (new, old)
        if source.count(expected) != 2:
            raise RuntimeError("Changed accountable membership source.")
        result = source.replace(expected, desired)
    else:
        old = "WHEN 'announcements_operators' THEN 'announcements-operators'"
        new = (
            old
            + "\n                  WHEN 'workspace_operators' THEN 'workspace-operators'"
        )
        result = _previous._replace_once(
            source, old if forward else new, new if forward else old
        )
    _ann._rewritten(identity, source if forward else result, forward=False)
    return result


def _replace(cursor: Any, identity: str, source: str) -> None:
    name = identity.split("(", maxsplit=1)[0]
    if identity == _APPOINTMENT:
        arguments, returns, config = "", "trigger", ""
    else:
        arguments, returns, config = (
            "target_representation_id uuid",
            "void",
            "SET search_path = pg_catalog, public, pg_temp",
        )
    cursor.execute(
        f"CREATE OR REPLACE FUNCTION public.{name}({arguments}) RETURNS {returns} LANGUAGE plpgsql VOLATILE CALLED ON NULL INPUT SECURITY INVOKER PARALLEL UNSAFE {config} AS %s",
        [source],
    )


def install(apps: Any, schema_editor: Any) -> None:
    del apps
    with schema_editor.connection.cursor() as cursor:
        public = _previous._function_state(cursor, "public." + _PUBLIC)
        board = _previous._replace_once(
            _ann._rewritten(_PUBLIC, public[1], forward=False),
            _previous._NEUTRAL_DISPATCH,
            "BEGIN\n",
        )
        older = _previous._function_state(
            cursor, "public.maru_assert_active_executive_board_v0009(uuid)"
        )
        if (
            _previous._source_sha256(board) != _previous._BOARD_VALIDATOR_SHA256
            or _previous._source_sha256(older[1]) != _previous._BOARD_V0009_SHA256
        ):
            raise RuntimeError("Cannot clone changed accountable root validators.")
        for name, source in zip(_HELPERS, (board, older[1]), strict=True):
            _previous._create_function(cursor, name=name, source=_clone(source))
        for identity in (_PUBLIC, _MEMBERSHIP, _APPOINTMENT):
            before = _lineage._state(cursor, identity)
            desired = _rewritten(identity, before[3], forward=True)
            _replace(cursor, identity, desired)
            after = _lineage._state(cursor, identity)
            if (
                before[:3] != after[:3]
                or before[4:] != after[4:]
                or after[3] != desired
            ):
                raise RuntimeError(
                    "Accountable root function identity or privileges changed."
                )
    for name in _HELPERS:
        _previous._copy_execute_privileges(
            schema_editor,
            identity=f"public.{name}(uuid)",
            owner_name=public[5],
            grantees=tuple(g for g in public[6] if g != "PUBLIC"),
        )


def restore(apps: Any, schema_editor: Any) -> None:
    del apps
    with schema_editor.connection.cursor() as cursor:
        for identity in (_PUBLIC, _MEMBERSHIP, _APPOINTMENT):
            before = _lineage._state(cursor, identity)
            desired = _rewritten(identity, before[3], forward=False)
            if _rewritten(identity, desired, forward=True) != before[3]:
                raise RuntimeError("Changed Workspace representation source.")
            _replace(cursor, identity, desired)
        for name in _HELPERS:
            cursor.execute(f"DROP FUNCTION public.{name}(uuid)")


def refuse_used_downgrade(apps: Any, schema_editor: Any) -> None:
    schema_editor.execute(
        "LOCK TABLE public.organizations_organizationrepresentation IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("organizations", "OrganizationRepresentation")
        .objects.filter(code="workspace_operators")
        .exists()
    ):
        raise RuntimeError(
            "Workspace operator records exist; retain them and fix forward."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("organizations", "0015_announcements_representation"),
        ("authorization", "0043_guidance_capabilities"),
    ]
    operations: ClassVar[list[object]] = [
        migrations.RemoveConstraint(
            model_name="organizationrepresentation",
            name="organization_representation_type_supported",
        ),
        migrations.AlterField(
            model_name="organizationrepresentation",
            name="code",
            field=models.CharField(
                choices=[
                    ("executive_board", "Executive Board"),
                    ("maru_operators", "Maru operators"),
                    ("announcements_operators", "Announcements operators"),
                    ("workspace_operators", "Workspace operators"),
                ],
                default="executive_board",
                editable=False,
                max_length=40,
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationrepresentation",
            constraint=models.CheckConstraint(
                condition=models.Q(code="executive_board", name="Executive Board")
                | models.Q(code="maru_operators", name="Maru operators")
                | models.Q(
                    code="announcements_operators", name="Announcements operators"
                )
                | models.Q(code="workspace_operators", name="Workspace operators"),
                name="organization_representation_type_supported",
            ),
        ),
        migrations.RunPython(install, restore),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade),
    ]
