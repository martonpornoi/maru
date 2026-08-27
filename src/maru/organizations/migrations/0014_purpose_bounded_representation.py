"""Add truthful Maru-operator representation with existing safety controls."""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from django.db import migrations, models


_BOARD_VALIDATOR_SHA256 = (
    "d659418aa83b08677cb7e13044d7d9a85c64dd70a3db66feb2454f59b18289b1"
)
_BOARD_V0009_SHA256 = "606f7a86e7a1dcbbdc076ef835860ead4dd51e369ba718868b4cde6117bcce27"
_MEMBERSHIP_VALIDATOR_SHA256 = (
    "9443b498d6f5b28e01d7d977f0b3fb12f61adf59cf811972a06409b8cf56fe6c"
)
_APPOINTMENT_VALIDATOR_SHA256 = (
    "75c81630ffa63c35531c13e97356af94f1c33f70bf08387972d58602b04bb642"
)
_SAFE_SEARCH_PATH = ("search_path=pg_catalog, public, pg_temp",)

_BOARD_CAPABILITY_ARRAY = """ARRAY[
           'audit.view_security',
           'authorization.delegate',
           'authorization.grant_direct',
           'authorization.manage_roles',
           'authorization.revoke',
           'events.create',
           'events.view_basic',
           'organizations.change_profile',
           'organizations.change_series',
           'organizations.create_series',
           'organizations.manage_representation',
           'organizations.view_basic'
       ]::varchar[]"""

_MARU_OPERATOR_CAPABILITY_ARRAY = """ARRAY[
           'audit.view_security',
           'authorization.delegate',
           'authorization.grant_direct',
           'authorization.manage_roles',
           'authorization.revoke',
           'events.change_profile',
           'events.create',
           'events.transition',
           'events.view_basic',
           'organizations.change_profile',
           'organizations.change_series',
           'organizations.create_series',
           'organizations.manage_representation',
           'organizations.view_basic',
           'workforce.manage_applications',
           'workforce.manage_assignments',
           'workforce.manage_documents',
           'workforce.manage_shifts',
           'workforce.manage_structure',
           'workforce.view_availability',
           'workforce.view_shifts',
           'workforce.view_structure'
       ]::varchar[]"""

_NEUTRAL_DISPATCH = """BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.organizations_organizationrepresentation AS representation
         WHERE representation.id = target_representation_id
           AND representation.code = 'maru_operators'
    ) THEN
        PERFORM public.maru_assert_active_maru_operators(
            target_representation_id
        );
        RETURN;
    END IF;
"""


