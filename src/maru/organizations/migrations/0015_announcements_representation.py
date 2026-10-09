"""Add a purpose-specific two-person Announcements representation."""

from importlib import import_module
from typing import Any, ClassVar

from django.db import migrations, models

_previous = import_module(
    "maru.organizations.migrations.0014_purpose_bounded_representation"
)
_lineage = import_module(
    "maru.authorization.migrations.0039_accountable_representation_lineage"
)
_caps = import_module("maru.authorization.migrations.0041_announcements_capabilities")
_ANNOUNCEMENTS_ARRAY = (
    "ARRAY[\n"
    + ",\n".join(
        f"           '{code}'"
        for code in sorted(_caps.ANNOUNCEMENTS_OPERATOR_CAPABILITIES)
    )
    + "\n       ]::varchar[]"
)
_DISPATCH = _previous._NEUTRAL_DISPATCH.replace(
    "maru_operators", "announcements_operators"
)
_PUBLIC = "maru_assert_active_executive_board(uuid)"
_MEMBERSHIP = "maru_assert_active_board_membership_provenance(uuid)"
_APPOINTMENT = "maru_validate_representation_appointment()"
_HELPERS = (
    "maru_assert_active_announcements_operators",
    "maru_assert_active_announcements_operators_v0009",
)


def _clone(board: str) -> str:
    source = _previous._replace_once(
        board, _previous._BOARD_CAPABILITY_ARRAY, _ANNOUNCEMENTS_ARRAY
    )
    source = _previous._replace_once(
        source,
        "cardinality(reserved_bundle_capabilities) != 12",
        "cardinality(reserved_bundle_capabilities) != 20",
    )
    return (
        source.replace("maru_assert_active_executive_board_v0009", _HELPERS[1])
        .replace("'Executive Board controller'", "'Announcements operator'")
        .replace("'executive-board'", "'announcements-operators'")
        .replace("'executive_board'", "'announcements_operators'")
        .replace("Executive Board", "Announcements operators")
    )


def _rewritten(identity: str, source: str, *, forward: bool) -> str:
    if identity == _PUBLIC:
        if forward:
            board = _previous._replace_once(
                source, _previous._NEUTRAL_DISPATCH, "BEGIN\n"
            )
            if _previous._source_sha256(board) != _previous._BOARD_VALIDATOR_SHA256:
                raise RuntimeError(
                    "Unrecognized accountable representation dispatcher."
                )
            return _previous._replace_once(source, "BEGIN\n", _DISPATCH)
        return _previous._replace_once(source, _DISPATCH, "BEGIN\n")
    if identity == _MEMBERSHIP:
        old = "WHEN representation.code = 'maru_operators'\n                                     THEN 'Maru operator'"
        new = (
            old
            + "\n                                 WHEN representation.code = 'announcements_operators'\n                                     THEN 'Announcements operator'"
        )
        expected, desired = (old, new) if forward else (new, old)
        if source.count(expected) != 2:
            raise RuntimeError("Unrecognized accountable membership source.")
        result = source.replace(expected, desired)
        previous = source if forward else result
        if (
            _previous._source_sha256(
                _previous._membership_source(previous, enable=False)
            )
            != _previous._MEMBERSHIP_VALIDATOR_SHA256
        ):
            raise RuntimeError("Changed accountable membership source.")
        return result
    old = "WHEN 'maru_operators' THEN 'maru-operators'"
    new = (
        old
        + "\n                  WHEN 'announcements_operators' THEN 'announcements-operators'"
    )
    result = _previous._replace_once(
        source, old if forward else new, new if forward else old
    )
    previous = source if forward else result
    if (
        _previous._source_sha256(_previous._appointment_source(previous, enable=False))
        != _previous._APPOINTMENT_VALIDATOR_SHA256
    ):
        raise RuntimeError("Changed accountable appointment source.")
    return result


def _replace(cursor: Any, identity: str, source: str) -> None:
    name = identity.split("(")[0]
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
            public[1], _previous._NEUTRAL_DISPATCH, "BEGIN\n"
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
                raise RuntimeError("Changed Announcements representation source.")
            _replace(cursor, identity, desired)
        for name in _HELPERS:
            cursor.execute(f"DROP FUNCTION public.{name}(uuid)")


def refuse_used_downgrade(apps: Any, schema_editor: Any) -> None:
    schema_editor.execute(
        "LOCK TABLE public.organizations_organizationrepresentation IN ACCESS EXCLUSIVE MODE"
    )
    if (
        apps.get_model("organizations", "OrganizationRepresentation")
        .objects.filter(code="announcements_operators")
        .exists()
    ):
        raise RuntimeError(
            "Announcements operator records exist; retain them and fix forward."
        )


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("organizations", "0014_purpose_bounded_representation"),
        ("authorization", "0041_announcements_capabilities"),
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
                ),
                name="organization_representation_type_supported",
            ),
        ),
        migrations.RunPython(install, restore),
        migrations.RunPython(migrations.RunPython.noop, refuse_used_downgrade),
    ]