def _source_sha256(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _function_state(
    cursor: Any,
    identity: str,
) -> tuple[object, str, tuple[str, ...], object, object, str, tuple[str, ...]]:
    cursor.execute(
        """
        SELECT procedure.oid,
               procedure.prosrc,
               procedure.proconfig,
               procedure.proowner,
               procedure.proacl,
               pg_catalog.pg_get_userbyid(procedure.proowner),
               ARRAY(
                   SELECT CASE
                              WHEN privilege.grantee = 0 THEN 'PUBLIC'
                              ELSE pg_catalog.pg_get_userbyid(privilege.grantee)
                          END
                     FROM pg_catalog.aclexplode(
                              COALESCE(
                                  procedure.proacl,
                                  pg_catalog.acldefault('f', procedure.proowner)
                              )
                          ) AS privilege
                    WHERE privilege.privilege_type = 'EXECUTE'
                    ORDER BY 1
               )
          FROM pg_catalog.pg_proc AS procedure
         WHERE procedure.oid = pg_catalog.to_regprocedure(%s)
        """,
        [identity],
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Required representation function {identity} is missing.")
    return (
        row[0],
        str(row[1]),
        tuple(row[2] or ()),
        row[3],
        row[4],
        str(row[5]),
        tuple(str(item) for item in (row[6] or ())),
    )


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(
            "Refusing to transform an unrecognized representation validator."
        )
    return source.replace(old, new)


def _neutral_validator_source(source: str) -> str:
    rewritten = source
    rewritten = (
        _replace_once(
            rewritten,
            "public.maru_assert_active_executive_board_v0009",
            "public.maru_assert_active_maru_operators_v0009",
        )
        if "public.maru_assert_active_executive_board_v0009" in rewritten
        else rewritten
    )
    replacements = (
        (
            "cardinality(reserved_bundle_capabilities) != 12",
            "cardinality(reserved_bundle_capabilities) != 22",
        ),
        (_BOARD_CAPABILITY_ARRAY, _MARU_OPERATOR_CAPABILITY_ARRAY),
    )
    for old, new in replacements:
        rewritten = _replace_once(rewritten, old, new)
    rewritten = rewritten.replace(
        "'Executive Board controller'",
        "'Maru operator'",
    )
    rewritten = rewritten.replace("'executive-board'", "'maru-operators'")
    rewritten = rewritten.replace("'executive_board'", "'maru_operators'")
    rewritten = rewritten.replace("Executive Board", "Maru operators")
    return rewritten


def _membership_source(source: str, *, enable: bool) -> str:
    old_multiline = """membership.relationship_label =
                      'Executive Board controller'"""
    old_inline = "membership.relationship_label = 'Executive Board controller'"
    new = """membership.relationship_label = (
                      SELECT CASE
                                 WHEN representation.code = 'maru_operators'
                                     THEN 'Maru operator'
                                 ELSE 'Executive Board controller'
                             END
                        FROM public.organizations_organizationrepresentation
                             AS representation
                       WHERE representation.id = target_representation_id
                  )"""
    if enable:
        if source.count(old_multiline) != 1 or source.count(old_inline) != 1:
            raise RuntimeError(
                "Refusing to transform an unrecognized membership validator."
            )
        rewritten = source.replace(old_multiline, new).replace(old_inline, new)
        rewritten = rewritten.replace(
            "active Executive Board membership",
            "active representation membership",
        )
    else:
        if source.count(new) != 2:
            raise RuntimeError(
                "Refusing to restore an unrecognized membership validator."
            )
        rewritten = source.replace(new, old_multiline, 1).replace(
            new,
            old_inline,
            1,
        )
        rewritten = rewritten.replace(
            "active representation membership",
            "active Executive Board membership",
        )
    return rewritten


def _appointment_source(source: str, *, enable: bool) -> str:
    original_declaration = "    representation_organization uuid;"
    bounded_declaration = """    representation_organization uuid;
    representation_code varchar;"""
    original_lookup = """        SELECT organization_id INTO representation_organization
          FROM organizations_organizationrepresentation
         WHERE id = NEW.representation_id;"""
    bounded_lookup = """        SELECT organization_id, code
          INTO representation_organization, representation_code
          FROM organizations_organizationrepresentation
         WHERE id = NEW.representation_id;"""
    original_role_check = (
        "           OR assignment_role_code IS DISTINCT FROM 'executive-board'"
    )
    bounded_role_check = """           OR assignment_role_code IS DISTINCT FROM (
              CASE representation_code
                  WHEN 'executive_board' THEN 'executive-board'
                  WHEN 'maru_operators' THEN 'maru-operators'
                  ELSE NULL
              END
           )"""
    replacements = (
        (
            original_declaration if enable else bounded_declaration,
            bounded_declaration if enable else original_declaration,
        ),
        (
            original_lookup if enable else bounded_lookup,
            bounded_lookup if enable else original_lookup,
        ),
        (
            original_role_check if enable else bounded_role_check,
            bounded_role_check if enable else original_role_check,
        ),
    )
    rewritten = source
    for old, new in replacements:
        rewritten = _replace_once(rewritten, old, new)
    return rewritten


def _create_function(
    cursor: Any,
    *,
    name: str,
    source: str,
) -> None:
    cursor.execute(
        f"""
        CREATE FUNCTION public.{name}(target_representation_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        VOLATILE
        CALLED ON NULL INPUT
        SECURITY INVOKER
        PARALLEL UNSAFE
        SET search_path = pg_catalog, public, pg_temp
        AS %s
        """,
        [source],
    )


def _copy_execute_privileges(
    schema_editor: Any,
    *,
    identity: str,
    owner_name: str,
    grantees: tuple[str, ...],
) -> None:
    quoted_owner = schema_editor.quote_name(owner_name)
    schema_editor.execute(f"ALTER FUNCTION {identity} OWNER TO {quoted_owner}")
    schema_editor.execute(f"REVOKE ALL ON FUNCTION {identity} FROM PUBLIC")
    for grantee in grantees:
        quoted_grantee = (
            "PUBLIC" if grantee == "PUBLIC" else schema_editor.quote_name(grantee)
        )
        schema_editor.execute(
            f"GRANT EXECUTE ON FUNCTION {identity} TO {quoted_grantee}"
        )


def install_purpose_bounded_validators(apps: Any, schema_editor: Any) -> None:
    """Clone known Board invariants for neutral operators and dispatch safely."""
    del apps
    with schema_editor.connection.cursor() as cursor:
        public_state = _function_state(
            cursor,
            "public.maru_assert_active_executive_board(uuid)",
        )
        v0009_state = _function_state(
            cursor,
            "public.maru_assert_active_executive_board_v0009(uuid)",
        )
        membership_state = _function_state(
            cursor,
            "public.maru_assert_active_board_membership_provenance(uuid)",
        )
        appointment_state = _function_state(
            cursor,
            "public.maru_validate_representation_appointment()",
        )
        expected = (
            (public_state, _BOARD_VALIDATOR_SHA256),
            (v0009_state, _BOARD_V0009_SHA256),
            (membership_state, _MEMBERSHIP_VALIDATOR_SHA256),
            (appointment_state, _APPOINTMENT_VALIDATOR_SHA256),
        )
        if any(_source_sha256(state[1]) != digest for state, digest in expected):
            raise RuntimeError(
                "Refusing to extend unrecognized organization validators."
            )
        if any(state[2] != _SAFE_SEARCH_PATH for state, _digest in expected[:3]):
            raise RuntimeError(
                "Refusing to extend representation validators with an unsafe path."
            )

        neutral_v0009 = _neutral_validator_source(v0009_state[1])
        neutral_current = _neutral_validator_source(public_state[1])
        _create_function(
            cursor,
            name="maru_assert_active_maru_operators_v0009",
            source=neutral_v0009,
        )
        _create_function(
            cursor,
            name="maru_assert_active_maru_operators",
            source=neutral_current,
        )

        public_source = _replace_once(
            public_state[1],
            "BEGIN\n",
            _NEUTRAL_DISPATCH,
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
                public.maru_assert_active_executive_board(
                    target_representation_id uuid
                )
            RETURNS void
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
            """,
            [public_source],
        )
        membership_source = _membership_source(membership_state[1], enable=True)
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
                public.maru_assert_active_board_membership_provenance(
                    target_representation_id uuid
                )
            RETURNS void
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
            """,
            [membership_source],
        )
        appointment_source = _appointment_source(
            appointment_state[1],
            enable=True,
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
                public.maru_validate_representation_appointment()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            AS %s
            """,
            [appointment_source],
        )

        after_public = _function_state(
            cursor,
            "public.maru_assert_active_executive_board(uuid)",
        )
        after_membership = _function_state(
            cursor,
            "public.maru_assert_active_board_membership_provenance(uuid)",
        )
        after_appointment = _function_state(
            cursor,
            "public.maru_validate_representation_appointment()",
        )
        if (
            after_public[0] != public_state[0]
            or after_public[2:5] != public_state[2:5]
            or after_public[1] != public_source
            or after_membership[0] != membership_state[0]
            or after_membership[2:5] != membership_state[2:5]
            or after_membership[1] != membership_source
            or after_appointment[0] != appointment_state[0]
            or after_appointment[2:5] != appointment_state[2:5]
            or after_appointment[1] != appointment_source
        ):
            raise RuntimeError(
                "Representation validator identity or privileges changed."
            )

    for helper_identity in (
        "public.maru_assert_active_maru_operators_v0009(uuid)",
        "public.maru_assert_active_maru_operators(uuid)",
    ):
        _copy_execute_privileges(
            schema_editor,
            identity=helper_identity,
            owner_name=public_state[5],
            grantees=public_state[6],
        )


def restore_board_only_validators(apps: Any, schema_editor: Any) -> None:
    """Restore the exact recognized Board-only public validator sources."""
    del apps
    with schema_editor.connection.cursor() as cursor:
        public_state = _function_state(
            cursor,
            "public.maru_assert_active_executive_board(uuid)",
        )
        membership_state = _function_state(
            cursor,
            "public.maru_assert_active_board_membership_provenance(uuid)",
        )
        appointment_state = _function_state(
            cursor,
            "public.maru_validate_representation_appointment()",
        )
        public_source = _replace_once(public_state[1], _NEUTRAL_DISPATCH, "BEGIN\n")
        membership_source = _membership_source(membership_state[1], enable=False)
        appointment_source = _appointment_source(
            appointment_state[1],
            enable=False,
        )
        if (
            _source_sha256(public_source) != _BOARD_VALIDATOR_SHA256
            or _source_sha256(membership_source) != _MEMBERSHIP_VALIDATOR_SHA256
            or _source_sha256(appointment_source) != _APPOINTMENT_VALIDATOR_SHA256
        ):
            raise RuntimeError(
                "Refusing to restore validators from an unrecognized definition."
            )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
                public.maru_assert_active_executive_board(
                    target_representation_id uuid
                )
            RETURNS void
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
            """,
            [public_source],
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
                public.maru_assert_active_board_membership_provenance(
                    target_representation_id uuid
                )
            RETURNS void
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            SET search_path = pg_catalog, public, pg_temp
            AS %s
            """,
            [membership_source],
        )
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION
                public.maru_validate_representation_appointment()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            CALLED ON NULL INPUT
            SECURITY INVOKER
            PARALLEL UNSAFE
            AS %s
            """,
            [appointment_source],
        )
        cursor.execute("DROP FUNCTION public.maru_assert_active_maru_operators(uuid)")
        cursor.execute(
            "DROP FUNCTION public.maru_assert_active_maru_operators_v0009(uuid)"
        )


def refuse_neutral_representation_downgrade(
    apps: Any,
    schema_editor: Any,
) -> None:
    """Refuse removing the representation type after durable use."""
    del schema_editor
    representation = apps.get_model("organizations", "OrganizationRepresentation")
    if representation.objects.filter(code="maru_operators").exists():
        raise RuntimeError(
            "Cannot remove the Maru-operator representation after durable "
            "records exist; keep compatible code and fix forward."
        )


class Migration(migrations.Migration):
    """Install a neutral representation without weakening Board controls."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("organizations", "0013_runtime_executable_function_hardening"),
        ("authorization", "0019_progressive_adoption_authority"),
    ]

    operations: ClassVar[list[object]] = [
        migrations.RemoveConstraint(
            model_name="organizationrepresentation",
            name="organization_representation_exec_board_code",
        ),
        migrations.RemoveConstraint(
            model_name="organizationrepresentation",
            name="organization_representation_exec_board_name",
        ),
        migrations.AlterField(
            model_name="organizationrepresentation",
            name="code",
            field=models.CharField(
                choices=[
                    ("executive_board", "Executive Board"),
                    ("maru_operators", "Maru operators"),
                ],
                default="executive_board",
                editable=False,
                max_length=40,
            ),
        ),
        migrations.AddConstraint(
            model_name="organizationrepresentation",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(code="executive_board", name="Executive Board")
                    | models.Q(code="maru_operators", name="Maru operators")
                ),
                name="organization_representation_type_supported",
            ),
        ),
        migrations.RunPython(
            install_purpose_bounded_validators,
            reverse_code=restore_board_only_validators,
        ),
        migrations.RunPython(
            migrations.RunPython.noop,
            reverse_code=refuse_neutral_representation_downgrade,
        ),
    ]
